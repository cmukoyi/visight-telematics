"""
Admin API endpoints: authentication, logging, billing, user management
"""
from fastapi import APIRouter, Depends, HTTPException, status, Request, Query
from sqlalchemy import or_
from sqlalchemy.orm import Session
from datetime import datetime, timedelta, date
from typing import List, Optional, Dict
from uuid import UUID
from pydantic import BaseModel, EmailStr, field_validator
import logging

from app.database import get_db
from app.models_admin import (
    AdminUser,
    AppLog,
    AuditLog,
    BillingData,
    BillingTransaction,
    CriticalServiceAlertSubscription,
    CriticalServiceCategory,
    AsyncJob,
)
from app.models import (
    AppFeatures,
    UserGroup,
    UserGroupPackage,
    PortalUser,
    Building,
    Floor,
    IndoorGateway,
    Room,
    BLETag,
    PortalAlert,
    TagIndoorPosition,
    DeviceState,
)
from app.admin_auth import (
    hash_password, verify_password, create_admin_access_token,
    decode_admin_token, check_role_permission
)
from app.services.critical_service_alert_service import CATEGORY_DEFS

router = APIRouter(prefix="/api/admin", tags=["admin"])
logger = logging.getLogger(__name__)


_EMAIL_NOTIFY_FLAG_BY_ALERT = {
    "battery_low": "notify_battery_low",
    "tag_offline": "notify_offline",
    "geofence_entry": "notify_geofence_exit",
    "geofence_exit": "notify_geofence_exit",
    "gdpr_deletion_warning": "alerts_enabled",
    "hive_breach": "notify_hive_breach",
    "hive_breach_cleared": "notify_hive_breach",
}


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


class CriticalServiceAlertSubscriptionOut(BaseModel):
    category: str
    label: str
    description: str
    is_enabled: bool
    failure_threshold: int
    window_minutes: int
    cooldown_minutes: int
    recipient_emails: List[str]
    last_alert_sent_at: Optional[datetime]


class CriticalServiceAlertSubscriptionUpdate(BaseModel):
    is_enabled: bool
    failure_threshold: int = 5
    window_minutes: int = 15
    cooldown_minutes: int = 60
    recipient_emails: List[EmailStr] = []

    @field_validator("failure_threshold", "window_minutes", "cooldown_minutes")
    @classmethod
    def validate_positive(cls, v: int) -> int:
        if v < 1:
            raise ValueError("must be >= 1")
        return v


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


def _resolve_stats_date_range(
    preset: str,
    start_date: Optional[str],
    end_date: Optional[str],
) -> tuple[datetime, datetime, str, str]:
    now = datetime.utcnow()
    today = now.date()

    if preset == "today":
        start = today
        end = today
    elif preset == "last_7_days":
        start = today - timedelta(days=6)
        end = today
    elif preset == "current_month":
        start = today.replace(day=1)
        end = today
    elif preset == "custom":
        if not start_date or not end_date:
            raise HTTPException(status_code=400, detail="start_date and end_date are required for custom preset")
        try:
            start = datetime.fromisoformat(start_date).date()
            end = datetime.fromisoformat(end_date).date()
        except ValueError:
            raise HTTPException(status_code=400, detail="Invalid custom date format. Use YYYY-MM-DD")
    else:
        raise HTTPException(status_code=400, detail="Invalid preset. Use today, last_7_days, current_month, or custom")

    if end < start:
        raise HTTPException(status_code=400, detail="end_date must be on or after start_date")

    # Inclusive date range: [start, end]
    start_dt = datetime.combine(start, datetime.min.time())
    end_exclusive = datetime.combine(end + timedelta(days=1), datetime.min.time())
    return start_dt, end_exclusive, start.isoformat(), end.isoformat()


def _extract_device_imei(tag: Optional[BLETag], meta_data: Optional[dict]) -> str:
    if tag and tag.imei:
        return tag.imei
    if isinstance(meta_data, dict):
        for key in ("imei", "outlier_imei", "tag_imei"):
            value = meta_data.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()
    return "unknown"


def _extract_device_label(tag: Optional[BLETag], imei: str) -> str:
    if tag:
        if tag.description:
            return tag.description
        if tag.device_name:
            return tag.device_name
        if tag.imei:
            return tag.imei
    return imei if imei and imei != "unknown" else "Unknown Device"


def _emails_for_group_alert_type(db: Session, usergroup_id: str, alert_type: str) -> list[str]:
    flag = _EMAIL_NOTIFY_FLAG_BY_ALERT.get(alert_type, "alerts_enabled")
    users = db.query(PortalUser).filter(
        PortalUser.usergroup_id == usergroup_id,
        PortalUser.is_active == True,
        PortalUser.alerts_enabled == True,
        PortalUser.notify_via_email == True,
    ).all()

    recipients: set[str] = set()
    for user in users:
        if not getattr(user, flag, True):
            continue
        if user.email and isinstance(user.email, str):
            recipients.add(user.email.strip().lower())
        if isinstance(user.notification_emails, list):
            for extra in user.notification_emails:
                if isinstance(extra, str) and extra.strip():
                    recipients.add(extra.strip().lower())

    return sorted(e for e in recipients if e)


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


# CRITICAL SERVICE ALERT SUBSCRIPTIONS
def _ensure_critical_subscriptions(db: Session) -> None:
    existing = {
        row.category.value if hasattr(row.category, "value") else str(row.category)
        for row in db.query(CriticalServiceAlertSubscription).all()
    }
    created = False
    for category_key in CATEGORY_DEFS.keys():
        if category_key in existing:
            continue
        db.add(
            CriticalServiceAlertSubscription(
                category=CriticalServiceCategory(category_key),
                is_enabled=False,
                failure_threshold=5,
                window_minutes=15,
                cooldown_minutes=60,
                recipient_emails=[],
            )
        )
        created = True
    if created:
        db.commit()


def _critical_subscription_out(row: CriticalServiceAlertSubscription) -> CriticalServiceAlertSubscriptionOut:
    key = row.category.value if hasattr(row.category, "value") else str(row.category)
    cfg = CATEGORY_DEFS[key]
    return CriticalServiceAlertSubscriptionOut(
        category=key,
        label=cfg["label"],
        description=cfg["description"],
        is_enabled=bool(row.is_enabled),
        failure_threshold=int(row.failure_threshold or 5),
        window_minutes=int(row.window_minutes or 15),
        cooldown_minutes=int(row.cooldown_minutes or 60),
        recipient_emails=[e for e in (row.recipient_emails or []) if isinstance(e, str)],
        last_alert_sent_at=row.last_alert_sent_at,
    )


@router.get("/critical-alerts/subscriptions", response_model=List[CriticalServiceAlertSubscriptionOut])
async def list_critical_alert_subscriptions(request: Request, db: Session = Depends(get_db)):
    """List all critical-service categories and their current notification settings."""
    admin = get_admin_from_request(request, db)
    if not check_role_permission(admin.role, "manager"):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Requires manager or admin role",
        )

    _ensure_critical_subscriptions(db)
    rows = db.query(CriticalServiceAlertSubscription).all()
    rows_by_key = {
        (r.category.value if hasattr(r.category, "value") else str(r.category)): r
        for r in rows
    }

    result = []
    for key in CATEGORY_DEFS.keys():
        row = rows_by_key.get(key)
        if not row:
            continue
        result.append(_critical_subscription_out(row))
    return result


@router.put("/critical-alerts/subscriptions/{category_key}", response_model=CriticalServiceAlertSubscriptionOut)
async def update_critical_alert_subscription(
    category_key: str,
    payload: CriticalServiceAlertSubscriptionUpdate,
    request: Request,
    db: Session = Depends(get_db),
):
    """Update one critical-service category toggle, thresholds, and recipients."""
    admin = get_admin_from_request(request, db)
    if not check_role_permission(admin.role, "manager"):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Requires manager or admin role",
        )

    key = (category_key or "").strip().lower()
    if key not in CATEGORY_DEFS:
        raise HTTPException(status_code=404, detail="Unknown category")

    _ensure_critical_subscriptions(db)
    row = db.query(CriticalServiceAlertSubscription).filter(
        CriticalServiceAlertSubscription.category == CriticalServiceCategory(key)
    ).first()
    if not row:
        raise HTTPException(status_code=404, detail="Subscription row not found")

    recipients = []
    seen = set()
    for email in payload.recipient_emails:
        value = str(email).strip().lower()
        if value in seen:
            continue
        seen.add(value)
        recipients.append(value)

    if payload.is_enabled and not recipients:
        raise HTTPException(
            status_code=400,
            detail="At least one recipient email is required when enabling a category",
        )

    row.is_enabled = payload.is_enabled
    row.failure_threshold = payload.failure_threshold
    row.window_minutes = payload.window_minutes
    row.cooldown_minutes = payload.cooldown_minutes
    row.recipient_emails = recipients
    row.updated_at = datetime.utcnow()
    db.commit()
    db.refresh(row)

    log_audit(
        db,
        str(admin.id),
        "update_critical_alert_subscription",
        "CriticalServiceAlertSubscription",
        key,
        new_value={
            "is_enabled": row.is_enabled,
            "failure_threshold": row.failure_threshold,
            "window_minutes": row.window_minutes,
            "cooldown_minutes": row.cooldown_minutes,
            "recipient_emails": row.recipient_emails,
        },
        description=f"Updated critical alert subscription for {key}",
        ip_address=request.client.host if request.client else None,
    )

    return _critical_subscription_out(row)


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
# HIVE Logs Export
# ---------------------------------------------------------------------------

