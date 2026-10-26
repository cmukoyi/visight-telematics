"""Breakdowns: logged by drivers in the mobile app, reviewed in Vehicle Maintenance → Breakdowns.

Mounted under /api/portal/breakdowns (bearer token or session, like the rest of
the portal API). Logging needs breakdowns.log and a vehicle the user may see;
the history needs maintenance.view (or the right to log, for one's own); the
review needs maintenance.manage. See app/services/breakdown_service.py.
"""
from datetime import datetime, timedelta, timezone
from typing import Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, field_validator
from sqlalchemy.orm import Session

from app.database import get_db
from app.models_maintenance import VehicleBreakdown
from app.routes_portal import get_portal_user_from_request
from app.services import access_service, audit_service
from app.services import breakdown_service as bs
from app.services import maintenance_service as ms

router = APIRouter(prefix="/api/portal/breakdowns", tags=["portal-breakdowns"])

LOG, VIEW, MANAGE = "breakdowns.log", "maintenance.view", "maintenance.manage"


def _me(request: Request, db: Session, *any_of: str):
    me = get_portal_user_from_request(request, db)
    access = access_service.for_user(me, db)
    if not any(access.can(p) for p in any_of):
        access.require(any_of[0])
    return me, access


def _names(db: Session, me, access) -> dict:
    return {i: v["name"] for i, v in ms.vehicles(db, me.usergroup_id, access.visible_imeis(db)).items()}


def _describe(db: Session, me):
    from app.services.address_service import Describer
    return Describer(db, me.usergroup_id)


def _own(db: Session, me, access, bid: str) -> VehicleBreakdown:
    try:
        b = db.get(VehicleBreakdown, UUID(bid))
    except ValueError:
        b = None
    if not b or b.usergroup_id != me.usergroup_id or not access.can_see(db, b.imei):
        raise HTTPException(status_code=404, detail="Breakdown not found")
    return b


class Position(BaseModel):
    latitude: Optional[float] = None
    longitude: Optional[float] = None
    accuracy: Optional[float] = None

    @field_validator("latitude")
    @classmethod
    def _lat(cls, v):
        if v is not None and not -90 <= v <= 90:
            raise ValueError("Latitude out of range")
        return v

    @field_validator("longitude")
    @classmethod
    def _lng(cls, v):
        if v is not None and not -180 <= v <= 180:
            raise ValueError("Longitude out of range")
        return v


class StartIn(Position):
    imei: str
    cause: Optional[str] = None

    @field_validator("cause")
    @classmethod
    def _cause(cls, v):
        if v and v not in bs.CAUSES:
            raise ValueError(f"Choose one of: {', '.join(bs.CAUSES)}")
        return v or None


class PhaseIn(Position):
    phase: str


class ResolveIn(Position):
    notes: Optional[str] = None


class ReviewIn(BaseModel):
    review: Optional[str] = None   # accepted | disputed | None (not reviewed)
    note: Optional[str] = None

    @field_validator("review")
    @classmethod
    def _r(cls, v):
        if v not in (None, "accepted", "disputed"):
            raise ValueError("Review is accepted or disputed")
        return v


@router.get("/options")
def options(request: Request, db: Session = Depends(get_db)):
    """Causes and phases the app offers."""
    _me(request, db, LOG, VIEW)
    return {"causes": list(bs.CAUSES), "phases": list(bs.PHASES)}


@router.get("/active")
def active(request: Request, db: Session = Depends(get_db), imei: str = Query(...)):
    """The vehicle's breakdown in progress, or null."""
    me, access = _me(request, db, LOG, VIEW)
    if not access.can_see(db, imei):
        raise HTTPException(status_code=404, detail="Vehicle not found")
    b = bs.active(db, me.usergroup_id, imei)
    return bs.row(db, b, _names(db, me, access), _describe(db, me)) if b else None


