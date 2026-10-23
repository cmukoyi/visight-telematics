"""Customer portal — Vehicle Maintenance.

Mounted under /api/portal/maintenance; scoped to the caller's user group and
the vehicles they may see. Viewing needs maintenance.view, recording jobs and
costs maintenance.manage, and the setup lists (schedules, types, items,
workshops, lookups) maintenance.configure. See app/services/maintenance_service.py
for how schedules fall due.
"""
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from typing import List, Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, field_validator, model_validator
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import POI, PortalUser
from app.models_maintenance import (LOOKUP_KINDS, MaintenanceCost, MaintenanceItem, MaintenanceLookup,
                                    MaintenanceSchedule, MaintenanceType, VehicleMaintenance, Workshop)
from app.routes_portal import get_portal_user_from_request
from app.services import access_service, audit_service
from app.services import maintenance_service as ms

router = APIRouter(prefix="/api/portal/maintenance", tags=["portal-maintenance"])

VIEW, MANAGE, CONFIGURE = "maintenance.view", "maintenance.manage", "maintenance.configure"


def _me(request: Request, db: Session, *any_of: str):
    me = get_portal_user_from_request(request, db)
    access = access_service.for_user(me, db)
    if not any(access.can(p) for p in any_of):
        access.require(any_of[0])
    return me, access


def _uuid(value, what: str) -> UUID:
    try:
        return UUID(str(value))
    except ValueError:
        raise HTTPException(status_code=404, detail=f"{what} not found")


def _own(db: Session, model, me: PortalUser, oid, what: str):
    row = db.query(model).filter(model.id == _uuid(oid, what), model.usergroup_id == me.usergroup_id).first()
    if not row:
        raise HTTPException(status_code=404, detail=f"{what} not found")
    return row


def _name(v: str, what: str = "a name", limit: int = 160) -> str:
    v = (v or "").strip()
    if not v or len(v) > limit:
        raise ValueError(f"Enter {what} (up to {limit} characters)")
    return v


def _unique(db: Session, model, me: PortalUser, name: str, exclude=None, **filters) -> None:
    q = db.query(model.id).filter(model.usergroup_id == me.usergroup_id, func.lower(model.name) == name.lower())
    for k, v in filters.items():
        q = q.filter(getattr(model, k) == v)
    if exclude is not None:
        q = q.filter(model.id != exclude)
    if q.first():
        raise HTTPException(status_code=409, detail=f"“{name}” already exists")


def _fleet(db: Session, me: PortalUser, access) -> dict:
    return ms.vehicles(db, me.usergroup_id, access.visible_imeis(db))


def _audit(db, me, action, summary, rid=None):
    audit_service.record(db, me, action, "Maintenance", summary, resource_id=rid)


# ---------------------------------------------------------------------------
# Everything the forms pick from
# ---------------------------------------------------------------------------

@router.get("/catalog")
def catalog(request: Request, db: Session = Depends(get_db)):
    """Lookups, items, types, schedules and workshops (names and ids) for filters and forms."""
    me, access = _me(request, db, VIEW, MANAGE, CONFIGURE)
    ms.ensure_defaults(db, me.usergroup_id)
    g = me.usergroup_id
    lookups = {k: [] for k in LOOKUP_KINDS}
    for row in db.query(MaintenanceLookup).filter(MaintenanceLookup.usergroup_id == g).order_by(func.lower(MaintenanceLookup.name)):
        lookups[row.kind].append({"id": str(row.id), "name": row.name})
    items = [{"id": str(i.id), "name": i.name} for i in
             db.query(MaintenanceItem).filter(MaintenanceItem.usergroup_id == g).order_by(func.lower(MaintenanceItem.name))]
    types = [_type_out(t) for t in db.query(MaintenanceType).filter(MaintenanceType.usergroup_id == g).order_by(func.lower(MaintenanceType.name))]
    workshops = [{"id": str(w.id), "name": w.name} for w in
                 db.query(Workshop).filter(Workshop.usergroup_id == g).order_by(func.lower(Workshop.name))]
    schedules = [{"id": str(s.id), "name": s.name, "type_id": str(s.type_id)} for s in
                 db.query(MaintenanceSchedule).filter(MaintenanceSchedule.usergroup_id == g).order_by(func.lower(MaintenanceSchedule.name))]
    fleet = _fleet(db, me, access)
    return {**lookups, "items": items, "types": types, "workshops": workshops, "schedules": schedules,
            "statuses": ms.STATUSES,
            "vehicles": [{"imei": i, "name": v["name"], "group": v["group"], "type_id": v["type_id"]}
                         for i, v in sorted(fleet.items(), key=lambda x: x[1]["name"].lower())]}


# ---------------------------------------------------------------------------
# Lookups: vehicle types, workshop chains, workshop types, cost centres
# ---------------------------------------------------------------------------

class NameIn(BaseModel):
    name: str

    @field_validator("name")
    @classmethod
    def _n(cls, v):
        return _name(v, limit=120)


def _kind(kind: str) -> str:
    if kind not in LOOKUP_KINDS:
        raise HTTPException(status_code=404, detail="Unknown list")
    return kind


@router.get("/lookups/{kind}")
def list_lookups(kind: str, request: Request, db: Session = Depends(get_db)):
    me, _ = _me(request, db, VIEW, MANAGE, CONFIGURE)
    rows = db.query(MaintenanceLookup).filter(MaintenanceLookup.usergroup_id == me.usergroup_id,
                                              MaintenanceLookup.kind == _kind(kind)).order_by(func.lower(MaintenanceLookup.name)).all()
    used = _lookup_use(db, me, kind)
    return [{"id": str(r.id), "name": r.name, "used": used.get(str(r.id), 0)} for r in rows]


