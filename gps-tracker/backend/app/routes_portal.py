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
import secrets
import logging

from app.database import get_db
from app.models import UserGroup, UserGroupPackage, PortalUser, Building, Floor, IndoorGateway, BLETag, User, TagCategory, GeofenceAlert, POI, POITrackerLink, GeofenceState, PortalAlert
from app.models_admin import TagPackage
from app.admin_auth import hash_password, verify_password
from app.services.device_providers.provider_factory import DeviceProviderFactory
from app.services.email_service import EmailService as _EmailService

_email_svc_portal = _EmailService()

# Alias map shared by create_tag and validate_tag_portal
_TAG_TYPE_ALIAS = {"series1": "scope", "series2": "tracksolid"}

router = APIRouter(prefix="/api/portal", tags=["portal"])
logger = logging.getLogger(__name__)

PORTAL_SECRET_KEY = os.getenv("PORTAL_SECRET_KEY", os.getenv("ADMIN_SECRET_KEY", "portal-secret-key-change-me"))
PORTAL_ALGORITHM = "HS256"
PORTAL_TOKEN_EXPIRE_HOURS = 12


# ---------------------------------------------------------------------------
# Feature / role constants
# ---------------------------------------------------------------------------

SECTION_FEATURES: dict = {
    "tracking":   ["livemap", "floorplan", "assets", "history", "hive"],
    "management": ["asset-mgmt", "users", "qr", "building", "locations", "settings"],
    "reports":    [
        "reports-subscriptions", "reports-activity", "reports-trips",
        "reports-battery", "reports-alerts",
        # reports-geofence is not yet released — excluded so it never appears in the nav
    ],
}
ALL_SECTIONS = list(SECTION_FEATURES.keys())


def _compute_effective_features(user: "PortalUser", group: "UserGroup") -> list:
    """Return the list of tab keys the user can access, given their role and
    the usergroup's allowed sections."""
    allowed_sections = group.allowed_sections or ALL_SECTIONS
    group_features = [f for s in allowed_sections for f in SECTION_FEATURES.get(s, [])]

    role = user.role or "admin"
    if role in ("admin", "system_admin"):
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

    # ── Domain enforcement ─────────────────────────────────────────────────
    group = db.query(UserGroup).filter(UserGroup.id == me.usergroup_id).first()
    if group and group.email_domain:
        allowed_domains = [d.strip().lower() for d in group.email_domain.split(",") if d.strip()]
        if allowed_domains:
            email_domain = email.split("@")[-1].lower() if "@" in email else ""
            if email_domain not in allowed_domains:
                raise HTTPException(
                    status_code=400,
                    detail=(
                        f"This group only accepts users with email domains: "
                        f"{', '.join('@' + d for d in allowed_domains)}. "
                        f"The address '{email}' does not qualify."
                    ),
                )
    # ──────────────────────────────────────────────────────────────────────

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

    # Built-in system admin accounts (created at group creation) cannot be modified
    if target.role == "system_admin":
        raise HTTPException(status_code=403, detail="Built-in system admin accounts cannot be modified")

    # Non-admin portal users cannot deactivate or set expiry on admin users
    target_is_admin = target.is_group_admin or target.role == "admin"
    if target_is_admin and not me.is_group_admin:
        if data.is_active is not None or "expires_at" in data.model_fields_set:
            raise HTTPException(
                status_code=403,
                detail="Only group admins can deactivate or set expiry on admin users"
            )

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
    logo_dark_data: Optional[str] = None
    theme_primary: Optional[str] = None
    theme_accent: Optional[str] = None
    history_retention_days: Optional[int] = 365

    class Config:
        from_attributes = True


class ThemeUpdate(BaseModel):
    logo_data: Optional[str] = None          # base64 data-URL or None to clear
    logo_dark_data: Optional[str] = None     # base64 data-URL (dark mode) or None to clear
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

    if data.logo_dark_data is not None:
        if data.logo_dark_data and not data.logo_dark_data.startswith("data:image/"):
            raise HTTPException(status_code=400, detail="logo_dark_data must be a data: URL")
        group.logo_dark_data = data.logo_dark_data or None

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
    notification_emails: Optional[List[str]] = None   # extra notification addresses
    # SMS
    phone_number: Optional[str] = None
    sms_enabled: bool = False
    notify_geofence_sms: bool = True
    notify_battery_sms: bool = True
    notify_offline_sms: bool = True
    # Whether the group has SMS enabled (read-only, for UI gating)
    group_sms_enabled: bool = False

    class Config:
        from_attributes = True


