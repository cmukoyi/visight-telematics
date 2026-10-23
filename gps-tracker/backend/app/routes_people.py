"""Customer portal — drivers and working-hours time profiles.

Mounted under /api/portal. Everyone in the group can read them (vehicle
editor, reports); adding and changing drivers needs vehicles.manage, time
profiles settings.manage.
"""
from typing import Dict, List, Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, field_validator
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import BLETag, Driver, PortalUser, TimeProfile
from app.models_dataprofiler import Trip
from app.routes_portal import get_portal_user_from_request
from app.services import access_service, drivers_service, time_profiles

router = APIRouter(prefix="/api/portal", tags=["portal-people"])


def _me(request: Request, db: Session, perm: Optional[str] = None) -> PortalUser:
    me = get_portal_user_from_request(request, db)
    if perm:
        access_service.for_user(me, db).require(perm)
    return me


def _own(db: Session, model, me: PortalUser, oid: str, what: str):
    try:
        key = UUID(oid)
    except ValueError:
        raise HTTPException(status_code=404, detail=f"{what} not found")
    row = db.query(model).filter(model.id == key, model.usergroup_id == me.usergroup_id).first()
    if not row:
        raise HTTPException(status_code=404, detail=f"{what} not found")
    return row


def _group_tags(db: Session, me: PortalUser):
    return db.query(BLETag).filter(BLETag.attributes.op("->>")("_created_usergroup_id") == str(me.usergroup_id))


# ---------------------------------------------------------------------------
# Drivers
# ---------------------------------------------------------------------------

class DriverIn(BaseModel):
    first_name: str
    last_name: Optional[str] = None
    employee_number: Optional[str] = None
    key_code: Optional[str] = None
    phone: Optional[str] = None
    is_active: bool = True

    @field_validator("first_name")
    @classmethod
    def _first(cls, v):
        v = (v or "").strip()
        if not v or len(v) > 100:
            raise ValueError("Enter the driver's name")
        return v

    @field_validator("last_name", "employee_number", "key_code", "phone")
    @classmethod
    def _trim(cls, v):
        return (v or "").strip()[:100] or None


def _driver_out(d: Driver, vehicles: Dict[str, List[str]], trips: Dict) -> dict:
    return {"id": str(d.id), "first_name": d.first_name, "last_name": d.last_name, "name": d.name,
            "employee_number": d.employee_number, "key_code": d.key_code, "phone": d.phone, "is_active": d.is_active,
            "vehicles": vehicles.get(str(d.id), []), "trips": trips.get(d.id, 0)}


def _driver_vehicles(db: Session, me: PortalUser) -> Dict[str, List[str]]:
    out: Dict[str, List[str]] = {}
    for tag in _group_tags(db, me):
        did = drivers_service.vehicle_driver_id(tag.attributes)
        if did:
            out.setdefault(did, []).append(tag.description or tag.device_name or tag.imei)
    return out


def _check_driver(db: Session, me: PortalUser, data: DriverIn, exclude=None) -> None:
    q = db.query(Driver).filter(Driver.usergroup_id == me.usergroup_id)
    if exclude is not None:
        q = q.filter(Driver.id != exclude)
    for other in q:
        if data.employee_number and other.employee_number and other.employee_number.lower() == data.employee_number.lower():
            raise HTTPException(status_code=409, detail=f"Employee number {data.employee_number} is already {other.name}'s")
        if data.key_code and other.key_code and \
                drivers_service.normalise_key(other.key_code) == drivers_service.normalise_key(data.key_code):
            raise HTTPException(status_code=409, detail=f"That key is already {other.name}'s")


@router.get("/drivers")
def list_drivers(request: Request, db: Session = Depends(get_db)):
    me = _me(request, db)
    trips = dict(db.query(Trip.driver_id, func.count(Trip.id)).filter(Trip.usergroup_id == me.usergroup_id,
                                                                     Trip.driver_id.isnot(None)).group_by(Trip.driver_id).all())
    vehicles = _driver_vehicles(db, me)
    rows = db.query(Driver).filter(Driver.usergroup_id == me.usergroup_id).order_by(func.lower(Driver.first_name), func.lower(Driver.last_name))
    return [_driver_out(d, vehicles, trips) for d in rows]


@router.post("/drivers", status_code=201)
def create_driver(data: DriverIn, request: Request, db: Session = Depends(get_db)):
    me = _me(request, db, "vehicles.manage")
    _check_driver(db, me, data)
    d = Driver(usergroup_id=me.usergroup_id, **data.model_dump())
    db.add(d)
    db.commit()
    return _driver_out(d, {}, {})


