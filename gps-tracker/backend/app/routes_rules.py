"""Customer portal — notification rules (Configuration → Misc → Notification Rules).

Mounted under /api/portal; scoped to the caller's user group.
"""
from typing import List, Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, EmailStr, field_validator
from sqlalchemy.orm import Session

from app.database import get_db
from app.dataprofiler.dictionary import EVENTS
from app.models import POI, EventTypeGroup, NotificationRule, PlaceGroup, PortalUser, TagCategory
from app.routes_portal import get_portal_user_from_request
from app.services import access_service, geofence_engine

router = APIRouter(prefix="/api/portal", tags=["portal-rules"])

RULE_TYPES = {"geofence": "Place entry / exit", "event": "Vehicle event"}


def _me(request: Request, db: Session, write: bool = False) -> PortalUser:
    me = get_portal_user_from_request(request, db)
    access = access_service.for_user(me, db)
    if write or not access.can("inbox.view"):
        access.require("rules.manage")
    return me


class RuleIn(BaseModel):
    name: str
    rule_type: str = "geofence"
    category: Optional[str] = None            # vehicle group; None = all vehicles
    place_ids: Optional[List[UUID]] = None    # None / [] = every place (with no place groups either)
    place_group_ids: Optional[List[UUID]] = None
    event_group_id: Optional[UUID] = None     # rule_type "event": fire on any event in this group…
    event_codes: List[str] = []               # …and/or on any of these event types (e.g. overspeed, harsh_braking)
    on_entry: bool = True
    on_exit: bool = True
    email_enabled: bool = False
    email_recipients: List[EmailStr] = []
    email_message: Optional[str] = None
    is_active: bool = True

    @field_validator("name")
    @classmethod
    def _name(cls, v):
        v = v.strip()
        if not v or len(v) > 120:
            raise ValueError("Enter a name (up to 120 characters)")
        return v

    @field_validator("rule_type")
    @classmethod
    def _type(cls, v):
        if v not in RULE_TYPES:
            raise ValueError("Unknown rule type")
        return v

    @field_validator("email_recipients")
    @classmethod
    def _recipients(cls, v):
        if len(v) > 20:
            raise ValueError("At most 20 email addresses")
        return v

    @field_validator("email_message")
    @classmethod
    def _message(cls, v):
        if v and len(v) > 2000:
            raise ValueError("Keep the message under 2000 characters")
        return v


def _out(r: NotificationRule) -> dict:
    return {"id": str(r.id), "name": r.name, "rule_type": r.rule_type, "rule_type_label": RULE_TYPES.get(r.rule_type, r.rule_type),
            "category": r.category, "place_ids": r.place_ids or [], "place_group_ids": r.place_group_ids or [],
            "event_group_id": str(r.event_group_id) if r.event_group_id else None, "event_codes": r.event_codes or [],
            "on_entry": r.on_entry, "on_exit": r.on_exit,
            "email_enabled": r.email_enabled, "email_recipients": r.email_recipients or [],
            "email_message": r.email_message, "is_active": r.is_active, "created_at": r.created_at}


