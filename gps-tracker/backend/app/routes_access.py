"""Customer portal — security groups and roles (Configuration → Security).

Mounted under /api/portal; everything is scoped to the caller's user group.
"""
from datetime import datetime
from typing import List, Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, field_validator
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import PortalRole, PortalUser, PortalUserRole, SecurityGroup, TagCategory
from app.routes_portal import get_portal_user_from_request
from app.services import access_service, audit_service

router = APIRouter(prefix="/api/portal", tags=["portal-access"])


def _reader(request: Request, db: Session) -> PortalUser:
    """Anyone who assigns roles or security groups (users, vehicle groups) may list them."""
    me = get_portal_user_from_request(request, db)
    access = access_service.for_user(me, db)
    access.require_any("security.manage", "roles.manage", "users.view", "users.manage", "vehicle_groups.manage")
    return me


def _manager(request: Request, db: Session, permission: str = "security.manage"):
    me = get_portal_user_from_request(request, db)
    access = access_service.for_user(me, db)
    access.require(permission)
    return me, access


def _uuid(value: str, what: str) -> UUID:
    try:
        return UUID(value)
    except ValueError:
        raise HTTPException(status_code=404, detail=f"{what} not found")


@router.get("/access/permissions")
def list_permissions(request: Request, db: Session = Depends(get_db)):
    _reader(request, db)
    return [{"key": k, "label": label, "section": section, "description": desc}
            for k, (label, section, desc) in access_service.PERMISSIONS.items()]


# ---------------------------------------------------------------------------
# Security groups
# ---------------------------------------------------------------------------

class SecurityGroupIn(BaseModel):
    name: str
    description: Optional[str] = None

    @field_validator("name")
    @classmethod
    def _name(cls, v):
        v = v.strip()
        if not v or len(v) > 100:
            raise ValueError("Enter a name (up to 100 characters)")
        return v


def _sg_out(db: Session, sg: SecurityGroup) -> dict:
    vehicle_groups = (db.query(TagCategory.name).filter(TagCategory.security_group_id == sg.id,
                                                         TagCategory.is_active == True)  # noqa: E712
                      .order_by(TagCategory.name).all())
    users = db.query(func.count(PortalUser.id)).filter(PortalUser.security_group_id == sg.id).scalar()
    return {"id": str(sg.id), "name": sg.name, "description": sg.description,
            "vehicle_groups": [n for (n,) in vehicle_groups], "user_count": users}


def _own_sg(db: Session, me: PortalUser, sg_id: str) -> SecurityGroup:
    sg = db.query(SecurityGroup).filter(SecurityGroup.id == _uuid(sg_id, "Security group"),
                                        SecurityGroup.usergroup_id == me.usergroup_id).first()
    if not sg:
        raise HTTPException(status_code=404, detail="Security group not found")
    return sg


def _unique_sg_name(db: Session, me: PortalUser, name: str, exclude=None):
    q = db.query(SecurityGroup).filter(SecurityGroup.usergroup_id == me.usergroup_id,
                                       func.lower(SecurityGroup.name) == name.lower())
    if exclude is not None:
        q = q.filter(SecurityGroup.id != exclude)
    if q.first():
        raise HTTPException(status_code=409, detail=f"A security group called '{name}' already exists")


@router.get("/security-groups")
def list_security_groups(request: Request, db: Session = Depends(get_db)):
    me = _reader(request, db)
    rows = db.query(SecurityGroup).filter(SecurityGroup.usergroup_id == me.usergroup_id).order_by(SecurityGroup.name).all()
    return [_sg_out(db, sg) for sg in rows]


@router.post("/security-groups", status_code=201)
def create_security_group(data: SecurityGroupIn, request: Request, db: Session = Depends(get_db)):
    me, _ = _manager(request, db)
    _unique_sg_name(db, me, data.name)
    sg = SecurityGroup(usergroup_id=me.usergroup_id, name=data.name, description=(data.description or "").strip() or None)
    db.add(sg)
    db.commit()
    return _sg_out(db, sg)


