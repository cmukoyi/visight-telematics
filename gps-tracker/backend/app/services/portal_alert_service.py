"""
Service for generating unified portal alerts (battery low, tag offline, geofence, GDPR deletion).

Called by:
  - housekeeping_service     (tag_offline, purge old alerts, package expiry)
  - geofence_service         (geofence_entry, geofence_exit)
  - main._gdpr_cleanup_loop  (gdpr_deletion_warning)
"""
import logging
from datetime import datetime, timedelta
from sqlalchemy.orm import Session

from app.models import PortalAlert, BLETag, PortalUser, UserGroup
from app.database import SessionLocal
from app.services.email_service import EmailService
from app.services.sms_service import sms_service as _sms_svc

logger = logging.getLogger(__name__)

# Shared email service instance (re-uses SendGrid key from env)
_email_svc = EmailService()

BATTERY_LOW_THRESHOLD = 20          # %
OFFLINE_THRESHOLD_DAYS = 7          # days with no last_seen
ALERT_RETENTION_DAYS = 7            # purge alerts older than this
BATTERY_DEDUPE_HOURS = 24           # re-raise battery alert at most once per day
OFFLINE_DEDUPE_HOURS = 24           # same for offline
TEMPERATURE_DEDUPE_HOURS = 6        # avoid repeating a persistent breach


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
                          alert_type: str, within_hours: float) -> bool:
    """True if an alert of this type for this tag already exists within N hours (fractional OK)."""
    since = datetime.utcnow() - timedelta(seconds=within_hours * 3600)
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


# ── SMS flag per alert type ─────────────────────────────────────────────────
_SMS_FLAG = {
    "battery_low":           "notify_battery_sms",
    "tag_offline":           "notify_offline_sms",
    "geofence_entry":        "notify_geofence_sms",
    "geofence_exit":         "notify_geofence_sms",
    "gdpr_deletion_warning": "sms_enabled",
}

# ── Notify flag per alert type ────────────────────────────────────────────────
_NOTIFY_FLAG = {
    "battery_low":           "notify_battery_low",
    "tag_offline":           "notify_offline",
    "geofence_entry":        "notify_geofence_exit",   # same preference covers both directions
    "geofence_exit":         "notify_geofence_exit",
    "gdpr_deletion_warning": "alerts_enabled",         # always send if alerts are on
    "temperature_high":      "notify_temperature",
    "temperature_low":       "notify_temperature",
}


def _group_has_temperature_subscriber(db: Session, usergroup_id: str) -> bool:
    """Return whether an active group member opted into temperature alerts."""
    import uuid as _uuid
    try:
        group_id = _uuid.UUID(usergroup_id)
    except (ValueError, TypeError):
        return False
    return db.query(PortalUser).filter(
        PortalUser.usergroup_id == group_id,
        PortalUser.is_active == True,
        PortalUser.alerts_enabled == True,
        PortalUser.notify_temperature == True,
    ).first() is not None


def check_temperature_alert(db: Session, tag: BLETag, temperature_c: float) -> bool:
    """Create a deduplicated alert when a tag crosses its configured limit."""
    config = (tag.attributes or {}).get("_temperature_monitoring")
    if not isinstance(config, dict) or not config.get("enabled"):
        return False
    try:
        high_c = float(config["high_c"])
        low_c = float(config["low_c"])
    except (KeyError, TypeError, ValueError):
        return False
    if low_c < temperature_c < high_c:
        return False

    alert_type = "temperature_high" if temperature_c >= high_c else "temperature_low"
    boundary = high_c if alert_type == "temperature_high" else low_c
    group_ids = _groups_for_tag(db, tag)
    label = _tag_label(tag)
    tag_id = str(tag.id)
    created = False
    for usergroup_id in group_ids:
        if not _group_has_temperature_subscriber(db, usergroup_id):
            continue
        if _recent_alert_exists(db, usergroup_id, tag_id, alert_type, TEMPERATURE_DEDUPE_HOURS):
            continue
        direction = "above" if alert_type == "temperature_high" else "below"
        title = f"Temperature {direction} threshold — {label}"
        message = f"{label} reported {temperature_c:.1f}°C, {direction} the configured limit of {boundary:.1f}°C."
        meta = {"temperature_c": temperature_c, "threshold_c": boundary, "imei": tag.imei}
        create_alert(db, usergroup_id, tag_id, alert_type, title, message, meta)
        _notify_group_by_email(db, usergroup_id, alert_type, title, message, meta)
        _notify_group_by_sms(db, usergroup_id, alert_type, title, message)
        created = True
        logger.info("Temperature %s alert created for tag %s -> group %s", alert_type, tag.imei, usergroup_id)
    return created


