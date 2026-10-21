"""DataProfiler admin API — unit types, resellers, data exchanges and IMEI inventory.

Mounted under /api/admin/dataprofiler and protected by the admin auth
dependency, like the rest of the admin portal API. Reads need viewer,
writes need manager — the same split as Tag Packages.
"""
import re
from datetime import datetime
from typing import List, Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, field_validator
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.admin_auth import check_role_permission, get_current_admin_user
from app.database import get_db
from app.models import UserGroup
from app.models_admin import AdminUser, TagPackage
from app.models_dataprofiler import DataExchange, Reseller, ResellerDevice, UnitType
from app.routes_admin import get_admin_from_request, log_audit
from app.services import dataprofiler_service as dp

router = APIRouter(
    prefix="/api/admin/dataprofiler",
    tags=["admin-dataprofiler"],
    dependencies=[Depends(get_current_admin_user)],
)

_IMEI_RE = re.compile(r"^\d{14,17}$")
_CODE_RE = re.compile(r"^[a-z0-9][a-z0-9-]{1,48}[a-z0-9]$")


def _require(request: Request, db: Session, role: str) -> AdminUser:
    admin = get_admin_from_request(request, db)
    if not check_role_permission(admin.role, role):
        raise HTTPException(status_code=403, detail=f"Requires {role} role")
    return admin


def _get_reseller(db: Session, reseller_id: str) -> Reseller:
    reseller = db.query(Reseller).filter(Reseller.id == reseller_id).first()
    if not reseller:
        raise HTTPException(status_code=404, detail="Reseller not found")
    return reseller


def _check_unit_type(db: Session, unit_type_id: Optional[str]) -> None:
    if unit_type_id and not db.query(UnitType).filter(
        UnitType.id == unit_type_id, UnitType.is_active == True
    ).first():
        raise HTTPException(status_code=400, detail="Unit type not found or inactive")


def _check_package(db: Session, package_id: Optional[str]) -> None:
    if package_id and not db.query(TagPackage).filter(
        TagPackage.id == package_id, TagPackage.is_active == True
    ).first():
        raise HTTPException(status_code=400, detail="Package not found or inactive")


# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------

class _UUIDOut(BaseModel):
    @field_validator("*", mode="before")
    @classmethod
    def _uuid_to_str(cls, v):
        return str(v) if isinstance(v, UUID) else v

    class Config:
        from_attributes = True


class ExchangeOut(_UUIDOut):
    id: str
    exchange_key: str
    status: str
    usergroup_id: Optional[str] = None
    usergroup_name: Optional[str] = None
    linked_at: Optional[datetime] = None
    linked_by: Optional[str] = None


class ResellerOut(_UUIDOut):
    id: str
    name: str
    code: str
    contact_name: Optional[str] = None
    contact_email: Optional[str] = None
    contact_phone: Optional[str] = None
    notes: Optional[str] = None
    default_package_id: Optional[str] = None
    default_package_name: Optional[str] = None
    is_active: bool
    created_at: Optional[datetime] = None
    exchange: Optional[ExchangeOut] = None
    device_counts: dict = {}


class ResellerCreated(ResellerOut):
    exchange_secret: str  # shown once


class ResellerCreate(BaseModel):
    name: str
    code: str
    contact_name: Optional[str] = None
    contact_email: Optional[str] = None
    contact_phone: Optional[str] = None
    notes: Optional[str] = None
    default_package_id: Optional[str] = None


class ResellerUpdate(BaseModel):
    name: Optional[str] = None
    contact_name: Optional[str] = None
    contact_email: Optional[str] = None
    contact_phone: Optional[str] = None
    notes: Optional[str] = None
    default_package_id: Optional[str] = None
    is_active: Optional[bool] = None


class LinkRequest(BaseModel):
    usergroup_id: str


class DeviceRow(BaseModel):
    imei: str
    label: Optional[str] = None


class DevicesAdd(BaseModel):
    devices: List[DeviceRow]
    unit_type_id: str
    package_id: Optional[str] = None  # NULL = reseller default


