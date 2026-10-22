"""Customer portal — place groups, event types, event type groups and geofence assignments.

Mounted under /api/portal; everything is scoped to the caller's user group.
"""
from typing import List, Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, field_validator
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.database import get_db
from app.dataprofiler.dictionary import CATEGORIES, EVENTS
from app.models import (POI, BLETag, EventTypeGroup, EventTypeSetting, GeofenceStatus, NotificationRule, PlaceGroup,
                        POITrackerLink, PortalUser)
from app.routes_portal import get_portal_user_from_request
from app.services import access_service

router = APIRouter(prefix="/api/portal", tags=["portal-catalog"])

_HEX = r"^#[0-9a-fA-F]{6}$"


def _me(request: Request, db: Session, *any_of: str) -> PortalUser:
    me = get_portal_user_from_request(request, db)
    access = access_service.for_user(me, db)
    if any_of and not any(access.can(p) for p in any_of):
        access.require(any_of[0])
    return me


def _uuid(value: str, what: str) -> UUID:
    try:
        return UUID(value)
    except ValueError:
        raise HTTPException(status_code=404, detail=f"{what} not found")


class NamedIn(BaseModel):
    name: str
    color: Optional[str] = None

    @field_validator("name")
    @classmethod
    def _name(cls, v):
        v = v.strip()
        if not v or len(v) > 100:
            raise ValueError("Enter a name (up to 100 characters)")
        return v

    @field_validator("color")
    @classmethod
    def _color(cls, v):
        import re
        if v and not re.match(_HEX, v):
            raise ValueError("Colour must be like #3e7cfb")
        return v or None


# ---------------------------------------------------------------------------
# Place groups
# ---------------------------------------------------------------------------

def _pg_out(db: Session, g: PlaceGroup) -> dict:
    n = db.query(func.count(POI.id)).filter(POI.place_group_id == g.id, POI.is_active == True).scalar()  # noqa: E712
    return {"id": str(g.id), "name": g.name, "color": g.color, "place_count": n}


def _own_pg(db: Session, me: PortalUser, gid: str) -> PlaceGroup:
    g = db.query(PlaceGroup).filter(PlaceGroup.id == _uuid(gid, "Place group"), PlaceGroup.usergroup_id == me.usergroup_id).first()
    if not g:
        raise HTTPException(status_code=404, detail="Place group not found")
    return g


def _unique(db: Session, model, me: PortalUser, name: str, exclude=None):
    q = db.query(model).filter(model.usergroup_id == me.usergroup_id, func.lower(model.name) == name.lower())
    if exclude is not None:
        q = q.filter(model.id != exclude)
    if q.first():
        raise HTTPException(status_code=409, detail=f"'{name}' already exists")


@router.get("/place-groups")
def list_place_groups(request: Request, db: Session = Depends(get_db)):
    me = _me(request, db)
    rows = db.query(PlaceGroup).filter(PlaceGroup.usergroup_id == me.usergroup_id).order_by(PlaceGroup.name).all()
    return [_pg_out(db, g) for g in rows]


@router.post("/place-groups", status_code=201)
def create_place_group(data: NamedIn, request: Request, db: Session = Depends(get_db)):
    me = _me(request, db, "places.manage")
    _unique(db, PlaceGroup, me, data.name)
    g = PlaceGroup(usergroup_id=me.usergroup_id, name=data.name, color=data.color)
    db.add(g)
    db.commit()
    return _pg_out(db, g)


@router.put("/place-groups/{gid}")
def update_place_group(gid: str, data: NamedIn, request: Request, db: Session = Depends(get_db)):
    me = _me(request, db, "places.manage")
    g = _own_pg(db, me, gid)
    _unique(db, PlaceGroup, me, data.name, exclude=g.id)
    g.name, g.color = data.name, data.color
    db.commit()
    return _pg_out(db, g)


@router.delete("/place-groups/{gid}", status_code=204)
def delete_place_group(gid: str, request: Request, db: Session = Depends(get_db)):
    """Delete the group; its places stay, without a group."""
    me = _me(request, db, "places.manage")
    g = _own_pg(db, me, gid)
    db.query(POI).filter(POI.place_group_id == g.id).update({"place_group_id": None})
    db.delete(g)
    db.commit()


# ---------------------------------------------------------------------------
# Event types (our dictionary, with the group's own names and marker colours)
# ---------------------------------------------------------------------------

def event_labels(db: Session, usergroup_id) -> dict:
    """{code: the group's own name} for codes the group renamed."""
    return {s.code: s.label for s in db.query(EventTypeSetting).filter(
        EventTypeSetting.usergroup_id == usergroup_id, EventTypeSetting.label.isnot(None))}


@router.get("/event-type-list")
def list_event_types(request: Request, db: Session = Depends(get_db)):
    me = _me(request, db)
    settings = {s.code: s for s in db.query(EventTypeSetting).filter(EventTypeSetting.usergroup_id == me.usergroup_id)}
    cats = {c["key"]: c["label"] for c in CATEGORIES}
    out = []
    for i, (code, (label, category, kind)) in enumerate(EVENTS.items(), start=1):
        st = settings.get(code)
        out.append({"id": i, "code": code, "default_label": label, "label": (st.label if st and st.label else label),
                    "custom_label": st.label if st else None, "color": st.color if st else None,
                    "category": category, "category_label": cats.get(category, category), "kind": kind})
    return out