def _lookup_use(db: Session, me: PortalUser, kind: str) -> dict:
    """{lookup id: how many things use it}."""
    g, out = me.usergroup_id, {}
    if kind == "vehicle_type":
        for v in ms.vehicles(db, g).values():
            if v["type_id"]:
                out[v["type_id"]] = out.get(v["type_id"], 0) + 1
    elif kind == "workshop_chain":
        for (cid,) in db.query(Workshop.chain_id).filter(Workshop.usergroup_id == g, Workshop.chain_id.isnot(None)):
            out[str(cid)] = out.get(str(cid), 0) + 1
    elif kind == "workshop_type":
        for (ids,) in db.query(Workshop.type_ids).filter(Workshop.usergroup_id == g):
            for i in ids or []:
                out[str(i)] = out.get(str(i), 0) + 1
    else:
        for cid, n in (db.query(MaintenanceCost.cost_centre_id, func.count(MaintenanceCost.id))
                       .filter(MaintenanceCost.usergroup_id == g, MaintenanceCost.cost_centre_id.isnot(None))
                       .group_by(MaintenanceCost.cost_centre_id)):
            out[str(cid)] = n
    return out


@router.post("/lookups/{kind}", status_code=201)
def create_lookup(kind: str, data: NameIn, request: Request, db: Session = Depends(get_db)):
    # Cost centres can be added inline while recording a cost
    me, _ = _me(request, db, CONFIGURE, *( [MANAGE] if kind == "cost_centre" else []))
    _unique(db, MaintenanceLookup, me, data.name, kind=_kind(kind))
    row = MaintenanceLookup(usergroup_id=me.usergroup_id, kind=kind, name=data.name)
    db.add(row)
    db.commit()
    return {"id": str(row.id), "name": row.name, "used": 0}


@router.put("/lookups/{kind}/{lid}")
def update_lookup(kind: str, lid: str, data: NameIn, request: Request, db: Session = Depends(get_db)):
    me, _ = _me(request, db, CONFIGURE)
    row = _own(db, MaintenanceLookup, me, lid, "Entry")
    if row.kind != _kind(kind):
        raise HTTPException(status_code=404, detail="Entry not found")
    _unique(db, MaintenanceLookup, me, data.name, exclude=row.id, kind=kind)
    row.name = data.name
    db.commit()
    return {"id": str(row.id), "name": row.name}


@router.delete("/lookups/{kind}/{lid}", status_code=204)
def delete_lookup(kind: str, lid: str, request: Request, db: Session = Depends(get_db)):
    me, _ = _me(request, db, CONFIGURE)
    row = _own(db, MaintenanceLookup, me, lid, "Entry")
    if row.kind != _kind(kind):
        raise HTTPException(status_code=404, detail="Entry not found")
    if kind == "vehicle_type":
        n = _lookup_use(db, me, kind).get(str(row.id), 0)
        if n:
            raise HTTPException(status_code=409, detail=f"{n} vehicle{'s are' if n != 1 else ' is'} this type — change them first")
        for s in db.query(MaintenanceSchedule).filter(MaintenanceSchedule.usergroup_id == me.usergroup_id):
            if str(row.id) in (s.vehicle_type_ids or []):
                s.vehicle_type_ids = [t for t in s.vehicle_type_ids if t != str(row.id)]
    if kind == "workshop_type":
        for w in db.query(Workshop).filter(Workshop.usergroup_id == me.usergroup_id):
            if str(row.id) in (w.type_ids or []):
                w.type_ids = [t for t in w.type_ids if t != str(row.id)]
    db.delete(row)
    db.commit()


# ---------------------------------------------------------------------------
# Maintenance items and types
# ---------------------------------------------------------------------------

@router.get("/items")
def list_items(request: Request, db: Session = Depends(get_db)):
    me, _ = _me(request, db, VIEW, MANAGE, CONFIGURE)
    ms.ensure_defaults(db, me.usergroup_id)
    used = {}
    for (ids,) in db.query(MaintenanceType.item_ids).filter(MaintenanceType.usergroup_id == me.usergroup_id):
        for i in ids or []:
            used[i] = used.get(i, 0) + 1
    return [{"id": str(i.id), "name": i.name, "types": used.get(str(i.id), 0)} for i in
            db.query(MaintenanceItem).filter(MaintenanceItem.usergroup_id == me.usergroup_id).order_by(func.lower(MaintenanceItem.name))]


@router.post("/items", status_code=201)
def create_item(data: NameIn, request: Request, db: Session = Depends(get_db)):
    me, _ = _me(request, db, CONFIGURE)
    _unique(db, MaintenanceItem, me, data.name)
    row = MaintenanceItem(usergroup_id=me.usergroup_id, name=data.name)
    db.add(row)
    db.commit()
    return {"id": str(row.id), "name": row.name, "types": 0}


@router.put("/items/{iid}")
def update_item(iid: str, data: NameIn, request: Request, db: Session = Depends(get_db)):
    me, _ = _me(request, db, CONFIGURE)
    row = _own(db, MaintenanceItem, me, iid, "Item")
    _unique(db, MaintenanceItem, me, data.name, exclude=row.id)
    row.name = data.name
    db.commit()
    return {"id": str(row.id), "name": row.name}


@router.delete("/items/{iid}", status_code=204)
def delete_item(iid: str, request: Request, db: Session = Depends(get_db)):
    me, _ = _me(request, db, CONFIGURE)
    row = _own(db, MaintenanceItem, me, iid, "Item")
    for t in db.query(MaintenanceType).filter(MaintenanceType.usergroup_id == me.usergroup_id):
        if str(row.id) in (t.item_ids or []):
            t.item_ids = [i for i in t.item_ids if i != str(row.id)]
    db.delete(row)
    db.commit()