class DeviceUpdate(BaseModel):
    label: Optional[str] = None
    unit_type_id: Optional[str] = None
    package_id: Optional[str] = None


class UnitTypeIn(BaseModel):
    manufacturer: str
    model: str
    description: Optional[str] = None


class UnitTypeUpdate(BaseModel):
    manufacturer: Optional[str] = None
    model: Optional[str] = None
    description: Optional[str] = None
    is_active: Optional[bool] = None


class UnitTypeOut(_UUIDOut):
    id: str
    manufacturer: str
    model: str
    name: str
    description: Optional[str] = None
    is_active: bool
    device_count: int = 0
    created_at: Optional[datetime] = None


class DeviceOut(_UUIDOut):
    id: str
    imei: str
    label: Optional[str] = None
    unit_type_id: Optional[str] = None
    unit_type_name: Optional[str] = None
    package_id: Optional[str] = None
    package_name: Optional[str] = None
    status: str
    status_detail: Optional[str] = None
    ble_tag_id: Optional[str] = None
    first_routed_at: Optional[datetime] = None
    last_event_at: Optional[datetime] = None
    created_at: Optional[datetime] = None


def _package_names(db: Session) -> dict:
    return {str(p.id): p.name for p in db.query(TagPackage.id, TagPackage.name).all()}


def _device_counts(db: Session, reseller_ids: list) -> dict:
    rows = (
        db.query(ResellerDevice.reseller_id, ResellerDevice.status, func.count())
        .filter(ResellerDevice.reseller_id.in_(reseller_ids))
        .group_by(ResellerDevice.reseller_id, ResellerDevice.status)
        .all()
    ) if reseller_ids else []
    out: dict = {}
    for rid, st, n in rows:
        bucket = out.setdefault(str(rid), {"total": 0, "routed": 0, "pending": 0, "conflict": 0})
        bucket[st] = bucket.get(st, 0) + n
        bucket["total"] += n
    return out


def _reseller_out(db: Session, r: Reseller, pkg_names: dict, counts: dict) -> ResellerOut:
    ex = r.exchange
    exchange_out = None
    if ex:
        exchange_out = ExchangeOut(
            id=ex.id, exchange_key=ex.exchange_key, status=ex.status,
            usergroup_id=ex.usergroup_id,
            usergroup_name=ex.usergroup.name if ex.usergroup else None,
            linked_at=ex.linked_at, linked_by=ex.linked_by,
        )
    return ResellerOut(
        id=r.id, name=r.name, code=r.code,
        contact_name=r.contact_name, contact_email=r.contact_email,
        contact_phone=r.contact_phone, notes=r.notes,
        default_package_id=r.default_package_id,
        default_package_name=pkg_names.get(str(r.default_package_id)) if r.default_package_id else None,
        is_active=r.is_active, created_at=r.created_at,
        exchange=exchange_out,
        device_counts=counts.get(str(r.id), {"total": 0, "routed": 0, "pending": 0, "conflict": 0}),
    )


def _device_out(d: ResellerDevice, pkg_names: dict, reseller: Reseller) -> DeviceOut:
    effective = d.package_id or reseller.default_package_id
    return DeviceOut(
        id=d.id, imei=d.imei, label=d.label,
        unit_type_id=d.unit_type_id, unit_type_name=d.unit_type.name if d.unit_type else None,
        package_id=d.package_id,
        package_name=pkg_names.get(str(effective)) if effective else None,
        status=d.status, status_detail=d.status_detail, ble_tag_id=d.ble_tag_id,
        first_routed_at=d.first_routed_at, last_event_at=d.last_event_at, created_at=d.created_at,
    )


# ---------------------------------------------------------------------------
# Catalogue + overview
# ---------------------------------------------------------------------------

@router.get("/event-types")
def list_event_types(request: Request, db: Session = Depends(get_db)):
    """Event types a package can expose to the customer dashboard (viewer+)."""
    _require(request, db, "viewer")
    return dp.EVENT_TYPES


