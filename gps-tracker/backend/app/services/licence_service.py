"""Vehicle licence renewal — expiry 12 months after the licence start date, with reminders.

The start date is set in the vehicle editor (attributes.licence_start, YYYY-MM-DD).
An inbox alert and email go out once 7 days before expiry ("licence_expiring")
and once on the day it expires ("licence_expired"); a reminder missed while the
service was down is still sent within a few days.
"""
import logging
from datetime import date, datetime, timedelta, timezone
from typing import Optional
from zoneinfo import ZoneInfo

from sqlalchemy.orm import Session

from app.models import BLETag, UserGroup
from app.models_maintenance import MaintenanceNotice
from app.services.maintenance_service import add_months

logger = logging.getLogger(__name__)

VALID_MONTHS = 12
WARN_DAYS = 7
LATE_GRACE_DAYS = 3   # still send a missed reminder this many days late


def licence_start(attributes: Optional[dict]) -> Optional[date]:
    raw = ((attributes or {}).get("licence_start") or {}).get("value")
    try:
        return date.fromisoformat(raw) if raw else None
    except ValueError:
        return None


def expiry(start: date) -> date:
    return add_months(start, VALID_MONTHS)


def status(start: Optional[date], today: date) -> dict:
    """{start, expires, days_left, state: valid | expiring | expired | unknown}."""
    if not start:
        return {"start": None, "expires": None, "days_left": None, "state": "unknown"}
    ends = expiry(start)
    left = (ends - today).days
    state = "expired" if left <= 0 else "expiring" if left <= WARN_DAYS else "valid"
    return {"start": start.isoformat(), "expires": ends.isoformat(), "days_left": left, "state": state}


def _today(db: Session, group_id) -> date:
    group = db.get(UserGroup, group_id)
    try:
        tz = ZoneInfo((group.timezone if group else None) or "Africa/Johannesburg")
    except Exception:
        tz = timezone.utc
    return datetime.now(tz).date()


def send_reminders(db: Session) -> int:
    """Alerts for licences expiring in 7 days or expiring today (once each). Does not commit."""
    from app.services import portal_alert_service as alerts
    sent, todays = 0, {}
    for tag in db.query(BLETag).filter(BLETag.attributes.op("->>")("licence_start").isnot(None)):
        attrs = tag.attributes or {}
        start, group_id = licence_start(attrs), attrs.get("_created_usergroup_id")
        if not start or not group_id:
            continue
        today = todays.setdefault(group_id, _today(db, group_id))
        ends = expiry(start)
        left = (ends - today).days
        if 0 < left <= WARN_DAYS and left > WARN_DAYS - LATE_GRACE_DAYS - 1:
            stage = "expiring"
        elif -LATE_GRACE_DAYS <= left <= 0:
            stage = "expired"
        else:
            continue
        key = f"licence:{tag.imei}:{ends.isoformat()}:{stage}"
        if db.query(MaintenanceNotice.id).filter(MaintenanceNotice.occurrence == key).first():
            continue
        vehicle = tag.description or tag.device_name or tag.imei
        reg = ((attrs.get("registration") or {}).get("value") or "")
        name = f"{vehicle}{f' ({reg})' if reg else ''}"
        if stage == "expiring":
            title = f"{vehicle}: licence expires in {left} day{'s' if left != 1 else ''}"
            message = f"The vehicle licence for {name} expires on {ends:%d %b %Y}. Renew it before then."
        else:
            title = f"{vehicle}: licence expired"
            message = f"The vehicle licence for {name} expired on {ends:%d %b %Y}. Renew it and update the licence start date in Configuration → Vehicles."
        meta = {"imei": tag.imei, "registration": reg or None, "licence_start": start.isoformat(),
                "licence_expires": ends.isoformat(), "days_left": left}
        atype = f"licence_{stage}"
        alerts.create_alert(db, str(group_id), str(tag.id), alert_type=atype, title=title, message=message, meta_data=meta)
        db.add(MaintenanceNotice(usergroup_id=group_id, occurrence=key))
        db.flush()
        try:
            alerts._notify_group_by_email(db, str(group_id), atype, title, message, meta, imei=tag.imei)
        except Exception:
            logger.exception("Licence email for %s failed", tag.imei)
        sent += 1
    return sent
