"""
Admin API endpoints: authentication, logging, billing, user management
"""
from fastapi import APIRouter, Depends, HTTPException, status, Request, Query
from sqlalchemy.orm import Session
from datetime import datetime, timedelta
from typing import List, Optional, Dict
from uuid import UUID
from pydantic import BaseModel, EmailStr, field_validator
import logging

from app.database import get_db
from app.models_admin import AdminUser, AppLog, AuditLog, BillingData, BillingTransaction
from app.models import AppFeatures, UserGroup, UserGroupPackage, PortalUser, Building, Floor, IndoorGateway, Room
from app.admin_auth import (
    hash_password, verify_password, create_admin_access_token,
    decode_admin_token, check_role_permission
)

router = APIRouter(prefix="/api/admin", tags=["admin"])
logger = logging.getLogger(__name__)


# Pydantic Models
class AdminLogin(BaseModel):
    username: str
    password: str


class AdminCreate(BaseModel):
    username: str
    email: EmailStr
    password: str
    full_name: Optional[str] = None
    role: str = "viewer"


class AdminResponse(BaseModel):
    id: str
    username: str
    email: str
    full_name: Optional[str]
    role: str
    is_active: bool
    last_login: Optional[datetime]
    created_at: datetime

    @field_validator('id', mode='before')
    @classmethod
    def coerce_uuid_to_str(cls, v):
        return str(v) if v is not None else v

    class Config:
        from_attributes = True


class AdminToken(BaseModel):
    access_token: str
    token_type: str = "bearer"
    admin: AdminResponse


class AppLogRequest(BaseModel):
    level: str  # DEBUG, INFO, WARNING, ERROR
    category: str  # auth, location, api, ui, device
    message: str
    context: Optional[Dict] = None
    stack_trace: Optional[str] = None
    source: Optional[str] = None


class AppLogResponse(BaseModel):
    id: str
    user_id: Optional[str]
    admin_user_id: str
    level: str
    category: str
    message: str
    context: Optional[Dict]
    stack_trace: Optional[str]
    source: Optional[str]
    ip_address: Optional[str]
    created_at: datetime

    @field_validator('id', 'admin_user_id', mode='before')
    @classmethod
    def coerce_uuid_to_str(cls, v):
        return str(v) if v is not None else v

    class Config:
        from_attributes = True


class BillingDataResponse(BaseModel):
    date: datetime
    total_users: int
    active_users: int
    total_imeis: int
    active_devices_by_user: Optional[Dict]
    imei_to_user: Optional[Dict]
    user_device_count: Optional[Dict]

    class Config:
        from_attributes = True


# Helper function to get admin from token
def get_admin_from_request(request: Request, db: Session) -> AdminUser:
    """Extract and validate admin from request header"""
    auth_header = request.headers.get("Authorization", "")
    if not auth_header.startswith("Bearer "):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing or invalid authorization header"
        )
    
    token = auth_header[7:]  # Remove "Bearer "
    payload = decode_admin_token(token)
    if not payload:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired token"
        )
    
    admin = db.query(AdminUser).filter(AdminUser.id == payload["admin_id"]).first()
    if not admin or not admin.is_active:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Admin user not found or inactive"
        )
    
    return admin


def log_audit(
    db: Session,
    admin_user_id: str,
    action: str,
    resource_type: str,
    resource_id: Optional[str] = None,
    old_value: Optional[Dict] = None,
    new_value: Optional[Dict] = None,
    description: Optional[str] = None,
    ip_address: Optional[str] = None
):
    """Create audit log entry"""
    audit = AuditLog(
        admin_user_id=admin_user_id,
        action=action,
        resource_type=resource_type,
        resource_id=resource_id,
        old_value=old_value,
        new_value=new_value,
        description=description,
        ip_address=ip_address,
        created_at=datetime.utcnow()
    )
    db.add(audit)
    db.commit()


# AUTHENTICATION ENDPOINTS
@router.post("/login", response_model=AdminToken)
async def admin_login(credentials: AdminLogin, request: Request, db: Session = Depends(get_db)):
    """Admin login endpoint"""
    admin = db.query(AdminUser).filter(AdminUser.username == credentials.username).first()
    
    if not admin or not verify_password(admin.hashed_password, credentials.password):
        logger.warning(f"Failed login attempt for username: {credentials.username}")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid username or password"
        )
    
    if not admin.is_active:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Admin account is inactive"
        )
    
    # Update last login
    admin.last_login = datetime.utcnow()
    db.commit()
    
    # Create token
    token = create_admin_access_token(str(admin.id), admin.username, admin.role)
    
    # Log audit
    log_audit(
        db,
        str(admin.id),
        "login",
        "AdminUser",
        str(admin.id),
        description=f"Admin login successful",
        ip_address=request.client.host if request.client else None
    )
    
    # Convert UUID to string for response
    admin_data = {
        "id": str(admin.id),
        "username": admin.username,
        "email": admin.email,
        "full_name": admin.full_name,
        "role": admin.role,
        "is_active": admin.is_active,
        "last_login": admin.last_login,
        "created_at": admin.created_at
    }
    
    return {
        "access_token": token,
        "token_type": "bearer",
        "admin": admin_data
    }


@router.post("/logout")
async def admin_logout(request: Request, db: Session = Depends(get_db)):
    """Admin logout endpoint (token invalidation happens client-side)"""
    admin = get_admin_from_request(request, db)
    
    log_audit(
        db,
        str(admin.id),
        "logout",
        "AdminUser",
        str(admin.id),
        ip_address=request.client.host if request.client else None
    )
    
    return {"message": "Logged out successfully"}


# ADMIN USER MANAGEMENT
@router.post("/users", response_model=AdminResponse)
async def create_admin_user(
    user_data: AdminCreate,
    request: Request,
    db: Session = Depends(get_db)
):
    """Create new admin user (admin only)"""
    admin = get_admin_from_request(request, db)
    
    if not check_role_permission(admin.role, "admin"):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only admins can create new admin users"
        )
    
    # Check if username exists
    if db.query(AdminUser).filter(AdminUser.username == user_data.username).first():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Username already exists"
        )
    
    # Check if email exists
    if db.query(AdminUser).filter(AdminUser.email == user_data.email).first():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Email already exists"
        )
    
    # Create new admin
    new_admin = AdminUser(
        username=user_data.username,
        email=user_data.email,
        full_name=user_data.full_name,
        hashed_password=hash_password(user_data.password),
        role=user_data.role,
        is_active=True,
        created_at=datetime.utcnow()
    )
    
    db.add(new_admin)
    db.commit()
    db.refresh(new_admin)
    
    # Audit log
    log_audit(
        db,
        str(admin.id),
        "create_admin",
        "AdminUser",
        str(new_admin.id),
        new_value={"username": user_data.username, "email": user_data.email, "role": user_data.role},
        description=f"Created new admin user: {user_data.username}",
        ip_address=request.client.host if request.client else None
    )
    
    return new_admin


