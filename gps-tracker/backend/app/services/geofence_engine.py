"""Geofence engine — entry/exit alerts from Teltonika positions.

Called by the dashboard ingest for every batch of new GPS fixes. For each
place (POI) the vehicle is armed to, fixes are checked in device-time order
and the link's last_known_state moves between INSIDE and OUTSIDE; a change
raises a geofence_entry / geofence_exit alert (inbox, email, SMS).

- Circles use 10% hysteresis on the radius so a vehicle parked on the edge
  doesn't flap; polygons and rectangles use the drawn outline.
- The first fix after arming only records the state (no alert).
- link.last_state_check is the device time of the last fix checked, so late,
  buffered records from before it are skipped rather than replayed.
"""
import json
import logging
import math
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy.orm import Session

from app.models import POI, BLETag, GeofenceState, POITrackerLink
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


def _raise(db: Session, tag: BLETag, poi: POI, entered: bool, fix: dict) -> None:
    label = tag.description or tag.device_name or tag.imei
    atype = "geofence_entry" if entered else "geofence_exit"
    verb = "entered" if entered else "left"
    title = f"{label} {verb} {poi.name}"
    when = _utc(fix["recorded_at"])
    message = f"{label} {verb} the place '{poi.name}' at {when:%Y-%m-%d %H:%M} UTC ({fix.get('speed') or 0} km/h)."
    meta = {"poi_name": poi.name, "poi_id": str(poi.id), "imei": tag.imei,
            "event_type": "entry" if entered else "exit", "latitude": fix["latitude"], "longitude": fix["longitude"],
            "speed": fix.get("speed"), "recorded_at": when.isoformat()}
    group_id = str(poi.usergroup_id)
    with db.begin_nested():
        alerts.create_alert(db, group_id, str(tag.id), alert_type=atype, title=title, message=message, meta_data=meta)
        db.flush()
    alerts._notify_group_by_email(db, group_id, atype, title, message, meta, imei=tag.imei)
    alerts._notify_group_by_sms(db, group_id, atype, title, message, imei=tag.imei)
    logger.info("Geofence %s: %s %s %s", atype, tag.imei, verb, poi.name)


def check_positions(db: Session, tag: BLETag, fixes: list) -> int:
    """Check new fixes ({recorded_at, latitude, longitude, speed}) against the tag's armed places.

    Returns the number of alerts raised. Does not commit.
    """
    links = (db.query(POITrackerLink).join(POI, POI.id == POITrackerLink.poi_id)
             .filter(POITrackerLink.tracker_id == tag.id, POITrackerLink.is_armed == True,  # noqa: E712
                     POI.is_active == True)  # noqa: E712
             .with_for_update(of=POITrackerLink).all())
    if not links:
        return 0
    ordered = sorted((f for f in fixes if f.get("latitude") is not None and f.get("longitude") is not None),
                     key=lambda f: f["recorded_at"])
    raised = 0
    for link in links:
        poi = link.poi
        checked = _utc(link.last_state_check) if link.last_state_check else None
        for fix in ordered:
            at = _utc(fix["recorded_at"])
            if checked and at <= checked:
                continue
            state = link.last_known_state
            inside = is_inside(poi, fix["latitude"], fix["longitude"], state)
            new_state = GeofenceState.INSIDE if inside else GeofenceState.OUTSIDE
            if state in (GeofenceState.INSIDE, GeofenceState.OUTSIDE) and new_state != state:
                try:
                    _raise(db, tag, poi, inside, fix)
                    raised += 1
                except Exception:
                    logger.exception("Geofence alert for %s / %s failed", tag.imei, poi.id)
            link.last_known_state = new_state
            link.last_state_check = checked = at
    return raised