class NotificationPrefsUpdate(BaseModel):
    alerts_enabled: Optional[bool] = None
    notify_geofence_exit: Optional[bool] = None
    notify_battery_low: Optional[bool] = None
    notify_offline: Optional[bool] = None
    notify_via_email: Optional[bool] = None
    notification_emails: Optional[List[str]] = None   # None = do not change; [] = clear all extra
    # SMS
    phone_number: Optional[str] = None
    sms_enabled: Optional[bool] = None
    notify_geofence_sms: Optional[bool] = None
    notify_battery_sms: Optional[bool] = None
    notify_offline_sms: Optional[bool] = None


@router.get("/notifications", response_model=NotificationPrefsOut)
def get_notification_prefs(request: Request, db: Session = Depends(get_db)):
    """Return the current user's notification preferences."""
    me = get_portal_user_from_request(request, db)
    group = db.query(UserGroup).filter(UserGroup.id == me.usergroup_id).first()
    out = NotificationPrefsOut.model_validate(me)
    out.group_sms_enabled = bool(group and getattr(group, 'sms_enabled', False))
    return out


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
    if data.notification_emails is not None:
        # Validate each entry is a plausible email
        cleaned = [e.strip().lower() for e in data.notification_emails if e.strip()]
        for addr in cleaned:
            if '@' not in addr or '.' not in addr.split('@')[-1]:
                raise HTTPException(status_code=400, detail=f"Invalid email address: {addr}")
        me.notification_emails = cleaned if cleaned else None
    # SMS prefs
    import re as _re
    if data.phone_number is not None:
        cleaned_num = _re.sub(r"[\s\-\(\)]", "", data.phone_number.strip())
        if cleaned_num and not cleaned_num.startswith("+"):
            if cleaned_num.startswith("07") and len(cleaned_num) == 11:
                cleaned_num = "+44" + cleaned_num[1:]
        if cleaned_num and not _re.match(r"^\+[1-9]\d{7,14}$", cleaned_num):
            raise HTTPException(status_code=400, detail="Invalid phone number — use E.164 format e.g. +447700123456")
        me.phone_number = cleaned_num or None
    if data.sms_enabled is not None:
        me.sms_enabled = data.sms_enabled
    if data.notify_geofence_sms is not None:
        me.notify_geofence_sms = data.notify_geofence_sms
    if data.notify_battery_sms is not None:
        me.notify_battery_sms = data.notify_battery_sms
    if data.notify_offline_sms is not None:
        me.notify_offline_sms = data.notify_offline_sms
    db.commit()
    db.refresh(me)
    group = db.query(UserGroup).filter(UserGroup.id == me.usergroup_id).first()
    out = NotificationPrefsOut.model_validate(me)
    out.group_sms_enabled = bool(group and getattr(group, 'sms_enabled', False))
    return out


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


class ChangeEmailRequest(BaseModel):
    new_email: str
    current_password: str


@router.post("/account/change-email", status_code=200)
def change_email(
    data: ChangeEmailRequest,
    request: Request,
    db: Session = Depends(get_db),
):
    """Let the logged-in portal user change their own email address."""
    me = get_portal_user_from_request(request, db)
    if not verify_password(me.hashed_password, data.current_password):
        raise HTTPException(status_code=400, detail="Current password is incorrect")
    new_email = data.new_email.strip().lower()
    if not new_email or '@' not in new_email:
        raise HTTPException(status_code=400, detail="Invalid email address")
    # Ensure no other portal user has this email
    conflict = db.query(PortalUser).filter(
        PortalUser.email == new_email,
        PortalUser.id != str(me.id),
    ).first()
    if conflict:
        raise HTTPException(status_code=409, detail="That email address is already in use")
    me.email = new_email
    db.commit()
    return {"detail": "Email updated successfully", "new_email": new_email}


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

class MobileUserTagOut(BaseModel):
    id: UUID
    imei: str
    description: Optional[str] = None
    activation_date: Optional[datetime] = None
    expiry_date: Optional[datetime] = None
    days_remaining: Optional[int] = None
    package_name: Optional[str] = None
    is_active: bool = True

    class Config:
        from_attributes = True


class MobileUserOut(BaseModel):
    id: UUID
    email: str
    first_name: Optional[str]
    last_name: Optional[str]
    is_active: bool = True
    created_at: Optional[datetime] = None
    tags: List[MobileUserTagOut] = []

    class Config:
        from_attributes = True