@router.get("/users", response_model=List[AdminResponse])
async def list_admin_users(request: Request, db: Session = Depends(get_db)):
    """List all admin users (admin only)"""
    admin = get_admin_from_request(request, db)
    
    if not check_role_permission(admin.role, "admin"):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only admins can view user list"
        )
    
    users = db.query(AdminUser).all()
    return users


@router.get("/me", response_model=AdminResponse)
async def get_current_admin(request: Request, db: Session = Depends(get_db)):
    """Get current admin user info"""
    admin = get_admin_from_request(request, db)
    return admin


@router.put("/users/{admin_id}", response_model=AdminResponse)
async def update_admin_user(
    admin_id: str,
    updates: Dict,
    request: Request,
    db: Session = Depends(get_db)
):
    """Update admin user (admin only)"""
    current_admin = get_admin_from_request(request, db)
    
    if not check_role_permission(current_admin.role, "admin"):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only admins can update users"
        )
    
    admin = db.query(AdminUser).filter(AdminUser.id == admin_id).first()
    if not admin:
        raise HTTPException(status_code=404, detail="Admin user not found")
    
    # Store old values for audit
    old_values = {
        "role": admin.role,
        "is_active": admin.is_active,
        "full_name": admin.full_name
    }
    
    # Update allowed fields
    if "role" in updates and updates["role"] in ["viewer", "manager", "admin"]:
        admin.role = updates["role"]
    if "is_active" in updates:
        admin.is_active = updates["is_active"]
    if "full_name" in updates:
        admin.full_name = updates["full_name"]
    
    admin.updated_at = datetime.utcnow()
    db.commit()
    db.refresh(admin)
    
    # Audit log
    log_audit(
        db,
        str(current_admin.id),
        "update_admin",
        "AdminUser",
        admin_id,
        old_value=old_values,
        new_value=updates,
        ip_address=request.client.host if request.client else None
    )
    
    return admin


# LOGGING ENDPOINTS
@router.post("/logs")
async def submit_app_log(log_data: AppLogRequest, request: Request, db: Session = Depends(get_db)):
    """Submit log from mobile app"""
    # Sanitize the log (remove sensitive data)
    sanitized_message = log_data.message
    sanitized_context = log_data.context or {}
    
    # Remove sensitive keys
    sensitive_keys = ["password", "token", "secret", "api_key", "credit_card"]
    for key in sensitive_keys:
        if key in sanitized_context:
            sanitized_context[key] = "***REDACTED***"
    
    # Create a system admin user for app logs (created on startup)
    system_admin = db.query(AdminUser).filter(AdminUser.username == "system").first()
    if not system_admin:
        system_admin = db.query(AdminUser).first()  # Fallback to first admin
    
    if system_admin:
        app_log = AppLog(
            user_id=log_data.context.get("user_id") if log_data.context else None,
            admin_user_id=str(system_admin.id),
            level=log_data.level,
            category=log_data.category,
            message=sanitized_message,
            context=sanitized_context,
            stack_trace=log_data.stack_trace,
            source=log_data.source,
            ip_address=request.client.host if request.client else None,
            created_at=datetime.utcnow()
        )
        db.add(app_log)
        db.commit()
    
    return {"status": "logged"}


@router.get("/logs", response_model=List[AppLogResponse])
async def get_app_logs(
    request: Request,
    db: Session = Depends(get_db),
    level: Optional[str] = Query(None),
    category: Optional[str] = Query(None),
    limit: int = Query(100, ge=1, le=1000),
    skip: int = Query(0, ge=0),
    days: int = Query(7, ge=1, le=90)
):
    """Get app logs with filters (admin only)"""
    admin = get_admin_from_request(request, db)
    
    if not check_role_permission(admin.role, "manager"):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Requires manager or admin role"
        )
    
    query = db.query(AppLog)
    
    # Filter by date
    cutoff_date = datetime.utcnow() - timedelta(days=days)
    query = query.filter(AppLog.created_at >= cutoff_date)
    
    # Filter by level
    if level:
        query = query.filter(AppLog.level == level.upper())
    
    # Filter by category
    if category:
        query = query.filter(AppLog.category == category)
    
    # Get total count
    total = query.count()
    
    # Get paginated results
    logs = query.order_by(AppLog.created_at.desc()).offset(skip).limit(limit).all()
    
    return logs


@router.delete("/logs")
async def delete_old_logs(
    request: Request,
    db: Session = Depends(get_db),
    days: int = Query(30, ge=1)
):
    """Delete logs older than X days (admin only)"""
    admin = get_admin_from_request(request, db)
    
    if not check_role_permission(admin.role, "admin"):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only admins can delete logs"
        )
    
    cutoff_date = datetime.utcnow() - timedelta(days=days)
    deleted = db.query(AppLog).filter(AppLog.created_at < cutoff_date).delete()
    db.commit()
    
    log_audit(
        db,
        str(admin.id),
        "delete_logs",
        "AppLog",
        None,
        description=f"Deleted {deleted} logs older than {days} days",
        ip_address=request.client.host if request.client else None
    )
    
    return {"deleted": deleted}


# BILLING ENDPOINTS
@router.get("/billing/summary")
async def get_billing_summary(
    request: Request,
    db: Session = Depends(get_db)
):
    """Get billing summary with user and device stats (manager only)"""
    admin = get_admin_from_request(request, db)
    
    if not check_role_permission(admin.role, "manager"):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Requires manager or admin role"
        )
    
    # Import User and BLETag models
    from app.models import User, BLETag
    
    # Get total users
    total_users = db.query(User).count()
    
    # Get active users (users with at least one BLE tag/IMEI)
    users_with_tags = db.query(User.id).join(BLETag).distinct().count()
    active_users = users_with_tags
    
    # Get total devices (IMEIs)
    total_imeis = db.query(BLETag).count()
    
    # Get active devices by user
    active_devices_by_user = {}
    user_devices = db.query(User.id, BLETag.imei).join(BLETag).all()
    
    for user_id, imei in user_devices:
        user_id_str = str(user_id) if user_id else "unknown"
        if user_id_str not in active_devices_by_user:
            active_devices_by_user[user_id_str] = []
        active_devices_by_user[user_id_str].append(imei)
    
    # Create IMEI to user mapping
    imei_to_user = {}
    for user_id, imei in user_devices:
        imei_to_user[imei] = str(user_id) if user_id else "unknown"
    
    # Get user device count
    user_device_count = {}
    for user_id, imei in user_devices:
        user_id_str = str(user_id) if user_id else "unknown"
        user_device_count[user_id_str] = user_device_count.get(user_id_str, 0) + 1
    
    return {
        "date": datetime.utcnow(),
        "total_users": total_users,
        "active_users": active_users,
        "total_imeis": total_imeis,
        "active_devices_by_user": active_devices_by_user,
        "imei_to_user": imei_to_user,
        "user_device_count": user_device_count
    }