class TypeIn(BaseModel):
    name: str
    duration_days: int = 1
    duration_hours: int = 0
    item_ids: List[str] = []

    @field_validator("name")
    @classmethod
    def _n(cls, v):
        return _name(v)

    @model_validator(mode="after")
    def _duration(self):
        if self.duration_days < 0 or self.duration_hours < 0 or self.duration_days > 365 or self.duration_hours > 23:
            raise ValueError("Expected duration: 0–365 days and 0–23 hours")
        return self


def _type_out(t: MaintenanceType, schedules: int = 0) -> dict:
    return {"id": str(t.id), "name": t.name, "duration_days": t.duration_hours // 24, "duration_hours": t.duration_hours % 24,
            "item_ids": list(t.item_ids or []), "schedules": schedules}


@router.get("/types")
def list_types(request: Request, db: Session = Depends(get_db)):
    me, _ = _me(request, db, VIEW, MANAGE, CONFIGURE)
    used = dict(db.query(MaintenanceSchedule.type_id, func.count(MaintenanceSchedule.id))
                .filter(MaintenanceSchedule.usergroup_id == me.usergroup_id).group_by(MaintenanceSchedule.type_id).all())
    return [_type_out(t, used.get(t.id, 0)) for t in
            db.query(MaintenanceType).filter(MaintenanceType.usergroup_id == me.usergroup_id).order_by(func.lower(MaintenanceType.name))]


def _apply_type(db: Session, me: PortalUser, t: MaintenanceType, data: TypeIn) -> None:
    mine = {str(i) for (i,) in db.query(MaintenanceItem.id).filter(MaintenanceItem.usergroup_id == me.usergroup_id)}
    t.name, t.duration_hours = data.name, data.duration_days * 24 + data.duration_hours
    t.item_ids = [i for i in dict.fromkeys(data.item_ids) if i in mine]


@router.post("/types", status_code=201)
def create_type(data: TypeIn, request: Request, db: Session = Depends(get_db)):
    me, _ = _me(request, db, CONFIGURE)
    _unique(db, MaintenanceType, me, data.name)
    t = MaintenanceType(usergroup_id=me.usergroup_id)
    _apply_type(db, me, t, data)
    db.add(t)
    db.commit()
    return _type_out(t)


@router.put("/types/{tid}")
def update_type(tid: str, data: TypeIn, request: Request, db: Session = Depends(get_db)):
    me, _ = _me(request, db, CONFIGURE)
    t = _own(db, MaintenanceType, me, tid, "Maintenance type")
    _unique(db, MaintenanceType, me, data.name, exclude=t.id)
    _apply_type(db, me, t, data)
    db.commit()
    return _type_out(t)


@router.delete("/types/{tid}", status_code=204)
def delete_type(tid: str, request: Request, db: Session = Depends(get_db)):
    me, _ = _me(request, db, CONFIGURE)
    t = _own(db, MaintenanceType, me, tid, "Maintenance type")
    n = db.query(func.count(MaintenanceSchedule.id)).filter(MaintenanceSchedule.type_id == t.id).scalar()
    if n:
        raise HTTPException(status_code=409, detail=f"Used by {n} schedule{'s' if n != 1 else ''} — delete or change them first")
    db.delete(t)
    db.commit()


# ---------------------------------------------------------------------------
# Schedules
# ---------------------------------------------------------------------------

def _pos(v):
    if v is not None and v <= 0:
        raise ValueError("Use whole numbers above 0")
    return v


class ScheduleIn(BaseModel):
    type_id: str
    name: str
    starts_on: Optional[date] = None
    at_km: Optional[int] = None
    at_months: Optional[int] = None
    at_hours: Optional[int] = None
    recurring: bool = False
    every_km: Optional[int] = None
    every_months: Optional[int] = None
    every_hours: Optional[int] = None
    until_km: Optional[int] = None
    until_months: Optional[int] = None
    until_hours: Optional[int] = None
    remind_km: int = 500
    remind_days: int = 14
    remind_hours: int = 10
    vehicle_type_ids: List[str] = []
    imeis: List[str] = []
    is_active: bool = True

    @field_validator("name")
    @classmethod
    def _n(cls, v):
        return _name(v, "a description")

    @field_validator("at_km", "at_months", "at_hours", "every_km", "every_months", "every_hours",
                     "until_km", "until_months", "until_hours")
    @classmethod
    def _p(cls, v):
        return _pos(v)

    @model_validator(mode="after")
    def _rules(self):
        if self.at_km is None and self.at_months is None and self.at_hours is None:
            raise ValueError("Set at least one “At” value: odometer, months or engine hours")
        if self.recurring:
            if self.every_km is None and self.every_months is None and self.every_hours is None:
                raise ValueError("A recurring schedule needs at least one “Every” value")
            for meter, at, until, every in (("odometer", self.at_km, self.until_km, self.every_km),
                                            ("months", self.at_months, self.until_months, self.every_months),
                                            ("engine hours", self.at_hours, self.until_hours, self.every_hours)):
                if until is not None and at is not None and until <= at:
                    raise ValueError(f"“Until” {meter} must be more than “At”")
                if every is not None and at is None:
                    raise ValueError(f"Set “At” {meter} too, so “Every” {meter} has a starting point")
        else:
            self.every_km = self.every_months = self.every_hours = None
            self.until_km = self.until_months = self.until_hours = None
        for v in (self.remind_km, self.remind_days, self.remind_hours):
            if v < 0:
                raise ValueError("Reminders can't be negative")
        return self