@router.get("/mobile-users", response_model=List[MobileUserOut])
def list_mobile_users(request: Request, db: Session = Depends(get_db)):
    """Return all mobile-app Users (active and inactive) whose email domain
    matches the group's configured email_domain, with their assigned tags."""
    me = get_portal_user_from_request(request, db)
    group = db.query(UserGroup).filter(UserGroup.id == me.usergroup_id).first()
    if not group or not group.email_domain:
        return []
    domains = _domains(group)
    users = (
        db.query(User)
        .filter(_domain_filter(domains))          # all users, active or not
        .order_by(User.email)
        .all()
    )
    # Fetch all tags for these users in one query
    user_ids = [u.id for u in users]
    tags_rows = (
        db.query(BLETag)
        .filter(BLETag.user_id.in_(user_ids))
        .order_by(BLETag.added_at.desc())
        .all()
    ) if user_ids else []
    # Build package lookup
    pkg_ids = {t.package_id for t in tags_rows if t.package_id}
    pkg_map: dict = {}
    if pkg_ids:
        for p in db.query(TagPackage).filter(TagPackage.id.in_(pkg_ids)).all():
            pkg_map[str(p.id)] = p.name
    # Group tags by user_id
    from collections import defaultdict
    tags_by_user: dict = defaultdict(list)
    for tag in tags_rows:
        days_remaining = None
        if tag.expiry_date:
            days_remaining = (tag.expiry_date.replace(tzinfo=None) - datetime.utcnow()).days
        tags_by_user[str(tag.user_id)].append(MobileUserTagOut(
            id=tag.id,
            imei=tag.imei,
            description=tag.description,
            activation_date=tag.activation_date,
            expiry_date=tag.expiry_date,
            days_remaining=days_remaining,
            package_name=pkg_map.get(str(tag.package_id)) if tag.package_id else None,
            is_active=tag.is_active,
        ))
    return [
        MobileUserOut(
            id=u.id, email=u.email,
            first_name=u.first_name, last_name=u.last_name,
            is_active=u.is_active,
            created_at=u.created_at,
            tags=tags_by_user.get(str(u.id), [])
        )
        for u in users
    ]


class MobileUserPatch(BaseModel):
    is_active: bool


@router.patch("/mobile-users/{user_id}", status_code=200)
def toggle_mobile_user(user_id: UUID, body: MobileUserPatch,
                       request: Request, db: Session = Depends(get_db)):
    """Activate or deactivate a mobile-app user within the portal group's domain."""
    me = get_portal_user_from_request(request, db)
    group = db.query(UserGroup).filter(UserGroup.id == me.usergroup_id).first()
    if not group or not group.email_domain:
        raise HTTPException(status_code=403, detail="No email domain configured")
    domains = _domains(group)
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    # Ensure the target user belongs to this group's domain
    if not any(user.email.lower().endswith(f"@{d}") for d in domains):
        raise HTTPException(status_code=403, detail="User does not belong to your domain")
    user.is_active = body.is_active
    db.commit()
    return {"id": str(user_id), "is_active": user.is_active}


@router.delete("/mobile-users/{user_id}", status_code=204)
def delete_mobile_user(user_id: UUID, request: Request, db: Session = Depends(get_db)):
    """Permanently delete a mobile-app user from the system (domain-scoped)."""
    me = get_portal_user_from_request(request, db)
    group = db.query(UserGroup).filter(UserGroup.id == me.usergroup_id).first()
    if not group or not group.email_domain:
        raise HTTPException(status_code=403, detail="No email domain configured")
    domains = _domains(group)
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    if not any(user.email.lower().endswith(f"@{d}") for d in domains):
        raise HTTPException(status_code=403, detail="User does not belong to your domain")
    db.delete(user)
    db.commit()
    return


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
        # Track whether the user has explicitly named this tag so the poller
        # never overwrites it with whatever the vendor API returns.
        attrs = dict(tag.attributes or {})
        if data.description:
            attrs['_user_named'] = True   # user has set a custom name
        else:
            attrs.pop('_user_named', None)  # cleared name — allow API to fill it again
        tag.attributes = attrs
    if data.tag_type is not None:
        # Normalise UI aliases ('series1'/'series2') to canonical DB values ('scope'/'tracksolid')
        tag.tag_type = _TAG_TYPE_ALIAS.get(data.tag_type.lower(), data.tag_type.lower())
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


class PortalTagValidateRequest(BaseModel):
    imei: str
    tag_type: str  # 'series1' | 'series2' (or canonical 'scope' | 'tracksolid')