def _may_receive(db: Session, user: PortalUser, imei: str | None) -> bool:
    """Whether the user's role and security group let them see an alert about this vehicle."""
    from app.services import access_service
    access = access_service.for_user(user, db)
    return access.can("inbox.view") and (imei is None or access.can_see(db, imei))


def _notify_group_by_sms(db: Session, usergroup_id: str, alert_type: str,
                         title: str, message: str, imei: str | None = None) -> None:
    """Send an SMS alert to all opted-in portal users in the group.

    Only fires if:
      - The UserGroup has sms_enabled=True
      - The PortalUser has sms_enabled=True and a phone_number set
      - The per-type SMS flag is True for that user
    Uses its own DB session, isolated from the caller's transaction.
    """
    import uuid as _uuid
    flag = _SMS_FLAG.get(alert_type, "sms_enabled")
    notify_db = SessionLocal()
    try:
        try:
            gid = _uuid.UUID(usergroup_id)
        except ValueError:
            return

        group = notify_db.query(UserGroup).filter(UserGroup.id == gid).first()
        if not group or not getattr(group, 'sms_enabled', False):
            return

        users = notify_db.query(PortalUser).filter(
            PortalUser.usergroup_id == gid,
            PortalUser.is_active == True,
            PortalUser.alerts_enabled == True,
            PortalUser.sms_enabled == True,
        ).all()

        for pu in users:
            if not getattr(pu, flag, True):
                continue
            if not getattr(pu, 'phone_number', None):
                continue
            if not _may_receive(notify_db, pu, imei):
                continue
            ok = _sms_svc.send_alert(pu.phone_number, alert_type, title, message)
            if ok:
                logger.info("📱 Alert SMS sent to %s (%s)", pu.phone_number, alert_type)
            else:
                logger.warning("📱 Failed SMS to %s (%s)", pu.phone_number, alert_type)

    except Exception as exc:
        logger.error("Failed to send SMS alerts for group %s: %s", usergroup_id, exc)
    finally:
        notify_db.close()


def _notify_group_by_email(db: Session, usergroup_id: str, alert_type: str,
                            title: str, message: str,
                            meta_data: dict | None = None, imei: str | None = None) -> None:
    """Send a one-shot email for a new alert to all opted-in portal users in the group.

    Uses its own DB session so it is completely isolated from the caller's
    in-flight transaction (prevents PendingRollbackError / InFailedSqlTransaction
    from silently killing every email send).

    Respects per-user flags: alerts_enabled, notify_via_email, and the
    specific notify_battery_low / notify_offline / notify_geofence_exit flag.
    Also sends to any extra addresses in PortalUser.notification_emails.
    """
    flag = _NOTIFY_FLAG.get(alert_type, "alerts_enabled")
    notify_db = SessionLocal()
    try:
        import uuid as _uuid
        try:
            gid = _uuid.UUID(usergroup_id)
        except ValueError:
            logger.error("_notify_group_by_email: invalid usergroup_id %r", usergroup_id)
            return

        users = notify_db.query(PortalUser).filter(
            PortalUser.usergroup_id == gid,
            PortalUser.is_active == True,
            PortalUser.alerts_enabled == True,
            PortalUser.notify_via_email == True,
        ).all()

        if not users:
            logger.debug("No opted-in portal users for group %s — email skipped", usergroup_id)
            return

        sent_to: set[str] = set()

        for pu in users:
            # Check the specific per-type flag
            if not getattr(pu, flag, True):
                continue
            # Only users allowed to see this vehicle (role + security group)
            if not _may_receive(notify_db, pu, imei):
                continue

            # Primary address
            if pu.email and pu.email not in sent_to:
                ok = _email_svc.send_portal_alert_email(
                    pu.email, alert_type, title, message, meta_data
                )
                if ok:
                    sent_to.add(pu.email)
                    logger.info("📧 Alert email sent to %s (%s)", pu.email, alert_type)
                else:
                    logger.warning("📧 Failed to send alert email to %s (%s)", pu.email, alert_type)

            # Extra notification addresses
            for extra in (pu.notification_emails or []):
                if isinstance(extra, str) and extra.strip() and extra not in sent_to:
                    ok = _email_svc.send_portal_alert_email(
                        extra.strip(), alert_type, title, message, meta_data
                    )
                    if ok:
                        sent_to.add(extra.strip())

    except Exception as exc:
        logger.error("Failed to send alert notification emails for group %s: %s", usergroup_id, exc)
    finally:
        notify_db.close()