@router.get("/billing/history")
async def get_billing_history(
    request: Request,
    db: Session = Depends(get_db),
    days: int = Query(30, ge=1, le=365),
    skip: int = Query(0, ge=0),
    limit: int = Query(30, ge=1, le=100)
):
    """Get billing history (manager only)"""
    admin = get_admin_from_request(request, db)
    
    if not check_role_permission(admin.role, "manager"):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Requires manager or admin role"
        )
    
    cutoff_date = datetime.utcnow() - timedelta(days=days)
    
    billing_data = db.query(BillingData)\
        .filter(BillingData.date >= cutoff_date)\
        .order_by(BillingData.date.desc())\
        .offset(skip)\
        .limit(limit)\
        .all()
    
    return billing_data


@router.get("/audit-logs")
async def get_audit_logs(
    request: Request,
    db: Session = Depends(get_db),
    admin_id: Optional[str] = Query(None),
    action: Optional[str] = Query(None),
    resource_type: Optional[str] = Query(None),
    limit: int = Query(100, ge=1, le=1000),
    skip: int = Query(0, ge=0),
    days: int = Query(7, ge=1, le=90)
):
    """Get audit logs (admin only)"""
    admin = get_admin_from_request(request, db)
    
    if not check_role_permission(admin.role, "admin"):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only admins can view audit logs"
        )
    
    query = db.query(AuditLog)
    
    # Filter by date
    cutoff_date = datetime.utcnow() - timedelta(days=days)
    query = query.filter(AuditLog.created_at >= cutoff_date)
    
    # Filter by admin
    if admin_id:
        query = query.filter(AuditLog.admin_user_id == admin_id)
    
    # Filter by action
    if action:
        query = query.filter(AuditLog.action == action)
    
    # Filter by resource type
    if resource_type:
        query = query.filter(AuditLog.resource_type == resource_type)
    
    logs = query.order_by(AuditLog.created_at.desc()).offset(skip).limit(limit).all()
    
    return logs


# ---------------------------------------------------------------------------
# Container logs — backend from DB, nginx from mounted log files
# ---------------------------------------------------------------------------

import os


def _tail_file(path: str, lines: int) -> list:
    """Return the last N lines of a log file, or [] if not found."""
    try:
        with open(path, 'r', errors='replace') as fh:
            all_lines = fh.readlines()
        tail = all_lines[-lines:]
        return [{"timestamp": None, "message": ln.rstrip(), "level": "INFO", "source": os.path.basename(path)}
                for ln in tail]
    except FileNotFoundError:
        return []
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Cannot read {path}: {exc}")


@router.get("/container-logs")
async def get_container_logs(
    request: Request,
    db: Session = Depends(get_db),
    source: str = Query("backend", description="backend | nginx-access | nginx-error"),
    lines: int = Query(300, ge=10, le=2000),
    search: Optional[str] = Query(None),
):
    """
    Return recent container log lines for the admin portal log viewer.

    - source=backend      → last N rows from app_logs (all categories)
    - source=nginx-access → last N lines from /var/log/nginx/access.log
    - source=nginx-error  → last N lines from /var/log/nginx/error.log
    """
    admin = get_admin_from_request(request, db)
    if not check_role_permission(admin.role, "manager"):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Requires manager role")

    if source == "nginx-access":
        result = _tail_file("/var/log/nginx/access.log", lines)
    elif source == "nginx-error":
        result = _tail_file("/var/log/nginx/error.log", lines)
    else:  # backend — return recent app_logs rows as plain log lines
        rows = (
            db.query(AppLog)
            .order_by(AppLog.created_at.desc())
            .limit(lines)
            .all()
        )
        result = [
            {
                "timestamp": row.created_at.isoformat() if row.created_at else None,
                "message": row.message,
                "level": row.level,
                "source": row.source or row.category,
            }
            for row in rows
        ]

    # Optional search filter (case-insensitive)
    if search:
        search_lower = search.lower()
        result = [r for r in result if search_lower in r["message"].lower()]

    return result


# ---------------------------------------------------------------------------
# App Feature Flags
# ---------------------------------------------------------------------------

class AppFeaturesSchema(BaseModel):
    show_map: bool
    show_journey: bool
    show_assets: bool
    show_scan: bool
    show_settings: bool
    show_solutions: bool

    class Config:
        from_attributes = True


def _get_or_create_features(db: Session) -> AppFeatures:
    row = db.query(AppFeatures).filter(AppFeatures.id == "global").first()
    if not row:
        row = AppFeatures(id="global")
        db.add(row)
        db.commit()
        db.refresh(row)
    return row


@router.get("/app-features", response_model=AppFeaturesSchema)
def get_app_features(
    request: Request,
    db: Session = Depends(get_db),
):
    """Return the global app feature flags (admin auth required)."""
    admin = get_admin_from_request(request, db)
    if not check_role_permission(admin.role, "viewer"):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Requires viewer role")
    try:
        return _get_or_create_features(db)
    except Exception as exc:
        logger.error(f"app-features GET failed: {exc}")
        db.rollback()
        # Return safe defaults so the portal stays usable even if migration hasn't run
        return AppFeaturesSchema(
            show_map=True, show_journey=True, show_assets=True,
            show_scan=True, show_settings=True, show_solutions=False,
        )


@router.put("/app-features", response_model=AppFeaturesSchema)
def update_app_features(
    data: AppFeaturesSchema,
    request: Request,
    db: Session = Depends(get_db),
):
    """Update the global app feature flags (manager or above required)."""
    admin = get_admin_from_request(request, db)
    if not check_role_permission(admin.role, "manager"):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Requires manager role")

    row = _get_or_create_features(db)
    row.show_map       = data.show_map
    row.show_journey   = data.show_journey
    row.show_assets    = data.show_assets
    row.show_scan      = data.show_scan
    row.show_settings  = data.show_settings
    row.show_solutions = data.show_solutions
    db.commit()
    db.refresh(row)
    return row


# ---------------------------------------------------------------------------
# User Groups (customer portal tenants)
# ---------------------------------------------------------------------------

import re as _re
import secrets as _secrets


class UserGroupCreate(BaseModel):
    name: str                    # e.g. "Acme Corp"
    admin_email: str             # portal admin email
    admin_first_name: str = ""
    admin_last_name: str = ""
    email_domain: Optional[str] = None   # comma-separated e.g. "acme.com,acme.co.za"
    package_id: Optional[str] = None     # default package UUID (optional)