@router.post("/tags/validate")
async def validate_tag_portal(
    data: PortalTagValidateRequest,
    request: Request,
    db: Session = Depends(get_db),
):
    """Validate a tag IMEI against its vendor platform (portal auth required).
    Returns {is_valid, message} without persisting anything."""
    me = get_portal_user_from_request(request, db)
    if not me.is_group_admin:
        raise HTTPException(status_code=403, detail="Only group admins can validate tags")

    tag_type = _TAG_TYPE_ALIAS.get(data.tag_type.lower(), data.tag_type.lower())
    try:
        provider = DeviceProviderFactory.get_provider(tag_type)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    result = await provider.validate_tag(data.imei)
    return {"is_valid": result.is_valid, "message": result.message}


@router.post("/tags", response_model=PortalTagOut, status_code=201)
async def create_tag(data: PortalTagCreate, request: Request, db: Session = Depends(get_db)):
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

    # Validate IMEI against the vendor platform before persisting
    canonical_type = _TAG_TYPE_ALIAS.get((data.tag_type or "scope").lower(), (data.tag_type or "scope").lower())
    try:
        provider = DeviceProviderFactory.get_provider(canonical_type)
        validation = await provider.validate_tag(imei)
        if not validation.is_valid:
            raise HTTPException(status_code=422, detail=validation.message)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    now = datetime.utcnow()
    # Build attributes — mark _user_named if a description was provided at creation
    init_attrs: dict = {}
    if data.category:
        init_attrs['category'] = {'value': data.category}
    if data.description:
        init_attrs['_user_named'] = True
    tag = BLETag(
        user_id=str(data.user_id),
        imei=imei,
        description=data.description,
        tag_type=canonical_type,
        is_active=True,
        package_id=str(data.package_id),
        expiry_date=now + timedelta(days=pkg.validity_days),
        attributes=init_attrs or None,
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
        TagCategory.is_active == True,
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


# ---------------------------------------------------------------------------
# Portal Alerts — unified inbox (geofence, battery_low, tag_offline)
# ---------------------------------------------------------------------------

@router.get("/alerts")
def list_portal_alerts(
    request: Request,
    days: int = 7,
    db: Session = Depends(get_db),
):
    """Return alerts for this user's group from the last N days (max 7)."""
    me = get_portal_user_from_request(request, db)
    since = datetime.utcnow() - timedelta(days=max(1, min(days, 7)))
    alerts = (
        db.query(PortalAlert)
        .filter(
            PortalAlert.usergroup_id == str(me.usergroup_id),
            PortalAlert.created_at >= since,
        )
        .order_by(PortalAlert.created_at.desc())
        .limit(500)
        .all()
    )
    return [_portal_alert_dict(a) for a in alerts]


@router.get("/alerts/unread-count")
def portal_alerts_unread_count(
    request: Request,
    db: Session = Depends(get_db),
):
    """Return count of unread alerts in the last 7 days."""
    me = get_portal_user_from_request(request, db)
    since = datetime.utcnow() - timedelta(days=7)
    count = (
        db.query(PortalAlert)
        .filter(
            PortalAlert.usergroup_id == str(me.usergroup_id),
            PortalAlert.created_at >= since,
            PortalAlert.is_read == False,
        )
        .count()
    )
    return {"unread": count}


@router.put("/alerts/{alert_id}/read")
def mark_portal_alert_read(
    alert_id: str,
    request: Request,
    db: Session = Depends(get_db),
):
    """Mark a single alert as read."""
    me = get_portal_user_from_request(request, db)
    alert = db.query(PortalAlert).filter(
        PortalAlert.id == alert_id,
        PortalAlert.usergroup_id == str(me.usergroup_id),
    ).first()
    if not alert:
        raise HTTPException(status_code=404, detail="Alert not found")
    alert.is_read = True
    db.commit()
    return _portal_alert_dict(alert)


@router.put("/alerts/read-all")
def mark_all_portal_alerts_read(
    request: Request,
    db: Session = Depends(get_db),
):
    """Mark all unread alerts as read for this group."""
    me = get_portal_user_from_request(request, db)
    since = datetime.utcnow() - timedelta(days=7)
    db.query(PortalAlert).filter(
        PortalAlert.usergroup_id == str(me.usergroup_id),
        PortalAlert.created_at >= since,
        PortalAlert.is_read == False,
    ).update({"is_read": True})
    db.commit()
    return {"detail": "All alerts marked as read"}


@router.delete("/alerts/{alert_id}")
def delete_portal_alert(
    alert_id: str,
    request: Request,
    db: Session = Depends(get_db),
):
    """Delete (dismiss) a single alert."""
    me = get_portal_user_from_request(request, db)
    alert = db.query(PortalAlert).filter(
        PortalAlert.id == alert_id,
        PortalAlert.usergroup_id == str(me.usergroup_id),
    ).first()
    if not alert:
        raise HTTPException(status_code=404, detail="Alert not found")
    db.delete(alert)
    db.commit()
    return {"detail": "Alert deleted"}


def _portal_alert_dict(a: PortalAlert) -> dict:
    tag = a.tag
    tag_label = None
    if tag:
        tag_label = tag.description or tag.device_name or tag.imei
    return {
        "id":          str(a.id),
        "alert_type":  a.alert_type,
        "title":       a.title,
        "message":     a.message,
        "is_read":     a.is_read,
        "created_at":  a.created_at.isoformat() if a.created_at else None,
        "tag_id":      str(a.tag_id) if a.tag_id else None,
        "tag_label":   tag_label,
        "tag_imei":    tag.imei if tag else None,
        "meta_data":   a.meta_data or {},
    }


# ──────────────────────────────────────────────────────────────────────────────
# Locations (Portal-managed POIs / Geofences)
# ──────────────────────────────────────────────────────────────────────────────
import httpx as _httpx
import io as _io

try:
    import openpyxl as _openpyxl
    _HAS_OPENPYXL = True
except ImportError:  # pragma: no cover
    _HAS_OPENPYXL = False

from fastapi import UploadFile, File


def _poi_dict(poi: POI, db: Session, usergroup_id: str) -> dict:
    """Serialise a POI with armed-tag info for the portal."""
    armed_links = (
        db.query(POITrackerLink)
        .filter(POITrackerLink.poi_id == poi.id, POITrackerLink.is_armed == True)
        .all()
    )
    armed_tag_ids = [str(lk.tracker_id) for lk in armed_links]
    # Resolve labels for armed tags that belong to this group
    tags_armed = []
    for lk in armed_links:
        tag = lk.tracker
        if tag:
            tags_armed.append({
                "id":    str(tag.id),
                "imei":  tag.imei,
                "label": tag.description or tag.device_name or tag.imei,
            })
    return {
        "id":          str(poi.id),
        "name":        poi.name,
        "description": poi.description,
        "address":     poi.address,
        "latitude":    poi.latitude,
        "longitude":   poi.longitude,
        "radius":      poi.radius or 150.0,
        "shape_type":  getattr(poi, 'shape_type', None) or 'circle',
        "coordinates": getattr(poi, 'coordinates', None),
        "notes":       getattr(poi, 'notes', None),
        "is_active":   poi.is_active,
        "created_at":  poi.created_at.isoformat() if poi.created_at else None,
        "armed_count": len(armed_tag_ids),
        "tags_armed":  tags_armed,
    }


async def _geocode_postcode(postcode: str) -> dict:
    """
    Geocode a UK postcode (or any address) via Nominatim.
    Returns {"lat": float, "lon": float, "display": str} or raises HTTPException.
    Nominatim fair-use: 1 req/s max — bulk upload loops add a tiny sleep.
    """
    q = postcode.strip()
    url = f"https://nominatim.openstreetmap.org/search?q={_httpx.QueryParams({'q': q})}&format=json&limit=1&countrycodes=gb"
    async with _httpx.AsyncClient(timeout=10) as client:
        resp = await client.get(
            "https://nominatim.openstreetmap.org/search",
            params={"q": q, "format": "json", "limit": 1, "countrycodes": "gb"},
            headers={"User-Agent": "PinPlot-HPS/1.0 (portal)"},
        )
    if resp.status_code != 200:
        raise HTTPException(status_code=502, detail=f"Geocoding service error for '{q}'")
    results = resp.json()
    if not results:
        raise HTTPException(status_code=422, detail=f"Postcode not found: '{q}'")
    r = results[0]
    return {"lat": float(r["lat"]), "lon": float(r["lon"]), "display": r.get("display_name", q)}


def _get_group_poi(poi_id: str, usergroup_id: str, db: Session) -> POI:
    poi = db.query(POI).filter(
        POI.id == poi_id,
        POI.usergroup_id == usergroup_id,
    ).first()
    if not poi:
        raise HTTPException(status_code=404, detail="Location not found")
    return poi


# ── List all locations for this group ────────────────────────────────────────

@router.get("/locations")
def list_locations(request: Request, db: Session = Depends(get_db)):
    me = get_portal_user_from_request(request, db)
    pois = (
        db.query(POI)
        .filter(POI.usergroup_id == str(me.usergroup_id), POI.is_active == True)
        .order_by(POI.created_at.desc())
        .all()
    )
    return [_poi_dict(p, db, str(me.usergroup_id)) for p in pois]


# ── Create a single location by postcode OR drawn coordinates ────────────────

class LocationCreate(BaseModel):
    name: str
    description: Optional[str] = None
    radius: float = 150.0
    # Option A: postcode geocoding (legacy / bulk)
    postcode: Optional[str] = None
    # Option B: direct coordinates from drawn shape
    latitude: Optional[float] = None
    longitude: Optional[float] = None
    address: Optional[str] = None
    shape_type: str = 'circle'       # circle | polygon | rectangle
    coordinates: Optional[str] = None  # JSON string [[lat,lng], ...] for polygon/rectangle
    notes: Optional[str] = None
    status: Optional[str] = None     # 'active' | 'draft' | 'inactive'


@router.post("/locations", status_code=201)
async def create_location(data: LocationCreate, request: Request, db: Session = Depends(get_db)):
    me = get_portal_user_from_request(request, db)
    if not me.is_group_admin:
        raise HTTPException(status_code=403, detail="Admin access required")

    # Resolve coordinates: either from direct input or by geocoding a postcode
    if data.latitude is not None and data.longitude is not None:
        lat = float(data.latitude)
        lon = float(data.longitude)
        display = data.address or ""
    elif data.postcode:
        geo = await _geocode_postcode(data.postcode)
        lat = geo["lat"]
        lon = geo["lon"]
        display = geo["display"]
    else:
        raise HTTPException(status_code=422, detail="Either postcode or latitude/longitude is required")

    poi = POI(
        usergroup_id=str(me.usergroup_id),
        user_id=None,
        name=data.name.strip(),
        description=data.description,
        poi_type="single",
        latitude=lat,
        longitude=lon,
        radius=max(50.0, min(data.radius, 50000.0)),
        address=display,
        is_active=True,
    )
    # Set shape fields if the columns exist (migration 028)
    if hasattr(poi, 'shape_type'):
        poi.shape_type = data.shape_type or 'circle'
    if hasattr(poi, 'coordinates'):
        poi.coordinates = data.coordinates
    if hasattr(poi, 'notes'):
        poi.notes = data.notes
    db.add(poi)
    db.commit()
    db.refresh(poi)
    return _poi_dict(poi, db, str(me.usergroup_id))


# ── Update a location ────────────────────────────────────────────────────────

class LocationUpdate(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    radius: Optional[float] = None
    is_active: Optional[bool] = None
    latitude: Optional[float] = None
    longitude: Optional[float] = None
    address: Optional[str] = None
    shape_type: Optional[str] = None
    coordinates: Optional[str] = None
    notes: Optional[str] = None


@router.put("/locations/{location_id}")
def update_location(
    location_id: str, data: LocationUpdate,
    request: Request, db: Session = Depends(get_db),
):
    me = get_portal_user_from_request(request, db)
    if not me.is_group_admin:
        raise HTTPException(status_code=403, detail="Admin access required")
    poi = _get_group_poi(location_id, str(me.usergroup_id), db)
    if data.name is not None:
        poi.name = data.name.strip()
    if data.description is not None:
        poi.description = data.description
    if data.radius is not None:
        poi.radius = max(50.0, min(data.radius, 50000.0))
    if data.is_active is not None:
        poi.is_active = data.is_active
    if data.latitude is not None:
        poi.latitude = float(data.latitude)
    if data.longitude is not None:
        poi.longitude = float(data.longitude)
    if data.address is not None:
        poi.address = data.address
    if data.shape_type is not None and hasattr(poi, 'shape_type'):
        poi.shape_type = data.shape_type
    if data.coordinates is not None and hasattr(poi, 'coordinates'):
        poi.coordinates = data.coordinates
    if data.notes is not None and hasattr(poi, 'notes'):
        poi.notes = data.notes
    db.commit()
    db.refresh(poi)
    return _poi_dict(poi, db, str(me.usergroup_id))


# ── Delete a location ────────────────────────────────────────────────────────

@router.delete("/locations/{location_id}")
def delete_location(
    location_id: str, request: Request, db: Session = Depends(get_db),
):
    me = get_portal_user_from_request(request, db)
    if not me.is_group_admin:
        raise HTTPException(status_code=403, detail="Admin access required")
    poi = _get_group_poi(location_id, str(me.usergroup_id), db)
    # Remove arm links (so geofence checks stop)
    db.query(POITrackerLink).filter(POITrackerLink.poi_id == location_id).delete()
    db.delete(poi)
    db.commit()
    return {"detail": "Location deleted"}


# ── Arm / disarm a tag to a location ─────────────────────────────────────────

@router.post("/locations/{location_id}/arm/{tag_id}", status_code=200)
def arm_location(
    location_id: str, tag_id: str,
    request: Request, db: Session = Depends(get_db),
):
    me = get_portal_user_from_request(request, db)
    if not me.is_group_admin:
        raise HTTPException(status_code=403, detail="Admin access required")
    poi = _get_group_poi(location_id, str(me.usergroup_id), db)
    # Verify tag belongs to this group
    tag = _resolve_group_tag(tag_id, str(me.usergroup_id), db)
    link = db.query(POITrackerLink).filter(
        POITrackerLink.poi_id == location_id,
        POITrackerLink.tracker_id == tag_id,
    ).first()
    if link:
        if link.is_armed:
            return {"detail": "Already armed"}
        link.is_armed = True
        link.armed_at = datetime.utcnow()
        link.disarmed_at = None
        link.last_known_state = GeofenceState.UNKNOWN
    else:
        link = POITrackerLink(
            poi_id=location_id,
            tracker_id=tag_id,
            is_armed=True,
            last_known_state=GeofenceState.UNKNOWN,
        )
        db.add(link)
    db.commit()
    return {"detail": "Armed", "location": _poi_dict(poi, db, str(me.usergroup_id))}


@router.delete("/locations/{location_id}/arm/{tag_id}")
def disarm_location(
    location_id: str, tag_id: str,
    request: Request, db: Session = Depends(get_db),
):
    me = get_portal_user_from_request(request, db)
    if not me.is_group_admin:
        raise HTTPException(status_code=403, detail="Admin access required")
    _get_group_poi(location_id, str(me.usergroup_id), db)
    link = db.query(POITrackerLink).filter(
        POITrackerLink.poi_id == location_id,
        POITrackerLink.tracker_id == tag_id,
    ).first()
    if not link:
        raise HTTPException(status_code=404, detail="Tag not armed to this location")
    link.is_armed = False
    link.disarmed_at = datetime.utcnow()
    db.commit()
    return {"detail": "Disarmed"}


# ── Bulk upload via Excel ─────────────────────────────────────────────────────

@router.get("/locations/template")
def download_locations_template():
    """Return an Excel (.xlsx) template for bulk location upload."""
    if not _HAS_OPENPYXL:
        raise HTTPException(status_code=501, detail="openpyxl not installed")
    from fastapi.responses import StreamingResponse
    wb = _openpyxl.Workbook()
    ws = wb.active
    ws.title = "Locations"
    ws.append(["Postcode", "Name", "Description", "Radius (metres)"])
    ws.append(["SW1A 1AA", "Buckingham Palace", "Example geofence", 200])
    ws.column_dimensions["A"].width = 16
    ws.column_dimensions["B"].width = 30
    ws.column_dimensions["C"].width = 40
    ws.column_dimensions["D"].width = 18
    buf = _io.BytesIO()
    wb.save(buf)
    buf.seek(0)
    return StreamingResponse(
        buf,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": 'attachment; filename="locations_template.xlsx"'},
    )


@router.post("/locations/bulk-upload")
async def bulk_upload_locations(
    file: UploadFile = File(...),
    request: Request = None,
    db: Session = Depends(get_db),
):
    """
    Upload an Excel file with columns: Postcode, Name, Description, Radius.
    Geocodes each row and creates a POI. Returns a summary of successes/failures.
    """
    if not _HAS_OPENPYXL:
        raise HTTPException(status_code=501, detail="openpyxl not installed")
    me = get_portal_user_from_request(request, db)
    if not me.is_group_admin:
        raise HTTPException(status_code=403, detail="Admin access required")

    import asyncio as _asyncio

    contents = await file.read()
    try:
        wb = _openpyxl.load_workbook(filename=_io.BytesIO(contents), read_only=True, data_only=True)
        ws = wb.active
    except Exception:
        raise HTTPException(status_code=422, detail="Could not read Excel file. Please use the provided template.")

    rows = list(ws.iter_rows(min_row=2, values_only=True))
    if not rows:
        raise HTTPException(status_code=422, detail="No data rows found (row 1 is the header)")

    results = {"created": [], "failed": []}

    for i, row in enumerate(rows, start=2):
        postcode = str(row[0]).strip() if row[0] else ""
        name     = str(row[1]).strip() if row[1] else ""
        desc     = str(row[2]).strip() if len(row) > 2 and row[2] else None
        try:
            radius = float(row[3]) if len(row) > 3 and row[3] else 150.0
            radius = max(50.0, min(radius, 50000.0))
        except (TypeError, ValueError):
            radius = 150.0

        if not postcode or not name:
            results["failed"].append({"row": i, "reason": "Postcode and Name are required"})
            continue

        try:
            geo = await _geocode_postcode(postcode)
            poi = POI(
                usergroup_id=str(me.usergroup_id),
                user_id=None,
                name=name,
                description=desc,
                poi_type="single",
                latitude=geo["lat"],
                longitude=geo["lon"],
                radius=radius,
                address=geo["display"],
                is_active=True,
            )
            db.add(poi)
            db.flush()
            results["created"].append({"row": i, "name": name, "postcode": postcode, "id": str(poi.id)})
        except HTTPException as exc:
            results["failed"].append({"row": i, "name": name, "postcode": postcode, "reason": exc.detail})
        # Nominatim rate-limit: 1 req/s
        await _asyncio.sleep(1.1)

    db.commit()
    return {
        "total":   len(rows),
        "created": len(results["created"]),
        "failed":  len(results["failed"]),
        "details": results,
    }


def _resolve_group_tag(tag_id: str, usergroup_id: str, db: Session) -> BLETag:
    """Return a BLETag that belongs to the given group, or raise 404."""
    group = db.query(UserGroup).filter(UserGroup.id == usergroup_id).first()
    if not group:
        raise HTTPException(status_code=404, detail="Group not found")
    tag = db.query(BLETag).filter(BLETag.id == tag_id).first()
    if not tag:
        raise HTTPException(status_code=404, detail="Tag not found")
    # Verify the tag's owning user belongs to this group (by email domain)
    owner = db.query(User).filter(User.id == tag.user_id).first()
    if not owner:
        raise HTTPException(status_code=404, detail="Tag owner not found")
    if group.email_domain and not owner.email.lower().endswith("@" + group.email_domain.lstrip("@").lower()):
        raise HTTPException(status_code=403, detail="Tag does not belong to your group")
    return tag


# ---------------------------------------------------------------------------
# Portal password reset — PIN-based (no database table required)
# ---------------------------------------------------------------------------

# In-memory store:  { email.lower(): {"pin": str, "expires": datetime} }
_portal_reset_pins: dict = {}


class ForgotPasswordRequest(BaseModel):
    email: str


class ResetPasswordRequest(BaseModel):
    email: str
    pin: str
    new_password: str


@router.post("/auth/forgot-password", status_code=200)
def forgot_password(data: ForgotPasswordRequest, db: Session = Depends(get_db)):
    """
    Generate a 6-digit PIN and email it to the portal user.
    Always returns 200 to avoid leaking account existence.
    """
    email = data.email.strip().lower()
    user = db.query(PortalUser).filter(PortalUser.email == email).first()
    if user:
        pin = str(secrets.randbelow(900000) + 100000)  # 100000–999999
        _portal_reset_pins[email] = {
            "pin": pin,
            "expires": datetime.utcnow() + timedelta(minutes=15),
        }
        # Send PIN email
        try:
            _email_svc_portal.send_portal_reset_pin(
                to_email=user.email,
                pin=pin,
                first_name=user.first_name or None,
            )
        except Exception:
            logger.exception("Failed to send portal password reset PIN to %s", email)
    return {"detail": "If that email is registered you will receive a reset PIN shortly."}


@router.post("/auth/reset-password", status_code=200)
def reset_password(data: ResetPasswordRequest, db: Session = Depends(get_db)):
    """Validate the PIN and update the portal user's password."""
    email = data.email.strip().lower()
    entry = _portal_reset_pins.get(email)
    if not entry or datetime.utcnow() > entry["expires"] or entry["pin"] != data.pin.strip():
        raise HTTPException(status_code=400, detail="Invalid or expired PIN")
    if len(data.new_password) < 8:
        raise HTTPException(status_code=400, detail="New password must be at least 8 characters")
    user = db.query(PortalUser).filter(PortalUser.email == email).first()
    if not user:
        raise HTTPException(status_code=400, detail="Invalid or expired PIN")
    user.hashed_password = hash_password(data.new_password)
    db.commit()
    del _portal_reset_pins[email]
    return {"detail": "Password reset successfully"}

