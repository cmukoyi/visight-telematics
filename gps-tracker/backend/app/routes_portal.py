"""
Customer portal API endpoints — auth and portal-user management.

Routes are mounted at /api/portal (separate from /api/v1 user routes and
/api/admin admin routes).  Each PortalUser is scoped to a UserGroup (tenant).
"""
from fastapi import APIRouter, Depends, HTTPException, status, Request
from sqlalchemy.orm import Session
from sqlalchemy import or_
from datetime import datetime, timedelta
from typing import List, Optional
from uuid import UUID
from pydantic import BaseModel, EmailStr
import jwt
import os
import logging

from app.database import get_db
from app.models import UserGroup, UserGroupPackage, PortalUser, Building, Floor, IndoorGateway, BLETag, User, TagCategory, GeofenceAlert, POI
from app.models_admin import TagPackage
from app.admin_auth import hash_password, verify_password

router = APIRouter(prefix="/api/portal", tags=["portal"])
logger = logging.getLogger(__name__)

PORTAL_SECRET_KEY = os.getenv("PORTAL_SECRET_KEY", os.getenv("ADMIN_SECRET_KEY", "portal-secret-key-change-me"))
PORTAL_ALGORITHM = "HS256"
PORTAL_TOKEN_EXPIRE_HOURS = 12


# ---------------------------------------------------------------------------
# Feature / role constants
# ---------------------------------------------------------------------------

SECTION_FEATURES: dict = {
    "tracking":   ["livemap", "floorplan", "assets", "history"],
    "management": ["asset-mgmt", "users", "qr", "building", "settings"],
    "reports":    [
        "reports-subscriptions", "reports-activity", "reports-trips",
        "reports-geofence", "reports-battery", "reports-alerts",
    ],
}
ALL_SECTIONS = list(SECTION_FEATURES.keys())


def _compute_effective_features(user: "PortalUser", group: "UserGroup") -> list:
    """Return the list of tab keys the user can access, given their role and
    the usergroup's allowed sections."""
    allowed_sections = group.allowed_sections or ALL_SECTIONS
    group_features = [f for s in allowed_sections for f in SECTION_FEATURES.get(s, [])]

    role = user.role or "admin"
    if role == "admin":
        return group_features
    elif role == "manager":
        role_features = SECTION_FEATURES["tracking"] + SECTION_FEATURES["management"]
        return [f for f in role_features if f in group_features]
    elif role == "reporter":
        return [f for f in SECTION_FEATURES["reports"] if f in group_features]
    elif role == "custom":
        custom = user.custom_features or []
        return [f for f in custom if f in group_features]
    return group_features


# ---------------------------------------------------------------------------
# Pydantic schemas
# ---------------------------------------------------------------------------

class PortalLoginRequest(BaseModel):
    email: str
    password: str


class PortalUserOut(BaseModel):
    id: UUID
    email: str
    first_name: Optional[str]
    last_name: Optional[str]
    is_active: bool
    is_group_admin: bool
    expires_at: Optional[datetime] = None
    role: str = "admin"
    custom_features: Optional[list] = None

    class Config:
        from_attributes = True


class UserGroupOut(BaseModel):
    id: UUID
    name: str
    slug: str

    class Config:
        from_attributes = True


class PortalTokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    portal_user: PortalUserOut
    usergroup: UserGroupOut


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _create_portal_token(portal_user_id: str, usergroup_id: str) -> str:
    payload = {
        "portal_user_id": portal_user_id,
        "usergroup_id":   usergroup_id,
        "type":           "portal",
        "exp":            datetime.utcnow() + timedelta(hours=PORTAL_TOKEN_EXPIRE_HOURS),
        "iat":            datetime.utcnow(),
    }
    return jwt.encode(payload, PORTAL_SECRET_KEY, algorithm=PORTAL_ALGORITHM)


def _decode_portal_token(token: str) -> Optional[dict]:
    try:
        payload = jwt.decode(token, PORTAL_SECRET_KEY, algorithms=[PORTAL_ALGORITHM])
        if payload.get("type") != "portal":
            return None
        return payload
    except jwt.ExpiredSignatureError:
        return None
    except jwt.InvalidTokenError:
        return None


def get_portal_user_from_request(request: Request, db: Session) -> PortalUser:
    """Dependency: extract and validate portal JWT, return PortalUser."""
    auth = request.headers.get("Authorization", "")
    if not auth.startswith("Bearer "):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED,
                            detail="Missing or invalid authorization header")
    token = auth[7:]
    payload = _decode_portal_token(token)
    if not payload:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED,
                            detail="Invalid or expired token")
    user = db.query(PortalUser).filter(
        PortalUser.id == payload["portal_user_id"],
        PortalUser.is_active == True,
    ).first()
    if not user:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED,
                            detail="Portal user not found or inactive")
    return user


# ---------------------------------------------------------------------------
# Auth endpoints
# ---------------------------------------------------------------------------

@router.post("/login", response_model=PortalTokenResponse)
def portal_login(data: PortalLoginRequest, db: Session = Depends(get_db)):
    """Log in as a portal user. Returns a JWT scoped to the user's UserGroup."""
    user = db.query(PortalUser).filter(
        PortalUser.email == data.email.lower().strip(),
        PortalUser.is_active == True,
    ).first()

    if not user or not verify_password(user.hashed_password, data.password):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED,
                            detail="Invalid email or password")

    # Auto-deactivate if expiry has passed
    if user.expires_at and user.expires_at < datetime.now(user.expires_at.tzinfo):
        user.is_active = False
        db.commit()
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN,
                            detail="This account has expired")

    group = db.query(UserGroup).filter(
        UserGroup.id == user.usergroup_id,
        UserGroup.is_active == True,
    ).first()
    if not group:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN,
                            detail="User group is inactive or not found")

    token = _create_portal_token(str(user.id), str(user.usergroup_id))
    effective = _compute_effective_features(user, group)
    return {
        "access_token": token,
        "token_type": "bearer",
        "portal_user": PortalUserOut.model_validate(user),
        "usergroup": UserGroupOut.model_validate(group),
        "effective_features": effective,
    }


@router.get("/me")
def portal_me(
    request: Request,
    db: Session = Depends(get_db),
):
    """Return the logged-in portal user\'s profile + usergroup + effective features."""
    user = get_portal_user_from_request(request, db)
    group = db.query(UserGroup).filter(UserGroup.id == user.usergroup_id).first()
    effective = _compute_effective_features(user, group) if group else []
    return {
        "portal_user": PortalUserOut.model_validate(user),
        "usergroup":   UserGroupOut.model_validate(group) if group else None,
        "effective_features": effective,
    }


# ---------------------------------------------------------------------------
# Portal user management (group admin only)
# ---------------------------------------------------------------------------

