"""
Customer portal API endpoints — auth and portal-user management.

Routes are mounted at /api/portal (separate from /api/v1 user routes and
/api/admin admin routes).  Each PortalUser is scoped to a UserGroup (tenant).
"""
from fastapi import APIRouter, Depends, HTTPException, status, Request, Query
from sqlalchemy.orm import Session
from sqlalchemy import or_
from datetime import datetime, timedelta, timezone
from time import perf_counter
from typing import List, Optional
from uuid import UUID
from pydantic import BaseModel
import jwt
import os
import secrets
import logging

from app.database import get_db
from app.models import UserGroup, UserGroupPackage, PortalUser, BLETag, User, TagCategory, GeofenceAlert, POI, POITrackerLink, GeofenceState, PortalAlert
from app.models_admin import TagPackage
from app.admin_auth import hash_password, verify_password
from app.auth import get_password_hash, verify_password as verify_mobile_password
from app.services.email_service import EmailService as _EmailService

_email_svc_portal = _EmailService()

router = APIRouter(prefix="/api/portal", tags=["portal"])
logger = logging.getLogger(__name__)

# Required — falls back to ADMIN_SECRET_KEY for tenants that historically
# co-signed portal and admin tokens, but the literal final fallback
# ("portal-secret-key-change-me") is gone. Raises KeyError at import if
# neither is set. See .github/copilot-instructions.md.
PORTAL_SECRET_KEY = os.environ.get("PORTAL_SECRET_KEY") or os.environ["ADMIN_SECRET_KEY"]
PORTAL_ALGORITHM = "HS256"
PORTAL_TOKEN_EXPIRE_HOURS = 12


# ---------------------------------------------------------------------------
# Login rate limiter (in-process; per-IP)
# ---------------------------------------------------------------------------
# Simple sliding-window limiter to slow down credential-stuffing / brute-force
# against /api/portal/login. Counters live in-memory only — fine for a single
# backend container; if we ever scale horizontally this should move to Redis.
_LOGIN_MAX_ATTEMPTS = int(os.getenv("PORTAL_LOGIN_MAX_ATTEMPTS", "5"))
_LOGIN_WINDOW_SECONDS = int(os.getenv("PORTAL_LOGIN_WINDOW_SECONDS", "60"))
_LOGIN_LOCKOUT_SECONDS = int(os.getenv("PORTAL_LOGIN_LOCKOUT_SECONDS", "900"))  # 15 min
_login_attempts: dict = {}   # ip -> list[float] (timestamps of recent failures)
_login_lockouts: dict = {}   # ip -> float (unix ts when lockout ends)


def _client_ip(request: "Request") -> str:
    """Best-effort client IP, honouring X-Forwarded-For from the nginx proxy."""
    xff = request.headers.get("x-forwarded-for")
    if xff:
        return xff.split(",")[0].strip()
    try:
        return request.client.host  # type: ignore[union-attr]
    except Exception:
        return "unknown"


def _login_check_rate(ip: str) -> None:
    """Raise HTTP 429 if the caller is currently locked out."""
    import time
    now = time.time()
    until = _login_lockouts.get(ip)
    if until and until > now:
        retry = int(until - now)
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail=f"Too many failed login attempts. Try again in {retry} seconds.",
            headers={"Retry-After": str(retry)},
        )


def _login_record_failure(ip: str) -> None:
    import time
    now = time.time()
    window_start = now - _LOGIN_WINDOW_SECONDS
    bucket = [t for t in _login_attempts.get(ip, []) if t >= window_start]
    bucket.append(now)
    _login_attempts[ip] = bucket
    if len(bucket) >= _LOGIN_MAX_ATTEMPTS:
        _login_lockouts[ip] = now + _LOGIN_LOCKOUT_SECONDS
        _login_attempts.pop(ip, None)
        logger.warning("portal-login: locking out %s for %ds after %d failures", ip, _LOGIN_LOCKOUT_SECONDS, len(bucket))


def _login_record_success(ip: str) -> None:
    _login_attempts.pop(ip, None)
    _login_lockouts.pop(ip, None)


# ---------------------------------------------------------------------------
# Feature / role constants
# ---------------------------------------------------------------------------

SECTION_FEATURES: dict = {
    "tracking":   ["livemap", "assets", "trips"],
    "management": ["asset-mgmt", "users", "locations", "settings"],
    "reports":    [
        "reports-subscriptions", "reports-activity",
        "reports-battery", "reports-alerts", "reports-geofence",
    ],
}
ALL_SECTIONS = list(SECTION_FEATURES.keys())

# Tenant feature → tab name mapping
# Maps high-level tenant feature names to specific tab keys
TENANT_FEATURE_TABS: dict = {
    "livemap": ["livemap", "assets", "trips"],
    "alerts": ["reports-alerts"],
    "geofences": ["reports-geofence"],
    "reports": ["reports-subscriptions", "reports-activity"],
    "management": ["asset-mgmt", "users", "locations", "settings"],
    "settings": ["settings"],
    "developers": ["api-tokens"],  # Developers section (API Tokens tab)
}

# Standalone tenant features (not navigation tabs, but UI feature flags)
# These are always included in effective_features when tenant enables them
STANDALONE_TENANT_FEATURES: set = set()


# Tenant-level feature kill-switch (env-driven). Comma-separated list of
# feature keys that should be hidden from the portal *and* refused at the API
# boundary, regardless of role/group config. Used to ship the same code to
# multiple tenants while keeping certain features dark on some of them.
# Example:  TENANT_DISABLED_FEATURES=floorplan
_DISABLED_FEATURES: set = {
    f.strip() for f in os.getenv("TENANT_DISABLED_FEATURES", "").split(",") if f.strip()
}
if _DISABLED_FEATURES:
    logger.warning("portal: tenant feature kill-switch active for: %s", ", ".join(sorted(_DISABLED_FEATURES)))


def _compute_effective_features(user: "PortalUser", group: "UserGroup") -> list:
    """Return the list of tab keys the user can access, given their role and
    the usergroup's allowed sections. Tenant features are applied as master
    switch - user sees feature only if BOTH tenant enables it AND user role allows it."""
    from app.models import TenantFeature
    from sqlalchemy.orm import Session
    
    allowed_sections = group.allowed_sections or ALL_SECTIONS
    group_features = [f for s in allowed_sections for f in SECTION_FEATURES.get(s, [])]

    # The user's role decides which of the group's tabs they get.
    from app.services import access_service
    access = access_service.for_user(user)
    role_tabs = {t for p in access.permissions for t in access_service.CLASSIC_TABS.get(p, [])}
    result = [f for f in group_features if f in role_tabs]

    # Apply tenant-wide feature toggles (master switch)
    # Query enabled features for this tenant
    try:
        from sqlalchemy import inspect
        session = inspect(user).session
        if session:
            with session.begin_nested():   # a failure here mustn't abort the caller's transaction
                tenant_features = session.query(TenantFeature).filter(
                    TenantFeature.usergroup_id == user.usergroup_id,
                    TenantFeature.enabled == True
                ).all()
            tenant_enabled_features = {f.feature_name for f in tenant_features}
            
            # If tenant has feature records, expand feature names to tab names
            # and intersect with user features
            if tenant_enabled_features:
                # Expand tenant features to actual tab names using TENANT_FEATURE_TABS mapping
                tenant_enabled_tabs = set()
                for feature_name in tenant_enabled_features:
                    tabs = TENANT_FEATURE_TABS.get(feature_name, [])
                    tenant_enabled_tabs.update(tabs)
                
                # User sees tab only if BOTH tenant enables it AND user role allows it
                result = [f for f in result if f in tenant_enabled_tabs]
                
                # Add standalone features (not tabs) that tenant enabled
                standalone_features = tenant_enabled_features & STANDALONE_TENANT_FEATURES
                result.extend(standalone_features)
    except Exception:
        # If tenant features table doesn't exist yet or query fails,
        # fall back to user features only (backward compatible)
        pass
    
    # Apply the legacy kill-switch *last* so it overrides every other layer.
    return [f for f in result if f not in _DISABLED_FEATURES]


def _require(me: PortalUser, db: Session, *permissions: str) -> None:
    """403 unless the user's roles grant one of these permissions."""
    from app.services import access_service
    access_service.for_user(me, db).require_any(*permissions)