class PortalUserOut(BaseModel):
    id: UUID
    email: str
    first_name: Optional[str]
    last_name: Optional[str]
    is_group_admin: bool
    is_active: bool

    class Config:
        from_attributes = True


class GroupPackageOut(BaseModel):
    package_id: str
    package_name: str
    validity_days: int
    is_default: bool

    class Config:
        from_attributes = True


class UserGroupOut(BaseModel):
    id: UUID
    name: str
    slug: str
    is_active: bool
    email_domain: Optional[str] = None
    default_package_id: Optional[str] = None
    default_package_name: Optional[str] = None
    allowed_sections: Optional[list] = None
    packages: List[GroupPackageOut] = []
    created_at: Optional[datetime] = None
    portal_users: List[PortalUserOut] = []

    class Config:
        from_attributes = True

    @classmethod
    def from_group(cls, g, pkg_map: dict, group_pkgs: list):
        """Build response from a UserGroup ORM object.
        pkg_map: {str(pkg_id) -> TagPackage}
        group_pkgs: list of UserGroupPackage rows for this group (any order)
        """
        # Derive default from join table (is_default=True) or fall back to legacy column
        default_pkg_id: Optional[str] = None
        default_pkg_name: Optional[str] = None
        packages_out: List[GroupPackageOut] = []
        for gp in group_pkgs:
            pkg = pkg_map.get(str(gp.package_id))
            if pkg is None:
                continue
            packages_out.append(GroupPackageOut(
                package_id=str(gp.package_id),
                package_name=pkg.name,
                validity_days=pkg.validity_days,
                is_default=gp.is_default,
            ))
            if gp.is_default:
                default_pkg_id = str(gp.package_id)
                default_pkg_name = pkg.name
        # Fall back to legacy column if join table has no default row yet
        if not default_pkg_id and g.default_package_id:
            legacy = pkg_map.get(str(g.default_package_id))
            if legacy:
                default_pkg_id = str(g.default_package_id)
                default_pkg_name = legacy.name
        return cls(
            id=g.id,
            name=g.name,
            slug=g.slug,
            is_active=g.is_active,
            email_domain=g.email_domain,
            default_package_id=default_pkg_id,
            default_package_name=default_pkg_name,
            allowed_sections=g.allowed_sections,
            packages=packages_out,
            created_at=g.created_at,
            portal_users=g.portal_users,
        )


class UserGroupCreateResponse(BaseModel):
    usergroup: UserGroupOut
    temp_password: str   # shown once — admin should change it


def _slugify(text: str) -> str:
    s = text.lower().strip()
    s = _re.sub(r'[^a-z0-9]+', '-', s)
    return s.strip('-')[:80]


@router.post("/usergroups", response_model=UserGroupCreateResponse)
def create_usergroup(
    data: UserGroupCreate,
    request: Request,
    db: Session = Depends(get_db),
):
    """Create a new UserGroup and its initial portal admin user (manager+)."""
    admin = get_admin_from_request(request, db)
    if not check_role_permission(admin.role, "manager"):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Requires manager role")

    # Ensure name is unique
    if db.query(UserGroup).filter(UserGroup.name == data.name).first():
        raise HTTPException(status_code=400, detail="A user group with that name already exists")

    # Ensure portal admin email is unique
    from app.models import PortalUser as PU
    if db.query(PU).filter(PU.email == data.admin_email.lower().strip()).first():
        raise HTTPException(status_code=400, detail="A portal user with that email already exists")

    # Build a unique slug
    base_slug = _slugify(data.name)
    slug = base_slug
    counter = 1
    while db.query(UserGroup).filter(UserGroup.slug == slug).first():
        slug = f"{base_slug}-{counter}"
        counter += 1

    # Normalise email_domain (strip spaces, lowercase, remove leading @)
    domain_value = None
    if data.email_domain:
        raw_domains = [d.strip().lower().lstrip("@") for d in data.email_domain.split(",") if d.strip()]
        domain_value = ",".join(raw_domains) if raw_domains else None

    # Create group
    import uuid as _uuid
    group = UserGroup(
        id=str(_uuid.uuid4()),
        name=data.name,
        slug=slug,
        is_active=True,
        email_domain=domain_value,
    )
    db.add(group)
    db.flush()   # get group.id without committing

    # Generate a random temporary password
    temp_password = _secrets.token_urlsafe(12)

    # Create portal admin user
    portal_admin = PU(
        id=str(_uuid.uuid4()),
        usergroup_id=group.id,
        email=data.admin_email.lower().strip(),
        hashed_password=hash_password(temp_password),
        first_name=data.admin_first_name or None,
        last_name=data.admin_last_name or None,
        is_active=True,
        is_group_admin=True,
    )
    db.add(portal_admin)

    # Optionally link a default package
    if data.package_id:
        pkg = db.query(_TagPackage).filter(
            _TagPackage.id == data.package_id,
            _TagPackage.is_active == True,
        ).first()
        if pkg:
            gp = UserGroupPackage(
                usergroup_id=group.id,
                package_id=pkg.id,
                is_default=True,
            )
            db.add(gp)

    db.commit()

    # Re-query with relationships loaded so Pydantic serialization doesn't
    # trigger a lazy-load on an expired object
    from sqlalchemy.orm import selectinload as _selectinload
    group = (
        db.query(UserGroup)
        .options(_selectinload(UserGroup.portal_users))
        .filter(UserGroup.id == group.id)
        .first()
    )

    return UserGroupCreateResponse(
        usergroup=UserGroupOut.model_validate(group),
        temp_password=temp_password,
    )


@router.get("/usergroups", response_model=List[UserGroupOut])
def list_usergroups(
    request: Request,
    db: Session = Depends(get_db),
):
    """List all UserGroups with their portal users (viewer+)."""
    admin = get_admin_from_request(request, db)
    if not check_role_permission(admin.role, "viewer"):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Requires viewer role")
    from sqlalchemy.orm import selectinload as _selectinload
    groups = (
        db.query(UserGroup)
        .options(_selectinload(UserGroup.portal_users))
        .order_by(UserGroup.created_at.desc())
        .all()
    )
    # Collect all package IDs referenced by either join table or legacy column
    group_ids = [str(g.id) for g in groups]
    all_gps = (
        db.query(UserGroupPackage)
        .filter(UserGroupPackage.usergroup_id.in_(group_ids))
        .all()
    ) if group_ids else []
    pkg_ids = {str(gp.package_id) for gp in all_gps}
    pkg_ids |= {str(g.default_package_id) for g in groups if g.default_package_id}
    pkg_map = {}
    if pkg_ids:
        for p in db.query(_TagPackage).filter(_TagPackage.id.in_(pkg_ids)).all():
            pkg_map[str(p.id)] = p
    # Group join-table rows by group_id
    gps_by_group: dict = {}
    for gp in all_gps:
        gps_by_group.setdefault(str(gp.usergroup_id), []).append(gp)
    return [UserGroupOut.from_group(g, pkg_map, gps_by_group.get(str(g.id), [])) for g in groups]