class PortalUserCreate(BaseModel):
    email: str
    first_name: Optional[str] = None
    last_name: Optional[str] = None
    role: str = "admin"              # admin | manager | reporter | custom
    custom_features: Optional[list] = None  # only used when role='custom'


class PortalUserCreateResponse(BaseModel):
    portal_user: PortalUserOut
    temp_password: str


@router.get("/users", response_model=List[PortalUserOut])
def list_portal_users(
    request: Request,
    db: Session = Depends(get_db),
):
    """List all portal users in the caller's UserGroup."""
    me = get_portal_user_from_request(request, db)
    users = db.query(PortalUser).filter(
        PortalUser.usergroup_id == me.usergroup_id,
    ).order_by(PortalUser.created_at).all()
    return [PortalUserOut.model_validate(u) for u in users]


@router.post("/users", response_model=PortalUserCreateResponse)
def create_portal_user(
    data: PortalUserCreate,
    request: Request,
    db: Session = Depends(get_db),
):
    """Create a new portal user in the same UserGroup (group admin only)."""
    me = get_portal_user_from_request(request, db)
    if not me.is_group_admin:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN,
                            detail="Only group admins can create users")

    email = data.email.lower().strip()
    if db.query(PortalUser).filter(PortalUser.email == email).first():
        raise HTTPException(status_code=400, detail="A portal user with that email already exists")

    valid_roles = {"admin", "manager", "reporter", "custom"}
    role = data.role if data.role in valid_roles else "admin"

    import secrets as _secrets
    import uuid as _uuid
    temp_password = _secrets.token_urlsafe(12)

    new_user = PortalUser(
        id=str(_uuid.uuid4()),
        usergroup_id=me.usergroup_id,
        email=email,
        hashed_password=hash_password(temp_password),
        first_name=data.first_name or None,
        last_name=data.last_name or None,
        is_active=True,
        is_group_admin=False,
        role=role,
        custom_features=data.custom_features if role == "custom" else None,
    )
    db.add(new_user)
    db.commit()
    db.refresh(new_user)

    return PortalUserCreateResponse(
        portal_user=PortalUserOut.model_validate(new_user),
        temp_password=temp_password,
    )


class PortalUserPatch(BaseModel):
    is_active: Optional[bool] = None
    expires_at: Optional[datetime] = None
    role: Optional[str] = None
    custom_features: Optional[list] = None


@router.patch("/users/{user_id}", response_model=PortalUserOut)
def patch_portal_user(
    user_id: UUID,
    data: PortalUserPatch,
    request: Request,
    db: Session = Depends(get_db),
):
    """Update is_active and/or expires_at for a portal user (group admin only)."""
    me = get_portal_user_from_request(request, db)
    if not me.is_group_admin:
        raise HTTPException(status_code=403, detail="Only group admins can modify users")

    target = db.query(PortalUser).filter(
        PortalUser.id == str(user_id),
        PortalUser.usergroup_id == me.usergroup_id,
    ).first()
    if not target:
        raise HTTPException(status_code=404, detail="User not found in your group")
    if str(target.id) == str(me.id):
        raise HTTPException(status_code=400, detail="You cannot modify your own account")

    if data.is_active is not None:
        target.is_active = data.is_active
        # Re-activating a user clears any expiry so it doesn't immediately lapse again
        if data.is_active:
            target.expires_at = None

    # Use model_fields_set to detect explicit null (clearing expiry) vs field omitted
    if "expires_at" in data.model_fields_set:
        new_expiry = data.expires_at
        if new_expiry is not None:
            # Reject dates in the past (compare naive UTC)
            expiry_naive = new_expiry.replace(tzinfo=None)
            if expiry_naive < datetime.utcnow():
                raise HTTPException(status_code=400, detail="Expiry date cannot be in the past")
        target.expires_at = new_expiry

    # Role + custom features
    if data.role is not None:
        valid_roles = {"admin", "manager", "reporter", "custom"}
        if data.role not in valid_roles:
            raise HTTPException(status_code=400, detail=f"Invalid role. Must be one of: {', '.join(valid_roles)}")
        target.role = data.role
    if "custom_features" in data.model_fields_set:
        target.custom_features = data.custom_features if (target.role == "custom") else None

    db.commit()
    db.refresh(target)
    return PortalUserOut.model_validate(target)


# ---------------------------------------------------------------------------
# Buildings — read-only for portal users
# ---------------------------------------------------------------------------

class RoomOut(BaseModel):
    id: UUID
    floor_id: UUID
    name: str
    x: float
    y: float
    w: float
    h: float
    class Config: from_attributes = True

class GatewayOut(BaseModel):
    id: UUID
    floor_id: UUID
    receiver_id: str
    label: Optional[str]
    x: float
    y: float
    class Config: from_attributes = True

class FloorOut(BaseModel):
    id: UUID
    building_id: UUID
    label: str
    floor_order: int
    floor_plan: Optional[str]
    map_w: int
    map_h: int
    gateways: List[GatewayOut] = []
    rooms: List[RoomOut] = []
    class Config: from_attributes = True

class BuildingOut(BaseModel):
    id: UUID
    usergroup_id: UUID
    name: str
    mqtt_url: Optional[str]
    mqtt_topic: str
    floors: List[FloorOut] = []
    class Config: from_attributes = True


@router.get("/buildings", response_model=List[BuildingOut])
def list_buildings(request: Request, db: Session = Depends(get_db)):
    """Return all buildings for the calling user's UserGroup."""
    me = get_portal_user_from_request(request, db)
    buildings = (
        db.query(Building)
        .filter(Building.usergroup_id == me.usergroup_id)
        .order_by(Building.created_at)
        .all()
    )
    return [BuildingOut.model_validate(b) for b in buildings]


@router.get("/buildings/{building_id}", response_model=BuildingOut)
def get_building(building_id: str, request: Request, db: Session = Depends(get_db)):
    """Return a single building with all floors, gateways, and rooms."""
    me = get_portal_user_from_request(request, db)
    bldg = db.query(Building).filter(
        Building.id == building_id,
        Building.usergroup_id == me.usergroup_id,
    ).first()
    if not bldg:
        raise HTTPException(status_code=404, detail="Building not found")
    return BuildingOut.model_validate(bldg)


# ---------------------------------------------------------------------------
# Gateway lookup — used by the mqtt-bridge to fetch positions without a user token
# ---------------------------------------------------------------------------

BRIDGE_API_KEY = os.getenv("BRIDGE_API_KEY", "bridge-key-change-me")