def _user_can_manage(me, feature: str) -> bool:
    """True if `me` is allowed to perform write actions on `feature`.

    Background: the legacy gate `me.is_group_admin` is True ONLY for the
    bootstrap user created when the usergroup was provisioned via the
    system-admin API. Sub-users created through the portal are always
    is_group_admin=False even when their role is 'admin' or 'manager',
    which silently blocked them from saving geofences, users, etc. even
    though the UI showed they had the feature.

    This helper closes that gap by honoring `role` (and `custom_features`
    for custom roles) while still respecting the tenant kill-switch.
    """
    if feature in _DISABLED_FEATURES:
        return False
    from app.services import access_service
    access = access_service.for_user(me)
    permission = access_service.CLASSIC_MANAGE.get(feature)
    return access.is_admin if permission is None else access.can(permission)


def _delete_tag_with_cleanup(db: Session, tag: BLETag, logger_prefix: str = "TAG DELETE") -> dict:
    """Delete a device and its data (see housekeeping_service.delete_tag). Does not commit."""
    from app.services.housekeeping_service import delete_tag
    return delete_tag(db, tag, reason=logger_prefix.lower())


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
    mobile_user_id: Optional[UUID] = None
    role_id: Optional[UUID] = None
    role_ids: List[str] = []
    role_names: List[str] = []
    language: Optional[str] = None
    security_group_id: Optional[UUID] = None
    created_at: Optional[datetime] = None
    last_login_at: Optional[datetime] = None
    last_active_at: Optional[datetime] = None

    class Config:
        from_attributes = True


def _user_out(db: Session, user: PortalUser) -> "PortalUserOut":
    """A portal user with the roles they hold."""
    from app.models import PortalRole
    from app.services import access_service
    out = PortalUserOut.model_validate(user)
    ids = access_service.role_ids(db, user)
    roles = db.query(PortalRole).filter(PortalRole.id.in_(ids)).all() if ids else []
    roles.sort(key=lambda r: (not r.is_admin, r.name.lower()))
    out.role_ids, out.role_names = [str(r.id) for r in roles], [r.name for r in roles]
    return out


class UserGroupOut(BaseModel):
    id: UUID
    name: str
    slug: str
    allowed_tag_types: Optional[list] = None

    class Config:
        from_attributes = True


class PortalTokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    portal_user: PortalUserOut
    usergroup: UserGroupOut
    effective_features: Optional[list] = None
    access: Optional[dict] = None


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
        # Allow tokens without expiration (admin impersonation tokens)
        payload = jwt.decode(
            token, 
            PORTAL_SECRET_KEY, 
            algorithms=[PORTAL_ALGORITHM],
            options={"verify_exp": False}  # Support impersonation tokens with no exp field
        )
        if payload.get("type") != "portal":
            return None
        # If token has exp field, verify it manually
        if "exp" in payload:
            exp_timestamp = payload["exp"]
            if datetime.utcnow().timestamp() > exp_timestamp:
                return None  # Token expired
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
    # Last activity, recorded at most every 5 minutes
    now = datetime.now(timezone.utc)
    last = user.last_active_at
    if last is None or (last if last.tzinfo else last.replace(tzinfo=timezone.utc)) < now - timedelta(minutes=5):
        user.last_active_at = now
        db.commit()
    return user


# ---------------------------------------------------------------------------
# Auth endpoints
# ---------------------------------------------------------------------------

@router.post("/login", response_model=PortalTokenResponse)
def portal_login(data: PortalLoginRequest, request: Request, db: Session = Depends(get_db)):
    """Log in as a portal user. Returns a JWT scoped to the user's UserGroup."""
    ip = _client_ip(request)
    _login_check_rate(ip)

    user = db.query(PortalUser).filter(
        PortalUser.email == data.email.lower().strip(),
        PortalUser.is_active == True,
    ).first()

    if not user or not verify_password(user.hashed_password, data.password):
        _login_record_failure(ip)
        if user is not None:
            from app.services import audit_service
            audit_service.record(db, user, "Sign-in failed", "Sign-in", "Wrong password", outcome="failed", ip=ip)
            db.commit()
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

    _login_record_success(ip)
    user.last_login_at = user.last_active_at = datetime.now(timezone.utc)
    from app.services import audit_service
    audit_service.record(db, user, "Signed in", "Sign-in", "Signed in", ip=ip)
    db.commit()
    token = _create_portal_token(str(user.id), str(user.usergroup_id))
    effective = _compute_effective_features(user, group)
    from app.services import access_service
    return {
        "access_token": token,
        "token_type": "bearer",
        "portal_user": _user_out(db, user),
        "usergroup": UserGroupOut.model_validate(group),
        "effective_features": effective,
        "access": access_service.profile(db, access_service.for_user(user, db)),
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
    from app.services import access_service
    return {
        "portal_user": _user_out(db, user),
        "usergroup":   UserGroupOut.model_validate(group) if group else None,
        "effective_features": effective,
        "access": access_service.profile(db, access_service.for_user(user, db)),
    }


# ---------------------------------------------------------------------------
# Portal user management (group admin only)
# ---------------------------------------------------------------------------

class PortalUserCreate(BaseModel):
    email: str
    first_name: Optional[str] = None
    last_name: Optional[str] = None
    role: str = "admin"              # legacy: admin | manager | reporter | custom
    custom_features: Optional[list] = None  # only used when role='custom'
    role_id: Optional[UUID] = None           # one role (older clients); role_ids takes precedence
    role_ids: Optional[List[UUID]] = None    # the roles the user holds
    security_group_id: Optional[UUID] = None
    language: Optional[str] = None           # a language code from the admin portal; None = the group's default


def _check_roles_and_security_group(db: Session, access, role_ids, security_group_id, current_ids=()):
    """Validate roles / security group for a user in the caller's group. Returns the roles (admin first).

    A non-admin caller may only give roles whose permissions they hold (roles the
    user already has may stay).
    """
    from app.models import PortalRole, SecurityGroup
    usergroup_id = access.user.usergroup_id
    ids = list(dict.fromkeys(str(r) for r in role_ids or []))
    roles = db.query(PortalRole).filter(PortalRole.id.in_(ids), PortalRole.usergroup_id == usergroup_id).all() if ids else []
    if not roles:
        raise HTTPException(status_code=400, detail="Choose at least one role for this user")
    if len(roles) != len(ids):
        raise HTTPException(status_code=400, detail="Unknown role")
    current = {str(r) for r in current_ids}
    for role in roles:
        if str(role.id) not in current:
            access.check_grant(role.permissions or [], admin=role.is_admin)
    if security_group_id is not None:
        if not db.query(SecurityGroup).filter(SecurityGroup.id == security_group_id,
                                              SecurityGroup.usergroup_id == usergroup_id).first():
            raise HTTPException(status_code=400, detail="Unknown security group")
    elif not any(r.is_admin or "security.all_vehicles" in (r.permissions or []) for r in roles):
        raise HTTPException(status_code=400, detail="Add the user to a security group so they can see vehicles")
    return sorted(roles, key=lambda r: (not r.is_admin, r.name.lower()))


def _check_language(db: Session, code: Optional[str]) -> Optional[str]:
    """A language added (and active) in the admin portal, or None for the user group's default."""
    code = (code or "").strip()
    if not code:
        return None
    from app.models_i18n import Language
    if not db.query(Language).filter(Language.code == code, Language.is_active == True).first():  # noqa: E712
        raise HTTPException(status_code=400, detail=f"Language '{code}' isn't available")
    return code


class LanguageIn(BaseModel):
    language: Optional[str] = None


@router.put("/account/language")
def set_my_language(data: LanguageIn, request: Request, db: Session = Depends(get_db)):
    """Change the signed-in user's own language (None = the user group's default)."""
    me = get_portal_user_from_request(request, db)
    me.language = _check_language(db, data.language)
    db.commit()
    from app.services import access_service
    return {"language": access_service.user_language(db, me)}


def _guard_admin_target(db: Session, access, target: PortalUser) -> None:
    """Only an administrator may change, reset or delete an administrator."""
    from app.services import access_service
    if not access.is_admin and access_service.for_user(target, db).is_admin:
        raise HTTPException(status_code=403, detail="Only a User Group Administrator can change an administrator")


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
    from app.services import access_service
    access_service.for_user(me, db).require_any("users.view", "users.manage")
    users = db.query(PortalUser).filter(
        PortalUser.usergroup_id == me.usergroup_id,
    ).order_by(PortalUser.created_at).all()
    return [_user_out(db, user) for user in users]


@router.post("/users", response_model=PortalUserCreateResponse)
def create_portal_user(
    data: PortalUserCreate,
    request: Request,
    db: Session = Depends(get_db),
):
    """Create a new portal user in the same UserGroup (group admin only)."""
    me = get_portal_user_from_request(request, db)
    from app.services import access_service
    access = access_service.for_user(me, db)
    access.require("users.manage")

    email = data.email.lower().strip()
    if db.query(PortalUser).filter(PortalUser.email == email).first():
        raise HTTPException(status_code=400, detail="A portal user with that email already exists")

    valid_roles = {"admin", "manager", "reporter", "custom"}
    role = data.role if data.role in valid_roles else "admin"
    access_service.ensure_defaults(db, me.usergroup_id)
    wanted = data.role_ids if data.role_ids is not None else ([data.role_id] if data.role_id else None)
    new_roles = []
    if wanted is not None:
        new_roles = _check_roles_and_security_group(db, access, wanted, data.security_group_id)
        role = "admin" if any(r.is_admin for r in new_roles) else "custom"
    elif not access.is_admin:
        raise HTTPException(status_code=400, detail="Choose at least one role for this user")

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
        custom_features=data.custom_features if (role == "custom" and not new_roles) else None,
        security_group_id=data.security_group_id if new_roles else None,
        language=_check_language(db, data.language),
    )
    db.add(new_user)
    db.flush()
    if new_roles:
        access_service.set_roles(db, new_user, new_roles)
    db.commit()
    db.refresh(new_user)

    return PortalUserCreateResponse(
        portal_user=_user_out(db, new_user),
        temp_password=temp_password,
    )


