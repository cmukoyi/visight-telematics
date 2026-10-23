"""Geofence engine — entry/exit alerts from Teltonika positions.

Called by the dashboard ingest for every batch of new GPS fixes. A vehicle is
watched against a place when it is armed to it (Places page) or when an
active notification rule covers its vehicle group and that place. Fixes are
checked in device-time order; each change between inside and outside raises
one geofence_entry / geofence_exit inbox alert, then:

- armed places notify the group's users (email/SMS, per their preferences);
- each matching rule emails its own recipients with its custom message.

- Circles use 10% hysteresis on the radius so a vehicle parked on the edge
  doesn't flap; polygons and rectangles use the drawn outline.
- The first fix for a vehicle/place only records the state (no alert).
- geofence_states.checked_at is the device time of the last fix checked, so
  late, buffered records from before it are skipped rather than replayed.

Every active place of the vehicle's group is tracked (not only watched ones)
so each stay is recorded in place_visits for place reports; only watched
places raise alerts.
"""
import json
import logging
import math
import re
from datetime import datetime, timezone
from typing import Optional
from zoneinfo import ZoneInfo

from sqlalchemy.orm import Session

from app.models import (POI, BLETag, GeofenceState, GeofenceStatus, NotificationRule, PlaceVisit, POITrackerLink, UserGroup)
from app.services import portal_alert_service as alerts

logger = logging.getLogger(__name__)

HYSTERESIS = 0.10


def _distance_m(lat1, lng1, lat2, lng2) -> float:
    p1, p2 = math.radians(lat1), math.radians(lat2)
    a = (math.sin((p2 - p1) / 2) ** 2
         + math.cos(p1) * math.cos(p2) * math.sin(math.radians(lng2 - lng1) / 2) ** 2)
    return 2 * 6371000 * math.asin(math.sqrt(a))


def _outline(poi: POI) -> Optional[list]:
    """[[lat, lng], ...] for polygon/rectangle places, else None."""
    if (poi.shape_type or "circle") == "circle" or not poi.coordinates:
        return None
    try:
        pts = json.loads(poi.coordinates) if isinstance(poi.coordinates, str) else poi.coordinates
        pts = [(float(p[0]), float(p[1])) for p in pts]
        return pts if len(pts) >= 3 else None
    except (ValueError, TypeError, IndexError):
        logger.warning("Place %s has unreadable coordinates", poi.id)
        return None


def _in_polygon(lat: float, lng: float, pts: list) -> bool:
    inside = False
    j = len(pts) - 1
    for i in range(len(pts)):
        (yi, xi), (yj, xj) = pts[i], pts[j]
        if (yi > lat) != (yj > lat) and lng < (xj - xi) * (lat - yi) / (yj - yi) + xi:
            inside = not inside
        j = i
    return inside


def is_inside(poi: POI, lat: float, lng: float, state: Optional[GeofenceState] = None) -> bool:
    outline = _outline(poi)
    if outline:
        return _in_polygon(lat, lng, outline)
    radius = float(poi.radius or 150.0)
    if state == GeofenceState.INSIDE:
        radius *= 1 + HYSTERESIS
    elif state == GeofenceState.OUTSIDE:
        radius *= 1 - HYSTERESIS
    return _distance_m(lat, lng, poi.latitude, poi.longitude) <= radius


def _utc(dt: datetime) -> datetime:
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


PLACEHOLDERS = {
    "vehicle": "Vehicle description", "registration": "Registration", "make": "Make", "model": "Model",
    "year": "Year", "driver": "Driver", "imei": "Device IMEI", "place": "Place name",
    "event": "entered / left", "time": "Date and time", "speed": "Speed (km/h)",
}
DEFAULT_MESSAGE = "{vehicle} ({registration}) {event} {place} at {time}."


def vehicle_detail(tag: BLETag, key: str) -> str:
    """make / model / year / registration / driver from the vehicle's attributes."""
    value = ((tag.attributes or {}).get(key) or {})
    return str(value.get("value") or "") if isinstance(value, dict) else str(value or "")


def render(template: str, values: dict) -> str:
    """Replace {placeholder}s that we know; leave anything else as typed."""
    return re.sub(r"\{(\w+)\}", lambda m: str(values.get(m.group(1), m.group(0))), template)