@router.get("/hive-logs/export")
async def export_hive_logs(
    request: Request,
    db: Session = Depends(get_db),
    days: int = Query(7, ge=1, le=90, description="Number of days of logs to export"),
):
    """
    Export HIVE logs and database data as a downloadable tar.gz bundle.
    Includes backend logs, evaluations, events, and current hive state.
    """
    from fastapi.responses import StreamingResponse
    import subprocess
    import tempfile
    import os
    import tarfile
    from io import BytesIO
    
    admin = get_admin_from_request(request, db)
    if not check_role_permission(admin.role, "manager"):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Requires manager role")
    
    cutoff = datetime.utcnow() - timedelta(days=days)
    timestamp = datetime.utcnow().strftime("%Y%m%d-%H%M%S")
    
    # Create in-memory tar.gz
    buffer = BytesIO()
    
    with tarfile.open(fileobj=buffer, mode='w:gz') as tar:
        # 1. Backend HIVE logs (from docker logs)
        try:
            result = subprocess.run(
                ['docker', 'logs', '--since', f'{days}d', 'pinplot_backend'],
                capture_output=True, text=True, timeout=30
            )
            logs = result.stdout + result.stderr
            # Filter for HIVE-related lines
            hive_lines = [line for line in logs.split('\n') if any(x in line for x in ['🔍', '🛡️', 'HIVE', 'hive_service'])]
            hive_log_content = '\n'.join(hive_lines).encode('utf-8')
            
            info = tarfile.TarInfo(name='backend-hive-logs.log')
            info.size = len(hive_log_content)
            info.mtime = datetime.utcnow().timestamp()
            tar.addfile(info, BytesIO(hive_log_content))
        except Exception as e:
            logger.error(f"Failed to extract backend logs: {e}")
        
        # 2. Hives table
        from app.models import Hive
        hives = db.query(Hive).all()
        hives_data = f"Total hives: {len(hives)}\n\n"
        for h in hives:
            alert_state = h.live_state.alert_state if h.live_state else "N/A"
            hives_data += f"ID: {h.id}\nName: {h.name}\nCreated By: {h.created_by or 'N/A'}\nAlert State: {alert_state}\n"
            hives_data += f"Created: {h.created_at}\nArchived: {h.archived_at}\nStatus: {h.status}\n\n"
        
        info = tarfile.TarInfo(name='hives.txt')
        info.size = len(hives_data.encode('utf-8'))
        info.mtime = datetime.utcnow().timestamp()
        tar.addfile(info, BytesIO(hives_data.encode('utf-8')))
        
        # 3. Recent evaluations
        from app.models import HiveEvaluation
        evals = db.query(HiveEvaluation).filter(
            HiveEvaluation.evaluated_at >= cutoff
        ).order_by(HiveEvaluation.evaluated_at.desc()).limit(500).all()
        
        evals_data = f"Recent evaluations (last {days} days): {len(evals)}\n\n"
        for e in evals:
            evals_data += f"Hive: {e.hive_id}\nTime: {e.evaluated_at}\n"
            evals_data += f"State: {e.alert_state}\nDiameter: {e.diameter_m}m\nThreshold: {e.threshold_m}m\n"
            evals_data += f"Config V: {e.config_version_number}\nMotion: {e.motion_state or 'N/A'}\n"
            evals_data += f"Outlier: {e.outlier_tag_id or 'N/A'}\n"
            evals_data += f"Outlier reason: {getattr(e, 'outlier_selection_reason', None) or 'none'}\n"
            evals_data += f"Breaching pair counts: {getattr(e, 'breaching_pair_counts', None) or '{}'}\n"
            evals_data += f"Pairwise detail: {getattr(e, 'pairwise_detail', None) or 'N/A'}\n"
            evals_data += f"Positions used: {e.positions_used or 'N/A'}\n"
            evals_data += f"Max pair dt (s): {e.max_pair_dt_s if e.max_pair_dt_s is not None else 'N/A'}\n"
            evals_data += f"Coherent pairs: {e.coherent_pair_count if e.coherent_pair_count is not None else 'N/A'}\n"
            evals_data += f"Incoherent pairs: {e.incoherent_pair_count if e.incoherent_pair_count is not None else 'N/A'}\n"
            evals_data += f"Breach evidence: {e.breach_evidence or 'N/A'}\n\n"
        
        info = tarfile.TarInfo(name='hive-evaluations.txt')
        info.size = len(evals_data.encode('utf-8'))
        info.mtime = datetime.utcnow().timestamp()
        tar.addfile(info, BytesIO(evals_data.encode('utf-8')))
        
        # 4. Recent events
        from app.models import HiveEvent
        events = db.query(HiveEvent).filter(
            HiveEvent.occurred_at >= cutoff
        ).order_by(HiveEvent.occurred_at.desc()).limit(200).all()
        
        events_data = f"Recent events (last {days} days): {len(events)}\n\n"
        for ev in events:
            events_data += f"Hive: {ev.hive_id}\nTime: {ev.occurred_at}\n"
            events_data += f"Type: {ev.event_type}\nFrom: {ev.from_state} To: {ev.to_state}\n"
            events_data += f"Details: {ev.details}\n\n"
        
        info = tarfile.TarInfo(name='hive-events.txt')
        info.size = len(events_data.encode('utf-8'))
        info.mtime = datetime.utcnow().timestamp()
        tar.addfile(info, BytesIO(events_data.encode('utf-8')))
        
        # 5. Tag membership
        from app.models import HiveTagMembership
        members = db.query(HiveTagMembership).all()
        
        members_data = f"Total tag memberships: {len(members)}\n\n"
        for m in members:
            members_data += f"Hive: {m.hive_id}\nTag: {m.tag_id}\n\n"
        
        info = tarfile.TarInfo(name='hive-tag-membership.txt')
        info.size = len(members_data.encode('utf-8'))
        info.mtime = datetime.utcnow().timestamp()
        tar.addfile(info, BytesIO(members_data.encode('utf-8')))
    
    buffer.seek(0)
    
    return StreamingResponse(
        buffer,
        media_type='application/gzip',
        headers={
            'Content-Disposition': f'attachment; filename="hive-logs-{timestamp}.tar.gz"'
        }
    )


# ---------------------------------------------------------------------------
# Trip Engine Logs Export
# ---------------------------------------------------------------------------