class EventTypeIn(BaseModel):
    label: Optional[str] = None     # "" / None = back to the default name
    color: Optional[str] = None

    @field_validator("label")
    @classmethod
    def _label(cls, v):
        v = (v or "").strip()
        if len(v) > 120:
            raise ValueError("Keep the name under 120 characters")
        return v or None

    @field_validator("color")
    @classmethod
    def _color(cls, v):
        import re
        if v and not re.match(_HEX, v):
            raise ValueError("Colour must be like #3e7cfb")
        return v or None


@router.put("/event-type-list/{code}")
def update_event_type(code: str, data: EventTypeIn, request: Request, db: Session = Depends(get_db)):
    me = _me(request, db, "settings.manage", "rules.manage")
    if code not in EVENTS:
        raise HTTPException(status_code=404, detail="Unknown event type")
    st = db.get(EventTypeSetting, (me.usergroup_id, code))
    if st is None:
        st = EventTypeSetting(usergroup_id=me.usergroup_id, code=code)
        db.add(st)
    st.label, st.color = data.label, data.color
    if st.label is None and st.color is None:
        db.delete(st)
    db.commit()
    return {"code": code, "label": data.label or EVENTS[code][0], "custom_label": data.label, "color": data.color}


# ---------------------------------------------------------------------------
# Event type groups
# ---------------------------------------------------------------------------

class EventGroupIn(NamedIn):
    codes: List[str] = []

    @field_validator("codes")
    @classmethod
    def _codes(cls, v):
        unknown = [c for c in v if c not in EVENTS]
        if unknown:
            raise ValueError(f"Unknown event type: {', '.join(unknown)}")
        if not v:
            raise ValueError("Choose at least one event type")
        return sorted(set(v))


def _eg_out(db: Session, g: EventTypeGroup) -> dict:
    rules = db.query(func.count(NotificationRule.id)).filter(NotificationRule.event_group_id == g.id).scalar()
    return {"id": str(g.id), "name": g.name, "codes": g.codes or [], "rule_count": rules}


def _own_eg(db: Session, me: PortalUser, gid: str) -> EventTypeGroup:
    g = db.query(EventTypeGroup).filter(EventTypeGroup.id == _uuid(gid, "Event type group"),
                                        EventTypeGroup.usergroup_id == me.usergroup_id).first()
    if not g:
        raise HTTPException(status_code=404, detail="Event type group not found")
    return g


@router.get("/event-type-groups")
def list_event_groups(request: Request, db: Session = Depends(get_db)):
    me = _me(request, db)
    rows = db.query(EventTypeGroup).filter(EventTypeGroup.usergroup_id == me.usergroup_id).order_by(EventTypeGroup.name).all()
    return [_eg_out(db, g) for g in rows]


@router.post("/event-type-groups", status_code=201)
def create_event_group(data: EventGroupIn, request: Request, db: Session = Depends(get_db)):
    me = _me(request, db, "rules.manage", "settings.manage")
    _unique(db, EventTypeGroup, me, data.name)
    g = EventTypeGroup(usergroup_id=me.usergroup_id, name=data.name, codes=data.codes)
    db.add(g)
    db.commit()
    return _eg_out(db, g)


@router.put("/event-type-groups/{gid}")
def update_event_group(gid: str, data: EventGroupIn, request: Request, db: Session = Depends(get_db)):
    me = _me(request, db, "rules.manage", "settings.manage")
    g = _own_eg(db, me, gid)
    _unique(db, EventTypeGroup, me, data.name, exclude=g.id)
    g.name, g.codes = data.name, data.codes
    db.commit()
    return _eg_out(db, g)


@router.delete("/event-type-groups/{gid}", status_code=204)
def delete_event_group(gid: str, request: Request, db: Session = Depends(get_db)):
    me = _me(request, db, "rules.manage", "settings.manage")
    g = _own_eg(db, me, gid)
    if db.query(NotificationRule.id).filter(NotificationRule.event_group_id == g.id).first():
        raise HTTPException(status_code=409, detail="A notification rule uses this group; change or delete the rule first")
    db.delete(g)
    db.commit()


# ---------------------------------------------------------------------------
# Geofences: which vehicle is armed to which place, and whether it's inside
# ---------------------------------------------------------------------------

@router.get("/geofences")
def list_geofences(request: Request, db: Session = Depends(get_db)):
    me = _me(request, db, "places.view", "places.manage")
    visible = access_service.for_user(me, db).visible_imeis(db)
    rows = (db.query(POITrackerLink, POI, BLETag)
            .join(POI, POI.id == POITrackerLink.poi_id).join(BLETag, BLETag.id == POITrackerLink.tracker_id)
            .filter(POI.usergroup_id == me.usergroup_id, POI.is_active == True,  # noqa: E712
                    POITrackerLink.is_armed == True).all())  # noqa: E712
    states = {(s.tag_id, s.poi_id): s for s in db.query(GeofenceStatus).filter(
        GeofenceStatus.poi_id.in_([p.id for _, p, _ in rows] or [None]))}
    out = []
    for link, poi, tag in rows:
        if visible is not None and tag.imei not in visible:
            continue
        st = states.get((tag.id, poi.id))
        out.append({"poi_id": str(poi.id), "place": poi.name, "tag_id": str(tag.id), "imei": tag.imei,
                    "vehicle": tag.description or tag.device_name or tag.imei,
                    "armed_at": link.armed_at, "inside": None if st is None else st.inside,
                    "checked_at": st.checked_at if st else None})
    out.sort(key=lambda r: (r["place"].lower(), r["vehicle"].lower()))
    return out