def _values(db: Session, tag: BLETag, poi: POI, entered: bool, fix: dict) -> dict:
    when = _utc(fix["recorded_at"])
    group = db.get(UserGroup, poi.usergroup_id)
    tz_name = (group.timezone if group else None) or "Africa/Johannesburg"
    try:
        local = when.astimezone(ZoneInfo(tz_name))
    except Exception:
        local = when
    return {"vehicle": tag.description or tag.device_name or tag.imei, "imei": tag.imei, "place": poi.name,
            "event": "entered" if entered else "left", "time": local.strftime("%d %b %Y %H:%M"),
            "speed": fix.get("speed") or 0,
            **{k: vehicle_detail(tag, k) or "—" for k in ("registration", "make", "model", "year", "driver")}}


def _raise(db: Session, tag: BLETag, poi: POI, entered: bool, fix: dict, armed: bool, rules: list) -> None:
    atype = "geofence_entry" if entered else "geofence_exit"
    v = _values(db, tag, poi, entered, fix)
    title = f"{v['vehicle']} {v['event']} {poi.name}"
    message = f"{v['vehicle']} {v['event']} the place '{poi.name}' at {v['time']} ({v['speed']} km/h)."
    meta = {"poi_name": poi.name, "poi_id": str(poi.id), "imei": tag.imei,
            "event_type": "entry" if entered else "exit", "latitude": fix["latitude"], "longitude": fix["longitude"],
            "speed": fix.get("speed"), "recorded_at": _utc(fix["recorded_at"]).isoformat(),
            "rules": [r.name for r in rules], "registration": v["registration"]}
    group_id = str(poi.usergroup_id)
    with db.begin_nested():
        alerts.create_alert(db, group_id, str(tag.id), alert_type=atype, title=title, message=message, meta_data=meta)
        db.flush()
    if armed:
        alerts._notify_group_by_email(db, group_id, atype, title, message, meta, imei=tag.imei)
        alerts._notify_group_by_sms(db, group_id, atype, title, message, imei=tag.imei)
    for rule in rules:
        if rule.email_enabled and rule.email_recipients:
            text_ = render(rule.email_message or DEFAULT_MESSAGE, v)
            subject = f"{rule.name}: {title}"
            for to in rule.email_recipients:
                try:
                    alerts._email_svc.send_portal_alert_email(to, atype, subject, text_, meta)
                except Exception:
                    logger.exception("Rule %s email to %s failed", rule.id, to)
    logger.info("Geofence %s: %s %s %s (rules: %s)", atype, tag.imei, v["event"], poi.name, [r.name for r in rules])


def _record_visit(db: Session, tag: BLETag, poi: POI, entered: bool, at: Optional[datetime], fix: dict) -> None:
    """Open a place visit on entry; close the open one on exit (or record an exit whose entry we never saw)."""
    if poi.usergroup_id is None:   # an old per-user place, not a group's
        return
    if entered:
        db.add(PlaceVisit(usergroup_id=poi.usergroup_id, tag_id=tag.id, imei=tag.imei, poi_id=poi.id,
                          entered_at=at, entry_speed=fix.get("speed") if at else None))
        return
    visit = (db.query(PlaceVisit).filter(PlaceVisit.tag_id == tag.id, PlaceVisit.poi_id == poi.id,
                                         PlaceVisit.exited_at.is_(None))
             .order_by(PlaceVisit.id.desc()).first())
    if visit is None:
        visit = PlaceVisit(usergroup_id=poi.usergroup_id, tag_id=tag.id, imei=tag.imei, poi_id=poi.id)
        db.add(visit)
    visit.exited_at, visit.exit_speed = at, fix.get("speed")


def _watched(db: Session, tag: BLETag) -> dict:
    """{poi_id: (poi, armed, [rules])} — the places this vehicle is checked against (armed/rules: alerts)."""
    out: dict = {}
    links = (db.query(POITrackerLink).join(POI, POI.id == POITrackerLink.poi_id)
             .filter(POITrackerLink.tracker_id == tag.id, POITrackerLink.is_armed == True,  # noqa: E712
                     POI.is_active == True).all())  # noqa: E712
    for link in links:
        out[link.poi_id] = (link.poi, True, [])
    group_id = (tag.attributes or {}).get("_created_usergroup_id")
    if not group_id:
        return out
    places = {p.id: p for p in db.query(POI).filter(POI.usergroup_id == group_id, POI.is_active == True).all()}  # noqa: E712
    for poi in places.values():   # tracked for place visits, without alerts
        out.setdefault(poi.id, (poi, False, []))
    category = ((tag.attributes or {}).get("category") or {}).get("value")
    rules = [r for r in db.query(NotificationRule).filter(
                NotificationRule.usergroup_id == group_id, NotificationRule.is_active == True,  # noqa: E712
                NotificationRule.rule_type == "geofence").all()
             if not r.category or (category and r.category.lower() == category.lower())]
    if not rules:
        return out
    for rule in rules:
        ids = set(map(str, rule.place_ids or []))
        groups = set(map(str, rule.place_group_ids or []))
        wanted = (places.values() if not ids and not groups else
                  [p for p in places.values() if str(p.id) in ids or (p.place_group_id and str(p.place_group_id) in groups)])
        for poi in wanted:
            poi_, armed, rs = out.get(poi.id, (poi, False, []))
            out[poi.id] = (poi_, armed, rs + [rule])
    return out