@router.put("/security-groups/{sg_id}")
def update_security_group(sg_id: str, data: SecurityGroupIn, request: Request, db: Session = Depends(get_db)):
    me, _ = _manager(request, db)
    sg = _own_sg(db, me, sg_id)
    _unique_sg_name(db, me, data.name, exclude=sg.id)
    sg.name, sg.description = data.name, (data.description or "").strip() or None
    db.commit()
    return _sg_out(db, sg)


@router.delete("/security-groups/{sg_id}", status_code=204)
def delete_security_group(sg_id: str, request: Request, db: Session = Depends(get_db)):
    me, _ = _manager(request, db)
    sg = _own_sg(db, me, sg_id)
    out = _sg_out(db, sg)
    if out["vehicle_groups"] or out["user_count"]:
        raise HTTPException(status_code=409, detail="Move its vehicle groups and users to another security group first")
    db.delete(sg)
    db.commit()


# ---------------------------------------------------------------------------
# Roles
# ---------------------------------------------------------------------------

class RoleIn(BaseModel):
    name: str
    description: Optional[str] = None
    permissions: List[str] = []
    user_ids: Optional[List[UUID]] = None     # who holds the role (None = leave as is)

    @field_validator("name")
    @classmethod
    def _name(cls, v):
        v = v.strip()
        if not v or len(v) > 100:
            raise ValueError("Enter a name (up to 100 characters)")
        return v

    @field_validator("permissions")
    @classmethod
    def _perms(cls, v):
        unknown = [p for p in v if p not in access_service.PERMISSIONS]
        if unknown:
            raise ValueError(f"Unknown permission: {', '.join(unknown)}")
        return [p for p in access_service.ALL_PERMISSIONS if p in set(v)]


def _role_users(db: Session, role: PortalRole) -> list:
    rows = (db.query(PortalUser).join(PortalUserRole, PortalUserRole.user_id == PortalUser.id)
            .filter(PortalUserRole.role_id == role.id).order_by(PortalUser.email).all())
    return [{"id": str(u.id), "email": u.email, "name": " ".join(filter(None, [u.first_name, u.last_name])) or u.email}
            for u in rows]


def _role_out(db: Session, role: PortalRole) -> dict:
    perms = access_service.ALL_PERMISSIONS if role.is_admin else [p for p in role.permissions or [] if p in access_service.PERMISSIONS]
    users = _role_users(db, role)
    return {"id": str(role.id), "name": role.name, "description": role.description, "permissions": perms,
            "is_admin": role.is_admin, "is_system": role.is_system, "user_count": len(users), "users": users}


def _own_role(db: Session, me: PortalUser, role_id: str) -> PortalRole:
    role = db.query(PortalRole).filter(PortalRole.id == _uuid(role_id, "Role"),
                                       PortalRole.usergroup_id == me.usergroup_id).first()
    if not role:
        raise HTTPException(status_code=404, detail="Role not found")
    return role


def _unique_role_name(db: Session, me: PortalUser, name: str, exclude=None):
    q = db.query(PortalRole).filter(PortalRole.usergroup_id == me.usergroup_id, func.lower(PortalRole.name) == name.lower())
    if exclude is not None:
        q = q.filter(PortalRole.id != exclude)
    if q.first():
        raise HTTPException(status_code=409, detail=f"A role called '{name}' already exists")


def _set_role_users(db: Session, me: PortalUser, access, role: PortalRole, user_ids: List[UUID]) -> None:
    """Give the role to exactly these users (assigning roles is user management)."""
    access.require("users.manage")
    wanted = {str(u) for u in user_ids}
    users = db.query(PortalUser).filter(PortalUser.usergroup_id == me.usergroup_id).all()
    by_id = {str(u.id): u for u in users}
    if wanted - set(by_id):
        raise HTTPException(status_code=400, detail="Unknown user")
    access.check_grant(role.permissions or [], admin=role.is_admin)
    for uid, user in by_id.items():
        held = {str(r) for r in access_service.role_ids(db, user)}
        has = str(role.id) in held
        if (uid in wanted) == has:
            continue
        if uid == str(me.id):
            raise HTTPException(status_code=400, detail="You can't change your own roles")
        new_ids = (held | {str(role.id)}) if uid in wanted else (held - {str(role.id)})
        if not new_ids:
            raise HTTPException(status_code=400, detail=f"{user.email} would have no role left — give them another role first")
        roles = db.query(PortalRole).filter(PortalRole.id.in_(list(new_ids))).all()
        if not any(r.is_admin for r in roles) and user.security_group_id is None:
            raise HTTPException(status_code=400, detail=f"Add {user.email} to a security group first")
        access_service.set_roles(db, user, sorted(roles, key=lambda r: (not r.is_admin, r.name.lower())))