@router.get("/trip-logs/export")
async def export_trip_logs(
    request: Request,
    db: Session = Depends(get_db),
    days: int = Query(7, ge=1, le=90, description="Number of days of logs to export"),
):
    """
    Export Trip Engine logs and database data as a downloadable tar.gz bundle.
    Includes backend logs, journeys, legs, stationaries, and device states.
    """
    from fastapi.responses import StreamingResponse
    import subprocess
    import tempfile
    import os
    import tarfile
    from io import BytesIO
    
    admin = get_admin_from_request(request, db)
    if not check_role_permission(admin.role, "manager"):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Requires manager role")
    
    cutoff = datetime.utcnow() - timedelta(days=days)
    timestamp = datetime.utcnow().strftime("%Y%m%d-%H%M%S")
    
    # Create in-memory tar.gz
    buffer = BytesIO()
    
    with tarfile.open(fileobj=buffer, mode='w:gz') as tar:
        # 1. Backend Trip Engine logs (from docker logs)
        try:
            result = subprocess.run(
                ['docker', 'logs', '--since', f'{days}d', 'pinplot_backend'],
                capture_output=True, text=True, timeout=30
            )
            logs = result.stdout + result.stderr
            # Filter for Trip Engine-related lines
            trip_lines = [line for line in logs.split('\n') if any(x in line for x in [
                'TripEngine', 'trip_engine', 'Journey', 'Leg', 'Stationary',
                '🆕', '✅', '🔵', '🟠', '✈️', '🔚', '📅', 'IMEI'
            ])]
            trip_log_content = '\n'.join(trip_lines).encode('utf-8')
            
            info = tarfile.TarInfo(name='backend-trip-logs.log')
            info.size = len(trip_log_content)
            info.mtime = datetime.utcnow().timestamp()
            tar.addfile(info, BytesIO(trip_log_content))
        except Exception as e:
            logger.error(f"Failed to extract backend trip logs: {e}")
        
        # 2. Journeys table
        from app.models import Journey
        journeys = db.query(Journey).filter(
            Journey.started_at >= cutoff
        ).order_by(Journey.started_at.desc()).limit(1000).all()
        
        journeys_data = f"Journeys (last {days} days): {len(journeys)}\n\n"
        for j in journeys:
            duration_min = j.total_duration_seconds / 60 if j.total_duration_seconds else 0
            journeys_data += f"ID: {j.id}\n"
            journeys_data += f"Device: {j.device_imei}\n"
            journeys_data += f"Started: {j.started_at}\n"
            journeys_data += f"Ended: {j.ended_at}\n"
            journeys_data += f"Duration: {duration_min:.1f} min\n"
            journeys_data += f"Distance: {j.total_distance_m/1000:.2f} km\n"
            journeys_data += f"Legs: {j.leg_count}\n"
            journeys_data += f"Stationaries: {j.stationary_count}\n"
            journeys_data += f"Air Journey: {j.is_air_journey}\n"
            journeys_data += f"Created: {j.created_at}\n\n"
        
        info = tarfile.TarInfo(name='journeys.txt')
        info.size = len(journeys_data.encode('utf-8'))
        info.mtime = datetime.utcnow().timestamp()
        tar.addfile(info, BytesIO(journeys_data.encode('utf-8')))
        
        # 3. Legs table (sample from recent journeys)
        from app.models import Leg
        legs = db.query(Leg).filter(
            Leg.started_at >= cutoff
        ).order_by(Leg.started_at.desc()).limit(500).all()
        
        legs_data = f"Legs (last {days} days): {len(legs)}\n\n"
        for leg in legs:
            duration_min = leg.duration_seconds / 60 if leg.duration_seconds else 0
            legs_data += f"ID: {leg.id}\n"
            legs_data += f"Journey: {leg.journey_id}\n"
            legs_data += f"Device: {leg.device_imei}\n"
            legs_data += f"Started: {leg.started_at}\n"
            legs_data += f"Ended: {leg.ended_at}\n"
            legs_data += f"Duration: {duration_min:.1f} min\n"
            legs_data += f"Distance: {leg.distance_m/1000:.3f} km\n"
            legs_data += f"Points: {leg.point_count}\n"
            legs_data += f"Air Leg: {leg.is_air_leg}\n"
            legs_data += f"Start: ({leg.start_lat:.6f}, {leg.start_lng:.6f})\n"
            legs_data += f"End: ({leg.end_lat:.6f}, {leg.end_lng:.6f})\n\n"
        
        info = tarfile.TarInfo(name='legs.txt')
        info.size = len(legs_data.encode('utf-8'))
        info.mtime = datetime.utcnow().timestamp()
        tar.addfile(info, BytesIO(legs_data.encode('utf-8')))
        
        # 4. Stationaries table
        from app.models import Stationary
        stationaries = db.query(Stationary).filter(
            Stationary.started_at >= cutoff
        ).order_by(Stationary.started_at.desc()).limit(500).all()
        
        stats_data = f"Stationaries (last {days} days): {len(stationaries)}\n\n"
        for stat in stationaries:
            duration_min = stat.duration_seconds / 60 if stat.duration_seconds else 0
            stats_data += f"ID: {stat.id}\n"
            stats_data += f"Journey: {stat.journey_id or 'NULL (journey-breaking)'}\n"
            stats_data += f"Device: {stat.device_imei}\n"
            stats_data += f"Started: {stat.started_at}\n"
            stats_data += f"Ended: {stat.ended_at}\n"
            stats_data += f"Duration: {duration_min:.1f} min\n"
            stats_data += f"Points: {stat.point_count}\n"
            stats_data += f"Anchor: ({stat.anchor_lat:.6f}, {stat.anchor_lng:.6f})\n\n"
        
        info = tarfile.TarInfo(name='stationaries.txt')
        info.size = len(stats_data.encode('utf-8'))
        info.mtime = datetime.utcnow().timestamp()
        tar.addfile(info, BytesIO(stats_data.encode('utf-8')))
        
        # 5. Device states (trip subscriptions)
        device_states = db.query(DeviceState).all()
        
        states_data = f"Device States (total): {len(device_states)}\n\n"
        for ds in device_states:
            states_data += f"Device: {ds.device_imei}\n"
            states_data += f"Trip Subscribed: {ds.trip_subscribed}\n"
            states_data += f"Last Batch: {ds.last_batch_ts}\n"
            states_data += f"Last Position: {ds.last_position_ts}\n"
            states_data += f"Last Tracklist Pull: {ds.last_tracklist_pull_at}\n"
            states_data += f"Updated: {ds.updated_at}\n\n"
        
        info = tarfile.TarInfo(name='device-states.txt')
        info.size = len(states_data.encode('utf-8'))
        info.mtime = datetime.utcnow().timestamp()
        tar.addfile(info, BytesIO(states_data.encode('utf-8')))
        
        # 6. Engine states (trip processing state)
        from app.models import EngineState
        engine_states = db.query(EngineState).all()
        
        engine_data = f"Engine States (total): {len(engine_states)}\n\n"
        for es in engine_states:
            engine_data += f"Device: {es.device_imei}\n"
            engine_data += f"Current State: {es.current_state}\n"
            engine_data += f"Current Journey: {es.current_journey_id or 'None'}\n"
            engine_data += f"Current Leg: {es.current_leg_id or 'None'}\n"
            engine_data += f"Last Processed: {es.last_processed_at}\n"
            
            # Format anchor coordinates safely
            anchor_str = f"({es.anchor_lat:.6f}, {es.anchor_lng:.6f})" if es.anchor_lat is not None and es.anchor_lng is not None else "N/A"
            engine_data += f"Anchor: {anchor_str}\n"
            engine_data += f"Anchor Count: {es.anchor_count}\n"
            engine_data += f"Updated: {es.updated_at}\n\n"
        
        info = tarfile.TarInfo(name='engine-states.txt')
        info.size = len(engine_data.encode('utf-8'))
        info.mtime = datetime.utcnow().timestamp()
        tar.addfile(info, BytesIO(engine_data.encode('utf-8')))
    
    buffer.seek(0)
    
    return StreamingResponse(
        buffer,
        media_type='application/gzip',
        headers={
            'Content-Disposition': f'attachment; filename="trip-logs-{timestamp}.tar.gz"'
        }
    )


# ---------------------------------------------------------------------------
# Trip Engine Reprocess (v2.2 A4)
# ---------------------------------------------------------------------------

class TripReprocessRequest(BaseModel):
    """Request to reprocess trip data for a device."""
    device_imei: str
    start_date: Optional[date] = None  # Accepts "YYYY-MM-DD" format
    end_date: Optional[date] = None    # Accepts "YYYY-MM-DD" format

class TripReprocessResponse(BaseModel):
    """Result of trip reprocess operation."""
    device_imei: str
    positions_processed: int
    journeys_created: int
    legs_created: int
    stationaries_created: int
    engine_version: str

@router.post("/trips/reprocess", response_model=TripReprocessResponse)
async def reprocess_device_trips(
    data: TripReprocessRequest,
    request: Request,
    db: Session = Depends(get_db),
):
    """
    Reprocess trip segmentation for a device from stored positions (A4).
    
    Deletes all derived trip data (journeys/legs/stationaries) and replays
    positions through the current engine with current parameters. Use this
    after engine updates to adopt new logic (e.g. v2.1 settle-dwell/merge/air-leg).
    
    **WARNING**: This is a DESTRUCTIVE operation. All existing trip data for
    this device will be deleted and regenerated.
    
    Args:
        data: Device IMEI and optional date window
    
    Returns:
        Statistics about positions processed and trips created
    
    Note:
        - Positions table is never modified (source of truth)
        - Requires manager role
        - Runs in a transaction (atomic)
    """
    from app.services.trip_reprocess_service import replay_device_trips, ENGINE_VERSION
    
    admin = get_admin_from_request(request, db)
    if not check_role_permission(admin.role, "manager"):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Requires manager role")
    
    logger.info(
        "🔄 Admin %s triggered reprocess for device %s (window: %s to %s)",
        admin.email,
        data.device_imei,
        data.start_date,
        data.end_date
    )
    
    try:
        # Run replay in a transaction
        result = replay_device_trips(
            db=db,
            device_imei=data.device_imei,
            start_date=data.start_date,
            end_date=data.end_date,
            tenant_id=None  # TODO: resolve from device's usergroup when available
        )
        
        db.commit()
        
        logger.info(
            "✅ Reprocess complete for %s: %d positions → %d journeys, %d legs, %d stationaries",
            data.device_imei,
            result["positions_processed"],
            result["journeys_created"],
            result["legs_created"],
            result["stationaries_created"]
        )
        
        return TripReprocessResponse(
            device_imei=data.device_imei,
            positions_processed=result["positions_processed"],
            journeys_created=result["journeys_created"],
            legs_created=result["legs_created"],
            stationaries_created=result["stationaries_created"],
            engine_version=ENGINE_VERSION
        )
        
    except ValueError as e:
        db.rollback()
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))
    except Exception as e:
        db.rollback()
        logger.error("❌ Reprocess failed for %s: %s", data.device_imei, e, exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Reprocess failed: {str(e)}"
        )


# ---------------------------------------------------------------------------
# Trip Backfill (v2.2 A3)
# ---------------------------------------------------------------------------

class TripBackfillRequest(BaseModel):
    """Request to backfill historical positions for a device."""
    device_imei: str
    preset: str  # today | yesterday | last_7_days | last_30_days