@router.get("/overview")
def overview(request: Request, db: Session = Depends(get_db)):
    """Platform-wide counts for the DataProfiler header cards (viewer+)."""
    _require(request, db, "viewer")
    by_status = dict(db.query(ResellerDevice.status, func.count()).group_by(ResellerDevice.status).all())
    return {
        "resellers": db.query(func.count(Reseller.id)).scalar() or 0,
        "active_resellers": db.query(func.count(Reseller.id)).filter(Reseller.is_active == True).scalar() or 0,
        "linked_exchanges": db.query(func.count(DataExchange.id)).filter(DataExchange.status == "linked").scalar() or 0,
        "devices": sum(by_status.values()),
        "devices_by_status": by_status,
    }


# ---------------------------------------------------------------------------
# Unit types
# ---------------------------------------------------------------------------

def _unit_type_out(u: UnitType, counts: dict) -> UnitTypeOut:
    return UnitTypeOut(
        id=u.id, manufacturer=u.manufacturer, model=u.model, name=u.name,
        description=u.description, is_active=u.is_active,
        device_count=counts.get(str(u.id), 0), created_at=u.created_at,
    )


def _unit_type_counts(db: Session) -> dict:
    return {
        str(uid): n for uid, n in
        db.query(ResellerDevice.unit_type_id, func.count())
        .filter(ResellerDevice.unit_type_id.isnot(None))
        .group_by(ResellerDevice.unit_type_id).all()
    }


def _clean_unit_type_fields(db: Session, manufacturer: str, model: str, exclude_id=None) -> tuple:
    manufacturer, model = (manufacturer or "").strip(), (model or "").strip()
    if not manufacturer or not model:
        raise HTTPException(status_code=400, detail="Manufacturer and model are required")
    q = db.query(UnitType).filter(
        func.lower(UnitType.manufacturer) == manufacturer.lower(),
        func.lower(UnitType.model) == model.lower(),
    )
    if exclude_id:
        q = q.filter(UnitType.id != exclude_id)
    if q.first():
        raise HTTPException(status_code=409, detail=f"{manufacturer} {model} already exists")
    return manufacturer, model


@router.get("/unit-types", response_model=List[UnitTypeOut])
def list_unit_types(request: Request, db: Session = Depends(get_db)):
    _require(request, db, "viewer")
    counts = _unit_type_counts(db)
    types = db.query(UnitType).order_by(UnitType.manufacturer, UnitType.model).all()
    return [_unit_type_out(u, counts) for u in types]


@router.post("/unit-types", response_model=UnitTypeOut, status_code=201)
def create_unit_type(data: UnitTypeIn, request: Request, db: Session = Depends(get_db)):
    admin = _require(request, db, "manager")
    manufacturer, model = _clean_unit_type_fields(db, data.manufacturer, data.model)
    u = UnitType(manufacturer=manufacturer, model=model,
                 description=(data.description or "").strip() or None, is_active=True)
    db.add(u)
    db.commit()
    db.refresh(u)
    log_audit(db, str(admin.id), "create_unit_type", "UnitType", str(u.id), new_value={"name": u.name})
    return _unit_type_out(u, {})


@router.put("/unit-types/{unit_type_id}", response_model=UnitTypeOut)
def update_unit_type(unit_type_id: str, data: UnitTypeUpdate, request: Request, db: Session = Depends(get_db)):
    admin = _require(request, db, "manager")
    u = db.query(UnitType).filter(UnitType.id == unit_type_id).first()
    if not u:
        raise HTTPException(status_code=404, detail="Unit type not found")
    changes = data.model_dump(exclude_unset=True)
    if "manufacturer" in changes or "model" in changes:
        changes["manufacturer"], changes["model"] = _clean_unit_type_fields(
            db, changes.get("manufacturer", u.manufacturer), changes.get("model", u.model), exclude_id=u.id)
    if "description" in changes:
        changes["description"] = (changes["description"] or "").strip() or None
    for field, val in changes.items():
        setattr(u, field, val)
    db.commit()
    db.refresh(u)
    log_audit(db, str(admin.id), "update_unit_type", "UnitType", str(u.id),
              new_value={k: str(v) for k, v in changes.items()})
    return _unit_type_out(u, _unit_type_counts(db))