class PortalUserPatch(BaseModel):
    is_active: Optional[bool] = None
    expires_at: Optional[datetime] = None
    role: Optional[str] = None
    custom_features: Optional[list] = None
    role_id: Optional[UUID] = None
    role_ids: Optional[List[UUID]] = None
    security_group_id: Optional[UUID] = None
    first_name: Optional[str] = None
    last_name: Optional[str] = None
    language: Optional[str] = None


@router.patch("/users/{user_id}", response_model=PortalUserOut)
def patch_portal_user(
    user_id: UUID,
    data: PortalUserPatch,
    request: Request,
    db: Session = Depends(get_db),
):
    """Update is_active and/or expires_at for a portal user (group admin only)."""
    me = get_portal_user_from_request(request, db)
    from app.services import access_service
    access = access_service.for_user(me, db)
    access.require("users.manage")

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

    _guard_admin_target(db, access, target)

    if data.is_active is False and access_service.for_user(target, db).is_admin \
            and access_service.admin_count(db, me.usergroup_id, exclude_user_id=target.id) == 0:
        raise HTTPException(status_code=400, detail="The user group needs at least one active User Group Administrator")
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

    if "language" in data.model_fields_set:
        target.language = _check_language(db, data.language)
    if data.first_name is not None:
        target.first_name = data.first_name.strip() or None
    if data.last_name is not None:
        target.last_name = data.last_name.strip() or None
    fields = data.model_fields_set
    if fields & {"role_id", "role_ids", "security_group_id"}:
        current = access_service.role_ids(db, target)
        wanted = (data.role_ids if "role_ids" in fields else [data.role_id] if "role_id" in fields and data.role_id else current)
        sg_id = data.security_group_id if "security_group_id" in fields else target.security_group_id
        new_roles = _check_roles_and_security_group(db, access, wanted, sg_id, current_ids=current)
        if not any(r.is_admin for r in new_roles) and access_service.for_user(target, db).is_admin \
                and access_service.admin_count(db, me.usergroup_id, exclude_user_id=target.id) == 0:
            raise HTTPException(status_code=400, detail="The user group needs at least one User Group Administrator")
        target.security_group_id = sg_id
        access_service.set_roles(db, target, new_roles)

    db.commit()
    db.refresh(target)
    return _user_out(db, target)


@router.delete("/users/{user_id}", status_code=204)
def delete_portal_user(user_id: UUID, request: Request, db: Session = Depends(get_db)):
    """Delete a portal user in the caller's group (needs users.manage; their audit entries stay)."""
    me = get_portal_user_from_request(request, db)
    from app.services import access_service
    access = access_service.for_user(me, db)
    access.require("users.manage")
    target = db.query(PortalUser).filter(PortalUser.id == str(user_id), PortalUser.usergroup_id == me.usergroup_id).first()
    if not target:
        raise HTTPException(status_code=404, detail="User not found in your group")
    if str(target.id) == str(me.id):
        raise HTTPException(status_code=400, detail="You can't delete your own account")
    if target.role == "system_admin":
        raise HTTPException(status_code=403, detail="Built-in system admin accounts can't be deleted")
    _guard_admin_target(db, access, target)
    from sqlalchemy.exc import IntegrityError
    try:
        db.delete(target)
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(status_code=409, detail="Older records still point to this user — deactivate them instead")


# ---------------------------------------------------------------------------
# Settings — the group's identity (used by the classic dashboard)
# ---------------------------------------------------------------------------

class GroupSettingsOut(BaseModel):
    id: UUID
    name: str
    slug: str

    class Config:
        from_attributes = True


@router.get("/settings", response_model=GroupSettingsOut)
def get_settings(request: Request, db: Session = Depends(get_db)):
    """Return the logged-in portal user's UserGroup."""
    me = get_portal_user_from_request(request, db)
    group = db.query(UserGroup).filter(UserGroup.id == me.usergroup_id).first()
    if not group:
        raise HTTPException(status_code=404, detail="User group not found")
    return GroupSettingsOut.model_validate(group)


# ---------------------------------------------------------------------------
# Data Exchange — link this group to a DataProfiler reseller exchange
# ---------------------------------------------------------------------------

class DataExchangeLinkRequest(BaseModel):
    exchange_key: str
    exchange_secret: str


def _data_exchange_status(group_id, db: Session) -> dict:
    from app.models_dataprofiler import DataExchange, ResellerDevice
    from sqlalchemy import func as _func
    ex = db.query(DataExchange).filter(DataExchange.usergroup_id == group_id).first()
    if not ex:
        return {"linked": False}
    counts = dict(
        db.query(ResellerDevice.status, _func.count())
        .filter(ResellerDevice.reseller_id == ex.reseller_id)
        .group_by(ResellerDevice.status).all()
    )
    return {
        "linked": True,
        "exchange_key": ex.exchange_key,
        "reseller_name": ex.reseller.name if ex.reseller else None,
        "linked_at": ex.linked_at,
        "devices_routed": counts.get("routed", 0),
        "devices_pending": counts.get("pending", 0) + counts.get("conflict", 0),
    }


@router.get("/data-exchange")
def get_data_exchange(request: Request, db: Session = Depends(get_db)):
    """Return the DataProfiler exchange linked to this group, if any."""
    me = get_portal_user_from_request(request, db)
    return _data_exchange_status(me.usergroup_id, db)


@router.post("/data-exchange/link")
def link_data_exchange(data: DataExchangeLinkRequest, request: Request, db: Session = Depends(get_db)):
    """Link this group to an exchange using the key + secret issued in DataProfiler.

    Failed attempts share the portal login lockout so secrets can't be brute-forced.
    """
    from app.models_dataprofiler import DataExchange
    from app.services import dataprofiler_service as dp

    me = get_portal_user_from_request(request, db)
    _require(me, db, "data_exchange.manage")
    ip = _client_ip(request)
    _login_check_rate(ip)

    ex = db.query(DataExchange).filter(DataExchange.exchange_key == data.exchange_key.strip()).first()
    if not ex or not dp.verify_exchange_secret(ex, data.exchange_secret.strip()):
        _login_record_failure(ip)
        raise HTTPException(status_code=400, detail="Invalid exchange key or secret")
    _login_record_success(ip)

    group = db.query(UserGroup).filter(UserGroup.id == me.usergroup_id).first()
    if not group:
        raise HTTPException(status_code=404, detail="User group not found")
    try:
        dp.link_exchange(db, ex, group, linked_by=me.email)
    except ValueError as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail=str(exc))
    db.commit()
    return _data_exchange_status(group.id, db)