class TripBackfillResponse(BaseModel):
    """Result of trip backfill operation."""
    device_imei: str
    preset: str
    window_start: datetime
    window_end: datetime
    clamped: bool
    positions_fetched: int
    positions_inserted: int
    positions_processed: int
    journeys_created: int
    legs_created: int
    stationaries_created: int
    engine_version: str

@router.post("/trips/backfill", response_model=TripBackfillResponse)
async def backfill_device_trips(
    data: TripBackfillRequest,
    request: Request,
    db: Session = Depends(get_db),
):
    """
    Backfill historical positions from TrackSolid and reprocess trips (A3).
    
    Fetches historical GPS positions for a device using TrackSolid track.list API,
    then reprocesses trips. The backfill window is clamped to the forward pipeline
    high-water mark (last_position_ts) to prevent overlap with automated pulls.
    
    **Use cases:**
    - Device wasn't subscribed when it moved (missing history)
    - Gap in position data needs to be filled
    - One-off historical analysis
    
    **Safe guarantees:**
    - Never crosses forward pipeline boundary (last_position_ts)
    - Idempotent position storage (duplicates ignored)
    - Does NOT modify forward pipeline state
    - Works for subscribed AND unsubscribed devices
    
    Args:
        data: Device IMEI and time window preset
    
    Returns:
        Statistics about positions fetched, inserted, and trips created
    
    Note:
        - Requires manager role
        - Runs async (may take several seconds for large windows)
        - Positions are upserted (idempotent on device_imei, observed_at)
    """
    from app.services.trip_backfill_service import backfill_device_positions, BackfillPreset
    
    admin = get_admin_from_request(request, db)
    if not check_role_permission(admin.role, "manager"):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Requires manager role")
    
    # Validate preset
    try:
        preset_enum = BackfillPreset(data.preset)
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid preset: {data.preset}. Must be one of: today, yesterday, last_7_days, last_30_days"
        )
    
    logger.info(
        "📥 Admin %s triggered backfill for device %s (preset: %s)",
        admin.email,
        data.device_imei,
        data.preset
    )
    
    try:
        # Run backfill (fetches + upserts + reprocesses)
        result = await backfill_device_positions(
            db=db,
            device_imei=data.device_imei,
            preset=preset_enum
        )
        
        db.commit()
        
        logger.info(
            "✅ Backfill complete for %s: %d fetched, %d inserted, %d journeys",
            data.device_imei,
            result["positions_fetched"],
            result["positions_inserted"],
            result["journeys_created"]
        )
        
        return TripBackfillResponse(
            device_imei=result["device_imei"],
            preset=result["preset"],
            window_start=result["window_start"],
            window_end=result["window_end"],
            clamped=result["clamped"],
            positions_fetched=result["positions_fetched"],
            positions_inserted=result["positions_inserted"],
            positions_processed=result["positions_processed"],
            journeys_created=result["journeys_created"],
            legs_created=result["legs_created"],
            stationaries_created=result["stationaries_created"],
            engine_version=result["engine_version"]
        )
        
    except ValueError as e:
        db.rollback()
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))
    except Exception as e:
        db.rollback()
        logger.error("❌ Backfill failed for %s: %s", data.device_imei, e, exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Backfill failed: {str(e)}"
        )


# ---------------------------------------------------------------------------
# Async Jobs - Batch Operations (v2.2 A5)
# ---------------------------------------------------------------------------

class BatchBackfillRequest(BaseModel):
    """Request to backfill all subscribed devices in a tenant."""
    tenant_id: UUID
    preset: str  # today | yesterday | last_7_days | last_30_days

class BatchReprocessRequest(BaseModel):
    """Request to reprocess all subscribed devices in a tenant."""
    tenant_id: UUID

class AsyncJobResponse(BaseModel):
    """Response for async job operations."""
    id: UUID
    job_type: str
    status: str
    created_by: str
    created_at: datetime
    started_at: Optional[datetime]
    completed_at: Optional[datetime]
    total_devices: Optional[int]
    completed_devices: int
    failed_devices: int
    results: Optional[Dict]
    error_message: Optional[str]
    last_processed_imei: Optional[str]
    
    class Config:
        from_attributes = True


@router.post("/jobs/batch-backfill", response_model=AsyncJobResponse)
async def create_batch_backfill_job(
    data: BatchBackfillRequest,
    request: Request,
    db: Session = Depends(get_db),
):
    """
    Create a batch backfill job for all subscribed devices in a tenant (A5).
    
    Queues an async background job to backfill historical positions from
    TrackSolid for all subscribed devices in the specified tenant.
    
    The job runs asynchronously and can be monitored via GET /jobs/{job_id}.
    
    Args:
        data: Tenant ID and time window preset
    
    Returns:
        Created job with status "pending"
    
    Note:
        - Requires manager role
        - Job runs in background (non-blocking)
        - Use GET /jobs/{job_id} to monitor progress
        - Background worker processes jobs sequentially
    """
    admin = get_admin_from_request(request, db)
    if not check_role_permission(admin.role, "manager"):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Requires manager role")
    
    # Validate tenant exists
    tenant = db.query(UserGroup).filter(UserGroup.id == data.tenant_id).first()
    if not tenant:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Tenant not found")
    
    # Validate preset
    valid_presets = ["today", "yesterday", "last_7_days", "last_30_days"]
    if data.preset not in valid_presets:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid preset. Must be one of: {', '.join(valid_presets)}"
        )
    
    logger.info(
        "📥 Admin %s creating batch backfill job: tenant=%s (%s), preset=%s",
        admin.email,
        tenant.name,
        data.tenant_id,
        data.preset
    )
    
    # Create job
    job = AsyncJob(
        job_type="batch_backfill",
        status="pending",
        created_by=admin.email,
        params={
            "tenant_id": str(data.tenant_id),
            "preset": data.preset
        },
        completed_devices=0,
        failed_devices=0
    )
    
    db.add(job)
    db.commit()
    db.refresh(job)
    
    logger.info("✅ Created batch backfill job %s", job.id)
    
    return job


@router.post("/jobs/batch-reprocess", response_model=AsyncJobResponse)
async def create_batch_reprocess_job(
    data: BatchReprocessRequest,
    request: Request,
    db: Session = Depends(get_db),
):
    """
    Create a batch reprocess job for all subscribed devices in a tenant (A5).
    
    Queues an async background job to reprocess trip segmentation for all
    subscribed devices in the specified tenant.
    
    Use this after engine updates to adopt new logic across all tenant devices.
    
    Args:
        data: Tenant ID
    
    Returns:
        Created job with status "pending"
    
    Note:
        - Requires manager role
        - Job runs in background (non-blocking)
        - Use GET /jobs/{job_id} to monitor progress
        - Background worker processes jobs sequentially
    """
    admin = get_admin_from_request(request, db)
    if not check_role_permission(admin.role, "manager"):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Requires manager role")
    
    # Validate tenant exists
    tenant = db.query(UserGroup).filter(UserGroup.id == data.tenant_id).first()
    if not tenant:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Tenant not found")
    
    logger.info(
        "🔄 Admin %s creating batch reprocess job: tenant=%s (%s)",
        admin.email,
        tenant.name,
        data.tenant_id
    )
    
    # Create job
    job = AsyncJob(
        job_type="batch_reprocess",
        status="pending",
        created_by=admin.email,
        params={
            "tenant_id": str(data.tenant_id)
        },
        completed_devices=0,
        failed_devices=0
    )
    
    db.add(job)
    db.commit()
    db.refresh(job)
    
    logger.info("✅ Created batch reprocess job %s", job.id)
    
    return job


@router.get("/jobs/{job_id}", response_model=AsyncJobResponse)
async def get_job_status(
    job_id: UUID,
    request: Request,
    db: Session = Depends(get_db),
):
    """
    Get status and progress of an async job.
    
    Args:
        job_id: Job UUID
    
    Returns:
        Job details including status, progress, and results
    
    Note:
        - Requires viewer role
        - Poll this endpoint to monitor job progress
        - Check status field: pending | running | completed | failed | cancelled
    """
    admin = get_admin_from_request(request, db)
    if not check_role_permission(admin.role, "viewer"):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Requires viewer role")
    
    job = db.query(AsyncJob).filter(AsyncJob.id == job_id).first()
    if not job:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Job not found")
    
    return job