@router.put("/usergroups/{group_id}/deactivate")
def deactivate_usergroup(
    group_id: str,
    request: Request,
    db: Session = Depends(get_db),
):
    """Deactivate a UserGroup and all its portal users (manager+)."""
    admin = get_admin_from_request(request, db)
    if not check_role_permission(admin.role, "manager"):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Requires manager role")
    group = db.query(UserGroup).filter(UserGroup.id == group_id).first()
    if not group:
        raise HTTPException(status_code=404, detail="User group not found")
    group.is_active = False
    for pu in group.portal_users:
        pu.is_active = False
    db.commit()
    return {"detail": "User group deactivated"}


@router.put("/usergroups/{group_id}/activate")
def activate_usergroup(
    group_id: str,
    request: Request,
    db: Session = Depends(get_db),
):
    """Re-activate a UserGroup and all its portal users (manager+)."""
    admin = get_admin_from_request(request, db)
    if not check_role_permission(admin.role, "manager"):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Requires manager role")
    group = db.query(UserGroup).filter(UserGroup.id == group_id).first()
    if not group:
        raise HTTPException(status_code=404, detail="User group not found")
    group.is_active = True
    for pu in group.portal_users:
        pu.is_active = True
    db.commit()
    return {"detail": "User group activated"}


class UserGroupUpdate(BaseModel):
    email_domain: Optional[str] = None   # empty string clears it; comma-separated for multiple domains
    allowed_sections: Optional[list] = None  # e.g. ["tracking","management","reports"] — None means no change


@router.put("/usergroups/{group_id}")
def update_usergroup(
    group_id: str,
    data: UserGroupUpdate,
    request: Request,
    db: Session = Depends(get_db),
):
    """Update UserGroup settings (manager+). Supports comma-separated email_domain for multiple domains."""
    admin = get_admin_from_request(request, db)
    if not check_role_permission(admin.role, "manager"):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Requires manager role")
    group = db.query(UserGroup).filter(UserGroup.id == group_id).first()
    if not group:
        raise HTTPException(status_code=404, detail="User group not found")
    if data.email_domain is not None:
        # Parse and normalise the comma-separated list
        raw_domains = [d.strip().lower().lstrip("@") for d in data.email_domain.split(",")]
        clean_domains = [d for d in raw_domains if d]
        domain_value = ",".join(clean_domains) or None
        # Ensure no other group claims any of these domains
        if clean_domains:
            for d in clean_domains:
                conflict = (
                    db.query(UserGroup)
                    .filter(UserGroup.email_domain.ilike(f"%{d}%"), UserGroup.id != group_id)
                    .first()
                )
                if conflict:
                    # Check exact match within comma-separated list
                    existing = [x.strip().lower() for x in (conflict.email_domain or "").split(",")]
                    if d in existing:
                        raise HTTPException(status_code=409, detail=f"Domain '{d}' is already used by another group")
        group.email_domain = domain_value

    # allowed_sections: use model_fields_set so explicit null = "reset to all"
    if "allowed_sections" in data.model_fields_set:
        secs = data.allowed_sections
        valid = {"tracking", "management", "reports"}
        if secs is not None:
            bad = [s for s in secs if s not in valid]
            if bad:
                raise HTTPException(status_code=400, detail=f"Invalid section(s): {bad}. Allowed: {list(valid)}")
            secs = secs or None   # empty list → store null (= all enabled)
        group.allowed_sections = secs

    db.commit()
    return {"id": str(group.id), "name": group.name, "email_domain": group.email_domain, "allowed_sections": group.allowed_sections}


class UserGroupPackageAssign(BaseModel):
    package_id: Optional[str] = None  # None clears the default package (legacy)


@router.put("/usergroups/{group_id}/package")
def assign_group_package(
    group_id: str,
    data: UserGroupPackageAssign,
    request: Request,
    db: Session = Depends(get_db),
):
    """Legacy single-assign kept for backward compat. Prefer the /packages sub-routes."""
    admin = get_admin_from_request(request, db)
    if not check_role_permission(admin.role, "manager"):
        raise HTTPException(status_code=403, detail="Requires manager role")
    group = db.query(UserGroup).filter(UserGroup.id == group_id).first()
    if not group:
        raise HTTPException(status_code=404, detail="User group not found")
    if data.package_id:
        pkg = db.query(_TagPackage).filter(_TagPackage.id == data.package_id, _TagPackage.is_active == True).first()
        if not pkg:
            raise HTTPException(status_code=404, detail="Package not found or inactive")
        group.default_package_id = data.package_id
        # Also upsert into join table as is_default
        _upsert_group_package(db, group_id, data.package_id, make_default=True)
    else:
        group.default_package_id = None
    db.commit()
    pkg_name = pkg.name if data.package_id else None
    return {"id": str(group.id), "default_package_id": group.default_package_id, "default_package_name": pkg_name}


def _upsert_group_package(db: Session, group_id: str, package_id: str, make_default: bool = False):
    """Add package to group's join table if not present; optionally set as default."""
    import uuid as _uuid2
    existing = db.query(UserGroupPackage).filter(
        UserGroupPackage.usergroup_id == group_id,
        UserGroupPackage.package_id == package_id,
    ).first()
    if existing:
        if make_default:
            existing.is_default = True
    else:
        db.add(UserGroupPackage(
            id=str(_uuid2.uuid4()),
            usergroup_id=group_id,
            package_id=package_id,
            is_default=make_default,
        ))


# --- Multi-package management routes ---

@router.get("/usergroups/{group_id}/packages", response_model=List[GroupPackageOut])
def list_group_packages(
    group_id: str,
    request: Request,
    db: Session = Depends(get_db),
):
    """List all packages assigned to a UserGroup (viewer+)."""
    admin = get_admin_from_request(request, db)
    if not check_role_permission(admin.role, "viewer"):
        raise HTTPException(status_code=403, detail="Requires viewer role")
    if not db.query(UserGroup).filter(UserGroup.id == group_id).first():
        raise HTTPException(status_code=404, detail="User group not found")
    rows = db.query(UserGroupPackage).filter(UserGroupPackage.usergroup_id == group_id).all()
    pkg_ids = [str(r.package_id) for r in rows]
    pkg_map = {str(p.id): p for p in db.query(_TagPackage).filter(_TagPackage.id.in_(pkg_ids)).all()} if pkg_ids else {}
    return [
        GroupPackageOut(
            package_id=str(r.package_id),
            package_name=pkg_map[str(r.package_id)].name if str(r.package_id) in pkg_map else "Unknown",
            validity_days=pkg_map[str(r.package_id)].validity_days if str(r.package_id) in pkg_map else 0,
            is_default=r.is_default,
        )
        for r in rows
    ]


