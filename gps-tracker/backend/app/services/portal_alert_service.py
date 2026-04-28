"""
Service for generating unified portal alerts (battery low, tag offline, geofence).

Called by:
  - location_poller_service  (battery_low, tag_offline, purge old alerts)
  - geofence_service         (geofence_entry, geofence_exit)
"""
import logging
import uuid
from datetime import datetime, timedelta
from sqlalchemy.orm import Session

from app.models import PortalAlert, BLETag, PortalUser

logger = logging.getLogger(__name__)

BATTERY_LOW_THRESHOLD = 20          # %
OFFLINE_THRESHOLD_DAYS = 7          # days with no last_seen
ALERT_RETENTION_DAYS = 7            # purge alerts older than this
BATTERY_DEDUPE_HOURS = 24           # re-raise battery alert at most once per day
OFFLINE_DEDUPE_HOURS = 24           # same for offline


def _tag_label(tag: BLETag) -> str:
    return tag.description or tag.device_name or tag.imei or str(tag.id)


def _group_for_tag(db: Session, tag: BLETag) -> str | None:
    """Return the usergroup_id for the portal group that owns this tag's user."""
    from app.models import User, UserGroup
    user = db.query(User).filter(User.id == tag.user_id).first()
    if not user:
        return None
    group = (
        db.query(UserGroup)
        .filter(
            UserGroup.email_domain.isnot(None),
            UserGroup.is_active == True,
        )
        .all()
    )
    domain = user.email.split("@")[-1].lower() if user.email and "@" in user.email else None
    if not domain:
        return None
    for g in group:
        domains = [d.strip().lower() for d in (g.email_domain or "").split(",")]
        if domain in domains:
            return str(g.id)
    return None


def _recent_alert_exists(db: Session, usergroup_id: str, tag_id: str,
                          alert_type: str, within_hours: int) -> bool:
    """True if an alert of this type for this tag already exists within N hours."""
    since = datetime.utcnow() - timedelta(hours=within_hours)
    return db.query(PortalAlert).filter(
        PortalAlert.usergroup_id == usergroup_id,
        PortalAlert.tag_id == tag_id,
        PortalAlert.alert_type == alert_type,
        PortalAlert.created_at >= since,
    ).first() is not None


def create_alert(db: Session, usergroup_id: str, tag_id: str | None,
                 alert_type: str, title: str, message: str,
                 meta_data: dict | None = None) -> PortalAlert:
    """Insert a new PortalAlert row."""
    alert = PortalAlert(
        id=str(uuid.uuid4()),
        usergroup_id=usergroup_id,
        tag_id=tag_id,
        alert_type=alert_type,
        title=title,
        message=message,
        is_read=False,
        meta_data=meta_data or {},
    )
    db.add(alert)
    return alert


def check_battery_alert(db: Session, tag: BLETag) -> bool:
    """Generate a battery_low alert if battery < threshold and not raised recently."""
    if tag.battery_level is None or tag.battery_level > BATTERY_LOW_THRESHOLD:
        return False
    usergroup_id = _group_for_tag(db, tag)
    if not usergroup_id:
        return False
    if _recent_alert_exists(db, usergroup_id, str(tag.id), "battery_low", BATTERY_DEDUPE_HOURS):
        return False
    label = _tag_label(tag)
    create_alert(
        db, usergroup_id, str(tag.id),
        alert_type="battery_low",
        title=f"Low battery — {label}",
        message=f"{label} has a battery level of {tag.battery_level}%. Please recharge or replace the battery soon.",
        meta_data={"battery": tag.battery_level, "imei": tag.imei},
    )
    logger.info("🔋 Battery-low alert created for tag %s (%d%%)", tag.imei, tag.battery_level)
    return True


def check_offline_alert(db: Session, tag: BLETag) -> bool:
    """Generate a tag_offline alert if tag hasn't been seen for >7 days."""
    if not tag.last_seen:
        return False
    last_seen = tag.last_seen.replace(tzinfo=None) if tag.last_seen.tzinfo else tag.last_seen
    age_days = (datetime.utcnow() - last_seen).days
    if age_days < OFFLINE_THRESHOLD_DAYS:
        return False
    usergroup_id = _group_for_tag(db, tag)
    if not usergroup_id:
        return False
    if _recent_alert_exists(db, usergroup_id, str(tag.id), "tag_offline", OFFLINE_DEDUPE_HOURS):
        return False
    label = _tag_label(tag)
    create_alert(
        db, usergroup_id, str(tag.id),
        alert_type="tag_offline",
        title=f"Tag offline — {label}",
        message=f"{label} hasn't been detected for {age_days} days. Check the device or its location.",
        meta_data={"days_offline": age_days, "last_seen": tag.last_seen.isoformat(), "imei": tag.imei},
    )
    logger.info("📡 Offline alert created for tag %s (%d days)", tag.imei, age_days)
    return True


def create_geofence_alert(db: Session, tag: BLETag, poi_name: str, poi_id: str,
                           event_type: str) -> bool:
    """Generate a geofence_entry or geofence_exit PortalAlert."""
    usergroup_id = _group_for_tag(db, tag)
    if not usergroup_id:
        return False
    is_entry = "enter" in event_type.lower()
    atype = "geofence_entry" if is_entry else "geofence_exit"
    label = _tag_label(tag)
    verb = "entered" if is_entry else "exited"
    create_alert(
        db, usergroup_id, str(tag.id),
        alert_type=atype,
        title=f"Geofence {verb} — {label}",
        message=f"{label} has {verb} the zone '{poi_name}'.",
        meta_data={"poi_name": poi_name, "poi_id": poi_id, "imei": tag.imei,
                   "event_type": event_type},
    )
    return True


def purge_old_alerts(db: Session) -> int:
    """Delete portal_alerts older than ALERT_RETENTION_DAYS. Returns count deleted."""
    cutoff = datetime.utcnow() - timedelta(days=ALERT_RETENTION_DAYS)
    deleted = db.query(PortalAlert).filter(PortalAlert.created_at < cutoff).delete()
    if deleted:
        logger.info("🧹 Purged %d portal alerts older than %d days", deleted, ALERT_RETENTION_DAYS)
    return deleted