@router.get("/jobs", response_model=List[AsyncJobResponse])
async def list_jobs(
    request: Request,
    status: Optional[str] = Query(None, description="Filter by status: pending|running|completed|failed"),
    limit: int = Query(50, le=200, description="Max results to return"),
    db: Session = Depends(get_db),
):
    """
    List async jobs with optional filtering.
    
    Args:
        status: Optional status filter
        limit: Max results (default 50, max 200)
    
    Returns:
        List of jobs ordered by created_at desc
    
    Note:
        - Requires viewer role
        - Returns most recent jobs first
    """
    admin = get_admin_from_request(request, db)
    if not check_role_permission(admin.role, "viewer"):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Requires viewer role")
    
    query = db.query(AsyncJob)
    
    if status:
        if status not in ["pending", "running", "completed", "failed", "cancelled"]:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid status")
        query = query.filter(AsyncJob.status == status)
    
    jobs = query.order_by(AsyncJob.created_at.desc()).limit(limit).all()
    
    return jobs


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
    allowed_tag_types: Optional[list] = None  # e.g. ["series1", "series2"] — None means all allowed


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
    allowed_tag_types: Optional[list] = None
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
            allowed_tag_types=g.allowed_tag_types,
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
        allowed_tag_types=data.allowed_tag_types,
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
        role="system_admin",
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
    allowed_tag_types: Optional[list] = None  # e.g. ["series1","series2"] — None means no change


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

    # allowed_tag_types: use model_fields_set so explicit null = "reset to all"
    if "allowed_tag_types" in data.model_fields_set:
        tag_types = data.allowed_tag_types
        valid = {"series1", "series2", "series3"}
        if tag_types is not None:
            bad = [t for t in tag_types if t not in valid]
            if bad:
                raise HTTPException(status_code=400, detail=f"Invalid tag type(s): {bad}. Allowed: {list(valid)}")
            tag_types = tag_types or None   # empty list → store null (= all allowed)
        group.allowed_tag_types = tag_types

    db.commit()
    return {"id": str(group.id), "name": group.name, "email_domain": group.email_domain, "allowed_sections": group.allowed_sections, "allowed_tag_types": group.allowed_tag_types}


# ---------------------------------------------------------------------------
# System Admin (built-in) management for a usergroup
# ---------------------------------------------------------------------------

class SystemAdminCreate(BaseModel):
    email: EmailStr
    first_name: Optional[str] = None
    last_name: Optional[str] = None


class SystemAdminCreateResponse(BaseModel):
    portal_user_id: str
    email: str
    temp_password: str


@router.post("/usergroups/{group_id}/system-admin", response_model=SystemAdminCreateResponse)
def create_system_admin(
    group_id: str,
    data: SystemAdminCreate,
    request: Request,
    db: Session = Depends(get_db),
):
    """Create an additional Built-in System Admin for an existing usergroup.

    System admins always have role='system_admin' and is_group_admin=True. The
    generated password is returned ONCE — it is not stored or recoverable.
    Requires admin role on the admin portal.
    """
    admin = get_admin_from_request(request, db)
    if not check_role_permission(admin.role, "admin"):
        raise HTTPException(status_code=403, detail="Requires admin role")

    group = db.query(UserGroup).filter(UserGroup.id == group_id).first()
    if not group:
        raise HTTPException(status_code=404, detail="User group not found")

    email = data.email.lower().strip()
    if db.query(PortalUser).filter(PortalUser.email == email).first():
        raise HTTPException(status_code=409, detail="A portal user with that email already exists")

    import uuid as _uuid
    temp_password = _secrets.token_urlsafe(12)
    new_user = PortalUser(
        id=str(_uuid.uuid4()),
        usergroup_id=group.id,
        email=email,
        hashed_password=hash_password(temp_password),
        first_name=data.first_name or None,
        last_name=data.last_name or None,
        is_active=True,
        is_group_admin=True,
        role="system_admin",
    )
    db.add(new_user)
    db.commit()
    db.refresh(new_user)

    log_audit(db, str(admin.id), "create_system_admin", "PortalUser", str(new_user.id),
              new_value={"email": email, "usergroup_id": str(group.id)},
              description=f"Created system admin {email} for {group.name}",
              ip_address=request.client.host if request.client else None)

    return SystemAdminCreateResponse(
        portal_user_id=str(new_user.id),
        email=new_user.email,
        temp_password=temp_password,
    )


class PortalPasswordResetResponse(BaseModel):
    portal_user_id: str
    email: str
    temp_password: str


@router.post("/portal-users/{portal_user_id}/reset-password",
             response_model=PortalPasswordResetResponse)
def reset_portal_user_password(
    portal_user_id: str,
    request: Request,
    db: Session = Depends(get_db),
):
    """Admin override: reset a portal user's password to a generated value.

    Intended for recovering Built-in System Admin accounts. Returns the new
    password ONCE. Requires admin role on the admin portal.
    """
    admin = get_admin_from_request(request, db)
    if not check_role_permission(admin.role, "admin"):
        raise HTTPException(status_code=403, detail="Requires admin role")

    target = db.query(PortalUser).filter(PortalUser.id == portal_user_id).first()
    if not target:
        raise HTTPException(status_code=404, detail="Portal user not found")

    temp_password = _secrets.token_urlsafe(12)
    target.hashed_password = hash_password(temp_password)
    db.commit()

    log_audit(db, str(admin.id), "reset_portal_password", "PortalUser", str(target.id),
              new_value={"email": target.email, "role": target.role},
              description=f"Reset password for portal user {target.email} ({target.role})",
              ip_address=request.client.host if request.client else None)

    return PortalPasswordResetResponse(
        portal_user_id=str(target.id),
        email=target.email,
        temp_password=temp_password,
    )


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
    sms_addon: bool = False     # whether this package includes SMS alerts