# ---------------------------------------------------------------------------
# Theme / Branding
# ---------------------------------------------------------------------------

class ThemeOut(BaseModel):
    name: Optional[str] = None
    logo_data: Optional[str] = None
    logo_dark_data: Optional[str] = None
    report_logo_data: Optional[str] = None
    theme_primary: Optional[str] = None
    theme_accent: Optional[str] = None
    timezone: Optional[str] = None
    history_retention_days: Optional[int] = 365
    theme_settings: Optional[dict] = None
    default_language: Optional[str] = None

    class Config:
        from_attributes = True


# White-label settings (UserGroup.theme_settings); anything else sent is dropped
THEME_FONTS = ("Inter", "System", "Roboto", "Open Sans", "Lato", "Montserrat", "Poppins", "Nunito", "Source Sans 3")
THEME_SETTINGS = {
    "menu_bg": "colour",          # side menu background
    "surface": "colour",          # dark-mode background (the app's panels are shades of it)
    "light_bg": "colour",         # light-mode page background
    "color_scheme": ("dark", "light"),   # default for users who haven't picked one
    "lock_scheme": "bool",        # hide the light/dark switch
    "font": THEME_FONTS,
    "radius": ("xs", "sm", "md", "lg", "xl"),
    "brand_name": "text",         # platform name in the browser tab and menu (no logo)
}


def _check_theme_settings(raw: dict) -> Optional[dict]:
    import re
    out = {}
    for key, kind in THEME_SETTINGS.items():
        v = raw.get(key)
        if v is None or v == "":
            continue
        if kind == "colour":
            if not isinstance(v, str) or not re.fullmatch(r"#[0-9a-fA-F]{6}", v):
                raise HTTPException(status_code=400, detail=f"{key}: use a hex colour like #113356")
            out[key] = v.lower()
        elif kind == "bool":
            if v:
                out[key] = True
        elif kind == "text":
            v = str(v).strip()
            if len(v) > 60:
                raise HTTPException(status_code=400, detail="Keep the platform name under 60 characters")
            if v:
                out[key] = v
        elif v not in kind:
            raise HTTPException(status_code=400, detail=f"{key}: choose one of {', '.join(kind)}")
        else:
            out[key] = v
    return out or None


class ThemeUpdate(BaseModel):
    logo_data: Optional[str] = None          # base64 data-URL or None to clear
    logo_dark_data: Optional[str] = None     # base64 data-URL (dark mode) or None to clear
    theme_primary: Optional[str] = None      # hex e.g. '#3b82f6' or None to reset
    theme_accent: Optional[str] = None
    history_retention_days: Optional[int] = None
    report_logo_data: Optional[str] = None   # data URL, '' clears
    timezone: Optional[str] = None           # IANA name, '' clears
    theme_settings: Optional[dict] = None    # THEME_SETTINGS keys; {} resets to the default look


_LOGO_PREFIXES = ("data:image/png", "data:image/jpeg", "data:image/jpg", "data:image/svg+xml")
_LOGO_MAX_CHARS = 1_500_000   # ~1 MB image


def _check_logo(value: str, field: str) -> Optional[str]:
    if not value:
        return None
    if not value.startswith(_LOGO_PREFIXES):
        raise HTTPException(status_code=400, detail=f"{field}: use a PNG, JPEG or SVG image")
    if len(value) > _LOGO_MAX_CHARS:
        raise HTTPException(status_code=400, detail=f"{field}: the image is too large (max 1 MB)")
    return value


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
    group = db.query(UserGroup).filter(UserGroup.id == me.usergroup_id).first()
    if not group:
        raise HTTPException(status_code=404, detail="User group not found")
    # Look (theme.manage) and settings (settings.manage) are separate permissions; a field
    # that is sent unchanged needs neither, so each page can save the whole form
    def changed(field, current):
        value = getattr(data, field)
        return value is not None and (value or None) != (current or None)
    if any(changed(f, getattr(group, f)) for f in ("logo_data", "logo_dark_data", "report_logo_data", "theme_primary", "theme_accent")) \
            or (data.theme_settings is not None and _check_theme_settings(data.theme_settings) != (group.theme_settings or None)):
        _require(me, db, "theme.manage")
    if changed("timezone", group.timezone) or (data.history_retention_days is not None
                                                 and data.history_retention_days != group.history_retention_days):
        _require(me, db, "settings.manage")

    if data.logo_data is not None:
        group.logo_data = _check_logo(data.logo_data, "Platform logo")

    if data.report_logo_data is not None:
        group.report_logo_data = _check_logo(data.report_logo_data, "Report logo")

    if data.timezone is not None:
        tz = data.timezone.strip()
        if tz:
            try:
                from zoneinfo import ZoneInfo
                ZoneInfo(tz)
            except Exception:
                raise HTTPException(status_code=400, detail=f"Unknown timezone '{tz}'")
        group.timezone = tz or None

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

    if data.theme_settings is not None:
        group.theme_settings = _check_theme_settings(data.theme_settings)

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
    notify_temperature: bool = True
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
    notify_temperature: Optional[bool] = None
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
    if data.notify_temperature is not None:
        me.notify_temperature = data.notify_temperature
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

class AdminPasswordResetResponse(BaseModel):
    user_id: UUID
    email: str
    temp_password: str


@router.post("/users/{user_id}/reset-password", response_model=AdminPasswordResetResponse)
def admin_reset_user_password(
    user_id: UUID,
    request: Request,
    db: Session = Depends(get_db),
):
    """Reset another portal user's password in the same usergroup (needs the
    users.manage permission). Returns the new temporary password ONCE.
    """
    me = get_portal_user_from_request(request, db)
    from app.services import access_service
    access = access_service.for_user(me, db)
    access.require("users.manage")

    target = db.query(PortalUser).filter(
        PortalUser.id == str(user_id),
        PortalUser.usergroup_id == me.usergroup_id,
    ).first()
    if not target:
        raise HTTPException(status_code=404, detail="User not found in your group")
    if str(target.id) == str(me.id):
        raise HTTPException(status_code=400, detail="Use change-password to update your own password")
    _guard_admin_target(db, access, target)

    import secrets as _secrets
    temp_password = _secrets.token_urlsafe(12)
    credential_user = db.query(User).filter(User.id == target.mobile_user_id).first() if target.mobile_user_id else None
    if credential_user:
        credential_user.hashed_password = get_password_hash(temp_password)
    else:
        target.hashed_password = hash_password(temp_password)
    db.commit()

    return AdminPasswordResetResponse(
        user_id=target.id,
        email=target.email,
        temp_password=temp_password,
    )


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
    credential_user = db.query(User).filter(User.id == me.mobile_user_id).first() if me.mobile_user_id else None
    password_is_valid = (
        verify_mobile_password(data.current_password, credential_user.hashed_password)
        if credential_user and credential_user.hashed_password
        else verify_password(me.hashed_password, data.current_password)
    )
    if not password_is_valid:
        raise HTTPException(status_code=400, detail="Current password is incorrect")
    if len(data.new_password) < 8:
        raise HTTPException(status_code=400, detail="New password must be at least 8 characters")
    if credential_user:
        credential_user.hashed_password = get_password_hash(data.new_password)
    else:
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
# Tags — the group's devices, and tags of mobile-app users who
#         are linked to the group
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
    # Trip engine subscription
    # Activity status derived from last_seen (real GPS-fix age):
    #   active  : reported within last 24 h
    #   idle    : reported within last 7 days but not within 24 h
    #   offline : older than 7 days, or never reported
    activity_status: Optional[str] = None
    # Sensor data and metadata (Series 5: Temperature, Battery, RSSI, etc.)
    attributes: Optional[dict] = None

    class Config:
        from_attributes = True


