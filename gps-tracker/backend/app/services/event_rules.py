"""Event notification rules — alerts when a vehicle reports one of the chosen events.

Called by the dashboard ingest with each batch of newly stored events. A rule
of type "event" covers a vehicle group (or all vehicles) and watches event
types picked directly (e.g. speeding, harsh braking) and/or an event type
group; every matching event raises an inbox alert (event_<code>) and, when the
rule has email enabled, emails its recipients with its custom message.
"""
import logging
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

from sqlalchemy.orm import Session

from app.dataprofiler.dictionary import EVENTS
from app.models import BLETag, EventTypeGroup, EventTypeSetting, NotificationRule, UserGroup
from app.services import geofence_engine
from app.services import portal_alert_service as alerts

logger = logging.getLogger(__name__)


def _utc(dt: datetime) -> datetime:
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def process(db: Session, imei: str, usergroup_id, rows: list) -> int:
    """rows: new events ({event_type, recorded_at, latitude, longitude, speed}). Returns alerts raised. Does not commit."""
    codes = {r.get("event_type") for r in rows if r.get("event_type")}
    if not codes or not usergroup_id:
        return 0
    rules = db.query(NotificationRule).filter(NotificationRule.usergroup_id == usergroup_id,
                                              NotificationRule.is_active == True,  # noqa: E712
                                              NotificationRule.rule_type == "event").all()
    if not rules:
        return 0
    group_codes = {g.id: set(g.codes or []) for g in db.query(EventTypeGroup).filter(
        EventTypeGroup.id.in_([r.event_group_id for r in rules if r.event_group_id]))}
    watched = {r.id: set(r.event_codes or []) | group_codes.get(r.event_group_id, set()) for r in rules}
    tag = db.query(BLETag).filter(BLETag.imei == imei).first()
    if tag is None:
        return 0
    category = (((tag.attributes or {}).get("category") or {}).get("value") or "").lower()
    rules = [r for r in rules if watched[r.id] & codes
             and (not r.category or r.category.lower() == category)]
    if not rules:
        return 0
    labels = {s.code: s.label for s in db.query(EventTypeSetting).filter(
        EventTypeSetting.usergroup_id == usergroup_id, EventTypeSetting.label.isnot(None))}
    group = db.get(UserGroup, usergroup_id)
    try:
        tz = ZoneInfo((group.timezone if group else None) or "Africa/Johannesburg")
    except Exception:
        tz = timezone.utc

    raised = 0
    vehicle = tag.description or tag.device_name or tag.imei
    for row in sorted(rows, key=lambda r: r["recorded_at"]):
        code = row.get("event_type")
        matching = [r for r in rules if code in watched[r.id]]
        if not matching:
            continue
        label = labels.get(code) or (EVENTS[code][0] if code in EVENTS else code)
        when = _utc(row["recorded_at"]).astimezone(tz)
        values = {"vehicle": vehicle, "imei": imei, "place": "", "event": label,
                  "time": when.strftime("%d %b %Y %H:%M"), "speed": row.get("speed") or 0,
                  **{k: geofence_engine.vehicle_detail(tag, k) or "—" for k in ("registration", "make", "model", "year", "driver")}}
        title = f"{vehicle}: {label}"
        message = f"{vehicle} reported {label} at {values['time']} ({values['speed']} km/h)."
        meta = {"imei": imei, "event_code": code, "event_label": label, "latitude": row.get("latitude"),
                "longitude": row.get("longitude"), "speed": row.get("speed"), "recorded_at": _utc(row["recorded_at"]).isoformat(),
                "rules": [r.name for r in matching], "registration": values["registration"]}
        try:
            with db.begin_nested():
                alerts.create_alert(db, str(usergroup_id), str(tag.id), alert_type=f"event_{code}",
                                    title=title, message=message, meta_data=meta)
                db.flush()
            raised += 1
        except Exception:
            logger.exception("Event alert for %s (%s) failed", imei, code)
            continue
        for rule in matching:
            if rule.email_enabled and rule.email_recipients:
                text_ = geofence_engine.render(rule.email_message or "{vehicle} ({registration}): {event} at {time}.", values)
                for to in rule.email_recipients:
                    try:
                        alerts._email_svc.send_portal_alert_email(to, f"event_{code}", f"{rule.name}: {title}", text_, meta)
                    except Exception:
                        logger.exception("Rule %s email to %s failed", rule.id, to)
    return raised