def _schedule_out(s: MaintenanceSchedule, types: dict, fleet: dict) -> dict:
    def fmt(km, months, hours):
        parts = [f"{km:,} km".replace(",", " ") if km else None, f"{hours:,} engine hours" if hours else None,
                 f"{months} month{'s' if months != 1 else ''}" if months else None]
        return " / ".join(p for p in parts if p) or ""
    return {
        "id": str(s.id), "type_id": str(s.type_id), "type": types.get(s.type_id), "name": s.name,
        "starts_on": s.starts_on.isoformat(), "is_active": s.is_active,
        **{k: getattr(s, k) for k in ("at_km", "at_months", "at_hours", "recurring", "every_km", "every_months",
                                       "every_hours", "until_km", "until_months", "until_hours", "remind_km",
                                       "remind_days", "remind_hours")},
        "vehicle_type_ids": list(s.vehicle_type_ids or []), "imeis": list(s.imeis or []),
        "vehicle_count": len(ms.schedule_vehicles(s, fleet)),
        "at": fmt(s.at_km, s.at_months, s.at_hours),
        "every": fmt(s.every_km, s.every_months, s.every_hours) if s.recurring else "",
        "until": fmt(s.until_km, s.until_months, s.until_hours) if s.recurring else "",
    }


@router.get("/schedules")
def list_schedules(request: Request, db: Session = Depends(get_db)):
    me, access = _me(request, db, VIEW, MANAGE, CONFIGURE)
    types = {t.id: t.name for t in db.query(MaintenanceType).filter(MaintenanceType.usergroup_id == me.usergroup_id)}
    fleet = ms.vehicles(db, me.usergroup_id)
    return [_schedule_out(s, types, fleet) for s in
            db.query(MaintenanceSchedule).filter(MaintenanceSchedule.usergroup_id == me.usergroup_id).order_by(func.lower(MaintenanceSchedule.name))]


def _apply_schedule(db: Session, me: PortalUser, s: MaintenanceSchedule, data: ScheduleIn) -> None:
    _own(db, MaintenanceType, me, data.type_id, "Maintenance type")
    types = {str(i) for (i,) in db.query(MaintenanceLookup.id).filter(MaintenanceLookup.usergroup_id == me.usergroup_id,
                                                                       MaintenanceLookup.kind == "vehicle_type")}
    fleet = ms.vehicles(db, me.usergroup_id)
    for k, v in data.model_dump().items():
        if k not in ("vehicle_type_ids", "imeis", "type_id", "starts_on"):
            setattr(s, k, v)
    s.type_id = _uuid(data.type_id, "Maintenance type")
    s.starts_on = data.starts_on or s.starts_on or datetime.now(timezone.utc).date()
    s.vehicle_type_ids = [t for t in dict.fromkeys(data.vehicle_type_ids) if t in types]
    s.imeis = [i for i in dict.fromkeys(data.imeis) if i in fleet]


@router.post("/schedules", status_code=201)
def create_schedule(data: ScheduleIn, request: Request, db: Session = Depends(get_db)):
    me, _ = _me(request, db, CONFIGURE)
    s = MaintenanceSchedule(usergroup_id=me.usergroup_id)
    _apply_schedule(db, me, s, data)
    db.add(s)
    _audit(db, me, "create", f"Added maintenance schedule “{s.name}”")
    db.commit()
    types = {t.id: t.name for t in db.query(MaintenanceType).filter(MaintenanceType.usergroup_id == me.usergroup_id)}
    return _schedule_out(s, types, ms.vehicles(db, me.usergroup_id))


@router.put("/schedules/{sid}")
def update_schedule(sid: str, data: ScheduleIn, request: Request, db: Session = Depends(get_db)):
    me, _ = _me(request, db, CONFIGURE)
    s = _own(db, MaintenanceSchedule, me, sid, "Schedule")
    _apply_schedule(db, me, s, data)
    _audit(db, me, "update", f"Changed maintenance schedule “{s.name}”", s.id)
    db.commit()
    types = {t.id: t.name for t in db.query(MaintenanceType).filter(MaintenanceType.usergroup_id == me.usergroup_id)}
    return _schedule_out(s, types, ms.vehicles(db, me.usergroup_id))


@router.post("/schedules/{sid}/copy", status_code=201)
def copy_schedule(sid: str, request: Request, db: Session = Depends(get_db)):
    me, _ = _me(request, db, CONFIGURE)
    s = _own(db, MaintenanceSchedule, me, sid, "Schedule")
    cols = [c.name for c in MaintenanceSchedule.__table__.columns if c.name not in ("id", "created_at")]
    c = MaintenanceSchedule(**{k: getattr(s, k) for k in cols})
    c.name = f"{s.name} (copy)"[:160]
    db.add(c)
    db.commit()
    types = {t.id: t.name for t in db.query(MaintenanceType).filter(MaintenanceType.usergroup_id == me.usergroup_id)}
    return _schedule_out(c, types, ms.vehicles(db, me.usergroup_id))


@router.delete("/schedules/{sid}", status_code=204)
def delete_schedule(sid: str, request: Request, db: Session = Depends(get_db)):
    """Delete the schedule; its saved jobs stay (without the link)."""
    me, _ = _me(request, db, CONFIGURE)
    s = _own(db, MaintenanceSchedule, me, sid, "Schedule")
    db.query(VehicleMaintenance).filter(VehicleMaintenance.schedule_id == s.id).update({"schedule_id": None})
    _audit(db, me, "delete", f"Deleted maintenance schedule “{s.name}”", s.id)
    db.delete(s)
    db.commit()


# ---------------------------------------------------------------------------
# Workshops
# ---------------------------------------------------------------------------

class WorkshopIn(BaseModel):
    name: str
    poi_id: Optional[str] = None
    chain_id: Optional[str] = None
    phone: Optional[str] = None
    type_ids: List[str] = []

    @field_validator("name")
    @classmethod
    def _n(cls, v):
        return _name(v)