@router.get("/gateways")
def list_all_gateways(request: Request, db: Session = Depends(get_db)):
    """Return a flat map of receiverId → {x, y, floor_id, floor_label, building_id}.

    Authenticated with the BRIDGE_API_KEY header (X-Bridge-Key) so the
    mqtt-bridge container can call it without a portal JWT.
    """
    key = request.headers.get("X-Bridge-Key", "")
    if key != BRIDGE_API_KEY:
        raise HTTPException(status_code=403, detail="Invalid bridge API key")

    gateways = (
        db.query(IndoorGateway)
        .join(Floor, Floor.id == IndoorGateway.floor_id)
        .all()
    )
    result = {}
    for gw in gateways:
        result[gw.receiver_id] = {
            "x":           gw.x,
            "y":           gw.y,
            "label":       gw.label,
            "floor_id":    str(gw.floor_id),
            "floor_label": gw.floor.label,
            "building_id": str(gw.floor.building_id),
        }
    return result


# ---------------------------------------------------------------------------
# Settings — group admin can configure email domain auto-assignment
# ---------------------------------------------------------------------------

class GroupSettingsOut(BaseModel):
    id: UUID
    name: str
    slug: str
    email_domain: Optional[str]

    class Config:
        from_attributes = True


class GroupSettingsUpdate(BaseModel):
    email_domain: Optional[str] = None   # set to "" or null to clear


@router.get("/settings", response_model=GroupSettingsOut)
def get_settings(request: Request, db: Session = Depends(get_db)):
    """Return the current UserGroup settings for the logged-in portal user."""
    me = get_portal_user_from_request(request, db)
    group = db.query(UserGroup).filter(UserGroup.id == me.usergroup_id).first()
    if not group:
        raise HTTPException(status_code=404, detail="User group not found")
    return GroupSettingsOut.model_validate(group)


@router.put("/settings", response_model=GroupSettingsOut)
def update_settings(
    data: GroupSettingsUpdate,
    request: Request,
    db: Session = Depends(get_db),
):
    """Update UserGroup settings (group admin only)."""
    me = get_portal_user_from_request(request, db)
    if not me.is_group_admin:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN,
                            detail="Only group admins can update settings")

    group = db.query(UserGroup).filter(UserGroup.id == me.usergroup_id).first()
    if not group:
        raise HTTPException(status_code=404, detail="User group not found")

    # Normalise comma-separated domains: strip whitespace, lowercase, strip leading "@"
    raw_domains = [d.strip().lower().lstrip("@") for d in (data.email_domain or "").split(",")]
    clean_domains = [d for d in raw_domains if d]
    domain_value = ",".join(clean_domains) or None

    # Ensure no other group already uses any of these domains
    if clean_domains:
        for d in clean_domains:
            conflict = db.query(UserGroup).filter(
                UserGroup.email_domain.ilike(f"%{d}%"),
                UserGroup.id != group.id,
            ).first()
            if conflict:
                existing = [x.strip().lower() for x in (conflict.email_domain or "").split(",")]
                if d in existing:
                    raise HTTPException(
                        status_code=400,
                        detail=f"Domain '{d}' is already claimed by another group",
                    )

    group.email_domain = domain_value
    db.commit()
    db.refresh(group)
    return GroupSettingsOut.model_validate(group)


# ---------------------------------------------------------------------------
# Theme / Branding
# ---------------------------------------------------------------------------

class ThemeOut(BaseModel):
    logo_data: Optional[str] = None
    theme_primary: Optional[str] = None
    theme_accent: Optional[str] = None
    history_retention_days: Optional[int] = 365

    class Config:
        from_attributes = True


class ThemeUpdate(BaseModel):
    logo_data: Optional[str] = None          # base64 data-URL or None to clear
    theme_primary: Optional[str] = None      # hex e.g. '#3b82f6' or None to reset
    theme_accent: Optional[str] = None
    history_retention_days: Optional[int] = None


@router.get("/theme", response_model=ThemeOut)
def get_theme(request: Request, db: Session = Depends(get_db)):
    """Return the group's branding/theme settings."""
    me = get_portal_user_from_request(request, db)
    group = db.query(UserGroup).filter(UserGroup.id == me.usergroup_id).first()
    if not group:
        raise HTTPException(status_code=404, detail="User group not found")
    return ThemeOut.model_validate(group)


@router.put("/theme", response_model=ThemeOut)
def update_theme(
    data: ThemeUpdate,
    request: Request,
    db: Session = Depends(get_db),
):
    """Update branding/theme (group admin only)."""
    me = get_portal_user_from_request(request, db)
    if not me.is_group_admin:
        raise HTTPException(status_code=403, detail="Only group admins can update branding")
    group = db.query(UserGroup).filter(UserGroup.id == me.usergroup_id).first()
    if not group:
        raise HTTPException(status_code=404, detail="User group not found")

    if data.logo_data is not None:
        # Validate it's a data URL (or empty string to clear)
        if data.logo_data and not data.logo_data.startswith("data:image/"):
            raise HTTPException(status_code=400, detail="logo_data must be a data: URL")
        group.logo_data = data.logo_data or None

    if data.theme_primary is not None:
        val = data.theme_primary.strip()
        if val and not val.startswith("#"):
            raise HTTPException(status_code=400, detail="theme_primary must be a hex color like #3b82f6")
        group.theme_primary = val or None

    if data.theme_accent is not None:
        val = data.theme_accent.strip()
        if val and not val.startswith("#"):
            raise HTTPException(status_code=400, detail="theme_accent must be a hex color like #10b981")
        group.theme_accent = val or None

    if data.history_retention_days is not None:
        days = data.history_retention_days
        if days < 7 or days > 3650:
            raise HTTPException(status_code=400, detail="Retention must be between 7 and 3650 days")
        group.history_retention_days = days

    db.commit()
    db.refresh(group)
    return ThemeOut.model_validate(group)


# ---------------------------------------------------------------------------
# Notification Preferences (per-user)
# ---------------------------------------------------------------------------

class NotificationPrefsOut(BaseModel):
    alerts_enabled: bool
    notify_geofence_exit: bool
    notify_battery_low: bool
    notify_offline: bool
    notify_via_email: bool

    class Config:
        from_attributes = True


class NotificationPrefsUpdate(BaseModel):
    alerts_enabled: Optional[bool] = None
    notify_geofence_exit: Optional[bool] = None
    notify_battery_low: Optional[bool] = None
    notify_offline: Optional[bool] = None
    notify_via_email: Optional[bool] = None


@router.get("/notifications", response_model=NotificationPrefsOut)
def get_notification_prefs(request: Request, db: Session = Depends(get_db)):
    """Return the current user's notification preferences."""
    me = get_portal_user_from_request(request, db)
    return NotificationPrefsOut.model_validate(me)