@router.delete("/unit-types/{unit_type_id}", status_code=204)
def delete_unit_type(unit_type_id: str, request: Request, db: Session = Depends(get_db)):
    """Delete an unused unit type (manager+). Deactivate it instead if devices use it."""
    admin = _require(request, db, "manager")
    u = db.query(UnitType).filter(UnitType.id == unit_type_id).first()
    if not u:
        raise HTTPException(status_code=404, detail="Unit type not found")
    if db.query(ResellerDevice).filter(ResellerDevice.unit_type_id == u.id).first():
        raise HTTPException(status_code=409, detail="Devices use this unit type — deactivate it instead")
    name = u.name
    db.delete(u)
    db.commit()
    log_audit(db, str(admin.id), "delete_unit_type", "UnitType", unit_type_id, old_value={"name": name})


# ---------------------------------------------------------------------------
# Resellers
# ---------------------------------------------------------------------------

@router.get("/resellers", response_model=List[ResellerOut])
def list_resellers(request: Request, db: Session = Depends(get_db)):
    _require(request, db, "viewer")
    resellers = db.query(Reseller).order_by(Reseller.name).all()
    pkg_names = _package_names(db)
    counts = _device_counts(db, [r.id for r in resellers])
    return [_reseller_out(db, r, pkg_names, counts) for r in resellers]


@router.post("/resellers", response_model=ResellerCreated, status_code=201)
def create_reseller(data: ResellerCreate, request: Request, db: Session = Depends(get_db)):
    """Create a reseller and its data exchange. The exchange secret is returned once."""
    admin = _require(request, db, "manager")
    name = data.name.strip()
    code = data.code.strip().lower()
    if not name:
        raise HTTPException(status_code=400, detail="Name is required")
    if not _CODE_RE.match(code):
        raise HTTPException(status_code=400, detail="Code must be 3-50 chars: lowercase letters, digits and dashes")
    if db.query(Reseller).filter((Reseller.name == name) | (Reseller.code == code)).first():
        raise HTTPException(status_code=409, detail="A reseller with that name or code already exists")
    _check_package(db, data.default_package_id)

    reseller = Reseller(
        name=name, code=code,
        contact_name=data.contact_name, contact_email=data.contact_email,
        contact_phone=data.contact_phone, notes=data.notes,
        default_package_id=data.default_package_id or None, is_active=True,
    )
    db.add(reseller)
    db.flush()
    _, secret = dp.create_exchange(db, reseller)
    db.commit()
    db.refresh(reseller)
    log_audit(db, str(admin.id), "create_reseller", "Reseller", str(reseller.id),
              new_value={"name": reseller.name, "code": reseller.code})
    out = _reseller_out(db, reseller, _package_names(db), {})
    return ResellerCreated(**out.model_dump(), exchange_secret=secret)


@router.get("/resellers/{reseller_id}", response_model=ResellerOut)
def get_reseller(reseller_id: str, request: Request, db: Session = Depends(get_db)):
    _require(request, db, "viewer")
    r = _get_reseller(db, reseller_id)
    return _reseller_out(db, r, _package_names(db), _device_counts(db, [r.id]))


@router.put("/resellers/{reseller_id}", response_model=ResellerOut)
def update_reseller(reseller_id: str, data: ResellerUpdate, request: Request, db: Session = Depends(get_db)):
    admin = _require(request, db, "manager")
    r = _get_reseller(db, reseller_id)
    changes = data.model_dump(exclude_unset=True)
    if "name" in changes:
        changes["name"] = (changes["name"] or "").strip()
        if not changes["name"]:
            raise HTTPException(status_code=400, detail="Name is required")
        if db.query(Reseller).filter(Reseller.name == changes["name"], Reseller.id != r.id).first():
            raise HTTPException(status_code=409, detail="A reseller with that name already exists")
    if "default_package_id" in changes:
        changes["default_package_id"] = changes["default_package_id"] or None
        _check_package(db, changes["default_package_id"])
    for field, val in changes.items():
        setattr(r, field, val)
    db.commit()
    db.refresh(r)
    log_audit(db, str(admin.id), "update_reseller", "Reseller", str(r.id),
              new_value={k: str(v) for k, v in changes.items()})
    return _reseller_out(db, r, _package_names(db), _device_counts(db, [r.id]))