@router.put("/drivers/{did}")
def update_driver(did: str, data: DriverIn, request: Request, db: Session = Depends(get_db)):
    me = _me(request, db, "vehicles.manage")
    d = _own(db, Driver, me, did, "Driver")
    _check_driver(db, me, data, exclude=d.id)
    for k, v in data.model_dump().items():
        setattr(d, k, v)
    drivers_service.sync_vehicle_names(db, d)
    db.commit()
    return _driver_out(d, _driver_vehicles(db, me), {})


@router.delete("/drivers/{did}", status_code=204)
def delete_driver(did: str, request: Request, db: Session = Depends(get_db)):
    """Delete the driver; their vehicles lose the assignment, their trips keep no driver."""
    me = _me(request, db, "vehicles.manage")
    d = _own(db, Driver, me, did, "Driver")
    for tag in _group_tags(db, me):
        attrs = dict(tag.attributes or {})
        if drivers_service.vehicle_driver_id(attrs) == str(d.id):
            attrs.pop("driver_id", None)
            attrs.pop("driver", None)
            tag.attributes = attrs
    db.delete(d)
    db.commit()


# ---------------------------------------------------------------------------
# Time profiles
# ---------------------------------------------------------------------------

class ProfileIn(BaseModel):
    name: str
    windows: Dict[str, List[List[str]]] = {}
    is_default: bool = False

    @field_validator("name")
    @classmethod
    def _name(cls, v):
        v = (v or "").strip()
        if not v or len(v) > 120:
            raise ValueError("Enter a name")
        return v

    @field_validator("windows")
    @classmethod
    def _windows(cls, v):
        return time_profiles.valid_windows(v)


def _profile_out(p: TimeProfile, vehicles: Dict[str, int]) -> dict:
    return {"id": str(p.id), "name": p.name, "windows": p.windows or {}, "is_default": p.is_default,
            "summary": time_profiles.describe(p.windows or {}), "vehicles": vehicles.get(str(p.id), 0)}


def _profile_use(db: Session, me: PortalUser) -> Dict[str, int]:
    out: Dict[str, int] = {}
    for tag in _group_tags(db, me):
        pid = ((tag.attributes or {}).get("time_profile_id") or {}).get("value")
        if pid:
            out[pid] = out.get(pid, 0) + 1
    return out


def _one_default(db: Session, me: PortalUser, p: TimeProfile) -> None:
    others = db.query(TimeProfile).filter(TimeProfile.usergroup_id == me.usergroup_id, TimeProfile.id != p.id)
    if p.is_default:
        others.update({"is_default": False})
    elif not others.filter(TimeProfile.is_default == True).first():  # noqa: E712
        p.is_default = True   # there's always a default once a profile exists


@router.get("/time-profiles")
def list_profiles(request: Request, db: Session = Depends(get_db)):
    me = _me(request, db)
    use = _profile_use(db, me)
    rows = db.query(TimeProfile).filter(TimeProfile.usergroup_id == me.usergroup_id).order_by(TimeProfile.is_default.desc(), func.lower(TimeProfile.name))
    return [_profile_out(p, use) for p in rows]


@router.post("/time-profiles", status_code=201)
def create_profile(data: ProfileIn, request: Request, db: Session = Depends(get_db)):
    me = _me(request, db, "settings.manage")
    p = TimeProfile(usergroup_id=me.usergroup_id, **data.model_dump())
    db.add(p)
    db.flush()
    _one_default(db, me, p)
    db.commit()
    return _profile_out(p, {})


@router.put("/time-profiles/{pid}")
def update_profile(pid: str, data: ProfileIn, request: Request, db: Session = Depends(get_db)):
    me = _me(request, db, "settings.manage")
    p = _own(db, TimeProfile, me, pid, "Time profile")
    p.name, p.windows, p.is_default = data.name, data.windows, data.is_default
    _one_default(db, me, p)
    db.commit()
    return _profile_out(p, _profile_use(db, me))


@router.delete("/time-profiles/{pid}", status_code=204)
def delete_profile(pid: str, request: Request, db: Session = Depends(get_db)):
    me = _me(request, db, "settings.manage")
    p = _own(db, TimeProfile, me, pid, "Time profile")
    n = _profile_use(db, me).get(str(p.id), 0)
    if n:
        raise HTTPException(status_code=409, detail=f"{n} vehicle{'s use' if n != 1 else ' uses'} it — change them first")
    was_default = p.is_default
    db.delete(p)
    db.flush()
    if was_default:
        nxt = db.query(TimeProfile).filter(TimeProfile.usergroup_id == me.usergroup_id).first()
        if nxt:
            nxt.is_default = True
    db.commit()
