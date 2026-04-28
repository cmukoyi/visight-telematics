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


def _groups_for_tag(db: Session, tag: BLETag) -> list[str]:
    """Return all usergroup_ids that should receive alerts for this tag.

    Priority order:
      1. POI-based: find all active UserGroups that own POIs this tag is armed to
         (POITrackerLink → POI.usergroup_id).  This is the correct structural link.
      2. Email-domain fallback: match the tag owner's email domain against
         UserGroup.email_domain — used for groups that don't use portal-managed POIs.

    Returns a deduplicated list of group ID strings (may be empty).
    """
    from app.models import User, UserGroup, POI, POITrackerLink
    found: dict[str, bool] = {}  # ordered dedup

    # ── 1. Via POI tracker links ───────────────────────────────────────────
    poi_links = (
        db.query(POITrackerLink)
        .filter(POITrackerLink.tracker_id == tag.id)
        .all()
    )
    poi_ids = [lnk.poi_id for lnk in poi_links]
    if poi_ids:
        pois_with_group = (
            db.query(POI)
            .filter(POI.id.in_(poi_ids), POI.usergroup_id.isnot(None), POI.is_active == True)
            .all()
        )
        for poi in pois_with_group:
            found[str(poi.usergroup_id)] = True

    # ── 2. Email-domain fallback ───────────────────────────────────────────
    if not found:
        user = db.query(User).filter(User.id == tag.user_id).first()
        if user and user.email and "@" in user.email:
            domain = user.email.split("@")[-1].lower()
            groups = (
                db.query(UserGroup)
                .filter(UserGroup.email_domain.isnot(None), UserGroup.is_active == True)
                .all()
            )
            for g in groups:
                domains = [d.strip().lower() for d in (g.email_domain or "").split(",")]
                if domain in domains:
                    found[str(g.id)] = True

    return list(found.keys())


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
    group_ids = _groups_for_tag(db, tag)
    if not group_ids:
        logger.debug("No group found for tag %s — battery alert skipped", tag.imei)
        return False
    label = _tag_label(tag)
    tag_id = str(tag.id)
    created = False
    for usergroup_id in group_ids:
        if _recent_alert_exists(db, usergroup_id, tag_id, "battery_low", BATTERY_DEDUPE_HOURS):
            continue
        create_alert(
            db, usergroup_id, tag_id,
            alert_type="battery_low",
            title=f"Low battery — {label}",
            message=f"{label} has a battery level of {tag.battery_level}%. Please recharge or replace the battery soon.",
            meta_data={"battery": tag.battery_level, "imei": tag.imei},
        )
        logger.info("🔋 Battery-low alert created for tag %s (%d%%) → group %s", tag.imei, tag.battery_level, usergroup_id)
        created = True
    return created


def check_offline_alert(db: Session, tag: BLETag) -> bool:
    """Generate a tag_offline alert if tag hasn't been seen for >= OFFLINE_THRESHOLD_DAYS."""
    if not tag.last_seen:
        return False
    last_seen = tag.last_seen.replace(tzinfo=None) if tag.last_seen.tzinfo else tag.last_seen
    age_days = (datetime.utcnow() - last_seen).days
    if age_days < OFFLINE_THRESHOLD_DAYS:
        return False
    group_ids = _groups_for_tag(db, tag)
    if not group_ids:
        logger.debug("No group found for tag %s — offline alert skipped", tag.imei)
        return False
    label = _tag_label(tag)
    tag_id = str(tag.id)
    last_seen_str = tag.last_seen.isoformat()
    created = False
    for usergroup_id in group_ids:
        if _recent_alert_exists(db, usergroup_id, tag_id, "tag_offline", OFFLINE_DEDUPE_HOURS):
            continue
        create_alert(
            db, usergroup_id, tag_id,
            alert_type="tag_offline",
            title=f"Tag offline — {label}",
            message=f"{label} hasn't been detected for {age_days} days. Check the device or its location.",
            meta_data={"days_offline": age_days, "last_seen": last_seen_str, "imei": tag.imei},
        )
        logger.info("📡 Offline alert created for tag %s (%d days) → group %s", tag.imei, age_days, usergroup_id)
        created = True
    return created


def create_geofence_alert(db: Session, tag: BLETag, poi_name: str, poi_id: str,
                           event_type: str) -> bool:
    """Generate a geofence_entry or geofence_exit PortalAlert."""
    from app.models import POI
    # For geofence alerts prefer the POI's own group first (most specific)
    poi = db.query(POI).filter(POI.id == poi_id).first()
    if poi and poi.usergroup_id:
        group_ids = [str(poi.usergroup_id)]
    else:
        group_ids = _groups_for_tag(db, tag)
    if not group_ids:
        return False
    is_entry = "enter" in event_type.lower()
    atype = "geofence_entry" if is_entry else "geofence_exit"
    label = _tag_label(tag)
    verb = "entered" if is_entry else "exited"
    tag_id = str(tag.id)
    for usergroup_id in group_ids:
        create_alert(
            db, usergroup_id, tag_id,
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