def _workshop_out(w: Workshop, places: dict, chains: dict, jobs: int = 0) -> dict:
    return {"id": str(w.id), "name": w.name, "poi_id": str(w.poi_id) if w.poi_id else None, "place": places.get(w.poi_id),
            "chain_id": str(w.chain_id) if w.chain_id else None, "chain": chains.get(w.chain_id), "phone": w.phone,
            "type_ids": list(w.type_ids or []), "jobs": jobs}


def _workshop_maps(db: Session, me: PortalUser) -> tuple:
    places = {p.id: p.name for p in db.query(POI).filter(POI.usergroup_id == me.usergroup_id)}
    chains = {c.id: c.name for c in db.query(MaintenanceLookup).filter(MaintenanceLookup.usergroup_id == me.usergroup_id,
                                                                       MaintenanceLookup.kind == "workshop_chain")}
    return places, chains


@router.get("/workshops")
def list_workshops(request: Request, db: Session = Depends(get_db)):
    me, _ = _me(request, db, VIEW, MANAGE, CONFIGURE)
    places, chains = _workshop_maps(db, me)
    jobs = dict(db.query(VehicleMaintenance.workshop_id, func.count(VehicleMaintenance.id))
                .filter(VehicleMaintenance.usergroup_id == me.usergroup_id).group_by(VehicleMaintenance.workshop_id).all())
    return [_workshop_out(w, places, chains, jobs.get(w.id, 0)) for w in
            db.query(Workshop).filter(Workshop.usergroup_id == me.usergroup_id).order_by(func.lower(Workshop.name))]


def _apply_workshop(db: Session, me: PortalUser, w: Workshop, data: WorkshopIn) -> None:
    w.name, w.phone = data.name, (data.phone or "").strip()[:50] or None
    w.poi_id = _own(db, POI, me, data.poi_id, "Place").id if data.poi_id else None
    w.chain_id = _own(db, MaintenanceLookup, me, data.chain_id, "Workshop chain").id if data.chain_id else None
    mine = {str(i) for (i,) in db.query(MaintenanceLookup.id).filter(MaintenanceLookup.usergroup_id == me.usergroup_id,
                                                                      MaintenanceLookup.kind == "workshop_type")}
    w.type_ids = [t for t in dict.fromkeys(data.type_ids) if t in mine]


@router.post("/workshops", status_code=201)
def create_workshop(data: WorkshopIn, request: Request, db: Session = Depends(get_db)):
    me, _ = _me(request, db, CONFIGURE)
    _unique(db, Workshop, me, data.name)
    w = Workshop(usergroup_id=me.usergroup_id)
    _apply_workshop(db, me, w, data)
    db.add(w)
    db.commit()
    return _workshop_out(w, *_workshop_maps(db, me))


@router.put("/workshops/{wid}")
def update_workshop(wid: str, data: WorkshopIn, request: Request, db: Session = Depends(get_db)):
    me, _ = _me(request, db, CONFIGURE)
    w = _own(db, Workshop, me, wid, "Workshop")
    _unique(db, Workshop, me, data.name, exclude=w.id)
    _apply_workshop(db, me, w, data)
    db.commit()
    return _workshop_out(w, *_workshop_maps(db, me))


@router.delete("/workshops/{wid}", status_code=204)
def delete_workshop(wid: str, request: Request, db: Session = Depends(get_db)):
    me, _ = _me(request, db, CONFIGURE)
    w = _own(db, Workshop, me, wid, "Workshop")
    n = db.query(func.count(VehicleMaintenance.id)).filter(VehicleMaintenance.workshop_id == w.id).scalar()
    if n:
        raise HTTPException(status_code=409, detail=f"Used by {n} maintenance job{'s' if n != 1 else ''} — it can't be deleted")
    db.delete(w)
    db.commit()


# ---------------------------------------------------------------------------
# Jobs: saved and projected
# ---------------------------------------------------------------------------

def _filtered_fleet(fleet: dict, vehicle_group: Optional[str], vehicle_type_id: Optional[str], imei: Optional[str]) -> dict:
    return {i: v for i, v in fleet.items()
            if (not vehicle_group or v["group"] == vehicle_group) and (not vehicle_type_id or v["type_id"] == vehicle_type_id)
            and (not imei or i == imei)}


@router.get("/jobs")
def list_jobs(request: Request, db: Session = Depends(get_db),
              date_from: Optional[datetime] = None, date_to: Optional[datetime] = None,
              status: Optional[str] = None, type_id: Optional[str] = None, workshop_id: Optional[str] = None,
              vehicle_group: Optional[str] = None, vehicle_type_id: Optional[str] = None, imei: Optional[str] = None):
    """Saved jobs planned in the period plus projected ones from schedules (Overdue ones always show)."""
    me, access = _me(request, db, VIEW, MANAGE)
    fleet = _filtered_fleet(_fleet(db, me, access), vehicle_group, vehicle_type_id, imei)
    types, workshops, schedules = ms.lookups(db, me.usergroup_id)
    start = date_from or datetime.now(timezone.utc) - timedelta(days=30)
    end = date_to or datetime.now(timezone.utc) + timedelta(days=30)
    q = db.query(VehicleMaintenance).filter(VehicleMaintenance.usergroup_id == me.usergroup_id,
                                            VehicleMaintenance.imei.in_(list(fleet)),
                                            VehicleMaintenance.planned_start >= start, VehicleMaintenance.planned_start < end)
    if type_id:
        q = q.filter(VehicleMaintenance.type_id == _uuid(type_id, "Maintenance type"))
    if workshop_id:
        q = q.filter(VehicleMaintenance.workshop_id == _uuid(workshop_id, "Workshop"))
    jobs = q.all() if fleet else []
    costs = ms.job_costs(db, [j.id for j in jobs])
    rows = [ms.job_row(j, fleet, types, workshops, schedules, costs) for j in jobs]
    if not workshop_id:
        for s, t, i, occ in ms.projections(db, me.usergroup_id, fleet):
            if type_id and str(s.type_id) != type_id:
                continue
            in_period = occ.planned is not None and start.date() <= occ.planned < end.date()
            if occ.status == "Overdue" or in_period or (occ.planned is None and occ.status == "Due"):
                rows.append(ms.projected_row(s, t, i, occ, fleet))
    if status:
        rows = [r for r in rows if r["status"] == status]
    rows.sort(key=lambda r: (r["planned_start"] or "9999", r["vehicle"].lower()))
    return rows