def check_battery_alert(db: Session, tag: BLETag) -> bool:
    """Generate a battery_low alert if battery < threshold and not raised recently.
    
    Stops generating new alerts after 3 notifications to prevent endless emails
    when battery reaches 0% and stays there.
    """
    if tag.battery_level is None or tag.battery_level > BATTERY_LOW_THRESHOLD:
        return False
    group_ids = _groups_for_tag(db, tag)
    if not group_ids:
        logger.debug("No group found for tag %s — battery alert skipped", tag.imei)
        return False
    
    # Count total battery_low alerts for this tag across all groups
    # Stop after 3 notifications to prevent endless email spam at 0%
    tag_id = str(tag.id)
    total_battery_alerts = db.query(PortalAlert).filter(
        PortalAlert.tag_id == tag_id,
        PortalAlert.alert_type == "battery_low"
    ).count()
    
    if total_battery_alerts >= 3:
        logger.debug("🔋 Battery alert limit reached for tag %s (3 notifications sent) — suppressing further alerts", tag.imei)
        return False
    
    label = _tag_label(tag)
    created = False
    for usergroup_id in group_ids:
        if _recent_alert_exists(db, usergroup_id, tag_id, "battery_low", BATTERY_DEDUPE_HOURS):
            continue
        _title = f"Low battery — {label}"
        _msg   = f"{label} has a battery level of {tag.battery_level}%. Please recharge or replace the battery soon."
        _meta  = {"battery": tag.battery_level, "imei": tag.imei}
        create_alert(db, usergroup_id, tag_id, alert_type="battery_low",
                     title=_title, message=_msg, meta_data=_meta)
        _notify_group_by_email(db, usergroup_id, "battery_low", _title, _msg, _meta)
        _notify_group_by_sms(db, usergroup_id, "battery_low", _title, _msg)
        logger.info("🔋 Battery-low alert created for tag %s (%d%%) → group %s (count: %d/3)", tag.imei, tag.battery_level, usergroup_id, total_battery_alerts + 1)
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
        _title = f"Tag offline — {label}"
        _msg   = f"{label} hasn't been detected for {age_days} days. Check the device or its location."
        _meta  = {"days_offline": age_days, "last_seen": last_seen_str, "imei": tag.imei}
        create_alert(db, usergroup_id, tag_id, alert_type="tag_offline",
                     title=_title, message=_msg, meta_data=_meta)
        _notify_group_by_email(db, usergroup_id, "tag_offline", _title, _msg, _meta)
        _notify_group_by_sms(db, usergroup_id, "tag_offline", _title, _msg)
        logger.info("📡 Offline alert created for tag %s (%d days) → group %s", tag.imei, age_days, usergroup_id)
        created = True
    return created