@router.put("/notifications", response_model=NotificationPrefsOut)
def update_notification_prefs(
    data: NotificationPrefsUpdate,
    request: Request,
    db: Session = Depends(get_db),
):
    """Update the current user's notification preferences."""
    me = get_portal_user_from_request(request, db)
    if data.alerts_enabled is not None:
        me.alerts_enabled = data.alerts_enabled
    if data.notify_geofence_exit is not None:
        me.notify_geofence_exit = data.notify_geofence_exit
    if data.notify_battery_low is not None:
        me.notify_battery_low = data.notify_battery_low
    if data.notify_offline is not None:
        me.notify_offline = data.notify_offline
    if data.notify_via_email is not None:
        me.notify_via_email = data.notify_via_email
    db.commit()
    db.refresh(me)
    return NotificationPrefsOut.model_validate(me)


# ---------------------------------------------------------------------------
# Account — Change Password
# ---------------------------------------------------------------------------

class ChangePasswordRequest(BaseModel):
    current_password: str
    new_password: str


@router.post("/account/change-password", status_code=200)
def change_password(
    data: ChangePasswordRequest,
    request: Request,
    db: Session = Depends(get_db),
):
    """Let the logged-in portal user change their own password."""
    me = get_portal_user_from_request(request, db)
    if not verify_password(me.hashed_password, data.current_password):
        raise HTTPException(status_code=400, detail="Current password is incorrect")
    if len(data.new_password) < 8:
        raise HTTPException(status_code=400, detail="New password must be at least 8 characters")
    me.hashed_password = hash_password(data.new_password)
    db.commit()
    return {"detail": "Password updated successfully"}


# ---------------------------------------------------------------------------
# Tags — all BLE tags belonging to mobile-app users whose email domain
#         matches the group's configured email_domain
# ---------------------------------------------------------------------------

class PortalTagOut(BaseModel):
    id: UUID
    imei: str
    device_name: Optional[str]
    device_model: Optional[str]
    description: Optional[str]
    tag_type: Optional[str]
    is_active: bool
    last_seen: Optional[datetime]
    latitude: Optional[str]
    longitude: Optional[str]
    location_description: Optional[str]
    battery_level: Optional[int]
    owner_email: str
    # Package / subscription fields
    package_id: Optional[str] = None
    package_name: Optional[str] = None
    added_at: Optional[datetime] = None
    expiry_date: Optional[datetime] = None
    days_remaining: Optional[int] = None  # None = no package; negative = expired
    activation_date: Optional[datetime] = None  # first GPS fix; expiry is calculated from this
    # Category (from attributes.category.value)
    category_id: Optional[str] = None
    category_name: Optional[str] = None

    class Config:
        from_attributes = True


@router.get("/tags", response_model=List[PortalTagOut])
def list_group_tags(request: Request, db: Session = Depends(get_db)):
    """Return all BLE tags belonging to mobile-app users whose email domain
    matches the group's configured email_domain.

    Returns an empty list (not an error) when no domain is configured yet.
    """
    me = get_portal_user_from_request(request, db)
    group = db.query(UserGroup).filter(UserGroup.id == me.usergroup_id).first()
    if not group or not group.email_domain:
        return []

    domains = _domains(group)

    tags = (
        db.query(BLETag, User.email)
        .join(User, User.id == BLETag.user_id)
        .filter(
            _domain_filter(domains),
            BLETag.is_active == True,
        )
        .order_by(BLETag.added_at.desc())
        .all()
    )

    # Build package lookup cache for this batch
    pkg_ids = {t.package_id for t, _ in tags if t.package_id}
    pkg_map: dict = {}
    if pkg_ids:
        for p in db.query(TagPackage).filter(TagPackage.id.in_(pkg_ids)).all():
            pkg_map[str(p.id)] = p

    # Build category name → id lookup for this group
    cat_name_map: dict = {}  # name.lower() → (id, name)
    for cat in db.query(TagCategory).filter(
        TagCategory.usergroup_id == str(me.usergroup_id),
        TagCategory.is_active == True,
    ).all():
        cat_name_map[cat.name.lower()] = (str(cat.id), cat.name)

    result = []
    for tag, owner_email in tags:
        pkg = pkg_map.get(str(tag.package_id)) if tag.package_id else None
        days_remaining = None
        if tag.expiry_date:
            days_remaining = (tag.expiry_date.replace(tzinfo=None) - datetime.utcnow()).days
        # Resolve category from attributes
        attrs = tag.attributes or {}
        raw_cat_name = (attrs.get('category') or {}).get('value') or None
        cat_id, cat_name = (None, None)
        if raw_cat_name:
            match = cat_name_map.get(raw_cat_name.lower())
            if match:
                cat_id, cat_name = match
            else:
                cat_name = raw_cat_name  # preserve even if category was deleted
        result.append(PortalTagOut(
            id=tag.id,
            imei=tag.imei,
            device_name=tag.device_name,
            device_model=tag.device_model,
            description=tag.description,
            tag_type=tag.tag_type,
            is_active=tag.is_active,
            last_seen=tag.last_seen,
            latitude=tag.latitude,
            longitude=tag.longitude,
            location_description=tag.location_description,
            battery_level=tag.battery_level,
            owner_email=owner_email,
            package_id=str(tag.package_id) if tag.package_id else None,
            package_name=pkg.name if pkg else None,
            added_at=tag.added_at,
            expiry_date=tag.expiry_date,
            days_remaining=days_remaining,
            activation_date=tag.activation_date,
            category_id=cat_id,
            category_name=cat_name,
        ))
    return result


# ---------------------------------------------------------------------------
# Packages — list active packages available for portal to assign to tags
# ---------------------------------------------------------------------------

class PackageOut(BaseModel):
    id: UUID
    name: str
    description: Optional[str]
    validity_days: int
    is_default: bool

    class Config:
        from_attributes = True


@router.get("/packages", response_model=List[PackageOut])
def list_active_packages(request: Request, db: Session = Depends(get_db)):
    """Return tag packages available to the caller's group for the Add Tag dropdown.
    Only packages explicitly assigned to the group are returned; falls back to all
    active packages if none have been assigned yet (backward compat)."""
    me = get_portal_user_from_request(request, db)
    assigned = db.query(UserGroupPackage).filter(UserGroupPackage.usergroup_id == me.usergroup_id).all()
    if assigned:
        pkg_ids = [str(r.package_id) for r in assigned]
        return (
            db.query(TagPackage)
            .filter(TagPackage.id.in_(pkg_ids), TagPackage.is_active == True)
            .order_by(TagPackage.validity_days)
            .all()
        )
    # Fallback: no explicit assignments — return all active packages
    return db.query(TagPackage).filter(TagPackage.is_active == True).order_by(TagPackage.validity_days).all()


# ---------------------------------------------------------------------------
# Mobile users — list mobile-app Users in the group's email domain
# ---------------------------------------------------------------------------