class JobIn(BaseModel):
    imei: str
    description: str
    type_id: Optional[str] = None
    schedule_id: Optional[str] = None
    planned_start: datetime
    planned_end: Optional[datetime] = None
    actual_start: Optional[datetime] = None
    actual_end: Optional[datetime] = None
    odometer_km: Optional[int] = None
    engine_hours: Optional[float] = None
    workshop_id: Optional[str] = None
    reference: Optional[str] = None
    notes: Optional[str] = None

    @field_validator("description")
    @classmethod
    def _d(cls, v):
        return _name(v, "a description", 200)

    @model_validator(mode="after")
    def _dates(self):
        if self.planned_end and self.planned_end < self.planned_start:
            raise ValueError("Planned end is before planned start")
        if self.actual_end and not self.actual_start:
            raise ValueError("Set the actual start too")
        if self.actual_start and self.actual_end and self.actual_end < self.actual_start:
            raise ValueError("Actual end is before actual start")
        if self.actual_start and self.actual_start > datetime.now(timezone.utc) + timedelta(minutes=5):
            raise ValueError("Actual start can't be in the future")
        if self.odometer_km is not None and self.odometer_km < 0:
            raise ValueError("Odometer can't be negative")
        return self


def _apply_job(db: Session, me: PortalUser, j: VehicleMaintenance, data: JobIn, fleet: dict) -> None:
    if data.imei not in fleet:
        raise HTTPException(status_code=404, detail="Vehicle not found")
    t = _own(db, MaintenanceType, me, data.type_id, "Maintenance type") if data.type_id else None
    j.imei, j.description = data.imei, data.description
    j.type_id = t.id if t else None
    j.schedule_id = _own(db, MaintenanceSchedule, me, data.schedule_id, "Schedule").id if data.schedule_id else None
    j.planned_start, j.actual_start, j.actual_end = data.planned_start, data.actual_start, data.actual_end
    j.planned_end = data.planned_end or (data.planned_start + timedelta(hours=t.duration_hours) if t else None)
    j.workshop_id = _own(db, Workshop, me, data.workshop_id, "Workshop").id if data.workshop_id else None
    j.reference = (data.reference or "").strip()[:100] or None
    j.notes = (data.notes or "").strip() or None
    j.odometer_km, j.engine_hours = data.odometer_km, data.engine_hours
    # The next occurrence counts from the job's meters: fill them in from the vehicle when not given
    if j.actual_start and (j.odometer_km is None or j.engine_hours is None):
        m = ms.meters(db, [j.imei]).get(j.imei)
        if m:
            if j.odometer_km is None and m.odometer_km is not None:
                j.odometer_km = int(m.odometer_km)
            if j.engine_hours is None:
                j.engine_hours = m.engine_hours


@router.post("/jobs", status_code=201)
def create_job(data: JobIn, request: Request, db: Session = Depends(get_db)):
    me, access = _me(request, db, MANAGE)
    fleet = _fleet(db, me, access)
    j = VehicleMaintenance(usergroup_id=me.usergroup_id, created_by=me.email)
    _apply_job(db, me, j, data, fleet)
    db.add(j)
    _audit(db, me, "create", f"Added maintenance “{j.description}” for {fleet[j.imei]['name']}")
    db.commit()
    types, workshops, schedules = ms.lookups(db, me.usergroup_id)
    return ms.job_row(j, fleet, types, workshops, schedules, {})


@router.put("/jobs/{jid}")
def update_job(jid: str, data: JobIn, request: Request, db: Session = Depends(get_db)):
    me, access = _me(request, db, MANAGE)
    fleet = _fleet(db, me, access)
    j = _own(db, VehicleMaintenance, me, jid, "Maintenance")
    if j.imei not in fleet:
        raise HTTPException(status_code=404, detail="Maintenance not found")
    before = ms.job_status(j)
    _apply_job(db, me, j, data, fleet)
    after = ms.job_status(j)
    _audit(db, me, "update", f"Changed maintenance “{j.description}” for {fleet[j.imei]['name']}"
           + (f" ({before} → {after})" if before != after else ""), j.id)
    db.commit()
    types, workshops, schedules = ms.lookups(db, me.usergroup_id)
    return ms.job_row(j, fleet, types, workshops, schedules, ms.job_costs(db, [j.id]))


@router.delete("/jobs/{jid}", status_code=204)
def delete_job(jid: str, request: Request, db: Session = Depends(get_db)):
    me, access = _me(request, db, MANAGE)
    j = _own(db, VehicleMaintenance, me, jid, "Maintenance")
    if j.imei not in _fleet(db, me, access):
        raise HTTPException(status_code=404, detail="Maintenance not found")
    db.query(MaintenanceCost).filter(MaintenanceCost.maintenance_id == j.id).update({"maintenance_id": None})
    _audit(db, me, "delete", f"Deleted maintenance “{j.description}”", j.id)
    db.delete(j)
    db.commit()