def _compute_activity_status(last_seen: Optional[datetime]) -> str:
    """Tri-state activity status based on real GPS-fix age.

    Conditions (single source of truth, mirrored in customer-dashboard JS):
      - active  : last_seen within 24 h
      - idle    : last_seen between 24 h and 7 days ago
      - offline : older than 7 days, or never reported
    """
    if last_seen is None:
        return "offline"
    ls = last_seen.replace(tzinfo=None) if last_seen.tzinfo else last_seen
    age_s = (datetime.utcnow() - ls).total_seconds()
    if age_s <= 24 * 3600:
        return "active"
    if age_s <= 7 * 24 * 3600:
        return "idle"
    return "offline"


@router.get("/tags", response_model=List[PortalTagOut])
def list_group_tags(request: Request, db: Session = Depends(get_db)):
    """Return all BLE tags belonging to mobile-app users in this usergroup.
    
    Includes devices created for the group (e.g. routed from a Data Exchange)
    and tags owned by mobile-app users who have a PortalUser record in the group.

    Returns an empty list (not an error) when the group has no devices.
    """
    started_at = perf_counter()
    me = get_portal_user_from_request(request, db)
    group = db.query(UserGroup).filter(UserGroup.id == me.usergroup_id).first()
    if not group:
        return []

    group_id = str(group.id)

    # Mobile-app users linked to the group (via the PortalUser table, joined to User by email)
    portal_user_rows = (
        db.query(User.id, User.email)
        .join(PortalUser, User.email == PortalUser.email)
        .filter(PortalUser.usergroup_id == me.usergroup_id)
        .all()
    )
    portal_user_ids = [str(uid) for uid, _ in portal_user_rows]
    
    all_owner_ids = list(set(portal_user_ids))
    owner_email_map = {str(uid): email for uid, email in portal_user_rows}

    tag_scope_filter = (
        or_(
            BLETag.user_id.in_(all_owner_ids),
            BLETag.attributes.op("->>")("_created_usergroup_id") == group_id,
        )
        if all_owner_ids
        else BLETag.attributes.op("->>")("_created_usergroup_id") == group_id
    )

    tags = (
        db.query(BLETag)
        .filter(
            tag_scope_filter,
            BLETag.is_active == True,
        )
        .order_by(BLETag.added_at.desc())
        .all()
    )
    from app.services import access_service
    visible = access_service.for_user(me, db).visible_imeis(db)
    if visible is not None:
        tags = [t for t in tags if t.imei in visible]

    # Some group-scoped tags are included via attributes._created_usergroup_id
    # and may belong to users outside the current domain filter. Resolve those
    # owner emails as well so response model validation never sees None.
    missing_owner_ids = {
        str(t.user_id)
        for t in tags
        if t.user_id and str(t.user_id) not in owner_email_map
    }
    if missing_owner_ids:
        extra_owner_rows = db.query(User.id, User.email).filter(User.id.in_(list(missing_owner_ids))).all()
        for uid, email in extra_owner_rows:
            owner_email_map[str(uid)] = email

    # Build package lookup cache for this batch
    pkg_ids = {t.package_id for t in tags if t.package_id}
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
    for tag in tags:
        owner_email = owner_email_map.get(str(tag.user_id)) if tag.user_id else None
        if not owner_email:
            owner_email = "unknown@unknown"
        pkg = pkg_map.get(str(tag.package_id)) if tag.package_id else None
        effective_expiry = tag.expiry_date
        days_remaining = None
        if effective_expiry:
            days_remaining = (effective_expiry.replace(tzinfo=None) - datetime.utcnow()).days
        # Resolve category from attributes
        attrs = tag.attributes or {}
        raw_cat_name = (attrs.get('category') or {}).get('value') or None
        cat_id, cat_name = (None, None)
        if raw_cat_name:
            match = cat_name_map.get(raw_cat_name.lower())
            if match:
                cat_id, cat_name = match
            else:
                cat_name = raw_cat_name
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
            expiry_date=effective_expiry,
            days_remaining=days_remaining,
            activation_date=tag.activation_date,
            category_id=cat_id,
            category_name=cat_name,
            activity_status=_compute_activity_status(tag.last_seen),
            attributes=tag.attributes,
        ))

    elapsed_ms = (perf_counter() - started_at) * 1000.0
    if elapsed_ms > 1500:
        logger.warning(
            "portal-tags slow path: usergroup_id=%s owners=%d tags=%d elapsed_ms=%.1f",
            group_id,
            len(all_owner_ids),
            len(result),
            elapsed_ms,
        )
    return result


# ---------------------------------------------------------------------------
# Packages — list active packages available for portal to assign to tags
# ---------------------------------------------------------------------------

class PackageOut(BaseModel):
    id: UUID
    name: str
    description: Optional[str]
    validity_days: Optional[int] = None
    validity_months: Optional[int] = None
    validity_label: str
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
        pkgs = db.query(TagPackage).filter(TagPackage.id.in_(pkg_ids), TagPackage.is_active == True).all()
    else:
        # Fallback: no explicit assignments — return all active packages
        pkgs = db.query(TagPackage).filter(TagPackage.is_active == True).all()
    return sorted(pkgs, key=lambda p: p.validity_sort_key)


# ---------------------------------------------------------------------------
# Mobile users — list mobile-app Users in the group's email domain
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# Tag management — create and reassign tags from the portal
# ---------------------------------------------------------------------------


class PortalTagDelete(BaseModel):
    tag_ids: List[str]


def _build_tag_out(tag: BLETag, owner_email: str, db: Optional[Session] = None) -> PortalTagOut:
    pkg = None
    if tag.package_id and db:
        pkg = db.query(TagPackage).filter(TagPackage.id == str(tag.package_id)).first()
    effective_expiry = tag.expiry_date
    days_remaining = None
    if effective_expiry:
        days_remaining = (effective_expiry.replace(tzinfo=None) - datetime.utcnow()).days
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
        expiry_date=effective_expiry,
        days_remaining=days_remaining,
        activation_date=tag.activation_date,
        category_name=((tag.attributes or {}).get("category") or {}).get("value"),
        activity_status=_compute_activity_status(tag.last_seen),
        attributes=tag.attributes,
    )


def _get_group_owner_ids(group: UserGroup, db: Session) -> list:
    """IDs of mobile-app users linked to the group (they have a PortalUser record in it)."""
    portal_user_ids = [
        str(uid) for (uid,) in 
        db.query(User.id)
        .join(PortalUser, User.email == PortalUser.email)
        .filter(PortalUser.usergroup_id == group.id)
        .all()
    ]
    
    return list(set(portal_user_ids))


def _group_tag_scope_filter(group: UserGroup, all_owner_ids: list):
    """Return a filter clause for tags visible to a portal group.

    Includes:
    1. Tags owned by users in all_owner_ids (domain-matched + manually assigned)
    
    Args:
        group: UserGroup object
        all_owner_ids: List of user IDs from _get_group_owner_ids()
    """
    gid = str(group.id)
    if all_owner_ids:
        return or_(
            BLETag.user_id.in_(all_owner_ids),
            BLETag.attributes.op("->>")("_created_usergroup_id") == gid,
        )
    else:
        return BLETag.attributes.op("->>")("_created_usergroup_id") == gid


class PortalTagUpdate(BaseModel):
    description: Optional[str] = None
    category: Optional[str] = None  # category name; empty string clears it
    package_id: Optional[str] = None  # UUID string; empty string clears package
    # Vehicle details, stored in attributes as {key: {"value": ...}}; "" clears one
    make: Optional[str] = None
    model: Optional[str] = None
    year: Optional[str] = None
    registration: Optional[str] = None
    driver: Optional[str] = None


VEHICLE_DETAILS = ("make", "model", "year", "registration", "driver")