def _apply(db: Session, me: PortalUser, r: NotificationRule, data: RuleIn) -> None:
    if data.rule_type == "geofence" and not data.on_entry and not data.on_exit:
        raise HTTPException(status_code=400, detail="Notify on entry, exit or both")
    codes = list(dict.fromkeys(data.event_codes)) if data.rule_type == "event" else []
    if data.rule_type == "event":
        if any(c not in EVENTS for c in codes):
            raise HTTPException(status_code=400, detail="Unknown event type")
        if data.event_group_id and not db.query(EventTypeGroup).filter(
                EventTypeGroup.id == data.event_group_id, EventTypeGroup.usergroup_id == me.usergroup_id).first():
            raise HTTPException(status_code=400, detail="Unknown event type group")
        if not codes and not data.event_group_id:
            raise HTTPException(status_code=400, detail="Choose the events this rule watches")
    group_ids = [str(g) for g in data.place_group_ids or []]
    if group_ids:
        found = {str(g) for (g,) in db.query(PlaceGroup.id).filter(PlaceGroup.usergroup_id == me.usergroup_id,
                                                                  PlaceGroup.id.in_(group_ids))}
        if len(found) != len(set(group_ids)):
            raise HTTPException(status_code=400, detail="Unknown place group")
    if data.category and not db.query(TagCategory).filter(TagCategory.usergroup_id == me.usergroup_id,
                                                          TagCategory.name == data.category,
                                                          TagCategory.is_active == True).first():  # noqa: E712
        raise HTTPException(status_code=400, detail="Unknown vehicle group")
    place_ids = [str(p) for p in data.place_ids or []]
    if place_ids:
        found = {str(p) for (p,) in db.query(POI.id).filter(POI.usergroup_id == me.usergroup_id, POI.id.in_(place_ids))}
        if len(found) != len(set(place_ids)):
            raise HTTPException(status_code=400, detail="Unknown place")
    if data.email_enabled and not data.email_recipients:
        raise HTTPException(status_code=400, detail="Add at least one email address, or untick Subscribe by email")
    r.name, r.rule_type, r.category = data.name, data.rule_type, data.category or None
    r.place_ids = place_ids or None
    r.place_group_ids = (group_ids or None) if data.rule_type == "geofence" else None
    r.event_group_id = data.event_group_id if data.rule_type == "event" else None
    r.event_codes = codes or None
    r.on_entry, r.on_exit, r.is_active = data.on_entry, data.on_exit, data.is_active
    r.email_enabled = data.email_enabled
    r.email_recipients = [str(e).lower() for e in data.email_recipients] if data.email_enabled else []
    r.email_message = (data.email_message or "").strip() or None if data.email_enabled else None


def _own(db: Session, me: PortalUser, rule_id: str) -> NotificationRule:
    try:
        UUID(rule_id)
    except ValueError:
        raise HTTPException(status_code=404, detail="Rule not found")
    r = db.query(NotificationRule).filter(NotificationRule.id == rule_id, NotificationRule.usergroup_id == me.usergroup_id).first()
    if not r:
        raise HTTPException(status_code=404, detail="Rule not found")
    return r


@router.get("/notification-rules/meta")
def rules_meta(request: Request, db: Session = Depends(get_db)):
    """Rule types, message placeholders and the default message, for the editor."""
    _me(request, db)
    return {"rule_types": [{"value": k, "label": v} for k, v in RULE_TYPES.items()],
            "placeholders": [{"key": k, "label": v} for k, v in geofence_engine.PLACEHOLDERS.items()],
            "default_message": geofence_engine.DEFAULT_MESSAGE}


@router.get("/notification-rules")
def list_rules(request: Request, db: Session = Depends(get_db)):
    me = _me(request, db)
    rows = db.query(NotificationRule).filter(NotificationRule.usergroup_id == me.usergroup_id).order_by(NotificationRule.name).all()
    return [_out(r) for r in rows]


@router.post("/notification-rules", status_code=201)
def create_rule(data: RuleIn, request: Request, db: Session = Depends(get_db)):
    me = _me(request, db, write=True)
    r = NotificationRule(usergroup_id=me.usergroup_id, created_by=me.id)
    _apply(db, me, r, data)
    db.add(r)
    db.commit()
    return _out(r)


@router.put("/notification-rules/{rule_id}")
def update_rule(rule_id: str, data: RuleIn, request: Request, db: Session = Depends(get_db)):
    me = _me(request, db, write=True)
    r = _own(db, me, rule_id)
    _apply(db, me, r, data)
    db.commit()
    return _out(r)


@router.delete("/notification-rules/{rule_id}", status_code=204)
def delete_rule(rule_id: str, request: Request, db: Session = Depends(get_db)):
    me = _me(request, db, write=True)
    db.delete(_own(db, me, rule_id))
    db.commit()