# ---------------------------------------------------------------------------
# Exchange
# ---------------------------------------------------------------------------

@router.post("/resellers/{reseller_id}/exchange/rotate-secret")
def rotate_secret(reseller_id: str, request: Request, db: Session = Depends(get_db)):
    """Issue a new exchange secret (manager+). Existing links are unaffected."""
    admin = _require(request, db, "manager")
    r = _get_reseller(db, reseller_id)
    if not r.exchange:
        raise HTTPException(status_code=404, detail="Reseller has no exchange")
    secret = dp.rotate_exchange_secret(r.exchange)
    db.commit()
    log_audit(db, str(admin.id), "rotate_exchange_secret", "DataExchange", str(r.exchange.id))
    return {"exchange_key": r.exchange.exchange_key, "exchange_secret": secret}


@router.post("/resellers/{reseller_id}/exchange/link")
def link_exchange(reseller_id: str, data: LinkRequest, request: Request, db: Session = Depends(get_db)):
    """Link the reseller's exchange to a customer dashboard usergroup (manager+)."""
    admin = _require(request, db, "manager")
    r = _get_reseller(db, reseller_id)
    group = db.query(UserGroup).filter(UserGroup.id == data.usergroup_id).first()
    if not group:
        raise HTTPException(status_code=404, detail="User group not found")
    try:
        counts = dp.link_exchange(db, r.exchange, group, linked_by=f"admin:{admin.username}")
    except ValueError as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail=str(exc))
    db.commit()
    log_audit(db, str(admin.id), "link_exchange", "DataExchange", str(r.exchange.id),
              new_value={"usergroup_id": str(group.id), **counts})
    return {"linked": True, "usergroup_name": group.name, "routing": counts}


@router.post("/resellers/{reseller_id}/exchange/unlink")
def unlink_exchange(reseller_id: str, request: Request, db: Session = Depends(get_db)):
    """Detach the exchange from its usergroup (manager+). Provisioned tags are kept."""
    admin = _require(request, db, "manager")
    r = _get_reseller(db, reseller_id)
    if not r.exchange or not r.exchange.usergroup_id:
        raise HTTPException(status_code=400, detail="Exchange is not linked")
    old_group = str(r.exchange.usergroup_id)
    dp.unlink_exchange(db, r.exchange)
    db.commit()
    log_audit(db, str(admin.id), "unlink_exchange", "DataExchange", str(r.exchange.id),
              old_value={"usergroup_id": old_group})
    return {"linked": False}


@router.post("/resellers/{reseller_id}/route")
def reroute(reseller_id: str, request: Request, db: Session = Depends(get_db)):
    """Retry routing for every device not yet on the dashboard (manager+)."""
    _require(request, db, "manager")
    r = _get_reseller(db, reseller_id)
    counts = dp.route_reseller_devices(db, r)
    db.commit()
    return {"routing": counts}


# ---------------------------------------------------------------------------
# Devices (IMEI inventory)
# ---------------------------------------------------------------------------

@router.get("/resellers/{reseller_id}/devices", response_model=List[DeviceOut])
def list_devices(reseller_id: str, request: Request, db: Session = Depends(get_db)):
    _require(request, db, "viewer")
    r = _get_reseller(db, reseller_id)
    pkg_names = _package_names(db)
    devices = db.query(ResellerDevice).filter(ResellerDevice.reseller_id == r.id).order_by(ResellerDevice.imei).all()
    return [_device_out(d, pkg_names, r) for d in devices]


