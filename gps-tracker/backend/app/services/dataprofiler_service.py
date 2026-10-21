"""DataProfiler routing — provisions reseller IMEIs onto the customer dashboard.

route_device() is the single entry point that turns a ResellerDevice into a
BLETag inside the usergroup its reseller's exchange is linked to. It is
idempotent: phase 1 calls it when an exchange is linked or IMEIs are added,
and the phase 2 event decoder will call it on a device's first event.
"""
import logging
import secrets
from datetime import datetime
from typing import Optional

from sqlalchemy.orm import Session

from app.admin_auth import hash_password, verify_password
from app.dataprofiler.dictionary import CATEGORIES, CATEGORY_KEYS
from app.models import BLETag, UserGroup
from app.models_admin import TagPackage
from app.models_dataprofiler import DataExchange, Reseller, ResellerDevice

logger = logging.getLogger(__name__)

# tag_type stored on provisioned tags. Push-only: the location poller skips it.
TELTONIKA_TAG_TYPE = "teltonika"

# Event categories a package can expose to the customer dashboard
# (each decoded event code belongs to one; see app.dataprofiler.dictionary).
EVENT_TYPES = CATEGORIES
EVENT_TYPE_KEYS = CATEGORY_KEYS


def generate_exchange_credentials() -> tuple[str, str]:
    """Return (exchange_key, plaintext_secret). Only the secret's hash is stored."""
    return f"dx_{secrets.token_hex(8)}", secrets.token_urlsafe(24)


def create_exchange(db: Session, reseller: Reseller) -> tuple[DataExchange, str]:
    key, secret = generate_exchange_credentials()
    exchange = DataExchange(
        reseller_id=reseller.id,
        exchange_key=key,
        secret_hash=hash_password(secret),
        status="pending",
    )
    db.add(exchange)
    db.flush()
    return exchange, secret


def rotate_exchange_secret(exchange: DataExchange) -> str:
    _, secret = generate_exchange_credentials()
    exchange.secret_hash = hash_password(secret)
    return secret


def verify_exchange_secret(exchange: DataExchange, secret: str) -> bool:
    try:
        return verify_password(exchange.secret_hash, secret)
    except Exception:
        return False


def _effective_package(db: Session, device: ResellerDevice, reseller: Reseller) -> Optional[TagPackage]:
    pkg_id = device.package_id or reseller.default_package_id
    if not pkg_id:
        return None
    return db.query(TagPackage).filter(TagPackage.id == pkg_id, TagPackage.is_active == True).first()


def route_device(db: Session, device: ResellerDevice) -> str:
    """Provision one device into its exchange's usergroup. Returns the new status.

    Leaves the device 'pending' when there is nothing to route to yet, and marks
    it 'conflict' when the IMEI already belongs to another group on the dashboard.
    Does not commit.
    """
    reseller = device.reseller
    exchange = reseller.exchange if reseller else None
    if not reseller or not reseller.is_active:
        device.status, device.status_detail = "pending", "Reseller is inactive"
        return device.status
    if not exchange or exchange.status != "linked" or not exchange.usergroup_id:
        device.status, device.status_detail = "pending", "Exchange not linked to a user group"
        return device.status

    group_id = str(exchange.usergroup_id)
    existing = db.query(BLETag).filter(BLETag.imei == device.imei).first()
    if existing:
        owner_group = (existing.attributes or {}).get("_created_usergroup_id")
        if owner_group != group_id:
            device.status = "conflict"
            device.status_detail = "IMEI already registered on the dashboard outside this exchange"
            return device.status
        device.ble_tag_id = existing.id
    else:
        pkg = _effective_package(db, device, reseller)
        if not pkg:
            device.status, device.status_detail = "pending", "No active package assigned"
            return device.status
        now = datetime.utcnow()
        tag = BLETag(
            imei=device.imei,
            device_name=device.label or None,
            device_model=device.unit_type.name if device.unit_type else None,
            tag_type=TELTONIKA_TAG_TYPE,
            is_active=True,
            package_id=str(pkg.id),
            expiry_date=pkg.expiry_from(now),
            attributes={
                "_created_usergroup_id": group_id,
                "_reseller_id": str(reseller.id),
                "_exchange_id": str(exchange.id),
            },
        )
        db.add(tag)
        db.flush()
        device.ble_tag_id = tag.id
        logger.info("DataProfiler: routed IMEI %s to usergroup %s (package %s)", device.imei, group_id, pkg.name)

    device.status, device.status_detail = "routed", None
    if not device.first_routed_at:
        device.first_routed_at = datetime.utcnow()
    return device.status


def route_reseller_devices(db: Session, reseller: Reseller) -> dict:
    """Try to route every not-yet-routed device of a reseller. Returns status counts."""
    counts = {"routed": 0, "pending": 0, "conflict": 0}
    for device in reseller.devices:
        if device.status == "routed" and device.ble_tag_id:
            continue
        counts[route_device(db, device)] += 1
    return counts


def link_exchange(db: Session, exchange: DataExchange, group: UserGroup, linked_by: str) -> dict:
    """Link an exchange 1:1 to a usergroup and route its reseller's devices.

    Raises ValueError when either side is already linked elsewhere. Does not commit.
    """
    if exchange.status == "disabled":
        raise ValueError("This exchange is disabled")
    if exchange.usergroup_id and str(exchange.usergroup_id) != str(group.id):
        raise ValueError("This exchange is already linked to another user group")
    other = db.query(DataExchange).filter(
        DataExchange.usergroup_id == group.id, DataExchange.id != exchange.id
    ).first()
    if other:
        raise ValueError("This user group is already linked to another exchange")

    exchange.usergroup_id = group.id
    exchange.status = "linked"
    exchange.linked_at = datetime.utcnow()
    exchange.linked_by = linked_by
    db.flush()
    return route_reseller_devices(db, exchange.reseller)


def unlink_exchange(db: Session, exchange: DataExchange) -> None:
    """Detach an exchange from its usergroup.

    Tags already provisioned stay on the dashboard (the customer keeps history);
    devices revert to 'pending' so a future link re-routes them.
    """
    exchange.usergroup_id = None
    exchange.status = "pending"
    exchange.linked_at = None
    exchange.linked_by = None
    for device in exchange.reseller.devices:
        device.status, device.status_detail, device.ble_tag_id = "pending", "Exchange unlinked", None
