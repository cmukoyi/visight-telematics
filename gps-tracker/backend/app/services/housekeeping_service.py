"""Device lifecycle housekeeping (runs inside the backend process).

  every 5 min   offline alerts for active devices that stopped reporting
  hourly        purge portal alerts past their retention
  daily         package expiry: one deletion warning at expiry, then delete
                the device and its data TAG_DELETE_GRACE_DAYS later

delete_tag() is the single place a device and its data are removed; the
portal, admin and expiry paths all use it.
"""
import asyncio
import logging
from datetime import datetime, timedelta

from sqlalchemy.orm import Session

from app.database import SessionLocal
from app.models import BLETag, DevicePosition, GeofenceAlert, POITrackerLink, PortalAlert
from app.models_dataprofiler import DeviceEvent
from app.services import portal_alert_service

logger = logging.getLogger(__name__)

TAG_DELETE_GRACE_DAYS = portal_alert_service.TAG_DELETE_GRACE_DAYS
OFFLINE_CHECK_INTERVAL_S = 300
PURGE_INTERVAL_S = 3600
EXPIRY_INTERVAL_S = 86400


def delete_tag(db: Session, tag: BLETag, reason: str = "deleted") -> dict:
    """Delete a device and everything keyed to it. Does not commit."""
    counts = {
        "poi_links": db.query(POITrackerLink).filter(POITrackerLink.tracker_id == tag.id)
                       .delete(synchronize_session=False),
        "geofence_alerts": db.query(GeofenceAlert).filter(GeofenceAlert.tracker_id == tag.id)
                             .delete(synchronize_session=False),
        "alerts_detached": db.query(PortalAlert).filter(PortalAlert.tag_id == tag.id)
                             .update({PortalAlert.tag_id: None}, synchronize_session=False),
    }
    if tag.imei:
        counts["positions"] = db.query(DevicePosition).filter(DevicePosition.device_imei == tag.imei) \
                                .delete(synchronize_session=False)
        counts["events"] = db.query(DeviceEvent).filter(DeviceEvent.imei == tag.imei) \
                             .delete(synchronize_session=False)
    db.delete(tag)
    logger.info("Device %s %s: %s", tag.imei or tag.id, reason, counts)
    return counts


def check_offline(db: Session) -> int:
    now = datetime.utcnow()
    tags = db.query(BLETag).filter(BLETag.is_active == True, BLETag.last_seen.isnot(None)).all()
    created = 0
    for tag in tags:
        if tag.expiry_date and tag.expiry_date.replace(tzinfo=None) < now:
            continue
        created += bool(portal_alert_service.check_offline_alert(db, tag))
    return created


def enforce_expiry(db: Session) -> tuple[int, int]:
    """Warn once at expiry; delete after the grace period. Returns (warned, deleted)."""
    now = datetime.utcnow()
    warned = 0
    for tag in db.query(BLETag).filter(BLETag.expiry_date.isnot(None), BLETag.expiry_date <= now,
                                       BLETag.gdpr_deletion_warned_at.is_(None)).all():
        portal_alert_service.send_gdpr_deletion_warning(db, tag)
        tag.gdpr_deletion_warned_at = now
        warned += 1
    cutoff = now - timedelta(days=TAG_DELETE_GRACE_DAYS)
    deleted = 0
    for tag in db.query(BLETag).filter(BLETag.expiry_date.isnot(None), BLETag.expiry_date <= cutoff).all():
        delete_tag(db, tag, reason=f"expired {tag.expiry_date:%Y-%m-%d}")
        deleted += 1
    return warned, deleted


async def _every(interval_s: int, name: str, job) -> None:
    while True:
        try:
            with SessionLocal() as db:
                result = job(db)
                db.commit()
            if result and (not isinstance(result, tuple) or any(result)):
                logger.info("Housekeeping %s: %s", name, result)
        except Exception:
            logger.exception("Housekeeping %s failed", name)
        await asyncio.sleep(interval_s)


def start() -> list[asyncio.Task]:
    return [
        asyncio.create_task(_every(OFFLINE_CHECK_INTERVAL_S, "offline alerts", check_offline)),
        asyncio.create_task(_every(PURGE_INTERVAL_S, "alert purge", portal_alert_service.purge_old_alerts)),
        asyncio.create_task(_every(EXPIRY_INTERVAL_S, "package expiry", enforce_expiry)),
    ]