def create_geofence_alert(db: Session, tag: BLETag, poi_name: str, poi_id: str,
                           event_type: str) -> bool:
    """Generate a geofence_entry or geofence_exit PortalAlert.

    Deduped: at most one alert per (group, tag, alert_type) per 24 hours.
    Catches UniqueViolation and rolls back cleanly so the caller's session
    is never left in a failed-transaction state.
    """
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
    # Normalise the event_type stored in meta so it always matches the alert
    # type ('entry'/'exit') regardless of what the caller passed in
    # (the GeofenceEventType enum's `.value` for EXIT is 'EXIT' in some
    #  paths and 'exit' in others, plus we don't want stale 'entry' on an
    #  EXIT row to confuse downstream consumers).
    canonical_event = "entry" if is_entry else "exit"
    _meta = {"poi_name": poi_name, "poi_id": poi_id, "imei": tag.imei,
             "event_type": canonical_event,
             "latitude": float(tag.latitude) if tag.latitude else None,
             "longitude": float(tag.longitude) if tag.longitude else None}
    created = False
    for usergroup_id in group_ids:
        # ── Dedupe: skip if same alert already raised in the last 5 min ──
        # (state machine already enforces strict EXIT↔ENTRY pairing; this
        #  guard only catches rapid GPS-jitter duplicates slipping through)
        if _recent_alert_exists(db, usergroup_id, tag_id, atype, within_hours=0.083):
            logger.debug("Geofence alert dedupe: %s for tag %s group %s — skipped",
                         atype, tag.imei, usergroup_id)
            continue
        _title = f"Geofence {verb} — {label}"
        _msg   = f"{label} has {verb} the zone '{poi_name}'."
        # IMPORTANT: wrap the insert in a SAVEPOINT so that if the per-day
        # unique constraint (uq_portal_alert_per_day) trips, ONLY the alert
        # insert is rolled back — not the caller's geofence-state update.
        # Previously a db.rollback() here was wiping the
        # last_known_state INSIDE→OUTSIDE change in geofence_service,
        # causing the same transition to re-fire on every poll (every 10s
        # after the poll-interval change), spamming the DB with
        # duplicate-key errors and never actually transitioning state.
        try:
            with db.begin_nested():   # SAVEPOINT
                create_alert(db, usergroup_id, tag_id, alert_type=atype,
                             title=_title, message=_msg, meta_data=_meta)
                # flush inside savepoint so IntegrityError raises here
                db.flush()
        except Exception as exc:
            logger.debug("Geofence alert insert skipped (already exists today): %s", exc)
            continue
        _notify_group_by_email(db, usergroup_id, atype, _title, _msg, _meta)
        _notify_group_by_sms(db, usergroup_id, atype, _title, _msg)
        logger.info("🚨 Geofence alert created: %s for tag %s → group %s",
                    atype, tag.imei, usergroup_id)
        created = True
    return created


def purge_old_alerts(db: Session) -> int:
    """Delete portal_alerts older than ALERT_RETENTION_DAYS. Returns count deleted."""
    cutoff = datetime.utcnow() - timedelta(days=ALERT_RETENTION_DAYS)
    deleted = db.query(PortalAlert).filter(PortalAlert.created_at < cutoff).delete()
    if deleted:
        logger.info("🧹 Purged %d portal alerts older than %d days", deleted, ALERT_RETENTION_DAYS)
    return deleted


TAG_DELETE_GRACE_DAYS = 7  # days after expiry before hard deletion


def send_gdpr_deletion_warning(db: Session, tag: BLETag) -> bool:
    """Send a one-time inbox alert + email warning that the tag and all its data
    will be permanently deleted in TAG_DELETE_GRACE_DAYS days.

    Returns True if at least one alert was created (i.e. a group was found).
    The caller must set tag.gdpr_deletion_warned_at and commit after calling this.
    """
    group_ids = _groups_for_tag(db, tag)
    if not group_ids:
        # No group found — still log, deletion will proceed silently
        logger.warning("[GDPR] No group found for tag %s — deletion warning skipped", tag.imei)
        return False

    label       = _tag_label(tag)
    tag_id      = str(tag.id)
    delete_date = (datetime.utcnow() + timedelta(days=TAG_DELETE_GRACE_DAYS)).strftime("%d %B %Y")
    _title = f"Data deletion notice — {label}"
    _msg   = (
        f"The following Tag and all associated data will be permanently deleted in "
        f"{TAG_DELETE_GRACE_DAYS} days as part of our GDPR data retention policy.\n\n"
        f"IMEI: {tag.imei}\n"
        f"Description: {label}\n\n"
        f"Scheduled deletion date: {delete_date}\n\n"
        f"If you wish to keep this tag, please renew its subscription before the deletion date."
    )
    _meta = {
        "imei": tag.imei,
        "tag_description": label,
        "delete_on": delete_date,
    }

    for usergroup_id in group_ids:
        create_alert(db, usergroup_id, tag_id,
                     alert_type="gdpr_deletion_warning",
                     title=_title, message=_msg, meta_data=_meta)
        _notify_group_by_email(db, usergroup_id, "gdpr_deletion_warning", _title, _msg, _meta)
        _notify_group_by_sms(db, usergroup_id, "gdpr_deletion_warning", _title, _msg)
        logger.info("[GDPR] Deletion warning sent for tag %s → group %s (deletes %s)",
                    tag.imei, usergroup_id, delete_date)
    return True