class PackageUpdate(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    validity_days: Optional[int] = None
    auto_delete_days: Optional[int] = None
    is_default: Optional[bool] = None
    is_active: Optional[bool] = None
    sms_addon: Optional[bool] = None


class PackageOut(BaseModel):
    id: UUID
    name: str
    description: Optional[str]
    validity_days: int
    auto_delete_days: Optional[int] = None
    is_default: bool
    is_active: bool
    sms_addon: bool = False
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
        sms_addon=data.sms_addon,
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


# ---------------------------------------------------------------------------
# Health / Diagnostics
# Uses the Docker daemon Unix socket directly — no docker CLI needed.
# The socket is already mounted: /var/run/docker.sock:/var/run/docker.sock:ro
# ---------------------------------------------------------------------------

import shutil
import platform
import socket as _socket
import json as _json
import urllib.parse


DOCKER_SOCK = "/var/run/docker.sock"

# Per-tenant container prefix — keep PinPlot back-compat default. Override
# in deployments where compose uses a different project name (e.g. Beacon
# Telematics uses 'beacon_telematics_').
_OPS_PREFIX = os.getenv("ADMIN_OPS_CONTAINER_PREFIX", "pinplot_")

_KNOWN_CONTAINERS = [
    f"{_OPS_PREFIX}nginx",
    f"{_OPS_PREFIX}backend",
    f"{_OPS_PREFIX}customer",
    f"{_OPS_PREFIX}admin",
    f"{_OPS_PREFIX}db",
    f"{_OPS_PREFIX}mosquitto",
    f"{_OPS_PREFIX}mqtt_bridge",
    f"{_OPS_PREFIX}flutter_web",
]

_FRIENDLY = {
    f"{_OPS_PREFIX}nginx":        "Nginx",
    f"{_OPS_PREFIX}backend":      "Backend API",
    f"{_OPS_PREFIX}customer":     "Customer Portal",
    f"{_OPS_PREFIX}admin":        "Admin Portal",
    f"{_OPS_PREFIX}db":           "PostgreSQL",
    f"{_OPS_PREFIX}mosquitto":    "MQTT Broker",
    f"{_OPS_PREFIX}mqtt_bridge":  "MQTT Bridge",
    f"{_OPS_PREFIX}flutter_web":  "Flutter Web",
}


def _docker_sock_available() -> bool:
    return os.path.exists(DOCKER_SOCK)


def _docker_request(method: str, path: str, body: dict | None = None, timeout: int = 10) -> tuple[int, any]:
    """
    Send an HTTP request to the Docker daemon over the Unix socket.
    Returns (status_code, parsed_json_body).
    """
    sock = _socket.socket(_socket.AF_UNIX, _socket.SOCK_STREAM)
    sock.settimeout(timeout)
    try:
        sock.connect(DOCKER_SOCK)
        payload_bytes = _json.dumps(body).encode() if body else b""
        headers = (
            f"{method} {path} HTTP/1.1\r\n"
            f"Host: localhost\r\n"
            f"Content-Type: application/json\r\n"
            f"Content-Length: {len(payload_bytes)}\r\n"
            f"Connection: close\r\n"
            f"\r\n"
        )
        sock.sendall(headers.encode() + payload_bytes)

        # Read the full response
        chunks = []
        while True:
            chunk = sock.recv(65536)
            if not chunk:
                break
            chunks.append(chunk)
        raw = b"".join(chunks).decode("utf-8", errors="replace")

        # Split HTTP response
        header_end = raw.find("\r\n\r\n")
        if header_end == -1:
            return 500, {}
        header_part = raw[:header_end]
        body_part   = raw[header_end + 4:]

        # Parse status code from first line
        first_line = header_part.split("\r\n")[0]
        status_code = int(first_line.split(" ")[1]) if len(first_line.split(" ")) > 1 else 500

        # Handle chunked transfer encoding
        transfer = ""
        for line in header_part.split("\r\n"):
            if line.lower().startswith("transfer-encoding:"):
                transfer = line.split(":", 1)[1].strip().lower()
        if transfer == "chunked":
            body_part = _decode_chunked(body_part)

        try:
            parsed = _json.loads(body_part) if body_part.strip() else {}
        except Exception:
            parsed = {}
        return status_code, parsed
    finally:
        sock.close()


def _decode_chunked(data: str) -> str:
    """Decode HTTP chunked transfer encoding."""
    result = []
    while data:
        nl = data.find("\r\n")
        if nl == -1:
            break
        size = int(data[:nl], 16)
        if size == 0:
            break
        chunk = data[nl + 2: nl + 2 + size]
        result.append(chunk)
        data = data[nl + 2 + size + 2:]
    return "".join(result)


def _container_status(name: str) -> dict:
    base = {
        "name": name,
        "friendly": _FRIENDLY.get(name, name),
        "status": "absent",
        "health": "—",
        "image": "—",
        "started_at": None,
        "restarts": 0,
        "cpu": "—",
        "mem": "—",
        "present": False,
    }
    try:
        code, data = _docker_request("GET", f"/containers/{name}/json")
        if code == 404:
            return base
        if code != 200:
            base["status"] = "error"
            return base

        state   = data.get("State", {})
        config  = data.get("Config", {})
        restart = data.get("RestartCount", 0)
        health  = state.get("Health", {})

        status_str = state.get("Status", "unknown")
        health_str = health.get("Status", "—") if health else "—"
        image_str  = config.get("Image", "—")
        started_at = state.get("StartedAt", None)

        cpu_pct = "—"
        mem_str = "—"
        if status_str == "running":
            try:
                scode, stats = _docker_request("GET", f"/containers/{name}/stats?stream=false", timeout=8)
                if scode == 200 and stats:
                    cpu_delta  = stats["cpu_stats"]["cpu_usage"]["total_usage"] - stats["precpu_stats"]["cpu_usage"]["total_usage"]
                    sys_delta  = stats["cpu_stats"]["system_cpu_usage"] - stats["precpu_stats"]["system_cpu_usage"]
                    num_cpus   = stats["cpu_stats"].get("online_cpus") or len(stats["cpu_stats"]["cpu_usage"].get("percpu_usage", [1]))
                    if sys_delta > 0:
                        cpu_pct = f"{round(cpu_delta / sys_delta * num_cpus * 100, 1)}%"
                    mem_usage = stats["memory_stats"].get("usage", 0)
                    mem_limit = stats["memory_stats"].get("limit", 0)
                    if mem_usage:
                        mem_mb = mem_usage / 1024 / 1024
                        lim_mb = mem_limit / 1024 / 1024
                        mem_str = f"{mem_mb:.0f} MB / {lim_mb:.0f} MB"
            except Exception:
                pass

        return {
            "name": name,
            "friendly": _FRIENDLY.get(name, name),
            "status": status_str,
            "health": health_str,
            "image": image_str,
            "started_at": started_at,
            "restarts": int(restart),
            "cpu": cpu_pct,
            "mem": mem_str,
            "present": True,
        }
    except Exception as exc:
        base["health"] = str(exc)[:80]
        return base


@router.get("/health/containers")
def health_containers(request: Request, db: Session = Depends(get_db)):
    """Return status of all known containers via Docker socket. Requires manager role."""
    admin = get_admin_from_request(request, db)
    if not check_role_permission(admin.role, "manager"):
        raise HTTPException(status_code=403, detail="Requires manager role")
    if not _docker_sock_available():
        raise HTTPException(status_code=503, detail="Docker socket not available — ensure /var/run/docker.sock is mounted")
    return [_container_status(n) for n in _KNOWN_CONTAINERS]


class ContainerAction(BaseModel):
    action: str   # start | stop | restart


@router.post("/health/containers/{container_name}/action")
def container_action(
    container_name: str,
    body: ContainerAction,
    request: Request,
    db: Session = Depends(get_db),
):
    """Start, stop, or restart a named container via Docker socket. Requires admin role."""
    admin = get_admin_from_request(request, db)
    if not check_role_permission(admin.role, "admin"):
        raise HTTPException(status_code=403, detail="Requires admin role")
    if container_name not in _KNOWN_CONTAINERS:
        raise HTTPException(status_code=400, detail="Unknown container")
    if body.action not in ("start", "stop", "restart"):
        raise HTTPException(status_code=400, detail="action must be start | stop | restart")
    if not _docker_sock_available():
        raise HTTPException(status_code=503, detail="Docker socket not available")
    if body.action == "stop" and container_name == "pinplot_backend":
        raise HTTPException(status_code=400, detail="Cannot stop the backend from itself — use the server directly")
    try:
        code, resp = _docker_request("POST", f"/containers/{container_name}/{body.action}", timeout=25)
        # Docker returns 204 (no content) on success, 304 if already in that state
        if code not in (200, 204, 304):
            msg = resp.get("message") if isinstance(resp, dict) else str(resp)
            raise HTTPException(status_code=502, detail=f"Docker daemon error {code}: {msg}")
        return {"ok": True, "container": container_name, "action": body.action}
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


@router.get("/health/system")
def health_system(request: Request, db: Session = Depends(get_db)):
    """Return disk usage, DB size, uptime, and key table row counts."""
    admin = get_admin_from_request(request, db)
    if not check_role_permission(admin.role, "manager"):
        raise HTTPException(status_code=403, detail="Requires manager role")

    result: dict = {}

    try:
        total, used, free = shutil.disk_usage("/")
        result["disk"] = {
            "total_gb": round(total / 1e9, 1),
            "used_gb":  round(used  / 1e9, 1),
            "free_gb":  round(free  / 1e9, 1),
            "pct":      round(used / total * 100, 1),
        }
    except Exception:
        result["disk"] = None

    try:
        with open("/proc/uptime") as f:
            uptime_secs = float(f.read().split()[0])
        days, rem = divmod(int(uptime_secs), 86400)
        hours, rem = divmod(rem, 3600)
        minutes = rem // 60
        result["uptime"] = f"{days}d {hours}h {minutes}m"
    except Exception:
        result["uptime"] = "—"

    try:
        from sqlalchemy import text
        row = db.execute(text("SELECT pg_size_pretty(pg_database_size(current_database())) AS sz")).fetchone()
        result["db_size"] = row[0] if row else "—"
    except Exception:
        result["db_size"] = "—"

    try:
        from sqlalchemy import text
        tables = ["users", "ble_tags", "app_logs", "audit_logs", "pois"]
        counts = {}
        for t in tables:
            try:
                r = db.execute(text(f"SELECT COUNT(*) FROM {t}")).fetchone()
                counts[t] = r[0] if r else 0
            except Exception:
                counts[t] = "—"
        result["table_counts"] = counts
    except Exception:
        result["table_counts"] = {}

    return result


# ─────────────────────────────────────────────────────────────────────────────
# SendGrid email statistics
# ─────────────────────────────────────────────────────────────────────────────

@router.get("/sendgrid/alert-device-stats")
def get_alert_device_email_stats(
    preset: str = Query("current_month", description="today | last_7_days | current_month | custom"),
    start_date: Optional[str] = Query(None, description="YYYY-MM-DD, required for custom"),
    end_date: Optional[str] = Query(None, description="YYYY-MM-DD, required for custom"),
    alert_type: Optional[str] = Query(None, description="Optional alert type filter, e.g. battery_low"),
    device_imei: Optional[str] = Query(None, description="Optional device IMEI contains filter"),
    limit: int = Query(20, ge=1, le=100),
    request: Request = None,
    db: Session = Depends(get_db),
):
    """Top alert/device rows by estimated generated emails for a date range."""
    get_admin_from_request(request, db)

    start_dt, end_dt_exclusive, applied_start, applied_end = _resolve_stats_date_range(
        preset=preset,
        start_date=start_date,
        end_date=end_date,
    )

    raw_alerts = db.query(PortalAlert).filter(
        PortalAlert.created_at >= start_dt,
        PortalAlert.created_at < end_dt_exclusive,
    ).all()

    alert_type_filter = (alert_type or "").strip().lower()
    imei_filter = (device_imei or "").strip().lower()

    alerts = []
    for alert in raw_alerts:
        if alert_type_filter and (alert.alert_type or "").strip().lower() != alert_type_filter:
            continue
        alerts.append(alert)

    # Cache BLE tags for fast device resolution
    tag_ids = {a.tag_id for a in alerts if a.tag_id is not None}
    tag_map: dict[str, BLETag] = {}
    if tag_ids:
        tags = db.query(BLETag).filter(BLETag.id.in_(list(tag_ids))).all()
        tag_map = {str(t.id): t for t in tags}

    group_ids = {str(a.usergroup_id) for a in alerts}
    group_map: dict[str, UserGroup] = {}
    if group_ids:
        groups = db.query(UserGroup).filter(UserGroup.id.in_(list(group_ids))).all()
        group_map = {str(g.id): g for g in groups}

    # Aggregate by (alert_type, usergroup_id, device_imei)
    buckets: dict[tuple[str, str, str], dict] = {}
    for alert in alerts:
        group_id = str(alert.usergroup_id)
        alert_type = alert.alert_type or "unknown"
        tag = tag_map.get(str(alert.tag_id)) if alert.tag_id is not None else None

        device_imei = _extract_device_imei(tag, alert.meta_data)
        device_label = _extract_device_label(tag, device_imei)

        if imei_filter and imei_filter not in (device_imei or "").lower():
            continue

        group = group_map.get(group_id)
        if group:
            group_display = group.name or group.slug or group_id
        else:
            group_display = group_id

        key = (alert_type, group_id, device_imei)
        row = buckets.get(key)
        if not row:
            row = {
                "alert_type": alert_type,
                "usergroup_id": group_id,
                "usergroup_name": group_display,
                "device_imei": device_imei,
                "device_label": device_label,
                "alerts": 0,
            }
            buckets[key] = row
        row["alerts"] += 1

    # Resolve recipients once per (group, alert_type)
    recipient_cache: dict[tuple[str, str], list[str]] = {}
    results = []
    for row in buckets.values():
        cache_key = (row["usergroup_id"], row["alert_type"])
        recipients = recipient_cache.get(cache_key)
        if recipients is None:
            recipients = _emails_for_group_alert_type(
                db,
                usergroup_id=row["usergroup_id"],
                alert_type=row["alert_type"],
            )
            recipient_cache[cache_key] = recipients

        recipient_count = len(recipients)
        generated_emails = row["alerts"] * recipient_count

        results.append({
            **row,
            "recipient_count": recipient_count,
            "generated_emails": generated_emails,
            "recipients": recipients,
        })

    results.sort(key=lambda r: (r["generated_emails"], r["alerts"]), reverse=True)

    return {
        "preset": preset,
        "start_date": applied_start,
        "end_date": applied_end,
        "applied_filters": {
            "alert_type": alert_type_filter or None,
            "device_imei": imei_filter or None,
        },
        "total_rows": len(results),
        "rows": results[:limit],
    }

@router.get("/sendgrid/stats")
def get_sendgrid_stats(
    start_date: str = "2026-01-01",
    aggregated_by: str = "month",
    request: Request = None,
    db: Session = Depends(get_db)
):
    """Proxy SendGrid stats API — keeps the API key server-side."""
    get_admin_from_request(request, db)

    import os, httpx
    from datetime import date

    api_key = (
        os.getenv("TWILIO_API_KEY", "") or
        os.getenv("TWILIO_API_SECRET", "") or
        os.getenv("TWILIO_AUTH_TOKEN", "") or
        os.getenv("SENDGRID_API_KEY", "")
    )
    if not api_key:
        raise HTTPException(status_code=503, detail="Email API key not configured")

    end_date = date.today().isoformat()
    url = (
        f"https://api.sendgrid.com/v3/stats"
        f"?start_date={start_date}&end_date={end_date}&aggregated_by={aggregated_by}"
    )
    try:
        resp = httpx.get(url, headers={"Authorization": f"Bearer {api_key}"}, timeout=10)
        resp.raise_for_status()
        return resp.json()
    except httpx.HTTPStatusError as exc:
        raise HTTPException(status_code=exc.response.status_code,
                            detail=f"SendGrid error: {exc.response.text}")
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Failed to reach SendGrid: {exc}")


# ─────────────────────────────────────────────────────────────────────────────
# BLE Tag Registration & Discovery
#
# Manages pure-BLE tags identified by mac_address (tag_type='ble').
# These are separate from GPS trackers (tracksolid / scope / series_3) which
# carry an IMEI.  BLE tags are registered by MAC address and then tracked
# indoors via the Pareto Anywhere → pareto_bridge pipeline.
# ─────────────────────────────────────────────────────────────────────────────

class BLETagCreate(BaseModel):
    mac_address: str                      # e.g. "27:13:C8:6C:41:15" or "2713c86c4115"
    device_name: Optional[str] = None
    description: Optional[str] = None
    usergroup_id: Optional[UUID] = None   # assign to a tenant; defaults to first active group
    is_active: bool = True


class BLETagUpdate(BaseModel):
    device_name: Optional[str] = None
    description: Optional[str] = None
    is_active: Optional[bool] = None


class BLETagOut(BaseModel):
    id: UUID
    mac_address: str
    device_name: Optional[str]
    description: Optional[str]
    is_active: bool
    last_seen: Optional[datetime]
    # current indoor position (if known)
    floor_id: Optional[UUID] = None
    zone: Optional[str] = None
    rssi: Optional[int] = None
    indoor_last_seen: Optional[datetime] = None
    class Config: from_attributes = True


class BLETagDiscovered(BaseModel):
    """An unregistered MAC address recently seen by Pareto."""
    mac_address: str
    rssi: Optional[int]
    zone: Optional[str]
    floor_id: Optional[UUID]
    last_seen: Optional[datetime]


def _normalise_mac(raw: str) -> str:
    """Normalise a MAC to 12-char lowercase hex with no separators."""
    return raw.lower().replace(":", "").replace("-", "").replace(".", "").strip()


@router.get("/ble-tags", response_model=List[BLETagOut])
def list_ble_tags(request: Request, db: Session = Depends(get_db)):
    """List all registered BLE-type tags with their latest indoor position."""
    get_admin_from_request(request, db)
    tags = (
        db.query(BLETag)
        .filter(BLETag.tag_type == "ble")
        .order_by(BLETag.added_at.desc())
        .all()
    )
    results = []
    for tag in tags:
        pos = (
            db.query(TagIndoorPosition)
            .filter(TagIndoorPosition.tag_id == tag.mac_address)
            .first()
            if tag.mac_address else None
        )
        out = BLETagOut(
            id=tag.id,
            mac_address=tag.mac_address or "",
            device_name=tag.device_name,
            description=tag.description,
            is_active=tag.is_active,
            last_seen=tag.last_seen,
            floor_id=pos.floor_id if pos else None,
            zone=pos.zone if pos else None,
            rssi=pos.rssi if pos else None,
            indoor_last_seen=pos.last_seen if pos else None,
        )
        results.append(out)
    return results


@router.post("/ble-tags", response_model=BLETagOut, status_code=201)
def register_ble_tag(data: BLETagCreate, request: Request, db: Session = Depends(get_db)):
    """Register a new BLE tag by MAC address."""
    admin = get_admin_from_request(request, db)
    if not check_role_permission(admin.role, "manager"):
        raise HTTPException(status_code=403, detail="Requires manager role")

    mac = _normalise_mac(data.mac_address)
    if not mac or len(mac) != 12:
        raise HTTPException(
            status_code=422,
            detail=f"Invalid MAC address '{data.mac_address}'. "
                   "Expected 12 hex characters e.g. 2713c86c4115 or 27:13:C8:6C:41:15"
        )

    # Duplicate check
    existing = db.query(BLETag).filter(BLETag.mac_address == mac).first()
    if existing:
        raise HTTPException(
            status_code=409,
            detail=f"A BLE tag with MAC {mac} already exists (id={existing.id})"
        )

    tag = BLETag(
        imei=None,           # migration 048 makes imei nullable for tag_type='ble'
        mac_address=mac,
        tag_type="ble",
        device_name=data.device_name,
        description=data.description,
        is_active=data.is_active,
    )
    db.add(tag)
    db.commit()
    db.refresh(tag)
    return BLETagOut(
        id=tag.id,
        mac_address=tag.mac_address,
        device_name=tag.device_name,
        description=tag.description,
        is_active=tag.is_active,
        last_seen=tag.last_seen,
    )


@router.get("/ble-tags/{tag_id}", response_model=BLETagOut)
def get_ble_tag(tag_id: str, request: Request, db: Session = Depends(get_db)):
    """Get a single registered BLE tag by its UUID."""
    get_admin_from_request(request, db)
    tag = db.query(BLETag).filter(BLETag.id == tag_id, BLETag.tag_type == "ble").first()
    if not tag:
        raise HTTPException(status_code=404, detail="BLE tag not found")
    pos = (
        db.query(TagIndoorPosition)
        .filter(TagIndoorPosition.tag_id == tag.mac_address)
        .first()
        if tag.mac_address else None
    )
    return BLETagOut(
        id=tag.id,
        mac_address=tag.mac_address or "",
        device_name=tag.device_name,
        description=tag.description,
        is_active=tag.is_active,
        last_seen=tag.last_seen,
        floor_id=pos.floor_id if pos else None,
        zone=pos.zone if pos else None,
        rssi=pos.rssi if pos else None,
        indoor_last_seen=pos.last_seen if pos else None,
    )


@router.put("/ble-tags/{tag_id}", response_model=BLETagOut)
def update_ble_tag(tag_id: str, data: BLETagUpdate,
                   request: Request, db: Session = Depends(get_db)):
    """Update device_name, description or is_active for a BLE tag."""
    admin = get_admin_from_request(request, db)
    if not check_role_permission(admin.role, "manager"):
        raise HTTPException(status_code=403, detail="Requires manager role")
    tag = db.query(BLETag).filter(BLETag.id == tag_id, BLETag.tag_type == "ble").first()
    if not tag:
        raise HTTPException(status_code=404, detail="BLE tag not found")
    if data.device_name is not None: tag.device_name = data.device_name
    if data.description  is not None: tag.description  = data.description
    if data.is_active    is not None: tag.is_active    = data.is_active
    db.commit()
    db.refresh(tag)
    pos = (
        db.query(TagIndoorPosition)
        .filter(TagIndoorPosition.tag_id == tag.mac_address)
        .first()
        if tag.mac_address else None
    )
    return BLETagOut(
        id=tag.id,
        mac_address=tag.mac_address or "",
        device_name=tag.device_name,
        description=tag.description,
        is_active=tag.is_active,
        last_seen=tag.last_seen,
        floor_id=pos.floor_id if pos else None,
        zone=pos.zone if pos else None,
        rssi=pos.rssi if pos else None,
        indoor_last_seen=pos.last_seen if pos else None,
    )


@router.delete("/ble-tags/{tag_id}")
def delete_ble_tag(tag_id: str, request: Request, db: Session = Depends(get_db)):
    """Permanently remove a BLE tag registration."""
    admin = get_admin_from_request(request, db)
    if not check_role_permission(admin.role, "manager"):
        raise HTTPException(status_code=403, detail="Requires manager role")
    tag = db.query(BLETag).filter(BLETag.id == tag_id, BLETag.tag_type == "ble").first()
    if not tag:
        raise HTTPException(status_code=404, detail="BLE tag not found")
    # Remove associated indoor position so stale data doesn't linger
    if tag.mac_address:
        db.query(TagIndoorPosition).filter(
            TagIndoorPosition.tag_id == tag.mac_address
        ).delete()
    db.delete(tag)
    db.commit()
    return {"detail": "BLE tag deleted"}


@router.get("/ble-tags/discovered", response_model=List[BLETagDiscovered])
def discovered_ble_tags(
    minutes: int = Query(10, ge=1, le=60, description="How far back (minutes) to look"),
    request: Request = None,
    db: Session = Depends(get_db),
):
    """Return MAC addresses recently seen by indoor gateways that are NOT yet registered.

    Pareto Anywhere forwards every raddec it hears to the backend.  The
    pareto_bridge service rejects unregistered MACs (whitelist filter) but
    TagIndoorPosition is only written for registered tags.  Instead we
    query the raw recent sightings from a separate lightweight table — but
    since we don't have a raw-sightings table yet we fall back to querying
    TagIndoorPosition rows whose tag_id is NOT in ble_tags.mac_address.

    Note: after migration 048 the pareto_bridge can be relaxed to also
    write unregistered MACs into a `ble_raw_sightings` staging table (future
    work).  For now this endpoint returns any position rows that survived
    the whitelist (i.e. recently registered but without device metadata).
    """
    get_admin_from_request(request, db)

    cutoff = datetime.utcnow() - timedelta(minutes=minutes)

    # All MAC addresses that ARE registered
    registered_macs = {
        row[0]
        for row in db.query(BLETag.mac_address)
        .filter(BLETag.tag_type == "ble", BLETag.mac_address.isnot(None))
        .all()
    }

    # Recent indoor positions whose tag_id is not in registered_macs
    recent_positions = (
        db.query(TagIndoorPosition)
        .filter(TagIndoorPosition.last_seen >= cutoff)
        .all()
    )

    discovered = [
        BLETagDiscovered(
            mac_address=pos.tag_id,
            rssi=pos.rssi,
            zone=pos.zone,
            floor_id=pos.floor_id,
            last_seen=pos.last_seen,
        )
        for pos in recent_positions
        if pos.tag_id not in registered_macs
    ]
    return discovered


@router.get("/tags-with-subscriptions")
def list_tags_with_subscriptions(
    usergroup_id: str = Query(..., description="User group ID to filter tags"),
    request: Request = None,
    db: Session = Depends(get_db),
):
    """Return GPS tracker tags (with IMEIs) for a specific tenant/user group,
    including their trip subscription status from device_state.
    
    Returns tags that:
    - Belong to users in the specified user group (via domain OR portal_users)
    - Have an IMEI (GPS trackers, not BLE-only tags)
    - Include trip_subscribed status from DeviceState table
    """
    get_admin_from_request(request, db)
    
    from app.models import PortalUser, User, UserGroup
    from uuid import UUID
    
    # Validate UUID
    try:
        group_uuid = UUID(usergroup_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid usergroup_id format")
    
    # Get the user group to check for email_domain
    group = db.query(UserGroup).filter(UserGroup.id == usergroup_id).first()
    if not group:
        raise HTTPException(status_code=404, detail="User group not found")
    
    # Build list of domains for this group
    domains = []
    if group.email_domain:
        domains = [d.strip().lower() for d in group.email_domain.split(',') if d.strip()]
    
    user_ids = []
    
    # Source 1: Domain-matched users (auto-assigned via email domain)
    if domains:
        domain_filters = [User.email.ilike(f"%@{domain}") for domain in domains]
        domain_users = db.query(User.id).filter(or_(*domain_filters)).all()
        user_ids.extend([str(uid[0]) for uid in domain_users])
    
    # Source 2: Manually assigned users (via PortalUser table)
    portal_users = (
        db.query(User.id)
        .join(PortalUser, User.email == PortalUser.email)
        .filter(PortalUser.usergroup_id == usergroup_id)
        .all()
    )
    user_ids.extend([str(uid[0]) for uid in portal_users])
    
    # Remove duplicates
    user_ids = list(set(user_ids))
    
    if not user_ids:
        return []
    
    # Get all tags owned by these users that have IMEIs (GPS trackers)
    tags = (
        db.query(BLETag)
        .filter(
            BLETag.user_id.in_(user_ids),
            BLETag.imei.isnot(None),
            BLETag.is_active == True
        )
        .order_by(BLETag.added_at.desc())
        .all()
    )
    
    # Build DeviceState lookup for trip_subscribed status
    device_state_map = {}
    imeis = [tag.imei for tag in tags if tag.imei]
    if imeis:
        states = db.query(DeviceState).filter(DeviceState.device_imei.in_(imeis)).all()
        for state in states:
            device_state_map[state.device_imei] = {
                'trip_subscribed': state.trip_subscribed,
                'last_position_ts': state.last_position_ts,
                'last_tracklist_pull_at': state.last_tracklist_pull_at
            }
    
    # Build response
    result = []
    for tag in tags:
        device_state = device_state_map.get(tag.imei, {})
        result.append({
            'id': str(tag.id),
            'imei': tag.imei,
            'device_name': tag.device_name,
            'description': tag.description,
            'tag_type': tag.tag_type,
            'is_active': tag.is_active,
            'last_seen': tag.last_seen.isoformat() if tag.last_seen else None,
            'battery_level': tag.battery_level,
            'device_state': {
                'trip_subscribed': device_state.get('trip_subscribed', False),
                'last_position_ts': device_state.get('last_position_ts').isoformat() if device_state.get('last_position_ts') else None,
                'last_tracklist_pull_at': device_state.get('last_tracklist_pull_at').isoformat() if device_state.get('last_tracklist_pull_at') else None
            } if device_state else None
        })
    
    return result


class TripSubscriptionUpdate(BaseModel):
    trip_subscribed: bool


@router.put("/devices/{imei}/trip-subscription")
def update_device_trip_subscription(
    imei: str,
    data: TripSubscriptionUpdate,
    request: Request,
    db: Session = Depends(get_db)
):
    """
    Update trip subscription status for a device (manager+).
    
    Creates DeviceState if it doesn't exist.
    """
    admin = get_admin_from_request(request, db)
    if not check_role_permission(admin.role, "manager"):
        raise HTTPException(status_code=403, detail="Requires manager role")
    
    # Verify device exists
    device = db.query(BLETag).filter(BLETag.imei == imei).first()
    if not device:
        raise HTTPException(status_code=404, detail=f"Device {imei} not found")
    
    # Get or create DeviceState
    device_state = db.query(DeviceState).filter(DeviceState.device_imei == imei).first()
    if not device_state:
        device_state = DeviceState(
            device_imei=imei,
            trip_subscribed=data.trip_subscribed
        )
        db.add(device_state)
        logger.info(f"Created DeviceState for {imei} with trip_subscribed={data.trip_subscribed}")
    else:
        old_value = device_state.trip_subscribed
        device_state.trip_subscribed = data.trip_subscribed
        logger.info(f"Updated {imei} trip_subscribed: {old_value} → {data.trip_subscribed}")
    
    db.commit()
    
    # Log audit
    log_audit(
        db,
        str(admin.id),
        "update_trip_subscription",
        "DeviceState",
        imei,
        old_value={"trip_subscribed": not data.trip_subscribed} if device_state else None,
        new_value={"trip_subscribed": data.trip_subscribed},
        description=f"{'Subscribed' if data.trip_subscribed else 'Unsubscribed'} device {imei} for trip processing",
        ip_address=request.client.host if request.client else None
    )
    
    return {
        "imei": imei,
        "trip_subscribed": device_state.trip_subscribed,
        "message": f"Device {'subscribed' if data.trip_subscribed else 'unsubscribed'} successfully"
    }