@router.get("/summary")
def summary(request: Request, db: Session = Depends(get_db)):
    me, access = _me(request, db, VIEW, MANAGE)
    return ms.summary(db, me.usergroup_id, _fleet(db, me, access))


@router.get("/meters/{imei}")
def vehicle_meters(imei: str, request: Request, db: Session = Depends(get_db)):
    """The vehicle's current odometer and engine hours (for the job form)."""
    me, access = _me(request, db, VIEW, MANAGE)
    if imei not in _fleet(db, me, access):
        raise HTTPException(status_code=404, detail="Vehicle not found")
    m = ms.meters(db, [imei]).get(imei)
    return {"odometer_km": m.odometer_km if m else None, "engine_hours": m.engine_hours if m else None}


# ---------------------------------------------------------------------------
# Overview
# ---------------------------------------------------------------------------

@router.get("/overview")
def overview(request: Request, db: Session = Depends(get_db), date_from: datetime = Query(...), date_to: datetime = Query(...),
             by: str = Query("vehicle_group", pattern="^(vehicle_group|vehicle_type)$")):
    """Vehicles in the workshop (jobs in progress) and maintenance costs in the period, per vehicle group or type."""
    me, access = _me(request, db, VIEW, MANAGE)
    fleet = _fleet(db, me, access)
    type_names = {str(r.id): r.name for r in db.query(MaintenanceLookup).filter(MaintenanceLookup.usergroup_id == me.usergroup_id,
                                                                                MaintenanceLookup.kind == "vehicle_type")}

    def key(imei):
        v = fleet[imei]
        return (v["group"] or "No group") if by == "vehicle_group" else type_names.get(v["type_id"] or "", "No type")

    rows = {}
    for imei in fleet:
        r = rows.setdefault(key(imei), {"name": key(imei), "vehicles": 0, "in_workshop": 0, "cost": 0.0, "trend": []})
        r["vehicles"] += 1
    jobs = (db.query(VehicleMaintenance)
            .filter(VehicleMaintenance.usergroup_id == me.usergroup_id, VehicleMaintenance.imei.in_(list(fleet)),
                    VehicleMaintenance.actual_start.isnot(None)).all()) if fleet else []
    days = max(1, min(31, (date_to.date() - date_from.date()).days + 1))
    trend_days = [date_to.date() - timedelta(days=i) for i in range(max(days, 14) - 1, -1, -1)]

    def busy(j, a: datetime, b: datetime) -> bool:   # in the workshop at some time in [a, b)
        return ms._utc(j.actual_start) < b and (j.actual_end is None or ms._utc(j.actual_end) >= a)

    def day(d: date) -> tuple:
        start = datetime.combine(d, datetime.min.time(), tzinfo=timezone.utc)
        return start, start + timedelta(days=1)

    a, b = ms._utc(date_from), ms._utc(date_to)
    for name, r in rows.items():
        mine = [j for j in jobs if key(j.imei) == name]
        r["in_workshop"] = len({j.imei for j in mine if busy(j, a, b)})
        r["trend"] = [len({j.imei for j in mine if busy(j, *day(d))}) for d in trend_days]
    for imei, amount in (db.query(MaintenanceCost.imei, func.sum(MaintenanceCost.amount))
                         .filter(MaintenanceCost.usergroup_id == me.usergroup_id, MaintenanceCost.imei.in_(list(fleet)),
                                 MaintenanceCost.cost_date >= date_from.date(), MaintenanceCost.cost_date <= date_to.date())
                         .group_by(MaintenanceCost.imei)) if fleet else []:
        rows[key(imei)]["cost"] += float(amount or 0)
    counts = {"Overdue": 0, "Due": 0}
    for _, _, _, occ in ms.projections(db, me.usergroup_id, fleet):
        if occ.status in counts:
            counts[occ.status] += 1
    return {"rows": sorted(rows.values(), key=lambda r: r["name"].lower()),
            "trend_days": [d.isoformat() for d in trend_days], "overdue": counts["Overdue"], "due": counts["Due"],
            "in_workshop_now": len({j.imei for j in jobs if j.actual_end is None}),
            "cost": round(sum(r["cost"] for r in rows.values()), 2)}


# ---------------------------------------------------------------------------
# Costs
# ---------------------------------------------------------------------------

class CostIn(BaseModel):
    imei: str
    cost_date: date
    maintenance_id: Optional[str] = None
    item_id: Optional[str] = None
    cost_centre_id: Optional[str] = None
    description: Optional[str] = None
    amount: Decimal
    amortise_from: Optional[date] = None
    amortise_to: Optional[date] = None

    @model_validator(mode="after")
    def _check(self):
        if self.amount < 0 or self.amount > Decimal("99999999"):
            raise ValueError("Enter a cost from 0")
        if (self.amortise_from is None) != (self.amortise_to is None):
            raise ValueError("Set both amortisation dates, or neither")
        if self.amortise_from and self.amortise_to < self.amortise_from:
            raise ValueError("Amortisation ends before it starts")
        return self


def _cost_out(c: MaintenanceCost, fleet: dict, names: dict, type_names: dict) -> dict:
    v = fleet.get(c.imei, {})
    return {"id": str(c.id), "imei": c.imei, "vehicle": v.get("name", c.imei), "vehicle_type": type_names.get(v.get("type_id") or ""),
            "cost_date": c.cost_date.isoformat(), "maintenance_id": str(c.maintenance_id) if c.maintenance_id else None,
            "maintenance": names["jobs"].get(c.maintenance_id), "item_id": str(c.item_id) if c.item_id else None,
            "item": names["items"].get(c.item_id), "cost_centre_id": str(c.cost_centre_id) if c.cost_centre_id else None,
            "cost_centre": names["centres"].get(c.cost_centre_id), "description": c.description, "amount": float(c.amount),
            "amortise_from": c.amortise_from.isoformat() if c.amortise_from else None,
            "amortise_to": c.amortise_to.isoformat() if c.amortise_to else None}