@router.post("/resellers/{reseller_id}/devices")
def add_devices(reseller_id: str, data: DevicesAdd, request: Request, db: Session = Depends(get_db)):
    """Add IMEIs to the reseller's inventory and route them if the exchange is linked (manager+)."""
    admin = _require(request, db, "manager")
    r = _get_reseller(db, reseller_id)
    _check_package(db, data.package_id)
    if not data.unit_type_id:
        raise HTTPException(status_code=400, detail="Choose a unit type")
    _check_unit_type(db, data.unit_type_id)
    if not (data.package_id or r.default_package_id):
        raise HTTPException(status_code=400, detail="Choose a package or set a default package on the reseller first")

    results = []
    seen = set()
    for row in data.devices:
        imei = (row.imei or "").strip()
        if not _IMEI_RE.match(imei):
            results.append({"imei": imei, "ok": False, "error": "IMEI must be 14-17 digits"})
            continue
        if imei in seen:
            results.append({"imei": imei, "ok": False, "error": "Duplicate in this batch"})
            continue
        seen.add(imei)
        existing = db.query(ResellerDevice).filter(ResellerDevice.imei == imei).first()
        if existing:
            owner = "this reseller" if existing.reseller_id == r.id else "another reseller"
            results.append({"imei": imei, "ok": False, "error": f"Already assigned to {owner}"})
            continue
        device = ResellerDevice(
            reseller_id=r.id, imei=imei,
            label=(row.label or "").strip() or None,
            unit_type_id=data.unit_type_id,
            package_id=data.package_id or None, status="pending",
        )
        db.add(device)
        db.flush()
        db.refresh(device)  # load reseller relationship for routing
        status = dp.route_device(db, device)
        results.append({"imei": imei, "ok": True, "status": status, "detail": device.status_detail})

    db.commit()
    added = sum(1 for x in results if x["ok"])
    if added:
        log_audit(db, str(admin.id), "add_reseller_devices", "Reseller", str(r.id),
                  new_value={"added": added, "package_id": data.package_id})
    return {"added": added, "results": results}


@router.put("/resellers/{reseller_id}/devices/{device_id}", response_model=DeviceOut)
def update_device(reseller_id: str, device_id: str, data: DeviceUpdate, request: Request, db: Session = Depends(get_db)):
    """Edit a device's label, unit type or package override (manager+).

    Package changes apply to the inventory record; a device already routed keeps
    the package and expiry it was provisioned with on the dashboard.
    """
    _require(request, db, "manager")
    r = _get_reseller(db, reseller_id)
    d = db.query(ResellerDevice).filter(ResellerDevice.id == device_id, ResellerDevice.reseller_id == r.id).first()
    if not d:
        raise HTTPException(status_code=404, detail="Device not found")
    changes = data.model_dump(exclude_unset=True)
    if "package_id" in changes:
        changes["package_id"] = changes["package_id"] or None
        _check_package(db, changes["package_id"])
    if "unit_type_id" in changes:
        if not changes["unit_type_id"]:
            raise HTTPException(status_code=400, detail="Unit type is required")
        _check_unit_type(db, changes["unit_type_id"])
    for field, val in changes.items():
        setattr(d, field, val)
    db.commit()
    db.refresh(d)
    return _device_out(d, _package_names(db), r)


@router.delete("/resellers/{reseller_id}/devices/{device_id}", status_code=204)
def remove_device(reseller_id: str, device_id: str, request: Request, db: Session = Depends(get_db)):
    """Remove an IMEI from the reseller's inventory (manager+).

    The tag on the customer dashboard, if any, is left in place.
    """
    admin = _require(request, db, "manager")
    r = _get_reseller(db, reseller_id)
    d = db.query(ResellerDevice).filter(ResellerDevice.id == device_id, ResellerDevice.reseller_id == r.id).first()
    if not d:
        raise HTTPException(status_code=404, detail="Device not found")
    imei = d.imei
    db.delete(d)
    db.commit()
    log_audit(db, str(admin.id), "remove_reseller_device", "Reseller", str(r.id), old_value={"imei": imei})


# ---------------------------------------------------------------------------
# Pipeline monitoring
# ---------------------------------------------------------------------------