class MobileUserOut(BaseModel):
    id: UUID
    email: str
    first_name: Optional[str]
    last_name: Optional[str]

    class Config:
        from_attributes = True


@router.get("/mobile-users", response_model=List[MobileUserOut])
def list_mobile_users(request: Request, db: Session = Depends(get_db)):
    """Return all active mobile-app Users whose email domain matches the group's
    configured email_domain. Used to populate the assign-tag dropdown."""
    me = get_portal_user_from_request(request, db)
    group = db.query(UserGroup).filter(UserGroup.id == me.usergroup_id).first()
    if not group or not group.email_domain:
        return []
    domains = _domains(group)
    users = (
        db.query(User)
        .filter(_domain_filter(domains), User.is_active == True)
        .order_by(User.email)
        .all()
    )
    return [MobileUserOut(id=u.id, email=u.email, first_name=u.first_name, last_name=u.last_name)
            for u in users]


# ---------------------------------------------------------------------------
# Tag management — create and reassign tags from the portal
# ---------------------------------------------------------------------------

class PortalTagCreate(BaseModel):
    imei: str
    description: Optional[str] = None
    tag_type: Optional[str] = "scope"
    user_id: UUID
    package_id: UUID  # mandatory — must select a package when adding a tag
    category: Optional[str] = None  # category name to store in attributes


class PortalTagAssign(BaseModel):
    user_id: UUID


class PortalTagDelete(BaseModel):
    tag_ids: List[str]


def _build_tag_out(tag: BLETag, owner_email: str, db: Optional[Session] = None) -> PortalTagOut:
    pkg = None
    if tag.package_id and db:
        pkg = db.query(TagPackage).filter(TagPackage.id == str(tag.package_id)).first()
    days_remaining = None
    if tag.expiry_date:
        days_remaining = (tag.expiry_date.replace(tzinfo=None) - datetime.utcnow()).days
    return PortalTagOut(
        id=tag.id,
        imei=tag.imei,
        device_name=tag.device_name,
        device_model=tag.device_model,
        description=tag.description,
        tag_type=tag.tag_type,
        is_active=tag.is_active,
        last_seen=tag.last_seen,
        latitude=tag.latitude,
        longitude=tag.longitude,
        location_description=tag.location_description,
        battery_level=tag.battery_level,
        owner_email=owner_email,
        package_id=str(tag.package_id) if tag.package_id else None,
        package_name=pkg.name if pkg else None,
        added_at=tag.added_at,
        expiry_date=tag.expiry_date,
        days_remaining=days_remaining,
        activation_date=tag.activation_date,
    )


def _get_group_and_assert_domain(me: PortalUser, db: Session) -> UserGroup:
    group = db.query(UserGroup).filter(UserGroup.id == me.usergroup_id).first()
    if not group or not group.email_domain:
        raise HTTPException(status_code=400, detail="Configure a domain in Settings before managing tags")
    return group


def _domains(group: UserGroup) -> list:
    """Return a lowercase list of domain strings for the group (supports comma-separated multiple domains)."""
    if not group or not group.email_domain:
        return []
    return [d.strip().lower() for d in group.email_domain.split(",") if d.strip()]


def _domain_filter(domains: list):
    """Return a SQLAlchemy filter clause matching user emails against any of the given domains."""
    return or_(*(User.email.ilike(f"%@{d}") for d in domains))


def _assert_user_in_domain(user: User, domain_or_domains) -> None:
    """Raise 403 if the user's email doesn't match any of the configured domains."""
    if not user:
        raise HTTPException(status_code=403, detail="User does not belong to this group's domain")
    if isinstance(domain_or_domains, str):
        domains = [domain_or_domains.lower()]
    else:
        domains = [d.lower() for d in domain_or_domains]
    email = user.email.lower()
    if not any(email.endswith(f"@{d}") for d in domains):
        raise HTTPException(status_code=403, detail="User does not belong to this group's domain")


class PortalTagUpdate(BaseModel):
    description: Optional[str] = None
    tag_type: Optional[str] = None
    user_id: Optional[str] = None
    category: Optional[str] = None  # category name; empty string clears it
    package_id: Optional[str] = None  # UUID string; empty string clears package


@router.put("/tags/{tag_id}", response_model=PortalTagOut)
def update_tag(tag_id: str, data: PortalTagUpdate, request: Request, db: Session = Depends(get_db)):
    """Update a BLE tag's description, type, or assigned user (group admin only)."""
    me = get_portal_user_from_request(request, db)
    if not me.is_group_admin:
        raise HTTPException(status_code=403, detail="Only group admins can edit tags")
    group = _get_group_and_assert_domain(me, db)

    tag = (
        db.query(BLETag)
        .join(User, User.id == BLETag.user_id)
        .filter(BLETag.id == tag_id, _domain_filter(_domains(group)))
        .first()
    )
    if not tag:
        raise HTTPException(status_code=404, detail="Tag not found in your group")

    if data.description is not None:
        tag.description = data.description or None
    if data.tag_type is not None:
        tag.tag_type = data.tag_type
    if data.user_id is not None:
        target_user = db.query(User).filter(User.id == str(data.user_id)).first()
        _assert_user_in_domain(target_user, _domains(group))
        tag.user_id = str(data.user_id)
    if data.category is not None:
        attrs = dict(tag.attributes or {})
        if data.category:
            attrs['category'] = {'value': data.category}
        else:
            attrs.pop('category', None)
        tag.attributes = attrs
    if data.package_id is not None:
        if data.package_id == "":
            # Clear the package
            tag.package_id = None
            tag.expiry_date = None
        else:
            pkg = db.query(TagPackage).filter(
                TagPackage.id == str(data.package_id),
                TagPackage.is_active == True,
            ).first()
            if not pkg:
                raise HTTPException(status_code=404, detail="Package not found or inactive")
            tag.package_id = str(data.package_id)
            # Expiry = base_date + validity_days.
            # base_date = activation_date if it exists, else now().
            # But if activation_date is old enough that the calculated expiry would
            # already be in the past, use now() instead so expiry is always future.
            if tag.activation_date:
                base = tag.activation_date.replace(tzinfo=None)
                candidate = base + timedelta(days=pkg.validity_days)
                if candidate <= datetime.utcnow():
                    base = datetime.utcnow()
                tag.expiry_date = base + timedelta(days=pkg.validity_days)
            else:
                tag.expiry_date = None  # pending first GPS fix

    db.commit()
    db.refresh(tag)
    owner = db.query(User).filter(User.id == tag.user_id).first()
    return _build_tag_out(tag, owner.email if owner else "", db)