@router.put("/tags/{tag_id}", response_model=PortalTagOut)
def update_tag(tag_id: str, data: PortalTagUpdate, request: Request, db: Session = Depends(get_db)):
    """Update a device's description, category or package (group admin only)."""
    me = get_portal_user_from_request(request, db)
    _require(me, db, "vehicles.manage")
    group = db.query(UserGroup).filter(UserGroup.id == me.usergroup_id).first()
    if not group:
        raise HTTPException(status_code=404, detail="User group not found")
    all_owner_ids = _get_group_owner_ids(group, db)
    try:
        UUID(str(tag_id))
    except ValueError:
        raise HTTPException(status_code=404, detail="Tag not found in your group")

    tag = (
        db.query(BLETag)
        .filter(BLETag.id == tag_id, _group_tag_scope_filter(group, all_owner_ids))
        .first()
    )
    from app.services import access_service
    if not tag or not access_service.for_user(me, db).can_see(db, tag.imei):
        raise HTTPException(status_code=404, detail="Tag not found in your group")

    details = {k: getattr(data, k) for k in VEHICLE_DETAILS if getattr(data, k) is not None}
    if details:
        attrs = dict(tag.attributes or {})
        for key, value in details.items():
            value = value.strip()[:100]
            if value:
                attrs[key] = {"value": value}
            else:
                attrs.pop(key, None)
        tag.attributes = attrs
    if data.description is not None:
        cleaned = data.description or None
        tag.description = cleaned
        tag.device_name = cleaned
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
            current_pkg_id = str(tag.package_id) if tag.package_id else None
            new_pkg_id = str(data.package_id)
            
            # Determine if we should recalculate expiry:
            # 1. Package changed (different package_id)
            # 2. Same package but expired/about to expire (renewal/extension use case)
            package_changed = current_pkg_id != new_pkg_id
            is_expired = tag.expiry_date is None or tag.expiry_date.replace(tzinfo=None) <= datetime.utcnow()
            should_recalculate = package_changed or is_expired
            
            if should_recalculate:
                tag.package_id = new_pkg_id
                # Expiry = base_date + package validity.
                # For renewals/extensions, always use NOW as base so expiry extends into the future.
                # For new assignments or package changes with valid activation_date, use activation_date.
                if is_expired or not tag.activation_date:
                    # Renewal or first assignment: extend from now
                    base = datetime.utcnow()
                    tag.expiry_date = pkg.expiry_from(base)
                else:
                    # Package changed but not expired: calculate from activation_date
                    base = tag.activation_date.replace(tzinfo=None)
                    candidate = pkg.expiry_from(base)
                    if candidate <= datetime.utcnow():
                        base = datetime.utcnow()
                    tag.expiry_date = pkg.expiry_from(base)

    db.commit()
    db.refresh(tag)
    owner = db.query(User).filter(User.id == tag.user_id).first()
    return _build_tag_out(tag, owner.email if owner else "", db)


@router.delete("/tags", status_code=204)
def delete_tags(data: PortalTagDelete, request: Request, db: Session = Depends(get_db)):
    """Permanently delete one or more devices of the group that the user may see."""
    me = get_portal_user_from_request(request, db)
    _require(me, db, "vehicles.delete")
    group = db.query(UserGroup).filter(UserGroup.id == me.usergroup_id).first()
    if not group:
        raise HTTPException(status_code=404, detail="User group not found")
    all_owner_ids = _get_group_owner_ids(group, db)
    from app.services import access_service
    access = access_service.for_user(me, db)

    deleted_count = 0
    for tag_id in data.tag_ids:
        try:
            UUID(str(tag_id))
        except ValueError:
            continue
        tag = (
            db.query(BLETag)
            .filter(BLETag.id == tag_id, _group_tag_scope_filter(group, all_owner_ids))
            .first()
        )
        if tag and access.can_see(db, tag.imei):
            try:
                _delete_tag_with_cleanup(db, tag, logger_prefix=f"BULK DELETE [{deleted_count+1}/{len(data.tag_ids)}]")
                deleted_count += 1
            except Exception as exc:
                logger.error(f"Failed to delete tag {tag_id}: {exc}")
                db.rollback()
                raise HTTPException(status_code=500, detail=f"Failed to delete tag {tag_id}: {str(exc)}")

    db.commit()
    logger.info(f"Bulk delete completed: {deleted_count}/{len(data.tag_ids)} tags deleted successfully")


@router.delete("/tags/{tag_id}", status_code=204)
def delete_tag_single(tag_id: str, request: Request, db: Session = Depends(get_db)):
    """Permanently delete a single BLE tag by its ID (group admin only)."""
    me = get_portal_user_from_request(request, db)
    _require(me, db, "vehicles.delete")
    group = db.query(UserGroup).filter(UserGroup.id == me.usergroup_id).first()
    if not group:
        raise HTTPException(status_code=404, detail="User group not found")
    all_owner_ids = _get_group_owner_ids(group, db)
    try:
        UUID(str(tag_id))
    except ValueError:
        raise HTTPException(status_code=404, detail="Tag not found in your group")

    tag = (
        db.query(BLETag)
        .filter(BLETag.id == tag_id, _group_tag_scope_filter(group, all_owner_ids))
        .first()
    )
    from app.services import access_service
    if not tag or not access_service.for_user(me, db).can_see(db, tag.imei):
        raise HTTPException(status_code=404, detail="Tag not found in your group")

    try:
        _delete_tag_with_cleanup(db, tag, logger_prefix="SINGLE DELETE")
        db.commit()
    except Exception as exc:
        db.rollback()
        logger.error(f"Failed to delete tag {tag_id}: {exc}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Failed to delete tag: {str(exc)}")


# ---------------------------------------------------------------------------
# Tag Categories — group-scoped user-defined categories
# ---------------------------------------------------------------------------

class CategoryOut(BaseModel):
    id: UUID
    name: str
    icon: Optional[str] = None
    color: Optional[str] = None
    is_active: bool
    security_group_id: Optional[UUID] = None

    class Config:
        from_attributes = True


class CategoryCreate(BaseModel):
    name: str
    icon: Optional[str] = None
    color: Optional[str] = None
    security_group_id: Optional[UUID] = None   # required (vehicle groups belong to a security group)


class CategoryUpdate(BaseModel):
    name: Optional[str] = None
    icon: Optional[str] = None
    color: Optional[str] = None
    is_active: Optional[bool] = None
    security_group_id: Optional[UUID] = None


def _check_security_group(db: Session, usergroup_id, security_group_id):
    from app.models import SecurityGroup
    if security_group_id is None or not db.query(SecurityGroup).filter(
            SecurityGroup.id == security_group_id, SecurityGroup.usergroup_id == usergroup_id).first():
        raise HTTPException(status_code=400, detail="Choose the security group this vehicle group belongs to")


@router.get("/categories", response_model=List[CategoryOut])
def list_categories(request: Request, db: Session = Depends(get_db)):
    """Return all active categories for the caller's user-group."""
    me = get_portal_user_from_request(request, db)
    from app.services import access_service
    visible = access_service.for_user(me, db).visible_categories(db)
    cats = (
        db.query(TagCategory)
        .filter(TagCategory.usergroup_id == str(me.usergroup_id), TagCategory.is_active == True)
        .order_by(TagCategory.name)
        .all()
    )
    return cats if visible is None else [c for c in cats if c.name in visible]


@router.post("/categories", response_model=CategoryOut, status_code=201)
def create_category(data: CategoryCreate, request: Request, db: Session = Depends(get_db)):
    """Create a new category (group admin only)."""
    me = get_portal_user_from_request(request, db)
    _require(me, db, "vehicle_groups.manage")
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
    _check_security_group(db, me.usergroup_id, data.security_group_id)
    cat = TagCategory(
        usergroup_id=str(me.usergroup_id),
        name=name,
        icon=data.icon,
        color=data.color,
        security_group_id=data.security_group_id,
    )
    db.add(cat)
    db.commit()
    db.refresh(cat)
    return cat


@router.put("/categories/{cat_id}", response_model=CategoryOut)
def update_category(cat_id: str, data: CategoryUpdate, request: Request, db: Session = Depends(get_db)):
    """Rename or deactivate a category (group admin only)."""
    me = get_portal_user_from_request(request, db)
    _require(me, db, "vehicle_groups.manage")
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
    if data.security_group_id is not None:
        _check_security_group(db, me.usergroup_id, data.security_group_id)
        cat.security_group_id = data.security_group_id
    db.commit()
    db.refresh(cat)
    return cat