@router.get("/roles")
def list_roles(request: Request, db: Session = Depends(get_db)):
    me = _reader(request, db)
    access_service.ensure_defaults(db, me.usergroup_id)
    db.commit()
    rows = db.query(PortalRole).filter(PortalRole.usergroup_id == me.usergroup_id).all()
    order = list(access_service.DEFAULT_ROLES)
    rows.sort(key=lambda r: (order.index(r.name) if r.name in order else len(order), r.name.lower()))
    return [_role_out(db, r) for r in rows]


@router.post("/roles", status_code=201)
def create_role(data: RoleIn, request: Request, db: Session = Depends(get_db)):
    me, access = _manager(request, db, "roles.manage")
    access.check_grant(data.permissions)
    _unique_role_name(db, me, data.name)
    role = PortalRole(usergroup_id=me.usergroup_id, name=data.name, description=(data.description or "").strip() or None,
                      permissions=data.permissions, is_admin=False, is_system=False)
    db.add(role)
    db.flush()
    if data.user_ids:
        _set_role_users(db, me, access, role, data.user_ids)
    db.commit()
    return _role_out(db, role)


@router.put("/roles/{role_id}")
def update_role(role_id: str, data: RoleIn, request: Request, db: Session = Depends(get_db)):
    me, access = _manager(request, db, "roles.manage")
    role = _own_role(db, me, role_id)
    if role.is_system:
        # Built-in roles keep their name and permissions; only who holds them can change
        if data.name != role.name or (not role.is_admin and set(data.permissions) != set(role.permissions or [])):
            raise HTTPException(status_code=400, detail="Built-in roles can't be changed — duplicate it to make your own")
    else:
        access.check_grant(set(data.permissions) - set(role.permissions or []))
        _unique_role_name(db, me, data.name, exclude=role.id)
        role.name, role.description, role.permissions = data.name, (data.description or "").strip() or None, data.permissions
    if data.user_ids is not None:
        _set_role_users(db, me, access, role, data.user_ids)
    db.commit()
    return _role_out(db, role)


@router.delete("/roles/{role_id}", status_code=204)
def delete_role(role_id: str, request: Request, db: Session = Depends(get_db)):
    me, _ = _manager(request, db, "roles.manage")
    role = _own_role(db, me, role_id)
    if role.is_system:
        raise HTTPException(status_code=400, detail="Built-in roles can't be deleted")
    if db.query(PortalUserRole).filter(PortalUserRole.role_id == role.id).first():
        raise HTTPException(status_code=409, detail="Take this role away from its users first")
    db.delete(role)
    db.commit()


# ---------------------------------------------------------------------------
# Audit trail
# ---------------------------------------------------------------------------

@router.get("/audit")
def list_audit(request: Request, db: Session = Depends(get_db), date_from: Optional[datetime] = None,
               date_to: Optional[datetime] = None, user_id: Optional[UUID] = None, area: Optional[str] = None,
               outcome: Optional[str] = None, search: Optional[str] = None, limit: int = Query(500, ge=1, le=5000)):
    """Who changed what in the caller's user group (audit.view)."""
    me, _ = _manager(request, db, "audit.view")
    return {"rows": audit_service.search(db, me.usergroup_id, date_from=date_from, date_to=date_to, user_id=user_id,
                                         area=area, outcome=outcome, text=search, limit=limit),
            "areas": ["Sign-in", *audit_service.AREAS]}