@router.post("/tags", response_model=PortalTagOut, status_code=201)
def create_tag(data: PortalTagCreate, request: Request, db: Session = Depends(get_db)):
    """Create a new BLE tag and assign it directly to a mobile-app user (group admin only)."""
    me = get_portal_user_from_request(request, db)
    if not me.is_group_admin:
        raise HTTPException(status_code=403, detail="Only group admins can add tags")
    group = _get_group_and_assert_domain(me, db)

    target_user = db.query(User).filter(User.id == str(data.user_id)).first()
    _assert_user_in_domain(target_user, _domains(group))

    pkg = db.query(TagPackage).filter(TagPackage.id == str(data.package_id), TagPackage.is_active == True).first()
    if not pkg:
        raise HTTPException(status_code=404, detail="Package not found or inactive")

    imei = data.imei.strip()
    if db.query(BLETag).filter(BLETag.imei == imei).first():
        raise HTTPException(status_code=409, detail=f"Tag with IMEI '{imei}' already exists")

    now = datetime.utcnow()
    tag = BLETag(
        user_id=str(data.user_id),
        imei=imei,
        description=data.description,
        tag_type=data.tag_type or "scope",
        is_active=True,
        package_id=str(data.package_id),
        expiry_date=now + timedelta(days=pkg.validity_days),
        attributes={'category': {'value': data.category}} if data.category else None,
    )
    db.add(tag)
    db.commit()
    db.refresh(tag)
    return _build_tag_out(tag, target_user.email, db)


@router.put("/tags/{tag_id}/assign", response_model=PortalTagOut)
def assign_tag(tag_id: str, data: PortalTagAssign, request: Request, db: Session = Depends(get_db)):
    """Reassign an existing BLE tag to a different mobile-app user (group admin only)."""
    me = get_portal_user_from_request(request, db)
    if not me.is_group_admin:
        raise HTTPException(status_code=403, detail="Only group admins can assign tags")
    group = _get_group_and_assert_domain(me, db)

    # Tag must belong to a user already in this group's domain
    tag = (
        db.query(BLETag)
        .join(User, User.id == BLETag.user_id)
        .filter(BLETag.id == tag_id, _domain_filter(_domains(group)))
        .first()
    )
    if not tag:
        raise HTTPException(status_code=404, detail="Tag not found in your group")

    target_user = db.query(User).filter(User.id == str(data.user_id)).first()
    _assert_user_in_domain(target_user, _domains(group))

    tag.user_id = str(data.user_id)
    db.commit()
    db.refresh(tag)
    return _build_tag_out(tag, target_user.email, db)


@router.delete("/tags", status_code=204)
def delete_tags(data: PortalTagDelete, request: Request, db: Session = Depends(get_db)):
    """Permanently delete one or more BLE tags (group admin only).
    Tags must belong to a user in the group's configured email domain."""
    me = get_portal_user_from_request(request, db)
    if not me.is_group_admin:
        raise HTTPException(status_code=403, detail="Only group admins can delete tags")
    group = _get_group_and_assert_domain(me, db)

    for tag_id in data.tag_ids:
        tag = (
            db.query(BLETag)
            .join(User, User.id == BLETag.user_id)
            .filter(BLETag.id == tag_id, _domain_filter(_domains(group)))
            .first()
        )
        if tag:
            db.delete(tag)

    db.commit()


@router.delete("/tags/{tag_id}", status_code=204)
def delete_tag_single(tag_id: str, request: Request, db: Session = Depends(get_db)):
    """Permanently delete a single BLE tag by its ID (group admin only)."""
    me = get_portal_user_from_request(request, db)
    if not me.is_group_admin:
        raise HTTPException(status_code=403, detail="Only group admins can delete tags")
    group = _get_group_and_assert_domain(me, db)

    tag = (
        db.query(BLETag)
        .join(User, User.id == BLETag.user_id)
        .filter(BLETag.id == tag_id, _domain_filter(_domains(group)))
        .first()
    )
    if not tag:
        raise HTTPException(status_code=404, detail="Tag not found in your group")
    db.delete(tag)
    db.commit()


class BulkTagRow(BaseModel):
    imei: str
    description: Optional[str] = None
    tag_type: Optional[str] = None
    owner_email: str


class BulkTagResult(BaseModel):
    imei: str
    success: bool
    error: Optional[str] = None


@router.post("/tags/bulk", response_model=List[BulkTagResult])
def bulk_create_tags(rows: List[BulkTagRow], request: Request, db: Session = Depends(get_db)):
    """Create multiple BLE tags from a list (group admin only).
    Each row must include imei and owner_email belonging to the group's domain.
    The group's default_package_id is applied automatically; tags are rejected
    if the group has no default package configured."""
    import uuid as _uuid
    me = get_portal_user_from_request(request, db)
    if not me.is_group_admin:
        raise HTTPException(status_code=403, detail="Only group admins can add tags")
    group = _get_group_and_assert_domain(me, db)

    # Require a default package on the group
    if not group.default_package_id:
        raise HTTPException(
            status_code=400,
            detail="No default package configured for this group. "
                   "Ask an admin to assign one before importing tags.",
        )
    pkg = db.query(TagPackage).filter(TagPackage.id == str(group.default_package_id), TagPackage.is_active == True).first()
    if not pkg:
        raise HTTPException(status_code=400, detail="The group's default package is no longer active")

    now = datetime.utcnow()
    expiry_date = now + timedelta(days=pkg.validity_days)

    results: List[BulkTagResult] = []
    for row in rows:
        try:
            imei = row.imei.strip()
            if not imei:
                results.append(BulkTagResult(imei=imei, success=False, error="IMEI is required"))
                continue
            if db.query(BLETag).filter(BLETag.imei == imei).first():
                results.append(BulkTagResult(imei=imei, success=False, error="IMEI already exists"))
                continue
            owner_email = row.owner_email.strip().lower()
            bulk_domains = _domains(group)
            if not any(owner_email.endswith(f"@{d}") for d in bulk_domains):
                results.append(BulkTagResult(imei=imei, success=False,
                                             error=f"Email must use one of: {', '.join('@'+d for d in bulk_domains)}"))
                continue
            owner = db.query(User).filter(User.email == owner_email).first()
            if not owner:
                results.append(BulkTagResult(imei=imei, success=False, error="Owner email not found"))
                continue
            tag = BLETag(
                id=str(_uuid.uuid4()),
                imei=imei,
                description=row.description or None,
                tag_type=row.tag_type or None,
                user_id=str(owner.id),
                is_active=True,
                package_id=str(pkg.id),
                expiry_date=expiry_date,
            )
            db.add(tag)
            db.flush()
            results.append(BulkTagResult(imei=imei, success=True))
        except Exception as exc:
            results.append(BulkTagResult(imei=row.imei, success=False, error=str(exc)))

    db.commit()
    return results


# ---------------------------------------------------------------------------
# Trips — portal-scoped proxy to MZone / TrackSolid
# ---------------------------------------------------------------------------