@router.post("/usergroups/{group_id}/packages/{pkg_id}", response_model=GroupPackageOut)
def add_package_to_group(
    group_id: str,
    pkg_id: str,
    request: Request,
    db: Session = Depends(get_db),
):
    """Assign a package to a UserGroup (manager+). First assigned package becomes default."""
    admin = get_admin_from_request(request, db)
    if not check_role_permission(admin.role, "manager"):
        raise HTTPException(status_code=403, detail="Requires manager role")
    group = db.query(UserGroup).filter(UserGroup.id == group_id).first()
    if not group:
        raise HTTPException(status_code=404, detail="User group not found")
    pkg = db.query(_TagPackage).filter(_TagPackage.id == pkg_id, _TagPackage.is_active == True).first()
    if not pkg:
        raise HTTPException(status_code=404, detail="Package not found or inactive")
    # Check if already assigned
    existing = db.query(UserGroupPackage).filter(
        UserGroupPackage.usergroup_id == group_id,
        UserGroupPackage.package_id == pkg_id,
    ).first()
    if existing:
        raise HTTPException(status_code=409, detail="Package already assigned to this group")
    # First package auto-becomes default
    has_any = db.query(UserGroupPackage).filter(UserGroupPackage.usergroup_id == group_id).count()
    make_default = has_any == 0
    import uuid as _uuid2
    row = UserGroupPackage(
        id=str(_uuid2.uuid4()),
        usergroup_id=group_id,
        package_id=pkg_id,
        is_default=make_default,
    )
    db.add(row)
    if make_default:
        group.default_package_id = pkg_id
    db.commit()
    return GroupPackageOut(
        package_id=str(pkg.id),
        package_name=pkg.name,
        validity_days=pkg.validity_days,
        is_default=make_default,
    )


@router.delete("/usergroups/{group_id}/packages/{pkg_id}")
def remove_package_from_group(
    group_id: str,
    pkg_id: str,
    request: Request,
    db: Session = Depends(get_db),
):
    """Remove a package from a UserGroup (manager+). Cannot remove the last package."""
    admin = get_admin_from_request(request, db)
    if not check_role_permission(admin.role, "manager"):
        raise HTTPException(status_code=403, detail="Requires manager role")
    row = db.query(UserGroupPackage).filter(
        UserGroupPackage.usergroup_id == group_id,
        UserGroupPackage.package_id == pkg_id,
    ).first()
    if not row:
        raise HTTPException(status_code=404, detail="Package not assigned to this group")
    total = db.query(UserGroupPackage).filter(UserGroupPackage.usergroup_id == group_id).count()
    if total <= 1:
        raise HTTPException(status_code=400, detail="Cannot remove the only package from a group")
    was_default = row.is_default
    db.delete(row)
    db.flush()
    if was_default:
        # Auto-assign the oldest remaining package as default
        next_row = (
            db.query(UserGroupPackage)
            .filter(UserGroupPackage.usergroup_id == group_id)
            .order_by(UserGroupPackage.created_at.asc())
            .first()
        )
        if next_row:
            next_row.is_default = True
            group = db.query(UserGroup).filter(UserGroup.id == group_id).first()
            if group:
                group.default_package_id = next_row.package_id
    db.commit()
    return {"detail": "Package removed"}


@router.put("/usergroups/{group_id}/packages/{pkg_id}/set-default")
def set_group_default_package(
    group_id: str,
    pkg_id: str,
    request: Request,
    db: Session = Depends(get_db),
):
    """Mark a package as the default for a UserGroup (manager+).
    Also keeps user_groups.default_package_id in sync for bulk-import."""
    admin = get_admin_from_request(request, db)
    if not check_role_permission(admin.role, "manager"):
        raise HTTPException(status_code=403, detail="Requires manager role")
    group = db.query(UserGroup).filter(UserGroup.id == group_id).first()
    if not group:
        raise HTTPException(status_code=404, detail="User group not found")
    target = db.query(UserGroupPackage).filter(
        UserGroupPackage.usergroup_id == group_id,
        UserGroupPackage.package_id == pkg_id,
    ).first()
    if not target:
        raise HTTPException(status_code=404, detail="Package not assigned to this group")
    # Clear existing default
    db.query(UserGroupPackage).filter(
        UserGroupPackage.usergroup_id == group_id,
        UserGroupPackage.is_default == True,
    ).update({"is_default": False}, synchronize_session="fetch")
    target.is_default = True
    group.default_package_id = pkg_id
    db.commit()
    return {"detail": "Default package updated"}


# ---------------------------------------------------------------------------
# Tag Packages — admin-managed subscription packages for BLE tags
# ---------------------------------------------------------------------------

from app.models_admin import TagPackage as _TagPackage


class PackageCreate(BaseModel):
    name: str
    description: Optional[str] = None
    validity_days: int          # e.g. 80, 120, 300
    auto_delete_days: Optional[int] = None  # days after expiry to auto-delete tag
    is_default: bool = False