@router.post("", status_code=201)
def start(data: StartIn, request: Request, db: Session = Depends(get_db)):
    """Start the breakdown timer for a vehicle (the job opens in Vehicle Maintenance)."""
    me, access = _me(request, db, LOG)
    if not access.can_see(db, data.imei):
        raise HTTPException(status_code=404, detail="Vehicle not found")
    b = bs.start(db, me, data.imei, data.latitude, data.longitude, data.accuracy, data.cause)
    names = _names(db, me, access)
    audit_service.record(db, me, "create", "Maintenance", f"Logged a breakdown for {names.get(b.imei, b.imei)}", resource_id=b.id)
    db.commit()
    return bs.row(db, b, names, _describe(db, me))


@router.post("/{bid}/phases")
def add_phase(bid: str, data: PhaseIn, request: Request, db: Session = Depends(get_db)):
    me, access = _me(request, db, LOG)
    b = _own(db, me, access, bid)
    bs.add_phase(db, b, data.phase, data.latitude, data.longitude)
    return bs.row(db, b, _names(db, me, access), _describe(db, me))


@router.post("/{bid}/resolve")
def resolve(bid: str, data: ResolveIn, request: Request, db: Session = Depends(get_db)):
    """Stop the clock: the breakdown and its maintenance job end now."""
    me, access = _me(request, db, LOG)
    b = _own(db, me, access, bid)
    bs.resolve(db, b, data.latitude, data.longitude, data.notes)
    return bs.row(db, b, _names(db, me, access), _describe(db, me))


@router.get("")
def list_breakdowns(request: Request, db: Session = Depends(get_db), date_from: Optional[datetime] = None,
                    date_to: Optional[datetime] = None, imei: Optional[str] = None):
    """Breakdowns that started in the period, newest first, with the tracker evidence.
    Without maintenance.view a user sees only the ones they logged."""
    me, access = _me(request, db, VIEW, LOG)
    names = _names(db, me, access)
    end = date_to or datetime.now(timezone.utc) + timedelta(days=1)
    start = date_from or end - timedelta(days=31)
    q = db.query(VehicleBreakdown).filter(VehicleBreakdown.usergroup_id == me.usergroup_id,
                                          VehicleBreakdown.imei.in_(list(names)),
                                          VehicleBreakdown.started_at >= start, VehicleBreakdown.started_at < end)
    if imei:
        q = q.filter(VehicleBreakdown.imei == imei)
    if not access.can(VIEW):
        q = q.filter(VehicleBreakdown.reported_by_id == me.id)
    rows = q.order_by(VehicleBreakdown.started_at.desc()).limit(500).all() if names else []
    describe = _describe(db, me).prefetch((b.start_lat, b.start_lng) for b in rows)
    return [bs.row(db, b, names, describe) for b in rows]


@router.get("/{bid}")
def get_breakdown(bid: str, request: Request, db: Session = Depends(get_db)):
    """One breakdown with the vehicle's track during it (for the map)."""
    me, access = _me(request, db, VIEW, LOG)
    b = _own(db, me, access, bid)
    if not access.can(VIEW) and b.reported_by_id != me.id:
        raise HTTPException(status_code=404, detail="Breakdown not found")
    return bs.row(db, b, _names(db, me, access), _describe(db, me), with_track=True)


@router.put("/{bid}/review")
def review(bid: str, data: ReviewIn, request: Request, db: Session = Depends(get_db)):
    """Accept or dispute a breakdown, with a note."""
    me, access = _me(request, db, MANAGE)
    b = _own(db, me, access, bid)
    b.review, b.review_note = data.review, (data.note or "").strip()[:2000] or None
    b.reviewed_by = (" ".join(x for x in (me.first_name, me.last_name) if x) or me.email) if data.review else None
    names = _names(db, me, access)
    audit_service.record(db, me, "update", "Maintenance",
                         f"{(data.review or 'cleared review').capitalize()}: breakdown of {names.get(b.imei, b.imei)}", resource_id=b.id)
    db.commit()
    return bs.row(db, b, names, _describe(db, me))