@router.delete("/categories/{cat_id}", status_code=204)
def delete_category(cat_id: str, request: Request, db: Session = Depends(get_db)):
    """Soft-delete a category by marking it inactive (group admin only)."""
    me = get_portal_user_from_request(request, db)
    _require(me, db, "vehicle_groups.manage")
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

    Scoped to the group's devices. Returns newest-first, capped at 1000 rows.
    """
    me = get_portal_user_from_request(request, db)
    group = db.query(UserGroup).filter(UserGroup.id == me.usergroup_id).first()
    if not group:
        return []

    all_owner_ids = _get_group_owner_ids(group, db)
    since = datetime.utcnow() - timedelta(days=max(1, min(days, 365)))

    q = (
        db.query(GeofenceAlert)
        .join(BLETag, BLETag.id == GeofenceAlert.tracker_id)
        .join(POI, POI.id == GeofenceAlert.poi_id)
        .filter(
            _group_tag_scope_filter(group, all_owner_ids),
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

def _scope_alerts(q, db: Session, me: PortalUser):
    """Limit an alert query to alerts about vehicles the user may see (plus group-wide alerts)."""
    from app.services import access_service
    visible = access_service.for_user(me, db).visible_imeis(db)
    if visible is None:
        return q
    tag_ids = [tid for (tid,) in db.query(BLETag.id).filter(BLETag.imei.in_(list(visible)))] if visible else []
    return q.filter(or_(PortalAlert.tag_id.is_(None), PortalAlert.tag_id.in_(tag_ids)))


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
        _scope_alerts(db.query(PortalAlert), db, me)
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
        _scope_alerts(db.query(PortalAlert), db, me)
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
        "place_group_id": str(poi.place_group_id) if poi.place_group_id else None,
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
            headers={"User-Agent": "ViSight-Track/1.0 (portal)"},
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
    place_group_id: Optional[UUID] = None


@router.post("/locations", status_code=201)
async def create_location(data: LocationCreate, request: Request, db: Session = Depends(get_db)):
    me = get_portal_user_from_request(request, db)
    if not _user_can_manage(me, "locations"):
        raise HTTPException(status_code=403, detail="You don't have permission to manage geofences")

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
    poi.place_group_id = _check_place_group(db, me.usergroup_id, data.place_group_id)
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
    place_group_id: Optional[str] = None    # "" clears


def _check_place_group(db: Session, usergroup_id, place_group_id):
    """The place group id if it belongs to the user group (None for none)."""
    from app.models import PlaceGroup
    if not place_group_id:
        return None
    try:
        UUID(str(place_group_id))
    except ValueError:
        raise HTTPException(status_code=400, detail="Unknown place group")
    if not db.query(PlaceGroup).filter(PlaceGroup.id == str(place_group_id), PlaceGroup.usergroup_id == usergroup_id).first():
        raise HTTPException(status_code=400, detail="Unknown place group")
    return place_group_id


@router.put("/locations/{location_id}")
def update_location(
    location_id: str, data: LocationUpdate,
    request: Request, db: Session = Depends(get_db),
):
    me = get_portal_user_from_request(request, db)
    if not _user_can_manage(me, "locations"):
        raise HTTPException(status_code=403, detail="You don't have permission to manage geofences")
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
    if data.place_group_id is not None:
        poi.place_group_id = _check_place_group(db, me.usergroup_id, data.place_group_id)
    db.commit()
    db.refresh(poi)
    return _poi_dict(poi, db, str(me.usergroup_id))


# ── Delete a location ────────────────────────────────────────────────────────

@router.delete("/locations/{location_id}")
def delete_location(
    location_id: str, request: Request, db: Session = Depends(get_db),
):
    me = get_portal_user_from_request(request, db)
    if not _user_can_manage(me, "locations"):
        raise HTTPException(status_code=403, detail="You don't have permission to manage geofences")
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
    _require(me, db, "places.arm")
    poi = _get_group_poi(location_id, str(me.usergroup_id), db)
    # Verify tag belongs to this group and is visible to the user
    tag = _resolve_group_tag(tag_id, str(me.usergroup_id), db)
    from app.services import access_service
    if not access_service.for_user(me, db).can_see(db, tag.imei):
        raise HTTPException(status_code=404, detail="Tag not found")
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
    _require(me, db, "places.arm")
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


class BulkUploadRow(BaseModel):
    name: str
    address: Optional[str] = None
    lat: Optional[float] = None
    lng: Optional[float] = None
    radius: Optional[float] = 150.0


class BulkUploadRequest(BaseModel):
    rows: List[BulkUploadRow]


@router.post("/locations/bulk-upload")
async def bulk_upload_locations(
    payload: BulkUploadRequest,
    request: Request,
    db: Session = Depends(get_db),
):
    """
    Bulk-create geofences from rows already validated client-side.

    Each row needs `name` plus EITHER (lat, lng) OR `address`. Address-only
    rows are geocoded server-side via Nominatim (1 req/s). Every created
    POI is an active circle — type/status are no longer per-row options.
    """
    me = get_portal_user_from_request(request, db)
    if not _user_can_manage(me, "locations"):
        raise HTTPException(status_code=403, detail="You don't have permission to manage geofences")

    if not payload.rows:
        raise HTTPException(status_code=422, detail="No rows to import")

    import asyncio as _asyncio

    results = {"created": [], "failed": []}

    for i, row in enumerate(payload.rows, start=1):
        name = (row.name or "").strip()
        if not name:
            results["failed"].append({"row": i, "reason": "Name is required"})
            continue

        try:
            radius = max(50.0, min(float(row.radius or 150.0), 50000.0))
        except (TypeError, ValueError):
            radius = 150.0

        lat = row.lat
        lng = row.lng
        address = (row.address or "").strip() or None
        display_addr = address

        # If no coords, geocode the address (rate-limited).
        if (lat is None or lng is None) and address:
            try:
                geo = await _geocode_postcode(address)
                lat, lng = geo["lat"], geo["lon"]
                display_addr = geo.get("display") or address
            except HTTPException as exc:
                results["failed"].append({"row": i, "name": name, "address": address, "reason": exc.detail})
                await _asyncio.sleep(1.1)
                continue
            await _asyncio.sleep(1.1)

        if lat is None or lng is None:
            results["failed"].append({"row": i, "name": name, "reason": "Missing coordinates and address"})
            continue

        try:
            poi = POI(
                usergroup_id=str(me.usergroup_id),
                user_id=None,
                name=name,
                description=None,
                poi_type="single",
                latitude=lat,
                longitude=lng,
                radius=radius,
                address=display_addr,
                is_active=True,
            )
            if hasattr(poi, "shape_type"):
                poi.shape_type = "circle"
            db.add(poi)
            db.flush()
            results["created"].append({"row": i, "name": name, "id": str(poi.id)})
        except Exception as exc:
            db.rollback()
            results["failed"].append({"row": i, "name": name, "reason": str(exc)})

    db.commit()
    return {
        "total":   len(payload.rows),
        "created": len(results["created"]),
        "failed":  len(results["failed"]),
        "details": results,
    }


def _resolve_group_tag(tag_id: str, usergroup_id: str, db: Session) -> BLETag:
    """Return a BLETag that belongs to the given group, or raise 404."""
    group = db.query(UserGroup).filter(UserGroup.id == usergroup_id).first()
    if not group:
        raise HTTPException(status_code=404, detail="Group not found")
    try:
        UUID(str(tag_id))
    except ValueError:
        raise HTTPException(status_code=404, detail="Tag not found")
    tag = db.query(BLETag).filter(BLETag.id == tag_id).first()
    if not tag:
        raise HTTPException(status_code=404, detail="Tag not found")
    # Devices created for the group (e.g. routed from a Data Exchange) carry the group id
    if (tag.attributes or {}).get("_created_usergroup_id") == str(group.id):
        return tag
    # Otherwise the tag's owning mobile-app user must be linked to this group
    if not tag.user_id or str(tag.user_id) not in _get_group_owner_ids(group, db):
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
    credential_user = db.query(User).filter(User.id == user.mobile_user_id).first() if user.mobile_user_id else None
    if credential_user:
        credential_user.hashed_password = get_password_hash(data.new_password)
    else:
        user.hashed_password = hash_password(data.new_password)
    db.commit()
    del _portal_reset_pins[email]
    return {"detail": "Password reset successfully"}


# ==============================================================================
# TRIP ENGINE CONFIGURATION (Phase 4.1)
# ==============================================================================



# ==============================================================================
# POSITION HISTORY (device_positions)
# ==============================================================================

class PositionResponse(BaseModel):
    """Position response model."""
    id: int
    device_imei: str
    observed_at: datetime
    latitude: float
    longitude: float
    speed_kmh: Optional[float]
    heading: Optional[float]
    ignition: Optional[bool]
    source: str
    created_at: datetime
    # Trip engine linkage (Section 3.4)
    # Reverse geocoding (Section 3.6)
    address: Optional[str] = None


class PositionListResponse(BaseModel):
    """Paginated position list."""
    positions: List[PositionResponse]
    total: int
    page: int
    page_size: int
    has_more: bool


@router.get("/positions", response_model=PositionListResponse)
def list_positions(
    request: Request,
    device_imei: str = Query(..., description="Device IMEI"),
    start_date: Optional[str] = Query(None, description="Start date (YYYY-MM-DD)"),
    end_date: Optional[str] = Query(None, description="End date (YYYY-MM-DD)"),
    page: int = Query(1, ge=1, description="Page number (1-indexed)"),
    page_size: int = Query(200, ge=1, le=1000, description="Items per page"),
    db: Session = Depends(get_db),
):
    """
    List raw GPS positions for a device with optional date filtering.
    
    🔒 REQUIRES AUTHENTICATION - User must be logged in to view position data.
    
    Returns paginated list of positions ordered by observed_at DESC.
    Used for timeline view and raw data inspection.
    """
    # SECURITY: Require authentication before returning any position data
    me = get_portal_user_from_request(request, db)
    
    from app.models import DevicePosition
    
    # Build query
    query = db.query(DevicePosition).filter(DevicePosition.device_imei == device_imei)
    
    # Date filtering
    if start_date:
        try:
            start_dt = datetime.fromisoformat(start_date).replace(hour=0, minute=0, second=0, microsecond=0)
            query = query.filter(DevicePosition.observed_at >= start_dt)
        except ValueError:
            raise HTTPException(status_code=400, detail="Invalid start_date format (use YYYY-MM-DD)")
    
    if end_date:
        try:
            end_dt = datetime.fromisoformat(end_date).replace(hour=23, minute=59, second=59, microsecond=999999)
            query = query.filter(DevicePosition.observed_at <= end_dt)
        except ValueError:
            raise HTTPException(status_code=400, detail="Invalid end_date format (use YYYY-MM-DD)")
    
    # Count total
    total = query.count()
    
    # Pagination
    offset = (page - 1) * page_size
    positions = query.order_by(DevicePosition.observed_at.desc()).offset(offset).limit(page_size).all()
    
    # Convert to response models
    position_responses = [
        PositionResponse(
            id=p.id,
            device_imei=p.device_imei,
            observed_at=p.observed_at,
            latitude=p.lat,
            longitude=p.lng,
            speed_kmh=p.gps_speed,
            heading=p.direction,
            ignition=(p.ignition == "ON") if p.ignition else None,
            source=p.source,
            created_at=p.created_at,
            address=p.address,
        )
        for p in positions
    ]
    
    return PositionListResponse(
        positions=position_responses,
        total=total,
        page=page,
        page_size=page_size,
        has_more=(offset + len(positions)) < total,
    )


# ==============================================================================
# TRIP ENGINE API - DEVICE ENDPOINTS (Phase 6.3)
# ==============================================================================


# ==============================================================================


# ==============================================================================
# TRIPS (built by app/services/trip_builder.py from Teltonika events)
# ==============================================================================

def _trip_out(trip, names: dict, drivers: Optional[dict] = None) -> dict:
    return {
        "id": str(trip.id), "imei": trip.imei, "device_name": names.get(trip.imei),
        "driver": (drivers or {}).get(trip.imei),
        "start_address": trip.start_address or None, "end_address": trip.end_address or None,
        "status": trip.status, "start_reason": trip.start_reason, "close_reason": trip.close_reason,
        "started_at": trip.started_at, "ended_at": trip.ended_at, "last_event_at": trip.last_event_at,
        "start": [trip.start_latitude, trip.start_longitude] if trip.start_latitude is not None else None,
        "end": [trip.end_latitude, trip.end_longitude] if trip.end_latitude is not None else None,
        "distance_m": trip.distance_m, "duration_s": trip.duration_s,
        "max_speed": trip.max_speed, "avg_speed": trip.avg_speed, "point_count": trip.point_count,
        "speeding_count": trip.speeding_count, "harsh_acceleration_count": trip.harsh_acceleration_count,
        "harsh_braking_count": trip.harsh_braking_count, "harsh_cornering_count": trip.harsh_cornering_count,
        "idling_count": trip.idling_count,
    }


def _group_drivers(db: Session, group_id) -> dict:
    """{imei: driver name} from the vehicles' details."""
    tags = db.query(BLETag.imei, BLETag.attributes).filter(
        BLETag.attributes.op("->>")("_created_usergroup_id") == str(group_id)).all()
    return {imei: ((a or {}).get("driver") or {}).get("value") for imei, a in tags if ((a or {}).get("driver") or {}).get("value")}