def _queue_stats() -> dict:
    """RabbitMQ raw-queue depth and rates from the management API."""
    import httpx
    from app.dataprofiler import config as dp_config

    mgmt = dp_config.rabbitmq_management(required=False)
    if not mgmt:
        return {"error": "RABBITMQ_PASSWORD not set"}
    base, user, password = mgmt
    try:
        res = httpx.get(f"{base}/queues/%2F/{dp_config.RAW_QUEUE}", auth=(user, password), timeout=3)
        res.raise_for_status()
        q = res.json()
    except Exception as exc:
        return {"error": f"RabbitMQ unavailable: {exc.__class__.__name__}"}
    stats = q.get("message_stats", {})
    return {
        "ready": q.get("messages_ready", 0),
        "unacked": q.get("messages_unacknowledged", 0),
        "consumers": q.get("consumers", 0),
        "publish_rate": round(stats.get("publish_details", {}).get("rate", 0.0), 2),
        "ack_rate": round(stats.get("ack_details", {}).get("rate", 0.0), 2),
    }


_PIPELINE_SQL = {
    "totals": """
        SELECT
          (SELECT count(*) FROM events_incoming WHERE received_at > now() - interval '1 hour') AS packets_1h,
          (SELECT coalesce(sum(record_count), 0) FROM events_incoming WHERE received_at > now() - interval '1 hour') AS records_1h,
          (SELECT count(*) FROM events_incoming WHERE status = 'new') AS backlog,
          (SELECT extract(epoch FROM now() - min(received_at)) FROM events_incoming WHERE status = 'new') AS oldest_new_s,
          (SELECT count(*) FROM events_incoming WHERE status = 'failed' AND received_at > now() - interval '24 hours') AS failed_24h,
          (SELECT count(*) FROM events_incoming WHERE status = 'unsupported' AND received_at > now() - interval '24 hours') AS unsupported_24h,
          (SELECT count(DISTINCT imei) FROM events_incoming WHERE received_at > now() - interval '10 minutes') AS active_devices_10m,
          (SELECT count(*) FROM events_processed WHERE visible AND NOT forwarded) AS forward_backlog
    """,
    "received": """
        SELECT date_trunc('minute', received_at) AS m, sum(record_count) AS n
        FROM events_incoming WHERE received_at > now() - interval '60 minutes' GROUP BY 1
    """,
    "decoded": """
        SELECT date_trunc('minute', created_at) AS m, count(*) AS n
        FROM events_processed WHERE created_at > now() - interval '60 minutes' GROUP BY 1
    """,
    "failures": """
        SELECT id, imei, status, error, received_at FROM events_incoming
        WHERE status IN ('failed', 'unsupported') ORDER BY id DESC LIMIT 10
    """,
}


def _events_stats() -> dict:
    from datetime import timedelta, timezone
    from sqlalchemy import text as _text
    from app.dataprofiler import config as dp_config
    from app.dataprofiler.events_db import get_engine

    url = dp_config.events_db_url(required=False)
    if not url:
        return {"error": "EVENTS_DB_PASSWORD not set"}
    try:
        with get_engine(url).connect() as conn:
            totals = dict(conn.execute(_text(_PIPELINE_SQL["totals"])).mappings().one())
            received = {r.m: int(r.n) for r in conn.execute(_text(_PIPELINE_SQL["received"]))}
            decoded = {r.m: int(r.n) for r in conn.execute(_text(_PIPELINE_SQL["decoded"]))}
            failures = [dict(r) for r in conn.execute(_text(_PIPELINE_SQL["failures"])).mappings()]
            now = conn.execute(_text("SELECT date_trunc('minute', now())")).scalar()
    except Exception as exc:
        return {"error": f"Events database unavailable: {exc.__class__.__name__}"}

    minutes = [now - timedelta(minutes=i) for i in range(59, -1, -1)]
    series = [{"minute": m.astimezone(timezone.utc).isoformat(),
               "received": received.get(m, 0), "decoded": decoded.get(m, 0)} for m in minutes]
    totals["oldest_new_s"] = round(totals["oldest_new_s"]) if totals["oldest_new_s"] is not None else None
    return {"totals": totals, "series": series, "failures": failures}


@router.get("/pipeline")
def pipeline_stats(request: Request, db: Session = Depends(get_db)):
    """Ingest pipeline health for the Pipeline page (viewer+)."""
    _require(request, db, "viewer")
    return {"queue": _queue_stats(), "events": _events_stats()}