def check_positions(db: Session, tag: BLETag, fixes: list) -> int:
    """Check new fixes ({recorded_at, latitude, longitude, speed}) against the places the tag is watched against.

    Returns the number of alerts raised. Does not commit.
    """
    watched = _watched(db, tag)
    if not watched:
        return 0
    ordered = sorted((f for f in fixes if f.get("latitude") is not None and f.get("longitude") is not None),
                     key=lambda f: f["recorded_at"])
    db.flush()   # the session doesn't autoflush: make earlier, still-pending states visible
    states = {s.poi_id: s for s in db.query(GeofenceStatus).filter(
        GeofenceStatus.tag_id == tag.id, GeofenceStatus.poi_id.in_(list(watched))).with_for_update().all()}
    raised = 0
    for poi_id, (poi, armed, rules) in watched.items():
        status = states.get(poi_id)
        for fix in ordered:
            at = _utc(fix["recorded_at"])
            if status and _utc(status.checked_at) >= at:
                continue
            prev = None if status is None else (GeofenceState.INSIDE if status.inside else GeofenceState.OUTSIDE)
            inside = is_inside(poi, fix["latitude"], fix["longitude"], prev)
            if status is None:
                status = GeofenceStatus(tag_id=tag.id, poi_id=poi_id, inside=inside, checked_at=at)
                db.add(status)
                if inside:   # already inside when tracking began: the stay's entry is unknown
                    _record_visit(db, tag, poi, True, None, fix)
                continue
            if inside != status.inside:
                _record_visit(db, tag, poi, inside, at, fix)
                wanting = [r for r in rules if (r.on_entry if inside else r.on_exit)]
                if armed or wanting:
                    try:
                        _raise(db, tag, poi, inside, fix, armed, wanting)
                        raised += 1
                    except Exception:
                        logger.exception("Geofence alert for %s / %s failed", tag.imei, poi.id)
            status.inside, status.checked_at = inside, at
    return raised


def rebuild_visits(db: Session, group_id) -> int:
    """Rebuild a group's place visits from its stored positions (all history). Does not commit.

    Replays each vehicle's fixes against each active place with the same
    inside/outside test and hysteresis as check_positions; replaces the
    group's existing visits. Returns the number of visits recorded.
    """
    from app.models_dataprofiler import DeviceEvent
    places = db.query(POI).filter(POI.usergroup_id == group_id, POI.is_active == True).all()  # noqa: E712
    tags = db.query(BLETag).filter(BLETag.attributes.op("->>")("_created_usergroup_id") == str(group_id),
                                   BLETag.imei.isnot(None)).all()
    db.query(PlaceVisit).filter(PlaceVisit.usergroup_id == group_id).delete(synchronize_session=False)
    count = 0
    for tag in tags:
        fixes = (db.query(DeviceEvent.recorded_at, DeviceEvent.latitude, DeviceEvent.longitude, DeviceEvent.speed)
                 .filter(DeviceEvent.imei == tag.imei, DeviceEvent.latitude.isnot(None), DeviceEvent.longitude.isnot(None))
                 .order_by(DeviceEvent.recorded_at, DeviceEvent.id).all())
        for poi in places:
            inside, visit = None, None
            for at, lat, lng, speed in fixes:
                prev = None if inside is None else (GeofenceState.INSIDE if inside else GeofenceState.OUTSIDE)
                now_inside = is_inside(poi, lat, lng, prev)
                if inside is None:
                    if now_inside:   # inside at the first fix we have: entry unknown
                        visit = PlaceVisit(usergroup_id=group_id, tag_id=tag.id, imei=tag.imei, poi_id=poi.id)
                elif now_inside and not inside:
                    visit = PlaceVisit(usergroup_id=group_id, tag_id=tag.id, imei=tag.imei, poi_id=poi.id,
                                       entered_at=_utc(at), entry_speed=speed)
                elif inside and not now_inside and visit is not None:
                    visit.exited_at, visit.exit_speed = _utc(at), speed
                    db.add(visit)
                    count += 1
                    visit = None
                inside = now_inside
            if visit is not None:   # still inside
                db.add(visit)
                count += 1
    return count