class PortalTripsRequest(BaseModel):
    vehicleId: str
    startDate: str   # ISO 8601 UTC e.g. "2025-10-01T07:00:00Z"
    endDate: str     # ISO 8601 UTC e.g. "2025-10-01T18:00:59Z"


@router.post("/trips")
async def portal_get_trips(
    data: PortalTripsRequest,
    request: Request,
    db: Session = Depends(get_db),
):
    """Fetch trips for a BLE tag within a date range.
    Routes to TrackSolid getPointList or MZone Trips API depending on tag_type.
    Auth: portal JWT (PortalUser scoped to a UserGroup)."""
    me = get_portal_user_from_request(request, db)
    group = db.query(UserGroup).filter(UserGroup.id == me.usergroup_id).first()
    if not group or not group.email_domain:
        return {"success": False, "error": "Group has no configured domain", "trips": []}

    # Verify the tag belongs to this group's domain
    tag = (
        db.query(BLETag)
        .join(User, User.id == BLETag.user_id)
        .filter(
            BLETag.id == data.vehicleId,
            BLETag.is_active == True,
            _domain_filter(_domains(group)),
        )
        .first()
    )
    if not tag:
        return {"success": False, "error": "Tag not found or not in your group", "trips": []}

    print(f"📱 PORTAL TRIPS REQUEST — group={group.slug} tag={tag.imei} {data.startDate}→{data.endDate}")

    # ── TrackSolid ────────────────────────────────────────────────────────────
    if (tag.tag_type or "").lower() == "tracksolid":
        from app.services.device_providers.tracksolid_provider import fetch_tracksolid_journey_points
        from datetime import datetime as _dt

        def _to_ts(s: str) -> str:
            return s.replace("T", " ").replace("Z", "").split(".")[0][:19]

        ts_start = _to_ts(data.startDate)
        ts_end   = _to_ts(data.endDate)
        print(f"🔵 TrackSolid journey: IMEI={tag.imei} {ts_start} → {ts_end}")

        track_data = await fetch_tracksolid_journey_points(tag.imei, ts_start, ts_end)
        if not track_data or not (track_data.get("gpsPointStrList") or []):
            return {"success": True, "count": 0, "trips": []}

        try:
            t0 = _dt.strptime(track_data["startDate"], "%Y-%m-%d %H:%M:%S")
            t1 = _dt.strptime(track_data["endDate"],   "%Y-%m-%d %H:%M:%S")
            duration_secs = int((t1 - t0).total_seconds())
        except Exception:
            duration_secs = 0

        try:
            distance_mi = float(track_data.get("totalMileage") or 0)
        except (ValueError, TypeError):
            distance_mi = 0.0

        trip_id = (
            f"tracksolid__{tag.imei}"
            f"__{ts_start.replace(' ', 'T')}"
            f"__{ts_end.replace(' ', 'T')}"
        )
        synthetic_trip = {
            "id": trip_id,
            "vehicle_Id": str(tag.id),
            "vehicle_Description": track_data.get("deviceName") or tag.description or tag.imei,
            "driver_Description": None,
            "driverKeyCode": None,
            "distance": distance_mi,
            "duration": duration_secs,
            "startUtcTimestamp": track_data["startDate"].replace(" ", "T") + "Z",
            "endUtcTimestamp":   track_data["endDate"].replace(" ", "T") + "Z",
            "startLocationDescription": track_data.get("startAddress"),
            "endLocationDescription":   track_data.get("endAddress"),
        }
        print(f"✅ TrackSolid: {len(track_data['gpsPointStrList'])} pts, {distance_mi:.1f} mi, {duration_secs}s")
        return {"success": True, "count": 1, "trips": [synthetic_trip]}

    # ── MZone ─────────────────────────────────────────────────────────────────
    from app.services.mzone_service import mzone_service

    mzone_vehicle_id = tag.mzone_vehicle_id
    if not mzone_vehicle_id:
        print(f"⚠️  No cached MZone vehicle_Id, performing IMEI lookup…")
        vehicles_data = mzone_service.get_all_vehicles()
        if not vehicles_data:
            return {"success": False, "error": "Failed to fetch vehicles from MZone", "trips": []}
        for vehicle in vehicles_data.get("value", []):
            if vehicle.get("registration") == tag.imei or vehicle.get("unit_Description") == tag.imei:
                mzone_vehicle_id = vehicle.get("id")
                tag.mzone_vehicle_id = mzone_vehicle_id
                db.commit()
                print(f"✅ Cached MZone vehicle_Id={mzone_vehicle_id}")
                break
        if not mzone_vehicle_id:
            return {"success": True, "count": 0, "trips": []}
    else:
        print(f"✅ Using cached MZone vehicle_Id (fast path)")

    trips_data = mzone_service.get_trips(
        vehicle_id=mzone_vehicle_id,
        start_date=data.startDate,
        end_date=data.endDate,
    )
    if not trips_data:
        return {"success": False, "error": "Failed to fetch trips from MZone", "trips": []}

    trips = trips_data.get("value", [])
    print(f"✅ MZone: {len(trips)} trips returned")
    return {"success": True, "count": len(trips), "trips": trips}


@router.get("/trips/{trip_id}/events")
async def portal_get_trip_events(
    trip_id: str,
    request: Request,
    db: Session = Depends(get_db),
):
    """Fetch waypoints for a specific trip. Routes to TrackSolid or MZone.
    Auth: portal JWT."""
    get_portal_user_from_request(request, db)  # auth only — trip_id encodes all needed info

    # ── TrackSolid compound ID: tracksolid__{imei}__{start}__{end} ────────────
    if trip_id.startswith("tracksolid__"):
        from app.services.device_providers.tracksolid_provider import fetch_tracksolid_journey_points

        parts = trip_id.split("__")
        if len(parts) != 4:
            return {"success": False, "error": "Invalid TrackSolid trip ID format", "events": []}

        _, imei, ts_start_raw, ts_end_raw = parts
        ts_start = ts_start_raw.replace("T", " ")
        ts_end   = ts_end_raw.replace("T", " ")
        print(f"🔵 TrackSolid events: IMEI={imei} {ts_start} → {ts_end}")

        track_data = await fetch_tracksolid_journey_points(imei, ts_start, ts_end)
        if not track_data:
            return {"success": True, "count": 0, "events": []}

        points_raw = track_data.get("gpsPointStrList") or []
        events = []
        for idx, point_str in enumerate(points_raw):
            try:
                p = point_str.split("|")
                if len(p) < 10:
                    continue
                lat = float(p[8])
                lng = float(p[9])
                if lat == 0.0 and lng == 0.0:
                    continue
                events.append({
                    "id": str(idx),
                    "utcTimestamp": p[7].replace(" ", "T") + "Z",
                    "latitude":  lat,
                    "longitude": lng,
                    "direction": int(float(p[1])) if p[1] else 0,
                    "speed":     int(float(p[0])) if p[0] else 0,
                    "decimalOdometer":        None,
                    "eventType_Id":           None,
                    "eventType_Description":  None,
                    "eventType_MapMarker2":   None,
                })
            except (ValueError, IndexError):
                continue

        print(f"✅ TrackSolid events: {len(events)} valid waypoints from {len(points_raw)} total")
        return {"success": True, "count": len(events), "events": events}

    # ── MZone ─────────────────────────────────────────────────────────────────
    from app.services.mzone_service import mzone_service

    events_data = mzone_service.get_trip_events(trip_id)
    if not events_data:
        return {"success": False, "error": "Failed to fetch trip events from MZone", "events": []}

    events = events_data.get("value", [])
    print(f"✅ MZone trip events: {len(events)} waypoints")
    return {"success": True, "count": len(events), "events": events}