def _group_device_names(db: Session, group_id) -> dict:
    tags = db.query(BLETag.imei, BLETag.description, BLETag.device_name).filter(
        BLETag.attributes.op("->>")("_created_usergroup_id") == str(group_id)).all()
    return {imei: (desc or name or imei) for imei, desc, name in tags}


@router.get("/trips")
def list_trips(request: Request, db: Session = Depends(get_db),
               imei: Optional[str] = None, date_from: Optional[datetime] = None,
               date_to: Optional[datetime] = None, limit: int = Query(200, ge=1, le=1000)):
    """Trips for this group's devices, newest first."""
    from app.models_dataprofiler import Trip

    from app.services import access_service

    me = get_portal_user_from_request(request, db)
    access = access_service.for_user(me, db)
    access.require("history.view")
    q = db.query(Trip).filter(Trip.usergroup_id == me.usergroup_id)
    visible = access.visible_imeis(db)
    if visible is not None:
        q = q.filter(Trip.imei.in_(list(visible)))
    if imei:
        q = q.filter(Trip.imei == imei.strip())
    if date_from:
        q = q.filter(Trip.started_at >= date_from)
    if date_to:
        q = q.filter(Trip.started_at < date_to)
    trips = q.order_by(Trip.started_at.desc()).limit(limit).all()
    names = _group_device_names(db, me.usergroup_id)
    drivers = _group_drivers(db, me.usergroup_id)
    return [_trip_out(t, names, drivers) for t in trips]


@router.get("/trips/{trip_id}")
def get_trip(trip_id: str, request: Request, db: Session = Depends(get_db)):
    """One trip with its route points and events (alerts, ignition, start/end)."""
    from app.dataprofiler.dictionary import EVENTS, describe_io, event_label
    from app.models_dataprofiler import DeviceEvent, Trip

    me = get_portal_user_from_request(request, db)
    try:
        UUID(trip_id)
    except ValueError:
        raise HTTPException(status_code=404, detail="Trip not found")
    trip = db.query(Trip).filter(Trip.id == trip_id, Trip.usergroup_id == me.usergroup_id).first()
    from app.services import access_service
    access = access_service.for_user(me, db)
    access.require("history.view")
    if not trip or not access.can_see(db, trip.imei):
        raise HTTPException(status_code=404, detail="Trip not found")
    events = (db.query(DeviceEvent).filter(DeviceEvent.trip_id == trip.id)
              .order_by(DeviceEvent.recorded_at, DeviceEvent.id).all())
    points = [[e.latitude, e.longitude, e.speed, e.recorded_at.isoformat()]
              for e in events if e.latitude is not None and e.longitude is not None]
    marked = [{
        "id": e.id, "code": e.event_type, "label": event_label(e.event_type, e.event_io_id),
        "kind": EVENTS[e.event_type][2] if e.event_type in EVENTS else "info",
        "recorded_at": e.recorded_at, "latitude": e.latitude, "longitude": e.longitude, "speed": e.speed,
        "io": describe_io(e.io or {}),
    } for e in events if e.event_type not in ("position", "parked_position")]
    out = _trip_out(trip, _group_device_names(db, me.usergroup_id))
    out.update(points=points, events=marked)
    return out