class PackageUpdate(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    validity_days: Optional[int] = None
    auto_delete_days: Optional[int] = None
    is_default: Optional[bool] = None
    is_active: Optional[bool] = None


class PackageOut(BaseModel):
    id: UUID
    name: str
    description: Optional[str]
    validity_days: int
    auto_delete_days: Optional[int] = None
    is_default: bool
    is_active: bool
    created_at: datetime

    @field_validator('id', mode='before')
    @classmethod
    def coerce_uuid(cls, v):
        return str(v) if v is not None else v

    class Config:
        from_attributes = True


@router.post("/packages", response_model=PackageOut, status_code=201)
def create_package(data: PackageCreate, request: Request, db: Session = Depends(get_db)):
    """Create a new tag subscription package (manager+)."""
    admin = get_admin_from_request(request, db)
    if not check_role_permission(admin.role, "manager"):
        raise HTTPException(status_code=403, detail="Requires manager role")

    if db.query(_TagPackage).filter(_TagPackage.name == data.name).first():
        raise HTTPException(status_code=409, detail="A package with that name already exists")

    if data.is_default:
        # Clear any previous default
        db.query(_TagPackage).filter(_TagPackage.is_default == True).update({"is_default": False})

    pkg = _TagPackage(
        name=data.name.strip(),
        description=data.description,
        validity_days=data.validity_days,
        auto_delete_days=data.auto_delete_days,
        is_default=data.is_default,
        is_active=True,
    )
    db.add(pkg)
    db.commit()
    db.refresh(pkg)
    log_audit(db, str(admin.id), "create_package", "TagPackage", str(pkg.id),
              new_value={"name": pkg.name, "validity_days": pkg.validity_days})
    return pkg


@router.get("/packages", response_model=List[PackageOut])
def list_packages(request: Request, db: Session = Depends(get_db)):
    """List all tag packages (viewer+)."""
    admin = get_admin_from_request(request, db)
    if not check_role_permission(admin.role, "viewer"):
        raise HTTPException(status_code=403, detail="Requires viewer role")
    return db.query(_TagPackage).order_by(_TagPackage.created_at.desc()).all()


@router.put("/packages/{pkg_id}", response_model=PackageOut)
def update_package(pkg_id: str, data: PackageUpdate, request: Request, db: Session = Depends(get_db)):
    """Update a tag package (manager+)."""
    admin = get_admin_from_request(request, db)
    if not check_role_permission(admin.role, "manager"):
        raise HTTPException(status_code=403, detail="Requires manager role")

    pkg = db.query(_TagPackage).filter(_TagPackage.id == pkg_id).first()
    if not pkg:
        raise HTTPException(status_code=404, detail="Package not found")

    if data.is_default is True:
        db.query(_TagPackage).filter(_TagPackage.id != pkg_id, _TagPackage.is_default == True).update({"is_default": False})

    for field, val in data.model_dump(exclude_unset=True).items():
        setattr(pkg, field, val)
    db.commit()
    db.refresh(pkg)
    return pkg


@router.put("/packages/{pkg_id}/set-default", response_model=PackageOut)
def set_default_package(pkg_id: str, request: Request, db: Session = Depends(get_db)):
    """Mark one package as the default for self-registered tags (manager+)."""
    admin = get_admin_from_request(request, db)
    if not check_role_permission(admin.role, "manager"):
        raise HTTPException(status_code=403, detail="Requires manager role")

    pkg = db.query(_TagPackage).filter(_TagPackage.id == pkg_id, _TagPackage.is_active == True).first()
    if not pkg:
        raise HTTPException(status_code=404, detail="Package not found or inactive")

    db.query(_TagPackage).filter(_TagPackage.id != pkg_id).update({"is_default": False})
    pkg.is_default = True
    db.commit()
    db.refresh(pkg)
    return pkg


@router.delete("/packages/{pkg_id}", status_code=204)
def deactivate_package(pkg_id: str, request: Request, db: Session = Depends(get_db)):
    """Deactivate a package so it no longer appears in dropdowns (manager+)."""
    admin = get_admin_from_request(request, db)
    if not check_role_permission(admin.role, "manager"):
        raise HTTPException(status_code=403, detail="Requires manager role")

    pkg = db.query(_TagPackage).filter(_TagPackage.id == pkg_id).first()
    if not pkg:
        raise HTTPException(status_code=404, detail="Package not found")
    pkg.is_active = False
    pkg.is_default = False
    db.commit()


# ── Buildings ────────────────────────────────────────────────────────────────

class BuildingCreate(BaseModel):
    usergroup_id: str
    name: str
    mqtt_url: Optional[str] = None
    mqtt_topic: str = "position/#"

class BuildingUpdate(BaseModel):
    name: Optional[str] = None
    mqtt_url: Optional[str] = None
    mqtt_topic: Optional[str] = None

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
    floor_plan: Optional[str]   # base64 data-URL (omit from list views for perf)
    map_w: int
    map_h: int
    gateways: List[GatewayOut] = []
    rooms: List[RoomOut] = []
    class Config: from_attributes = True

class FloorOutNoImage(BaseModel):
    id: UUID
    building_id: UUID
    label: str
    floor_order: int
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
    floors: List[FloorOutNoImage] = []
    class Config: from_attributes = True


def _str_id(obj_id) -> str:
    return str(obj_id)


@router.post("/buildings", response_model=BuildingOut)
def create_building(data: BuildingCreate, request: Request, db: Session = Depends(get_db)):
    admin = get_admin_from_request(request, db)
    if not check_role_permission(admin.role, "manager"):
        raise HTTPException(status_code=403, detail="Requires manager role")
    group = db.query(UserGroup).filter(UserGroup.id == data.usergroup_id).first()
    if not group:
        raise HTTPException(status_code=404, detail="UserGroup not found")
    bldg = Building(
        usergroup_id=data.usergroup_id,
        name=data.name,
        mqtt_url=data.mqtt_url,
        mqtt_topic=data.mqtt_topic,
    )
    db.add(bldg)
    db.commit()
    db.refresh(bldg)
    return BuildingOut.model_validate(bldg)


@router.get("/buildings", response_model=List[BuildingOut])
def list_buildings(request: Request, db: Session = Depends(get_db)):
    admin = get_admin_from_request(request, db)
    buildings = db.query(Building).order_by(Building.created_at.desc()).all()
    return [BuildingOut.model_validate(b) for b in buildings]


@router.get("/buildings/{building_id}", response_model=BuildingOut)
def get_building(building_id: str, request: Request, db: Session = Depends(get_db)):
    admin = get_admin_from_request(request, db)
    bldg = db.query(Building).filter(Building.id == building_id).first()
    if not bldg:
        raise HTTPException(status_code=404, detail="Building not found")
    return BuildingOut.model_validate(bldg)


@router.put("/buildings/{building_id}", response_model=BuildingOut)
def update_building(building_id: str, data: BuildingUpdate,
                    request: Request, db: Session = Depends(get_db)):
    admin = get_admin_from_request(request, db)
    if not check_role_permission(admin.role, "manager"):
        raise HTTPException(status_code=403, detail="Requires manager role")
    bldg = db.query(Building).filter(Building.id == building_id).first()
    if not bldg:
        raise HTTPException(status_code=404, detail="Building not found")
    if data.name is not None:       bldg.name       = data.name
    if data.mqtt_url is not None:   bldg.mqtt_url   = data.mqtt_url
    if data.mqtt_topic is not None: bldg.mqtt_topic = data.mqtt_topic
    db.commit()
    db.refresh(bldg)
    return BuildingOut.model_validate(bldg)


@router.delete("/buildings/{building_id}")
def delete_building(building_id: str, request: Request, db: Session = Depends(get_db)):
    admin = get_admin_from_request(request, db)
    if not check_role_permission(admin.role, "manager"):
        raise HTTPException(status_code=403, detail="Requires manager role")
    bldg = db.query(Building).filter(Building.id == building_id).first()
    if not bldg:
        raise HTTPException(status_code=404, detail="Building not found")
    db.delete(bldg)
    db.commit()
    return {"detail": "Building deleted"}


# ── Floors ───────────────────────────────────────────────────────────────────

class FloorCreate(BaseModel):
    label: str = "Ground Floor"
    floor_order: int = 0
    map_w: int = 800
    map_h: int = 500

class FloorUpdate(BaseModel):
    label: Optional[str] = None
    floor_order: Optional[int] = None
    floor_plan: Optional[str] = None   # base64 data-URL
    map_w: Optional[int] = None
    map_h: Optional[int] = None


@router.post("/buildings/{building_id}/floors", response_model=FloorOut)
def create_floor(building_id: str, data: FloorCreate,
                 request: Request, db: Session = Depends(get_db)):
    admin = get_admin_from_request(request, db)
    bldg = db.query(Building).filter(Building.id == building_id).first()
    if not bldg:
        raise HTTPException(status_code=404, detail="Building not found")
    floor = Floor(building_id=building_id, label=data.label,
                  floor_order=data.floor_order, map_w=data.map_w, map_h=data.map_h)
    db.add(floor)
    db.commit()
    db.refresh(floor)
    return FloorOut.model_validate(floor)


@router.get("/floors/{floor_id}", response_model=FloorOut)
def get_floor(floor_id: str, request: Request, db: Session = Depends(get_db)):
    admin = get_admin_from_request(request, db)
    floor = db.query(Floor).filter(Floor.id == floor_id).first()
    if not floor:
        raise HTTPException(status_code=404, detail="Floor not found")
    return FloorOut.model_validate(floor)


@router.put("/floors/{floor_id}", response_model=FloorOut)
def update_floor(floor_id: str, data: FloorUpdate,
                 request: Request, db: Session = Depends(get_db)):
    admin = get_admin_from_request(request, db)
    floor = db.query(Floor).filter(Floor.id == floor_id).first()
    if not floor:
        raise HTTPException(status_code=404, detail="Floor not found")
    if data.label       is not None: floor.label       = data.label
    if data.floor_order is not None: floor.floor_order = data.floor_order
    if data.floor_plan  is not None: floor.floor_plan  = data.floor_plan
    if data.map_w       is not None: floor.map_w       = data.map_w
    if data.map_h       is not None: floor.map_h       = data.map_h
    db.commit()
    db.refresh(floor)
    return FloorOut.model_validate(floor)


@router.delete("/floors/{floor_id}")
def delete_floor(floor_id: str, request: Request, db: Session = Depends(get_db)):
    admin = get_admin_from_request(request, db)
    floor = db.query(Floor).filter(Floor.id == floor_id).first()
    if not floor:
        raise HTTPException(status_code=404, detail="Floor not found")
    db.delete(floor)
    db.commit()
    return {"detail": "Floor deleted"}


# ── Gateways ─────────────────────────────────────────────────────────────────

class GatewayCreate(BaseModel):
    receiver_id: str
    label: Optional[str] = None
    x: float
    y: float

class GatewayUpdate(BaseModel):
    receiver_id: Optional[str] = None
    label: Optional[str] = None
    x: Optional[float] = None
    y: Optional[float] = None


@router.post("/floors/{floor_id}/gateways", response_model=GatewayOut)
def create_gateway(floor_id: str, data: GatewayCreate,
                   request: Request, db: Session = Depends(get_db)):
    admin = get_admin_from_request(request, db)
    floor = db.query(Floor).filter(Floor.id == floor_id).first()
    if not floor:
        raise HTTPException(status_code=404, detail="Floor not found")
    gw = IndoorGateway(
        floor_id=floor_id,
        receiver_id=data.receiver_id.lower().replace(":", ""),
        label=data.label,
        x=data.x,
        y=data.y,
    )
    db.add(gw)
    db.commit()
    db.refresh(gw)
    return GatewayOut.model_validate(gw)


@router.put("/gateways/{gateway_id}", response_model=GatewayOut)
def update_gateway(gateway_id: str, data: GatewayUpdate,
                   request: Request, db: Session = Depends(get_db)):
    admin = get_admin_from_request(request, db)
    gw = db.query(IndoorGateway).filter(IndoorGateway.id == gateway_id).first()
    if not gw:
        raise HTTPException(status_code=404, detail="Gateway not found")
    if data.receiver_id is not None: gw.receiver_id = data.receiver_id.lower().replace(":", "")
    if data.label       is not None: gw.label       = data.label
    if data.x           is not None: gw.x           = data.x
    if data.y           is not None: gw.y           = data.y
    db.commit()
    db.refresh(gw)
    return GatewayOut.model_validate(gw)


@router.delete("/gateways/{gateway_id}")
def delete_gateway(gateway_id: str, request: Request, db: Session = Depends(get_db)):
    admin = get_admin_from_request(request, db)
    gw = db.query(IndoorGateway).filter(IndoorGateway.id == gateway_id).first()
    if not gw:
        raise HTTPException(status_code=404, detail="Gateway not found")
    db.delete(gw)
    db.commit()
    return {"detail": "Gateway deleted"}


# ── Rooms ────────────────────────────────────────────────────────────────────

class RoomCreate(BaseModel):
    name: str
    x: float
    y: float
    w: float
    h: float

class RoomUpdate(BaseModel):
    name: Optional[str] = None
    x: Optional[float] = None
    y: Optional[float] = None
    w: Optional[float] = None
    h: Optional[float] = None


@router.post("/floors/{floor_id}/rooms", response_model=RoomOut)
def create_room(floor_id: str, data: RoomCreate,
                request: Request, db: Session = Depends(get_db)):
    admin = get_admin_from_request(request, db)
    floor = db.query(Floor).filter(Floor.id == floor_id).first()
    if not floor:
        raise HTTPException(status_code=404, detail="Floor not found")
    room = Room(floor_id=floor_id, name=data.name,
                x=data.x, y=data.y, w=data.w, h=data.h)
    db.add(room)
    db.commit()
    db.refresh(room)
    return RoomOut.model_validate(room)


@router.put("/rooms/{room_id}", response_model=RoomOut)
def update_room(room_id: str, data: RoomUpdate,
                request: Request, db: Session = Depends(get_db)):
    admin = get_admin_from_request(request, db)
    room = db.query(Room).filter(Room.id == room_id).first()
    if not room:
        raise HTTPException(status_code=404, detail="Room not found")
    if data.name is not None: room.name = data.name
    if data.x    is not None: room.x    = data.x
    if data.y    is not None: room.y    = data.y
    if data.w    is not None: room.w    = data.w
    if data.h    is not None: room.h    = data.h
    db.commit()
    db.refresh(room)
    return RoomOut.model_validate(room)


@router.delete("/rooms/{room_id}")
def delete_room(room_id: str, request: Request, db: Session = Depends(get_db)):
    admin = get_admin_from_request(request, db)
    room = db.query(Room).filter(Room.id == room_id).first()
    if not room:
        raise HTTPException(status_code=404, detail="Room not found")
    db.delete(room)
    db.commit()
    return {"detail": "Room deleted"}