# ---------------------------------------------------------------------------
# Tag Categories — group-scoped user-defined categories
# ---------------------------------------------------------------------------

class CategoryOut(BaseModel):
    id: UUID
    name: str
    icon: Optional[str] = None
    color: Optional[str] = None
    is_active: bool

    class Config:
        from_attributes = True


class CategoryCreate(BaseModel):
    name: str
    icon: Optional[str] = None
    color: Optional[str] = None


class CategoryUpdate(BaseModel):
    name: Optional[str] = None
    icon: Optional[str] = None
    color: Optional[str] = None
    is_active: Optional[bool] = None


@router.get("/categories", response_model=List[CategoryOut])
def list_categories(request: Request, db: Session = Depends(get_db)):
    """Return all active categories for the caller's user-group."""
    me = get_portal_user_from_request(request, db)
    return (
        db.query(TagCategory)
        .filter(TagCategory.usergroup_id == str(me.usergroup_id), TagCategory.is_active == True)
        .order_by(TagCategory.name)
        .all()
    )


@router.post("/categories", response_model=CategoryOut, status_code=201)
def create_category(data: CategoryCreate, request: Request, db: Session = Depends(get_db)):
    """Create a new category (group admin only)."""
    me = get_portal_user_from_request(request, db)
    if not me.is_group_admin:
        raise HTTPException(status_code=403, detail="Only group admins can manage categories")
    name = data.name.strip()
    if not name:
        raise HTTPException(status_code=400, detail="Category name is required")
    exists = db.query(TagCategory).filter(
        TagCategory.usergroup_id == str(me.usergroup_id),
        TagCategory.name.ilike(name),
    ).first()
    if exists:
        raise HTTPException(status_code=409, detail=f"Category '{name}' already exists")
    cat = TagCategory(
        usergroup_id=str(me.usergroup_id),
        name=name,
        icon=data.icon,
        color=data.color,
    )
    db.add(cat)
    db.commit()
    db.refresh(cat)
    return cat


@router.put("/categories/{cat_id}", response_model=CategoryOut)
def update_category(cat_id: str, data: CategoryUpdate, request: Request, db: Session = Depends(get_db)):
    """Rename or deactivate a category (group admin only)."""
    me = get_portal_user_from_request(request, db)
    if not me.is_group_admin:
        raise HTTPException(status_code=403, detail="Only group admins can manage categories")
    cat = db.query(TagCategory).filter(
        TagCategory.id == cat_id,
        TagCategory.usergroup_id == str(me.usergroup_id),
    ).first()
    if not cat:
        raise HTTPException(status_code=404, detail="Category not found")
    if data.name is not None:
        name = data.name.strip()
        if not name:
            raise HTTPException(status_code=400, detail="Category name cannot be empty")
        cat.name = name
    if data.icon is not None:
        cat.icon = data.icon or None
    if data.color is not None:
        cat.color = data.color or None
    if data.is_active is not None:
        cat.is_active = data.is_active
    db.commit()
    db.refresh(cat)
    return cat


@router.delete("/categories/{cat_id}", status_code=204)
def delete_category(cat_id: str, request: Request, db: Session = Depends(get_db)):
    """Soft-delete a category by marking it inactive (group admin only)."""
    me = get_portal_user_from_request(request, db)
    if not me.is_group_admin:
        raise HTTPException(status_code=403, detail="Only group admins can manage categories")
    cat = db.query(TagCategory).filter(
        TagCategory.id == cat_id,
        TagCategory.usergroup_id == str(me.usergroup_id),
    ).first()
    if not cat:
        raise HTTPException(status_code=404, detail="Category not found")
    cat.is_active = False
    db.commit()


# ---------------------------------------------------------------------------
# Reports — Geofence Events
# ---------------------------------------------------------------------------

@router.get("/reports/geofence-events")
def report_geofence_events(
    request: Request,
    days: int = 30,
    tag_id: Optional[str] = None,
    poi_id: Optional[str] = None,
    db: Session = Depends(get_db),
):
    """Return geofence entry/exit events for all tags in the caller's group.

    Scoped by joining GeofenceAlert → BLETag → User whose email domain
    matches the UserGroup's configured email_domain.
    Returns newest-first, capped at 1000 rows.
    """
    me = get_portal_user_from_request(request, db)
    group = db.query(UserGroup).filter(UserGroup.id == me.usergroup_id).first()
    if not group or not group.email_domain:
        return []

    since = datetime.utcnow() - timedelta(days=max(1, min(days, 365)))

    q = (
        db.query(GeofenceAlert)
        .join(BLETag, BLETag.id == GeofenceAlert.tracker_id)
        .join(User, User.id == BLETag.user_id)
        .join(POI, POI.id == GeofenceAlert.poi_id)
        .filter(
            _domain_filter(_domains(group)),
            GeofenceAlert.created_at >= since,
        )
    )
    if tag_id:
        q = q.filter(GeofenceAlert.tracker_id == tag_id)
    if poi_id:
        q = q.filter(GeofenceAlert.poi_id == poi_id)

    alerts = q.order_by(GeofenceAlert.created_at.desc()).limit(1000).all()

    result = []
    for a in alerts:
        tag = a.tracker
        poi = a.poi
        result.append({
            "id":          str(a.id),
            "event_type":  a.event_type.value if hasattr(a.event_type, "value") else str(a.event_type),
            "created_at":  a.created_at.isoformat() if a.created_at else None,
            "tag_id":      str(tag.id)  if tag else str(a.tracker_id),
            "tag_label":   (tag.description or tag.device_name or tag.imei) if tag else str(a.tracker_id),
            "tag_imei":    tag.imei if tag else "",
            "poi_id":      str(a.poi_id),
            "poi_name":    poi.name if poi else str(a.poi_id),
            "latitude":    a.latitude,
            "longitude":   a.longitude,
        })
    return result