def _cost_names(db: Session, me: PortalUser) -> tuple:
    g = me.usergroup_id
    names = {"jobs": {j.id: j.description for j in db.query(VehicleMaintenance).filter(VehicleMaintenance.usergroup_id == g)},
             "items": {i.id: i.name for i in db.query(MaintenanceItem).filter(MaintenanceItem.usergroup_id == g)},
             "centres": {c.id: c.name for c in db.query(MaintenanceLookup).filter(MaintenanceLookup.usergroup_id == g,
                                                                                  MaintenanceLookup.kind == "cost_centre")}}
    type_names = {str(r.id): r.name for r in db.query(MaintenanceLookup).filter(MaintenanceLookup.usergroup_id == g,
                                                                                MaintenanceLookup.kind == "vehicle_type")}
    return names, type_names


@router.get("/costs")
def list_costs(request: Request, db: Session = Depends(get_db),
               date_from: Optional[date] = None, date_to: Optional[date] = None, vehicle_group: Optional[str] = None,
               vehicle_type_id: Optional[str] = None, type_id: Optional[str] = None, item_id: Optional[str] = None,
               cost_centre_id: Optional[str] = None, maintenance_id: Optional[str] = None):
    me, access = _me(request, db, VIEW, MANAGE)
    fleet = _filtered_fleet(_fleet(db, me, access), vehicle_group, vehicle_type_id, None)
    if not fleet:
        return []
    q = db.query(MaintenanceCost).filter(MaintenanceCost.usergroup_id == me.usergroup_id, MaintenanceCost.imei.in_(list(fleet)))
    if date_from:
        q = q.filter(MaintenanceCost.cost_date >= date_from)
    if date_to:
        q = q.filter(MaintenanceCost.cost_date <= date_to)
    if item_id:
        q = q.filter(MaintenanceCost.item_id == _uuid(item_id, "Item"))
    if cost_centre_id:
        q = q.filter(MaintenanceCost.cost_centre_id == _uuid(cost_centre_id, "Cost centre"))
    if maintenance_id:
        q = q.filter(MaintenanceCost.maintenance_id == _uuid(maintenance_id, "Maintenance"))
    if type_id:
        q = q.join(VehicleMaintenance, VehicleMaintenance.id == MaintenanceCost.maintenance_id).filter(
            VehicleMaintenance.type_id == _uuid(type_id, "Maintenance type"))
    names, type_names = _cost_names(db, me)
    return [_cost_out(c, fleet, names, type_names) for c in q.order_by(MaintenanceCost.cost_date.desc()).limit(5000)]


def _apply_cost(db: Session, me: PortalUser, c: MaintenanceCost, data: CostIn, fleet: dict) -> None:
    if data.imei not in fleet:
        raise HTTPException(status_code=404, detail="Vehicle not found")
    job = _own(db, VehicleMaintenance, me, data.maintenance_id, "Maintenance") if data.maintenance_id else None
    if job and job.imei != data.imei:
        raise HTTPException(status_code=400, detail="That maintenance job is for another vehicle")
    c.imei, c.cost_date, c.amount = data.imei, data.cost_date, data.amount
    c.maintenance_id = job.id if job else None
    c.item_id = _own(db, MaintenanceItem, me, data.item_id, "Item").id if data.item_id else None
    c.cost_centre_id = _own(db, MaintenanceLookup, me, data.cost_centre_id, "Cost centre").id if data.cost_centre_id else None
    c.description = (data.description or "").strip()[:200] or None
    c.amortise_from, c.amortise_to = data.amortise_from, data.amortise_to


@router.post("/costs", status_code=201)
def create_cost(data: CostIn, request: Request, db: Session = Depends(get_db)):
    me, access = _me(request, db, MANAGE)
    fleet = _fleet(db, me, access)
    c = MaintenanceCost(usergroup_id=me.usergroup_id)
    _apply_cost(db, me, c, data, fleet)
    db.add(c)
    db.commit()
    return _cost_out(c, fleet, *_cost_names(db, me))


@router.put("/costs/{cid}")
def update_cost(cid: str, data: CostIn, request: Request, db: Session = Depends(get_db)):
    me, access = _me(request, db, MANAGE)
    fleet = _fleet(db, me, access)
    c = _own(db, MaintenanceCost, me, cid, "Cost item")
    if c.imei not in fleet:
        raise HTTPException(status_code=404, detail="Cost item not found")
    _apply_cost(db, me, c, data, fleet)
    db.commit()
    return _cost_out(c, fleet, *_cost_names(db, me))


@router.delete("/costs/{cid}", status_code=204)
def delete_cost(cid: str, request: Request, db: Session = Depends(get_db)):
    me, access = _me(request, db, MANAGE)
    c = _own(db, MaintenanceCost, me, cid, "Cost item")
    if c.imei not in _fleet(db, me, access):
        raise HTTPException(status_code=404, detail="Cost item not found")
    db.delete(c)
    db.commit()


# ---------------------------------------------------------------------------
# DTC
# ---------------------------------------------------------------------------

@router.get("/dtc")
def dtc(request: Request, db: Session = Depends(get_db), imei: str = Query(...),
        date_from: datetime = Query(...), date_to: datetime = Query(...)):
    """Fault codes the vehicle's device reported (OBD), newest first."""
    me, access = _me(request, db, VIEW, MANAGE)
    if imei not in _fleet(db, me, access):
        raise HTTPException(status_code=404, detail="Vehicle not found")
    return ms.dtc_events(db, imei, ms._utc(date_from), ms._utc(date_to))
