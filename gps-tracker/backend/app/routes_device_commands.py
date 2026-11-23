"""Tracker commands in the customer portal (Configuration → Vehicles → Edit vehicle → Commands).

    GET  /api/portal/tags/{tag_id}/commands   the vehicle's recent commands and their replies
    POST /api/portal/tags/{tag_id}/commands   queue a command ({"command": "web_connect"})

Needs vehicles.manage, like the rest of Edit vehicle. The GPRS listener sends
queued commands on the device's open session, or when it next connects
(app/dataprofiler/listener.py). Each send is written to the audit trail here;
the audit middleware skips this path.
"""
from datetime import datetime, timezone
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import BLETag, UserGroup
from app.models_dataprofiler import DeviceCommand
from app.routes_portal import _client_ip, _get_group_owner_ids, _group_tag_scope_filter, get_portal_user_from_request
from app.services import access_service, audit_service
from app.services import device_command_service as dc

router = APIRouter(prefix="/api/portal", tags=["portal-device-commands"])

HISTORY_LIMIT = 10


class CommandIn(BaseModel):
    command: str


def _vehicle(request: Request, db: Session, tag_id: str):
    """The signed-in user and the vehicle (404 unless it's in their group and security group)."""
    me = get_portal_user_from_request(request, db)
    access = access_service.for_user(me, db)
    access.require("vehicles.manage")
    group = db.query(UserGroup).filter(UserGroup.id == me.usergroup_id).first()
    try:
        UUID(str(tag_id))
    except ValueError:
        group = None
    tag = group and db.query(BLETag).filter(
        BLETag.id == tag_id, _group_tag_scope_filter(group, _get_group_owner_ids(group, db))).first()
    if not tag or not tag.imei or not access.can_see(db, tag.imei):
        raise HTTPException(status_code=404, detail="Vehicle not found in your group")
    return me, tag


def _out(c: DeviceCommand) -> dict:
    return {"id": str(c.id), "command": c.command, "status": c.status, "sent_by": c.created_by_name,
            "queued_at": c.created_at, "sent_at": c.sent_at, "responded_at": c.responded_at,
            "response": c.response, "error": c.error}


@router.get("/tags/{tag_id}/commands")
def list_commands(tag_id: str, request: Request, db: Session = Depends(get_db)):
    _, tag = _vehicle(request, db, tag_id)
    rows = (db.query(DeviceCommand).filter(DeviceCommand.vehicle_id == tag.id)
            .order_by(DeviceCommand.created_at.desc()).limit(HISTORY_LIMIT).all())
    return [_out(c) for c in rows]


@router.post("/tags/{tag_id}/commands", status_code=201)
def send_command(tag_id: str, data: CommandIn, request: Request, db: Session = Depends(get_db)):
    me, tag = _vehicle(request, db, tag_id)
    try:
        command = dc.validate(data.command)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    now = datetime.now(timezone.utc)
    cmd = DeviceCommand(vehicle_id=tag.id, usergroup_id=me.usergroup_id, imei=tag.imei, command=command,
                        status=dc.QUEUED, created_by=me.id,
                        created_by_name=" ".join(filter(None, [me.first_name, me.last_name])) or me.email,
                        created_at=now, expires_at=now + dc.DEFAULT_TTL)
    db.add(cmd)
    name = tag.description or tag.device_name or tag.imei
    audit_service.record(db, me, "Sent", "Vehicles", f"Sent command “{command}” to “{name}”",
                         resource_id=tag.id, details={"command": command}, ip=_client_ip(request))
    db.commit()
    db.refresh(cmd)
    return _out(cmd)
