from fastapi import FastAPI, Depends, HTTPException, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from datetime import datetime, timedelta
from typing import List, Dict, Optional
from uuid import UUID
from pydantic import BaseModel, EmailStr, field_validator
import random
import secrets
import os
import logging
from sqlalchemy.orm import Session

from app.database import get_db, init_db
from app.models import User, VerificationPIN, BLETag, POI, POITrackerLink, GeofenceAlert, PasswordResetToken, GeofenceState, AppFeatures, PortalUser
from app.models_admin import AdminUser, AppLog, AuditLog, BillingData, TagPackage
from app.auth import verify_password, get_password_hash, create_access_token, decode_token
from app.admin_auth import hash_password as admin_hash_password
from app.services.email_service import EmailService
from app.services.mzone_service import mzone_service
from app.services.geofence_service import GeofenceService
from app.services.location_poller_service import location_poller
from app.routes_admin import router as admin_router
from app.services.device_providers import DeviceProviderFactory
import asyncio
from app.schemas.poi import (
    POICreate, POIUpdate, POIResponse, POIWithArmedStatus,
    POITrackerLinkCreate, POITrackerLinkResponse,
    GeofenceAlertResponse, AlertsListResponse,
    PostcodeSearchRequest, PostcodeSearchResponse
)

# Pydantic models
class UserCreate(BaseModel):
    email: EmailStr
    password: str
    first_name: Optional[str] = None
    last_name: Optional[str] = None
    phone: Optional[str] = None
    is_admin: bool = False

class UserLogin(BaseModel):
    email: EmailStr
    password: str

class SendVerificationCodeRequest(BaseModel):
    email: EmailStr

class VerifyPINRequest(BaseModel):
    email: EmailStr
    pin: str

class ForgotPasswordRequest(BaseModel):
    email: EmailStr

class ResetPasswordRequest(BaseModel):
    token: str
    new_password: str

class Token(BaseModel):
    access_token: str
    token_type: str = "bearer"

class UserResponse(BaseModel):
    id: UUID
    email: str
    first_name: Optional[str]
    last_name: Optional[str]
    phone: Optional[str]
    email_verified: bool
    email_alerts_enabled: bool
    is_active: bool
    is_admin: bool
    created_at: datetime
    
    class Config:
        from_attributes = True

class MockLocationTestRequest(BaseModel):
    tracker_id: str
    latitude: float
    longitude: float

class BLETagCreate(BaseModel):
    imei: str
    device_name: Optional[str] = None
    device_model: Optional[str] = None
    description: Optional[str] = None
    mac_address: Optional[str] = None
    tag_type: Optional[str] = 'scope'  # 'tracksolid' | 'scope'
    battery_level: Optional[int] = None  # Initial battery % from validation (TrackSolid)

class BLETagResponse(BaseModel):
    id: str
    imei: str
    device_name: Optional[str]
    device_model: Optional[str]
    description: Optional[str]
    mac_address: Optional[str]
    tag_type: Optional[str]
    is_active: bool
    last_seen: Optional[datetime]
    battery_level: Optional[int]
    added_at: datetime
    
    @field_validator('id', mode='before')
    @classmethod
    def coerce_uuid_to_str(cls, v):
        return str(v)
    
    class Config:
        from_attributes = True

class BLETagWithUser(BaseModel):
    """BLE Tag with associated user information for admin billing"""
    id: str
    imei: str
    device_name: Optional[str]
    device_model: Optional[str]
    is_active: bool
    added_at: datetime
    activated_at: datetime  # Alias for added_at for clarity
    user_id: str
    user_email: str
    
    user_name: str
    
    @field_validator('id', 'user_id', mode='before')
    @classmethod
    def coerce_uuid_to_str(cls, v):
        return str(v)
    
    class Config:
        from_attributes = True
    
    @classmethod
    def from_db_model(cls, tag, user_email: str, user_name: str = ""):
        """Create from BLETag and user email/name with UUID conversion"""
        return cls(
            id=str(tag.id),
            imei=tag.imei,
            device_name=tag.device_name,
            device_model=tag.device_model,
            is_active=tag.is_active,
            added_at=tag.added_at,
            activated_at=tag.added_at,
            user_id=str(tag.user_id),
            user_email=user_email,
            user_name=user_name
        )

class UserWithTags(BaseModel):
    """User information with their BLE tags for admin billing"""
    id: str
    email: str
    first_name: Optional[str]
    last_name: Optional[str]
    full_name: str
    is_active: bool
    created_at: datetime
    tag_count: int
    tags: List[BLETagResponse]
    
    class Config:
        from_attributes = True

app = FastAPI(
    title="BLE Tracker API",
    version="0.1.0",
    description="Backend API for BLE tag tracking system"
)

# Include admin router
app.include_router(admin_router)

# Include portal router (customer portal auth)
from app.routes_portal import router as portal_router  # noqa: E402
app.include_router(portal_router)

# Include beacon-scan router
from app.routes_beacons import router as beacons_router  # noqa: E402
app.include_router(beacons_router)

# Include admin ops router (Docker container management)
from app.routes_ops import router as ops_router  # noqa: E402
app.include_router(ops_router)

# Include HIVE tracking router
from app.routes_hive import router as hive_router  # noqa: E402
app.include_router(hive_router)

# Include Floor Plan router (BLE indoor tracking via Pareto Anywhere)
from app.routes_floorplan import router as floorplan_router  # noqa: E402
app.include_router(floorplan_router)

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# CORS middleware - restrict to known origins only
_cors_origins_env = os.getenv("CORS_ORIGINS", "https://beacontelematics.co.uk,https://www.beacontelematics.co.uk")
_allowed_origins = [o.strip() for o in _cors_origins_env.split(",") if o.strip()]
app.add_middleware(
    CORSMiddleware,
    allow_origins=_allowed_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Security
security = HTTPBearer()

# Initialize email service
email_service = EmailService()

# Initialize database on startup
@app.on_event("startup")
async def startup_event():
    init_db()
    
    # Note: Admin tables are created and populated via Alembic migrations and init_admin.py script
    # Admin user initialization happens via:
    #   1. Database migrations (alembic upgrade head)
    #   2. Init script (python init_admin.py)
    # Running table creation here would conflict with Alembic
    
    print("Database initialized!")
    print(f"SMTP configured: {email_service.smtp_host}:{email_service.smtp_port}")
    print("MailHog Web UI available at: http://localhost:8025")
    print("Admin Portal available at: /admin/index.html")
    print("Admin API available at: /api/admin/")
    
    # Wire up DB log handler so backend logs appear in admin portal
    from app.db_log_handler import setup_db_logging
    import logging
    setup_db_logging(level=logging.WARNING)
    print("Admin log handler attached (WARNING+)")

    # Start background location poller
    asyncio.create_task(location_poller.start())
    print("🚀 Location Poller Service started (60-second interval)")

    # Start HIVE proximity tracking sweeper
    from app.services import hive_service as _hive_svc
    _hive_svc.start_sweeper()
    print("🛡️  HIVE sweeper started (2-minute freshness sweep)")

    # Start Pareto Anywhere bridge for floor-plan BLE indoor tracking
    from app.services import pareto_bridge as _pareto
    _pareto.start_bridge()
    print(f"📡 Pareto bridge started (url={_pareto.PARETO_URL})")

    # Start GDPR cleanup task (runs daily)
    asyncio.create_task(_gdpr_cleanup_loop())
    print("📜 GDPR cleanup task started (runs every 24 h)")

@app.on_event("shutdown")
async def shutdown_event():
    location_poller.stop()
    from app.services import hive_service as _hive_svc
    _hive_svc.stop_sweeper()
    from app.services import pareto_bridge as _pareto
    await _pareto.stop_bridge()
    print("🛑 Location Poller Service stopped")
    print("🛑 HIVE sweeper stopped")
    print("🛑 Pareto bridge stopped")


# ---------------------------------------------------------------------------
# GDPR cleanup — hard-delete tag + all data 7 days after package expiry
# ---------------------------------------------------------------------------
TAG_DELETE_GRACE_DAYS = 7   # days after expiry_date before hard deletion

async def _gdpr_cleanup_loop():
    """Run every 24 hours.

    Step 1 — Warning (fires once at expiry):
        For every tag whose expiry_date has passed AND gdpr_deletion_warned_at
        is NULL, send one inbox alert + one email to the owning group and record
        the warning timestamp.

    Step 2 — Hard delete (fires at expiry + 7 days):
        For every tag whose expiry_date + TAG_DELETE_GRACE_DAYS has passed,
        delete all associated rows (BeaconSightings, POITrackerLinks,
        GeofenceAlerts, PortalAlerts) then delete the tag row itself.
    """
    from app.database import SessionLocal
    from app.models import BeaconSighting, POITrackerLink, GeofenceAlert, PortalAlert
    import app.services.portal_alert_service as _pas

    while True:
        try:
            now = datetime.utcnow()
            delete_cutoff  = now - timedelta(days=TAG_DELETE_GRACE_DAYS)
            db: Session = SessionLocal()
            try:
                # ── Step 1: send deletion warnings ────────────────────────
                tags_to_warn = (
                    db.query(BLETag)
                    .filter(
                        BLETag.expiry_date != None,
                        BLETag.expiry_date <= now,
                        BLETag.gdpr_deletion_warned_at == None,
                    )
                    .all()
                )
                warned = 0
                for tag in tags_to_warn:
                    _pas.send_gdpr_deletion_warning(db, tag)
                    tag.gdpr_deletion_warned_at = now
                    warned += 1
                if warned:
                    db.commit()
                    print(f"[GDPR] Deletion warnings sent for {warned} expired tag(s)")

                # ── Step 2: hard-delete tags past the grace period ─────────
                tags_to_delete = (
                    db.query(BLETag)
                    .filter(
                        BLETag.expiry_date != None,
                        BLETag.expiry_date <= delete_cutoff,
                    )
                    .all()
                )
                deleted_count = 0
                for tag in tags_to_delete:
                    tag_id  = tag.id
                    tag_imei = tag.imei
                    # 1. Beacon sightings (keyed by IMEI string)
                    db.query(BeaconSighting).filter(
                        BeaconSighting.tag_id == tag_imei
                    ).delete(synchronize_session=False)
                    # 2. POI tracker links
                    db.query(POITrackerLink).filter(
                        POITrackerLink.tracker_id == tag_id
                    ).delete(synchronize_session=False)
                    # 3. Geofence alerts (NOT NULL FK — must go before tag)
                    db.query(GeofenceAlert).filter(
                        GeofenceAlert.tracker_id == tag_id
                    ).delete(synchronize_session=False)
                    # 4. Portal alerts (nullable FK — delete to keep inbox clean)
                    db.query(PortalAlert).filter(
                        PortalAlert.tag_id == tag_id
                    ).delete(synchronize_session=False)
                    # 5. Delete the tag itself
                    db.delete(tag)
                    deleted_count += 1
                    print(f"[GDPR] Hard-deleted tag {tag_imei} (expired {tag.expiry_date})")
                if deleted_count:
                    db.commit()
                    print(f"[GDPR] Hard-deleted {deleted_count} expired tag(s) and all associated data")
            finally:
                db.close()
        except Exception as exc:
            print(f"[GDPR] Cleanup error: {exc}")
        await asyncio.sleep(86400)  # 24 h

# Demo data - simulating BLE tags
DEMO_TAGS = [
    {
        "id": "tag-001",
        "name": "Office Tag",
        "battery": 85,
        "status": "active",
        "last_seen": "2024-02-28T10:30:00Z"
    },
    {
        "id": "tag-002",
        "name": "Car Tag",
        "battery": 92,
        "status": "active",
        "last_seen": "2024-02-28T10:25:00Z"
    },
    {
        "id": "tag-003",
        "name": "Backpack Tag",
        "battery": 67,
        "status": "active",
        "last_seen": "2024-02-28T10:28:00Z"
    }
]

# Demo locations
DEMO_LOCATIONS = {
    "tag-001": {"latitude": 37.7749, "longitude": -122.4194, "address": "San Francisco, CA"},
    "tag-002": {"latitude": 37.7849, "longitude": -122.4094, "address": "Near Golden Gate"},
    "tag-003": {"latitude": 37.7649, "longitude": -122.4294, "address": "Mission District"}
}

def get_current_user(credentials: HTTPAuthorizationCredentials = Depends(security), db: Session = Depends(get_db)) -> User:
    """Get current authenticated user"""
    token = credentials.credentials
    payload = decode_token(token)
    
    if payload is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid authentication credentials"
        )
    
    user_id = payload.get("sub")
    if user_id is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid token payload"
        )
    
    user = db.query(User).filter(User.id == user_id).first()
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User not found"
        )
    
    if not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Inactive user"
        )
    
    return user

@app.get("/")
def root():
    """Root endpoint"""
    return {
        "message": "BLE Tracker API",
        "version": "0.1.0",
        "status": "running",
        "timestamp": datetime.utcnow().isoformat()
    }

@app.get("/health")
def health_check():
    """Health check endpoint"""
    return {
        "status": "healthy",
        "timestamp": datetime.utcnow().isoformat()
    }

@app.get("/api/health")
def api_health_check():
    """API health check endpoint"""
    return {
        "status": "healthy",
        "timestamp": datetime.utcnow().isoformat()
    }

@app.get("/api/branding")
def branding():
    """Public branding endpoint — drives per-tenant white-label theming.

    All values come from BRAND_* environment variables so the same code can be
    deployed to PinPlot, BeaconTelematics, etc. without touching source. The
    frontend reads this at boot and overrides <title>, theme-color, header
    text, primary colour, etc. PinPlot defaults are kept for back-compat when
    no env vars are set."""
    return {
        "name":         os.getenv("BRAND_NAME", "PinPlot"),
        "product":      os.getenv("BRAND_PRODUCT", "PinPlot Customer Portal"),
        "domain":       os.getenv("BRAND_DOMAIN", "pinplot.me"),
        "supportEmail": os.getenv("BRAND_SUPPORT_EMAIL", "support@pinplot.me"),
        "fromEmail":    os.getenv("BRAND_FROM_EMAIL", "noreply@pinplot.me"),
        "primaryColor": os.getenv("BRAND_PRIMARY_COLOR", "#3B82F6"),
        "themeColor":   os.getenv("BRAND_THEME_COLOR", "#0F1117"),
        "tagline":      os.getenv("BRAND_TAGLINE", "Live asset tracking, geofencing, and reporting."),
        # Per-tenant MapTiler key. No default — each tenant MUST set
        # MAPTILER_KEY in backend/.env (free-tier keys are origin-restricted).
        "maptilerKey":  os.getenv("MAPTILER_KEY") or None,
    }


@app.get("/api/manifest")
def manifest():
    """Deployment manifest endpoint - lists API capabilities and version info"""
    return {
        "deployment": {
            "timestamp": datetime.utcnow().isoformat(),
            "version": "beacon-telematics-api",
            "environment": os.getenv("NODE_ENV", "production")
        },
        "api": {
            "version": "v1",
            "endpoints": {
                "health": "/api/health",
                "manifest": "/api/manifest",
                "auth": "/api/v1/auth",
                "ble_tags": "/api/v1/ble-tags",
                "tags": "/api/v1/tags",
                "trips": "/api/trips",
                "pois": "/api/v1/pois",
                "alerts": "/api/v1/alerts"
            }
        },
        "status": "operational"
    }

# Authentication endpoints

def _auto_provision_portal_user(db: Session, user: "User") -> None:
    """Auto-create a PortalUser for a self-registered User if their email domain
    matches exactly one active UserGroup with email_domain configured.

    Rules:
      - Skipped if no UserGroup has a matching email_domain.
      - Skipped if a PortalUser with that email already exists in *any* group.
      - The new PortalUser is created as role='admin' (non-group-admin), active.
        A random password is set — the user logs into the customer-facing app
        directly; the portal password can be set later via "Forgot Password" flow.
      - If multiple groups match (unlikely but valid), a PortalUser is created in each.
    """
    from app.models import UserGroup as _UG, PortalUser as _PU
    from app.admin_auth import hash_password as _hash
    import secrets as _secrets
    import uuid as _uuid

    email = user.email.lower().strip()
    if not email or "@" not in email:
        return
    domain = email.split("@")[-1].lower()

    # Already has a portal account somewhere?
    if db.query(_PU).filter(_PU.email == email).first():
        return

    matching_groups = [
        g for g in db.query(_UG).filter(_UG.email_domain.isnot(None), _UG.is_active == True).all()
        if domain in [d.strip().lower() for d in (g.email_domain or "").split(",") if d.strip()]
    ]
    if not matching_groups:
        return

    for group in matching_groups:
        temp_pw = _secrets.token_urlsafe(16)
        portal_user = _PU(
            id=str(_uuid.uuid4()),
            usergroup_id=group.id,
            email=email,
            hashed_password=_hash(temp_pw),
            first_name=user.first_name or None,
            last_name=user.last_name or None,
            is_active=True,
            is_group_admin=False,
            role="admin",
        )
        db.add(portal_user)
        logger.info(
            "👤 Auto-provisioned PortalUser %s into group '%s' (domain match: @%s)",
            email, group.name, domain,
        )
    db.commit()


@app.post("/api/v1/auth/register", response_model=Token)
def register(user_data: UserCreate, db: Session = Depends(get_db)):
    """Register a new user — only called after email/PIN verification and details entry"""
    # Require that a verified PIN exists for this email (proves email ownership)
    verified_pin = db.query(VerificationPIN).filter(
        VerificationPIN.email == user_data.email,
        VerificationPIN.is_used == True
    ).order_by(VerificationPIN.created_at.desc()).first()

    if not verified_pin:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Email not verified. Please complete PIN verification first."
        )

    # Reject if already fully registered
    existing_user = db.query(User).filter(User.email == user_data.email).first()
    if existing_user and existing_user.hashed_password is not None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Email already registered"
        )

    if existing_user:
        # Partial record exists (edge case) — complete it
        existing_user.hashed_password = get_password_hash(user_data.password)
        existing_user.first_name = user_data.first_name
        existing_user.last_name = user_data.last_name
        existing_user.is_admin = user_data.is_admin
        existing_user.email_verified = True
        existing_user.is_active = True
        db.commit()
        db.refresh(existing_user)
        access_token = create_access_token(data={"sub": str(existing_user.id)})
        return {"access_token": access_token, "token_type": "bearer"}

    # Create user for the first time — all details collected, email verified
    db_user = User(
        email=user_data.email,
        hashed_password=get_password_hash(user_data.password),
        first_name=user_data.first_name,
        last_name=user_data.last_name,
        is_admin=user_data.is_admin,
        email_verified=True,
        is_active=True
    )
    db.add(db_user)
    db.commit()
    db.refresh(db_user)

    access_token = create_access_token(data={"sub": str(db_user.id)})
    return {"access_token": access_token, "token_type": "bearer"}

@app.post("/api/v1/auth/login", response_model=Token)
def login(credentials: UserLogin, db: Session = Depends(get_db)):
    """Login user"""
    user = db.query(User).filter(User.email == credentials.email).first()
    
    if not user or not verify_password(credentials.password, user.hashed_password):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect email or password"
        )
    
    if not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="User account is inactive"
        )
    
    access_token = create_access_token(data={"sub": str(user.id)})
    
    return {"access_token": access_token, "token_type": "bearer"}

@app.post("/api/v1/auth/refresh", response_model=Token)
def refresh_token(current_user: User = Depends(get_current_user)):
    """
    Refresh JWT token for active users.
    Returns a new token with extended expiration.
    Call this endpoint before the current token expires.
    """
    # Create new token with same user ID
    access_token = create_access_token(data={"sub": str(current_user.id)})
    
    return {"access_token": access_token, "token_type": "bearer"}

@app.post("/api/v1/auth/send-verification-code")
def send_verification_code(request: SendVerificationCodeRequest, db: Session = Depends(get_db)):
    """Send verification PIN to email"""
    # Check if user exists
    user = db.query(User).filter(User.email == request.email).first()
    
    # If user exists and already registered (has password) OR email is verified
    if user and (user.hashed_password is not None or user.email_verified):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Email already registered. Please sign in instead."
        )

    # Generate 6-digit PIN
    pin = email_service.generate_pin()
    expires_at = datetime.utcnow() + timedelta(minutes=10)

    # Invalidate old PINs for this email (regardless of whether user exists)
    db.query(VerificationPIN).filter(
        VerificationPIN.email == request.email,
        VerificationPIN.is_used == False
    ).update({"is_used": True})

    # Create PIN record without a user_id — user is created only after PIN is verified
    verification = VerificationPIN(
        user_id=user.id if user else None,
        email=request.email,
        pin=pin,
        expires_at=expires_at
    )
    db.add(verification)
    db.commit()
    
    # Send email
    success = email_service.send_verification_pin(request.email, pin)
    
    if not success:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to send verification email"
        )
    
    return {
        "success": True,
        "message": "Verification code sent to email",
        "expires_in_minutes": 10
    }

@app.post("/api/v1/auth/verify-pin")
def verify_pin(request: VerifyPINRequest, db: Session = Depends(get_db)):
    """Verify PIN — confirms email ownership. User is NOT created here."""
    _debug_mode = os.getenv('DEBUG', 'False').lower() == 'true'

    # DEV BYPASS: In debug mode, PIN "123456" always succeeds without checking the DB.
    if _debug_mode and request.pin == "123456":
        print(f"[DEV] Bypassing PIN verification for {request.email} (DEBUG=True, pin=123456)")
        # Invalidate any old PINs, then insert a pre-used record so /register can proceed.
        db.query(VerificationPIN).filter(
            VerificationPIN.email == request.email,
            VerificationPIN.is_used == False
        ).update({"is_used": True})
        bypass_pin = VerificationPIN(
            user_id=None,
            email=request.email,
            pin="123456",
            is_used=True,
            expires_at=datetime.utcnow() + timedelta(minutes=10),
        )
        db.add(bypass_pin)
        existing_user = db.query(User).filter(User.email == request.email).first()
        if existing_user:
            existing_user.email_verified = True
            existing_user.is_active = True
        db.commit()
        return {"success": True, "message": "Email verified successfully"}

    # Find valid, unused, non-expired PIN
    verification = db.query(VerificationPIN).filter(
        VerificationPIN.email == request.email,
        VerificationPIN.pin == request.pin,
        VerificationPIN.is_used == False,
        VerificationPIN.expires_at > datetime.utcnow()
    ).first()
    
    if not verification:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid or expired verification code"
        )
    
    # Mark PIN as used — email ownership confirmed.
    # User record is created only when /register is called with name + password.
    verification.is_used = True

    # If a pre-existing user exists (e.g. re-registration), mark email verified.
    existing_user = db.query(User).filter(User.email == request.email).first()
    if existing_user:
        existing_user.email_verified = True
        existing_user.is_active = True
    
    db.commit()
    
    return {"success": True, "message": "Email verified successfully"}

@app.post("/api/v1/auth/forgot-password")
def forgot_password(request: ForgotPasswordRequest, db: Session = Depends(get_db)):
    """Request password reset - sends email with reset link"""
    # Check if user exists
    user = db.query(User).filter(User.email == request.email).first()
    
    if not user:
        # Don't reveal that the user doesn't exist for security
        return {
            "success": True,
            "message": "If an account exists with this email, a password reset link has been sent."
        }
    
    # Generate secure reset token
    reset_token = secrets.token_urlsafe(32)
    expires_at = datetime.utcnow() + timedelta(hours=1)
    
    # Invalidate old tokens for this user
    db.query(PasswordResetToken).filter(
        PasswordResetToken.user_id == user.id,
        PasswordResetToken.is_used == False
    ).update({"is_used": True})
    db.commit()
    
    # Create new reset token
    password_reset = PasswordResetToken(
        user_id=user.id,
        email=user.email,
        token=reset_token,
        expires_at=expires_at
    )
    db.add(password_reset)
    db.commit()
    
    # Send password reset email
    success = email_service.send_password_reset_email(
        to_email=user.email,
        reset_token=reset_token,
        first_name=user.first_name
    )
    
    if not success:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to send password reset email"
        )
    
    return {
        "success": True,
        "message": "If an account exists with this email, a password reset link has been sent."
    }

@app.post("/api/v1/auth/reset-password")
def reset_password(request: ResetPasswordRequest, db: Session = Depends(get_db)):
    """Reset password using reset token"""
    # Find valid reset token
    reset_token = db.query(PasswordResetToken).filter(
        PasswordResetToken.token == request.token,
        PasswordResetToken.is_used == False,
        PasswordResetToken.expires_at > datetime.utcnow()
    ).first()
    
    if not reset_token:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid or expired reset token"
        )
    
    # Get user
    user = db.query(User).filter(User.id == reset_token.user_id).first()
    
    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User not found"
        )
    
    # Validate password length
    if len(request.new_password) < 6:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Password must be at least 6 characters long"
        )
    
    # Update password
    user.hashed_password = get_password_hash(request.new_password)
    
    # Mark token as used
    reset_token.is_used = True
    
    db.commit()
    
    return {
        "success": True,
        "message": "Password has been reset successfully"
    }

@app.get("/api/v1/auth/me", response_model=UserResponse)
def get_me(current_user: User = Depends(get_current_user)):
    """Get current user info"""
    return current_user

class UserPreferencesUpdate(BaseModel):
    email_alerts_enabled: Optional[bool] = None

@app.put("/api/v1/user/preferences", response_model=UserResponse)
def update_user_preferences(
    preferences: UserPreferencesUpdate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Update user preferences (email alerts, etc.)"""
    if preferences.email_alerts_enabled is not None:
        current_user.email_alerts_enabled = preferences.email_alerts_enabled
    
    db.commit()
    db.refresh(current_user)
    
    return current_user

class EmailUpdate(BaseModel):
    email: str

@app.put("/api/v1/user/email", response_model=UserResponse)
def update_user_email(
    email_data: EmailUpdate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Update user's email address"""
    # Validate email format
    if not email_data.email or '@' not in email_data.email:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid email format"
        )
    
    # Check if email already exists for another user
    existing_user = db.query(User).filter(
        User.email == email_data.email,
        User.id != current_user.id
    ).first()
    
    if existing_user:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Email already in use by another account"
        )
    
    # Update email
    current_user.email = email_data.email
    current_user.email_verified = False  # Require re-verification for new email
    
    db.commit()
    db.refresh(current_user)
    
    return current_user

# BLE Tag Management endpoints
@app.post("/api/v1/ble-tags", response_model=BLETagResponse)
async def add_ble_tag(
    tag_data: BLETagCreate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Add a new BLE tag to user's account.

    Validation against the vendor platform is enforced here — a tag can never
    be saved with a tag_type that doesn't match what the vendor API confirms.
    This prevents a TrackSolid IMEI being silently saved as Scope (or vice versa)
    if the client sends the wrong type.
    """
    # Normalise and validate tag_type.
    # Accept both vendor names ('scope'/'tracksolid') and the Flutter app's
    # user-facing series names ('series1'/'series2') as aliases.
    # Always store the canonical vendor name so the DB is consistent.
    _ALIAS_MAP = {"series1": "scope", "series2": "tracksolid"}
    raw_type = (tag_data.tag_type or 'scope').lower()
    tag_type = _ALIAS_MAP.get(raw_type, raw_type)
    try:
        provider = DeviceProviderFactory.get_provider(tag_type)
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Unsupported tag_type: '{tag_type}'"
        )

    # Enforce vendor validation — client cannot bypass this
    validation = await provider.validate_tag(tag_data.imei)
    if not validation.is_valid:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=validation.message,
        )

    # Check if IMEI already exists
    existing_tag = db.query(BLETag).filter(BLETag.imei == tag_data.imei).first()
    if existing_tag:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="IMEI already registered"
        )

    # Seed battery into attributes so the map marker shows it immediately.
    # Use battery_level from validation (most accurate) falling back to client-supplied.
    battery = validation.battery_level if validation.battery_level is not None else tag_data.battery_level
    initial_attributes: dict | None = None
    if battery is not None:
        initial_attributes = {
            "Battery": {"value": f"{battery}%", "show_on_map": True}
        }

    ble_tag = BLETag(
        user_id=current_user.id,
        imei=tag_data.imei,
        device_name=tag_data.device_name,
        device_model=tag_data.device_model,
        mac_address=tag_data.mac_address,
        tag_type=tag_type,
        battery_level=battery,
        attributes=initial_attributes,
    )

    # Auto-assign the default package if one is configured
    default_pkg = db.query(TagPackage).filter(
        TagPackage.is_default == True,
        TagPackage.is_active == True,
    ).first()
    if default_pkg:
        ble_tag.package_id = str(default_pkg.id)
        ble_tag.expiry_date = datetime.utcnow() + timedelta(days=default_pkg.validity_days)

    db.add(ble_tag)
    db.commit()
    db.refresh(ble_tag)

    return ble_tag


class BLETagValidateRequest(BaseModel):
    imei: str
    tag_type: str  # 'tracksolid' | 'scope'


class BLETagValidateResponse(BaseModel):
    is_valid: bool
    message: str
    battery_level: Optional[int] = None  # Battery % for TrackSolid tags


@app.post("/api/v1/ble-tags/validate", response_model=BLETagValidateResponse)
async def validate_ble_tag(
    request: BLETagValidateRequest,
    current_user: User = Depends(get_current_user),
):
    """
    Validate an IMEI against its vendor platform before the tag is saved.

    - TrackSolid: checks the Beacontelematics FleetTrack account.
    - Scope: structural IMEI / GUID check (MZone polling confirms live match).

    Returns {is_valid, message}. The client should only call POST /api/v1/ble-tags
    after receiving is_valid=true.
    """
    try:
        provider = DeviceProviderFactory.get_provider(request.tag_type)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    result = await provider.validate_tag(request.imei)
    return BLETagValidateResponse(
        is_valid=result.is_valid,
        message=result.message,
        battery_level=result.battery_level,
    )


@app.get("/api/v1/ble-tags/supported-types")
async def get_supported_tag_types(_: User = Depends(get_current_user)):
    """Return the list of supported BLE tag types for the dropdown."""
    return {
        "types": [
            {"value": "tracksolid", "label": "TrackSolid"},
            {"value": "scope",      "label": "Scope"},
        ]
    }


@app.get("/api/v1/ble-tags", response_model=List[BLETagResponse])
def list_user_ble_tags(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Get all BLE tags for current user"""
    tags = db.query(BLETag).filter(
        BLETag.user_id == current_user.id,
        BLETag.is_active == True
    ).all()
    
    # Convert ORM objects to Pydantic models with UUID serialization
    return [BLETagResponse.from_orm(tag) for tag in tags]

@app.get("/api/v1/ble-tags/{tag_id}", response_model=BLETagResponse)
def get_ble_tag(
    tag_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Get specific BLE tag details"""
    tag = db.query(BLETag).filter(
        BLETag.id == tag_id,
        BLETag.user_id == current_user.id
    ).first()
    
    if not tag:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Tag not found"
        )
    
    return tag

@app.get("/api/v1/validate-imei/{imei}")
def validate_imei(
    imei: str,
    current_user: User = Depends(get_current_user)
):
    """
    Validate IMEI by checking if it exists in the MProfiler API
    Returns 200 if valid, 404 if not found
    """
    import requests
    
    debug = os.getenv('DEBUG', 'False').lower() == 'true'
    
    # Validate IMEI format
    if not imei.isdigit() or len(imei) != 15:
        if debug:
            print(f"❌ Invalid IMEI format: {imei} (length: {len(imei)})")
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid IMEI format. Must be 15 digits."
        )
    
    try:
        # Call MProfiler API to validate IMEI
        validation_url = f'https://live.scopemp.net/Scope.MProfiler.Api/v1/UnitExtendedProperties/{imei}'
        headers = {
            'Authorization': 'Basic T0NJX1Njb3BlVUtfTVo6T0NJU2NvcGVVS01aMDEh'
        }
        
        if debug:
            print(f"🔍 Validating IMEI: {imei}")
            print(f"📡 API URL: {validation_url}")
        
        response = requests.get(validation_url, headers=headers, timeout=10)
        
        if response.status_code == 200:
            if debug:
                print(f"✅ IMEI {imei} is valid")
            return {
                "success": True,
                "message": "IMEI is valid",
                "imei": imei
            }
        elif response.status_code == 404:
            if debug:
                print(f"❌ IMEI {imei} not found")
            return JSONResponse(
                status_code=404,
                content={
                    "success": False,
                    "error": "IMEI unknown error"
                }
            )
        else:
            if debug:
                print(f"⚠️ IMEI validation failed with status: {response.status_code}")
            return JSONResponse(
                status_code=500,
                content={
                    "success": False,
                    "error": f"Validation service error: {response.status_code}"
                }
            )
                
    except requests.exceptions.Timeout:
        if debug:
            print(f"⏱️ IMEI validation timeout for {imei}")
        return JSONResponse(
            status_code=500,
            content={
                "success": False,
                "error": "IMEI not recognised"
            }
        )
    except requests.exceptions.RequestException as e:
        if debug:
            print(f"❌ IMEI validation error: {str(e)}")
        return JSONResponse(
            status_code=500,
            content={
                "success": False,
                "error": "IMEI not recognised"
            }
        )
    except Exception as e:
        if debug:
            print(f"❌ Unexpected error during IMEI validation: {str(e)}")
        return JSONResponse(
            status_code=500,
            content={
                "success": False,
                "error": "An unexpected error occurred"
            }
        )

@app.delete("/api/v1/ble-tags/{tag_id}")
def remove_ble_tag(
    tag_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Remove BLE tag from user's account"""
    tag = db.query(BLETag).filter(
        BLETag.id == tag_id,
        BLETag.user_id == current_user.id
    ).first()
    
    if not tag:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Tag not found"
        )
    
    # Soft delete
    tag.is_active = False
    db.commit()
    
    return {"success": True, "message": "Tag removed successfully"}

# Admin endpoints
@app.get("/api/v1/admin/users", response_model=List[UserResponse])
def list_users(db: Session = Depends(get_db)):
    """List all users (admin only - auth temporarily disabled for development)"""
    # TODO: Re-enable authentication in production
    # if not current_user.is_admin:
    #     raise HTTPException(
    #         status_code=status.HTTP_403_FORBIDDEN,
    #         detail="Not enough permissions"
    #     )
    
    users = db.query(User).all()
    return users

@app.get("/api/v1/admin/billing/tags", response_model=List[BLETagWithUser])
def list_all_tags_with_users(db: Session = Depends(get_db)):
    """
    List all BLE tags with user information for billing purposes
    Shows: IMEI, activation date, user details
    """
    tags = db.query(BLETag).join(User).all()
    
    result = []
    for tag in tags:
        full_name = f"{tag.user.first_name or ''} {tag.user.last_name or ''}".strip()
        if not full_name:
            full_name = tag.user.email.split('@')[0]
        
        result.append({
            "id": str(tag.id),
            "imei": tag.imei,
            "device_name": tag.device_name,
            "device_model": tag.device_model,
            "is_active": tag.is_active,
            "added_at": tag.added_at,
            "activated_at": tag.added_at,  # Same as added_at, just clearer naming
            "user_id": str(tag.user_id),
            "user_email": tag.user.email,
            "user_name": full_name
        })
    
    return result

@app.get("/api/v1/admin/billing/users", response_model=List[UserWithTags])
def list_users_with_tags(db: Session = Depends(get_db)):
    """
    List all users with their BLE tags and tag count for billing purposes
    Shows: User details, tag count, all associated tags with activation dates
    """
    users = db.query(User).all()
    
    result = []
    for user in users:
        full_name = f"{user.first_name or ''} {user.last_name or ''}".strip()
        if not full_name:
            full_name = user.email.split('@')[0]
        
        # Convert tags to proper format with string IDs
        tags_list = []
        for tag in user.ble_tags:
            tags_list.append({
                "id": str(tag.id),
                "imei": tag.imei,
                "device_name": tag.device_name,
                "device_model": tag.device_model,
                "mac_address": tag.mac_address,
                "is_active": tag.is_active,
                "last_seen": tag.last_seen,
                "battery_level": tag.battery_level,
                "added_at": tag.added_at
            })
        
        result.append({
            "id": str(user.id),
            "email": user.email,
            "first_name": user.first_name,
            "last_name": user.last_name,
            "full_name": full_name,
            "is_active": user.is_active,
            "created_at": user.created_at,
            "tag_count": len(user.ble_tags),
            "tags": tags_list
        })
    
    return result

@app.get("/api/v1/admin/end-users")
def list_end_users_with_tags(db: Session = Depends(get_db)):
    """
    List all end users with their tag assignments for Admin Portal "End Users" section
    Returns: All users with expandable tag details including IMEI, package, expiry
    """
    users = db.query(User).order_by(User.created_at.desc()).all()
    
    result = []
    for user in users:
        full_name = f"{user.first_name or ''} {user.last_name or ''}".strip()
        if not full_name:
            full_name = user.email.split('@')[0]
        
        # Get usergroups for this user (via PortalUser association)
        usergroups = []
        portal_users = db.query(PortalUser).filter(PortalUser.email == user.email).all()
        for portal_user in portal_users:
            if portal_user.usergroup:
                usergroups.append(portal_user.usergroup.name)
        
        # Get all tags for this user with package details
        tags_list = []
        for tag in user.ble_tags:
            # Get package name if exists
            package_name = None
            if tag.package_id:
                package = db.query(TagPackage).filter(TagPackage.id == tag.package_id).first()
                if package:
                    package_name = package.name
            
            tags_list.append({
                "id": str(tag.id),
                "imei": tag.imei,
                "device_name": tag.device_name or tag.description or "Unknown",
                "tag_type": tag.tag_type,
                "is_active": tag.is_active,
                "package_name": package_name,
                "activation_date": tag.activation_date.isoformat() if tag.activation_date else None,
                "expiry_date": tag.expiry_date.isoformat() if tag.expiry_date else None,
                "last_seen": tag.last_seen.isoformat() if tag.last_seen else None,
                "battery_level": tag.battery_level
            })
        
        result.append({
            "id": str(user.id),
            "email": user.email,
            "full_name": full_name,
            "first_name": user.first_name,
            "last_name": user.last_name,
            "phone": user.phone,
            "is_active": user.is_active,
            "is_admin": user.is_admin,
            "created_at": user.created_at.isoformat(),
            "tag_count": len(user.ble_tags),
            "usergroups": usergroups,  # List of usergroup names
            "tags": tags_list
        })
    
    return result

@app.get("/api/v1/admin/imei")
def list_all_imei_details(db: Session = Depends(get_db)):
    """
    List all IMEI/tags with user, usergroup, expiry, package, and activation date
    For Admin Portal "IMEI" section - comprehensive tag inventory
    """
    tags = db.query(BLETag).order_by(BLETag.added_at.desc()).all()
    
    result = []
    for tag in tags:
        # Get user details
        user = db.query(User).filter(User.id == tag.user_id).first()
        user_email = user.email if user else "N/A"
        user_name = f"{user.first_name or ''} {user.last_name or ''}".strip() if user else "N/A"
        if not user_name or user_name == " ":
            user_name = user_email.split('@')[0] if user else "N/A"
        
        # Get package details
        package_name = None
        if tag.package_id:
            package = db.query(TagPackage).filter(TagPackage.id == tag.package_id).first()
            if package:
                package_name = package.name
        
        # Get usergroup (from portal_users or user_group_members if implemented)
        # For now, we'll look for any usergroup associations through buildings or other means
        usergroup_name = None
        # Try to find usergroup through portal users if this user is linked
        portal_user = db.query(PortalUser).filter(PortalUser.email == user_email).first() if user else None
        if portal_user and portal_user.usergroup:
            usergroup_name = portal_user.usergroup.name
        
        result.append({
            "id": str(tag.id),
            "imei": tag.imei,
            "device_name": tag.device_name or tag.description or "Unknown",
            "device_model": tag.device_model,
            "tag_type": tag.tag_type,
            "is_active": tag.is_active,
            "user_email": user_email,
            "user_name": user_name,
            "usergroup": usergroup_name or "N/A",
            "package_name": package_name or "N/A",
            "activation_date": tag.activation_date.isoformat() if tag.activation_date else "N/A",
            "expiry_date": tag.expiry_date.isoformat() if tag.expiry_date else "N/A",
            "added_at": tag.added_at.isoformat() if tag.added_at else None,
            "last_seen": tag.last_seen.isoformat() if tag.last_seen else None,
            "battery_level": tag.battery_level,
            "latitude": tag.latitude,
            "longitude": tag.longitude
        })
    
    return result

# Demo tag endpoints (will be replaced with external API calls)
@app.get("/api/v1/tags")
def get_tags(current_user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> List[Dict]:
    """
    Return the BLE tags registered to the current user.
    """
    tags = db.query(BLETag).filter(
        BLETag.user_id == current_user.id,
        BLETag.is_active == True,
    ).order_by(BLETag.added_at.desc()).all()
    return [
        {
            "id": str(t.id),
            "imei": t.imei,
            "name": t.description or t.device_name or t.imei,
            "device_name": t.device_name,
            "description": t.description,
            "tag_type": t.tag_type,
            "battery": t.battery_level,
            "status": "active" if t.is_active else "inactive",
            "last_seen": t.last_seen.isoformat() if t.last_seen else None,
            "latitude": t.latitude,
            "longitude": t.longitude,
            "location_description": t.location_description,
            "expiry_date": t.expiry_date.isoformat() if t.expiry_date else None,
        }
        for t in tags
    ]

@app.get("/api/v1/tags/{tag_id}")
def get_tag_details(tag_id: str, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> Dict:
    """
    Get specific tag details for the current user.
    """
    tag = db.query(BLETag).filter(
        BLETag.id == tag_id,
        BLETag.user_id == current_user.id,
    ).first()
    if not tag:
        raise HTTPException(status_code=404, detail="Tag not found")
    return {
        "id": str(tag.id),
        "imei": tag.imei,
        "name": tag.description or tag.device_name or tag.imei,
        "device_name": tag.device_name,
        "description": tag.description,
        "tag_type": tag.tag_type,
        "battery": tag.battery_level,
        "status": "active" if tag.is_active else "inactive",
        "last_seen": tag.last_seen.isoformat() if tag.last_seen else None,
        "latitude": tag.latitude,
        "longitude": tag.longitude,
        "location_description": tag.location_description,
        "expiry_date": tag.expiry_date.isoformat() if tag.expiry_date else None,
    }

@app.get("/api/v1/tags/{tag_id}/location")
def get_tag_location(tag_id: str, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> Dict:
    """
    Get latest GPS location of a tag (demo data)
    """
    # Verify tag belongs to user
    tag = db.query(BLETag).filter(
        BLETag.id == tag_id,
        BLETag.user_id == current_user.id
    ).first()
    
    if not tag:
        raise HTTPException(status_code=404, detail="Tag not found")
    
    # Check if tag has stored location
    if tag.latitude and tag.longitude:
        location = {
            "latitude": float(tag.latitude),
            "longitude": float(tag.longitude),
            "address": f"Location for {tag.device_name or tag.imei}"
        }
    # Otherwise, generate demo location based on tag_id for consistency
    elif tag_id in DEMO_LOCATIONS:
        location = DEMO_LOCATIONS[tag_id].copy()
    else:
        # Generate consistent demo location based on tag_id hash
        import hashlib
        hash_val = int(hashlib.md5(tag_id.encode()).hexdigest()[:8], 16)
        # San Francisco area: 37.7-37.8, -122.5 to -122.4
        lat = 37.7 + (hash_val % 1000) / 10000.0
        lon = -122.5 + (hash_val // 1000 % 1000) / 10000.0
        location = {
            "latitude": round(lat, 6),
            "longitude": round(lon, 6),
            "address": f"Demo location for {tag.device_name or tag.imei}"
        }
    
    location["tag_id"] = tag_id
    location["timestamp"] = datetime.utcnow().isoformat()
    location["accuracy"] = round(random.uniform(5.0, 15.0), 2)
    
    return location

@app.get("/api/v1/tags/{tag_id}/history")
def get_location_history(tag_id: str, current_user: User = Depends(get_current_user), limit: int = 10) -> List[Dict]:
    """
    Get location history (demo data)
    """
    if tag_id not in DEMO_LOCATIONS:
        return []
    
    base_location = DEMO_LOCATIONS[tag_id]
    history = []
    
    for i in range(limit):
        history.append({
            "latitude": base_location["latitude"] + random.uniform(-0.01, 0.01),
            "longitude": base_location["longitude"] + random.uniform(-0.01, 0.01),
            "accuracy": round(random.uniform(5.0, 15.0), 2),
            "timestamp": datetime.utcnow().isoformat(),
            "battery": random.randint(60, 100)
        })
    
    return history


# ============================================================================
# Mobile App Compatibility Endpoints (without /v1)
# ============================================================================

@app.post("/api/auth/send-pin")
def send_pin_compat(request: SendVerificationCodeRequest, db: Session = Depends(get_db)):
    """Mobile app compatibility endpoint for send-verification-code"""
    return send_verification_code(request, db)


@app.post("/api/auth/verify-pin")
def verify_pin_compat(request: VerifyPINRequest, db: Session = Depends(get_db)):
    """Mobile app compatibility endpoint for verify-pin"""
    verify_pin(request, db)
    return {"success": True, "message": "Email verified successfully"}


@app.get("/api/auth/me", response_model=UserResponse)
def get_me_compat(current_user: User = Depends(get_current_user)):
    """Mobile app compatibility endpoint for current user"""
    return current_user


@app.post("/api/tags/add")
def add_tag_compat(
    tag_data: BLETagCreate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Mobile app compatibility endpoint for adding tags"""
    import requests
    
    debug = os.getenv('DEBUG', 'False').lower() == 'true'
    
    try:
        # Validate IMEI format
        if not tag_data.imei.isdigit() or len(tag_data.imei) != 15:
            if debug:
                print(f"❌ Invalid IMEI format: {tag_data.imei} (length: {len(tag_data.imei)})")
            return {
                "success": False,
                "error": "Invalid IMEI format. Must be 15 digits."
            }
        
        # Check if IMEI already exists
        existing_tag = db.query(BLETag).filter(BLETag.imei == tag_data.imei).first()
        if existing_tag:
            if debug:
                print(f"❌ IMEI {tag_data.imei} already registered")
            return {
                "success": False,
                "error": "IMEI already registered"
            }
        
        # Validate IMEI with MProfiler API before adding
        validation_url = f'https://live.scopemp.net/Scope.MProfiler.Api/v1/UnitExtendedProperties/{tag_data.imei}'
        headers = {
            'Authorization': 'Basic T0NJX1Njb3BlVUtfTVo6T0NJU2NvcGVVS01aMDEh'
        }
        
        if debug:
            print(f"🔍 Validating IMEI before adding: {tag_data.imei}")
            print(f"📡 API URL: {validation_url}")
        
        try:
            validation_response = requests.get(validation_url, headers=headers, timeout=10)
            
            if validation_response.status_code == 404:
                if debug:
                    print(f"❌ IMEI {tag_data.imei} not found in MProfiler")
                return {
                    "success": False,
                    "error": "IMEI not recognised"
                }
            elif validation_response.status_code != 200:
                if debug:
                    print(f"⚠️ IMEI validation returned status: {validation_response.status_code}")
                return {
                    "success": False,
                    "error": "IMEI not recognised"
                }
            
            if debug:
                print(f"✅ IMEI {tag_data.imei} validated successfully")
                
        except requests.exceptions.Timeout:
            if debug:
                print(f"⏱️ IMEI validation timeout for {tag_data.imei}")
            return {
                "success": False,
                "error": "IMEI not recognised"
            }
        except requests.exceptions.RequestException as e:
            if debug:
                print(f"❌ IMEI validation error: {str(e)}")
            return {
                "success": False,
                "error": "IMEI not recognised"
            }
        
        # IMEI is valid, create new tag
        ble_tag = BLETag(
            user_id=current_user.id,
            imei=tag_data.imei,
            device_name=tag_data.device_name,
            device_model=tag_data.device_model,
            description=tag_data.description,
            mac_address=tag_data.mac_address
        )
        db.add(ble_tag)
        db.commit()
        db.refresh(ble_tag)
        
        if debug:
            print(f"✅ Tag added successfully: {tag_data.imei}")
        
        return {
            "success": True,
            "message": "IMEI added successfully",
            "tag": {
                "id": str(ble_tag.id),
                "imei": ble_tag.imei,
                "added_date": ble_tag.added_at.isoformat()
            }
        }
    except Exception as e:
        if debug:
            print(f"❌ Error adding tag: {str(e)}")
        return {
            "success": False,
            "error": str(e)
        }


@app.get("/api/tags/list")
def list_tags_compat(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Mobile app compatibility endpoint for listing tags"""
    try:
        tags = db.query(BLETag).filter(
            BLETag.user_id == current_user.id,
            BLETag.is_active == True
        ).all()
        
        return {
            "success": True,
            "tags": [
                {
                    "id": str(tag.id),
                    "imei": tag.imei,
                    "added_date": tag.added_at.isoformat(),
                    "device_name": tag.device_name,
                    "description": tag.description,
                    "attributes": tag.attributes or {}
                }
                for tag in tags
            ]
        }
    except Exception as e:
        return {
            "success": False,
            "error": str(e)
        }


@app.delete("/api/tags/remove/{imei}")
def remove_tag_compat(
    imei: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Mobile app compatibility endpoint for removing tags"""
    try:
        tag = db.query(BLETag).filter(
            BLETag.user_id == current_user.id,
            BLETag.imei == imei
        ).first()
        
        if not tag:
            return {
                "success": False,
                "error": "Tag not found"
            }
        
        # Soft delete
        tag.is_active = False
        db.commit()
        
        return {
            "success": True,
            "message": "Tag removed successfully"
        }
    except Exception as e:
        return {
            "success": False,
            "error": str(e)
        }


@app.put("/api/tags/{imei}/attributes")
def update_tag_attributes(
    imei: str,
    attributes_data: dict,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Update custom attributes for a BLE tag (includes show_on_map visibility settings)"""
    import os
    debug = os.getenv('DEBUG', 'False').lower() == 'true'
    
    try:
        if debug:
            print(f"\n{'='*60}")
            print(f"📝 Updating attributes for IMEI: {imei}")
            print(f"👤 User: {current_user.email}")
            print(f"📦 Attributes: {attributes_data}")
        
        # Find the tag
        tag = db.query(BLETag).filter(
            BLETag.user_id == current_user.id,
            BLETag.imei == imei
        ).first()
        
        if not tag:
            if debug:
                print(f"❌ Tag not found for IMEI: {imei}")
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Tag not found"
            )
        
        # Extract attributes from request (has "attributes" key)
        attrs = attributes_data.get('attributes', {})
        
        # Persist device_name if provided alongside attributes
        new_device_name = attributes_data.get('device_name')
        if new_device_name is not None:
            cleaned = new_device_name.strip() or None
            tag.device_name = cleaned
            # Keep portal `description` in sync with Flutter `device_name` so both UIs
            # show the same custom label. Also mark `_user_named` so background pollers
            # never overwrite this name with vendor-API values.
            tag.description = cleaned
            attrs_meta = dict(tag.attributes or {})
            if cleaned:
                attrs_meta['_user_named'] = True
            else:
                attrs_meta.pop('_user_named', None)
            tag.attributes = attrs_meta
            if debug:
                print(f"✏️  Updating device_name & description to: {cleaned}")
        
        # Validate structure - each attribute should have value and show_on_map
        for attr_name, attr_value in attrs.items():
            if not isinstance(attr_value, dict):
                if debug:
                    print(f"❌ Invalid attribute format for {attr_name}: {attr_value}")
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=f"Attribute '{attr_name}' must be an object with 'value' and 'show_on_map' fields"
                )
            
            # Ensure required fields
            if 'value' not in attr_value:
                attr_value['value'] = None
            if 'show_on_map' not in attr_value:
                attr_value['show_on_map'] = False
        
        # Update tag attributes
        tag.attributes = attrs
        db.commit()
        
        if debug:
            print(f"✅ Attributes updated successfully")
            print(f"💾 Saved to database: {tag.attributes}")
            print(f"{'='*60}\n")
        
        return {
            "success": True,
            "message": "Attributes saved successfully",
            "attributes": tag.attributes
        }
        
    except HTTPException:
        raise
    except Exception as e:
        if debug:
            print(f"❌ Error updating attributes: {str(e)}")
            print(f"{'='*60}\n")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to save attributes: {str(e)}"
        )


@app.post("/api/vehicles")
def get_vehicles(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Get vehicles from cached database (updated by background poller every 60 seconds)
    Returns last known positions without calling MZone API on every request
    """
    import os
    debug = os.getenv('DEBUG', 'False').lower() == 'true'
    
    try:
        # Get user's trackers from database (already updated by background poller)
        tags = db.query(BLETag).filter(
            BLETag.user_id == current_user.id,
            BLETag.is_active == True
        ).all()
        
        if debug:
            print(f"\n{'='*60}")
            print(f"📱 User {current_user.email} requesting vehicles (from cache)")
            print(f"🏷️  User has {len(tags)} tags")
            print(f"{'='*60}\n")
        
        if not tags:
            return {
                "success": True,
                "vehicles": [],
                "message": "No tags registered. Please add vehicle IMEIs first."
            }
        
        # Format response from cached database data
        formatted_vehicles = []
        for tag in tags:
            # Build lastKnownPosition from cached data
            last_known_position = None
            if tag.latitude and tag.longitude:
                try:
                    last_known_position = {
                        "latitude": float(tag.latitude),
                        "longitude": float(tag.longitude),
                        "utcTimestamp": tag.last_seen.isoformat() if tag.last_seen else None,
                        "speed": None,  # Not stored in database currently
                        "heading": None,  # Not stored in database currently
                        "locationDescription": tag.location_description,  # Formatted address from MZone
                    }
                except (ValueError, TypeError):
                    pass
            
            formatted_vehicles.append({
                "id": str(tag.id),  # Use BLETag database ID
                "description": tag.description or tag.device_name or tag.imei,
                "registration": tag.imei,
                "ignitionOn": False,  # Not stored in database currently
                "lastKnownPosition": last_known_position,
                "attributes": tag.attributes or {},  # Include custom attributes (job_accessories, notes, etc.)
                "battery_level": tag.battery_level,  # Battery % for TrackSolid tags
                "tag_type": tag.tag_type,
            })
        
        if debug:
            print(f"✅ Returning {len(formatted_vehicles)} vehicles from cache")
        
        return {
            "success": True,
            "count": len(formatted_vehicles),
            "vehicles": formatted_vehicles
        }
    
    except Exception as e:
        if debug:
            print(f"❌ Error in /api/vehicles: {str(e)}")
        return {
            "success": False,
            "error": str(e),
            "vehicles": []
        }


# ==================== Trips / Journeys Management ====================

@app.post("/api/trips")
async def get_trips(
    request: dict,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Fetch trips for a vehicle within date range.
    Routes to TrackSolid getPointList (V3 Bearer token) or MZone API
    depending on the tag type.

    Request body:
    {
        "vehicleId": "xxx-xxx-xxx",
        "startDate": "2024-01-15T00:00:00Z",
        "endDate": "2024-01-15T23:59:59Z"
    }
    """
    import os
    debug = os.getenv('DEBUG', 'False').lower() == 'true'
    
    try:
        vehicle_id = request.get('vehicleId')
        start_date = request.get('startDate')
        end_date = request.get('endDate')
        
        if not vehicle_id or not start_date or not end_date:
            return {
                "success": False,
                "error": "Missing required parameters: vehicleId, startDate, endDate",
                "trips": []
            }
        
        # ALWAYS log trips requests for debugging
        print(f"\n{'='*60}")
        print(f"📱 TRIPS REQUEST from {current_user.email}")
        print(f"   Vehicle ID: {vehicle_id}")
        print(f"   Date range: {start_date} to {end_date}")
        print(f"{'='*60}\n")
        
        # Verify user has access to this vehicle
        tag = db.query(BLETag).filter(
            BLETag.user_id == current_user.id,
            BLETag.is_active == True,
            BLETag.id == vehicle_id
        ).first()
        
        if not tag:
            print(f"❌ TRIPS ERROR: User does not have access to vehicle {vehicle_id}")
            print(f"   User ID: {current_user.id}")
            print(f"   Checked BLETag table for matching vehicle_id")
            return {
                "success": False,
                "error": "Vehicle not found or access denied",
                "trips": []
            }
        
        print(f"✅ Found BLETag for vehicle")
        print(f"   Tag ID: {tag.id}")
        print(f"   Tag IMEI: {tag.imei}")
        print(f"   Tag description: {tag.description}")
        print(f"   Tag type: {tag.tag_type}")
        print(f"   Cached MZone vehicle_Id: {tag.mzone_vehicle_id}")

        # ── TrackSolid tags: use V3 getPointList API (Bearer JWT) ────────────
        if (tag.tag_type or "").lower() == "tracksolid":
            from app.services.device_providers.tracksolid_provider import fetch_tracksolid_journey_points
            from datetime import datetime as _dt

            def _to_ts_dt(iso_str: str) -> str:
                return iso_str.replace("T", " ").replace("Z", "").split(".")[0][:19]

            ts_start = _to_ts_dt(start_date)
            ts_end = _to_ts_dt(end_date)
            print(f"🔵 TrackSolid journey: IMEI={tag.imei} {ts_start} → {ts_end}")

            track_data = await fetch_tracksolid_journey_points(tag.imei, ts_start, ts_end)

            if not track_data or not (track_data.get("gpsPointStrList") or []):
                print(f"⚠️  TrackSolid: no points returned for IMEI {tag.imei}")
                return {"success": True, "count": 0, "trips": []}

            try:
                t0 = _dt.strptime(track_data["startDate"], "%Y-%m-%d %H:%M:%S")
                t1 = _dt.strptime(track_data["endDate"], "%Y-%m-%d %H:%M:%S")
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
                "endUtcTimestamp": track_data["endDate"].replace(" ", "T") + "Z",
                "startLocationDescription": track_data.get("startAddress"),
                "endLocationDescription": track_data.get("endAddress"),
            }
            print(f"✅ TrackSolid: {len(track_data['gpsPointStrList'])} pts, {distance_mi} mi, {duration_secs}s")
            return {"success": True, "count": 1, "trips": [synthetic_trip]}

        # MZone path ──────────────────────────────────────────────────────────
        # Use cached MZone vehicle ID if available (much faster!)
        mzone_vehicle_id = tag.mzone_vehicle_id
        
        # If not cached yet, fall back to IMEI lookup (will be cached on next location poll)
        if not mzone_vehicle_id:
            print(f"⚠️  No cached MZone vehicle_Id, performing IMEI lookup...")
            from app.services.mzone_service import mzone_service
            
            # Get all vehicles to find the MZone vehicle ID
            vehicles_data = mzone_service.get_all_vehicles()
            if not vehicles_data:
                print(f"❌ TRIPS ERROR: Failed to fetch vehicles from MZone")
                return {
                    "success": False,
                    "error": "Failed to fetch vehicles from MZone",
                    "trips": []
                }
            
            print(f"📋 Checking {len(vehicles_data.get('value', []))} MZone vehicles for IMEI match")
            
            # Find vehicle matching this tag's IMEI
            for vehicle in vehicles_data.get('value', []):
                if (vehicle.get('registration') == tag.imei or 
                    vehicle.get('unit_Description') == tag.imei):
                    mzone_vehicle_id = vehicle.get('id')
                    # Cache it for future requests
                    tag.mzone_vehicle_id = mzone_vehicle_id
                    db.commit()
                    print(f"✅ Found MZone vehicle match and cached it!")
                    print(f"   MZone Vehicle ID: {mzone_vehicle_id}")
                    print(f"   MZone Vehicle Description: {vehicle.get('description')}")
                    print(f"   Registration: {vehicle.get('registration')}")
                    print(f"   Unit Description: {vehicle.get('unit_Description')}")
                    break
            
            if not mzone_vehicle_id:
                print(f"❌ TRIPS ERROR: Could not find MZone vehicle ID for IMEI {tag.imei}")
                print(f"   Searched registration and unit_Description fields")
                return {
                    "success": True,
                    "count": 0,
                    "trips": []
                }
        else:
            print(f"✅ Using cached MZone vehicle_Id (fast path)")
        
        # Fetch trips from MZone
        from app.services.mzone_service import mzone_service
        print(f"🚗 Fetching trips from MZone API...")
        trips_data = mzone_service.get_trips(
            vehicle_id=mzone_vehicle_id,
            start_date=start_date,
            end_date=end_date
        )
        
        if not trips_data:
            print(f"❌ TRIPS ERROR: MZone API returned None")
            return {
                "success": False,
                "error": "Failed to fetch trips from MZone",
                "trips": []
            }
        
        trips = trips_data.get('value', [])
        
        print(f"✅ SUCCESS: Returning {len(trips)} trips to frontend")
        if len(trips) == 0:
            print(f"⚠️  NO TRIPS FOUND in this date range")
            print(f"   Vehicle: {mzone_vehicle_id}")
            print(f"   Range: {start_date} to {end_date}")
        else:
            print(f"📊 Sample trip data:")
            for i, trip in enumerate(trips[:2]):  # First 2 trips
                print(f"   Trip {i+1}: {trip.get('startLocationDescription')} → {trip.get('endLocationDescription')}")
                print(f"           Start: {trip.get('startUtcTimestamp')}, Distance: {trip.get('distance')}m")
        print(f"{'='*60}\n")
        
        return {
            "success": True,
            "count": len(trips),
            "trips": trips
        }
    
    except Exception as e:
        if debug:
            print(f"❌ Error in /api/trips: {str(e)}")
        return {
            "success": False,
            "error": str(e),
            "trips": []
        }


@app.get("/api/trips/{trip_id}/events")
async def get_trip_events(
    trip_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Fetch trip events/waypoints for route plotting (proxy to MZone API)
    """
    import os
    debug = os.getenv('DEBUG', 'False').lower() == 'true'
    
    try:
        if debug:
            print(f"\n{'='*60}")
            print(f"📱 User {current_user.email} requesting trip events")
            print(f"   Trip ID: {trip_id}")
            print(f"{'='*60}\n")

        # ── TrackSolid compound trip ID: tracksolid__{imei}__{start}__{end} ──
        if trip_id.startswith("tracksolid__"):
            from app.services.device_providers.tracksolid_provider import fetch_tracksolid_journey_points

            parts = trip_id.split("__")
            if len(parts) != 4:
                return {"success": False, "error": "Invalid TrackSolid trip ID format", "events": []}

            _, imei, ts_start_raw, ts_end_raw = parts
            ts_start = ts_start_raw.replace("T", " ")
            ts_end = ts_end_raw.replace("T", " ")
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
                        "latitude": lat,
                        "longitude": lng,
                        "direction": int(float(p[1])) if p[1] else 0,
                        "speed": int(float(p[0])) if p[0] else 0,
                        "decimalOdometer": None,
                        "eventType_Id": None,
                        "eventType_Description": None,
                        "eventType_MapMarker2": None,
                    })
                except (ValueError, IndexError):
                    continue

            print(f"✅ TrackSolid events: {len(events)} valid waypoints from {len(points_raw)} total")
            return {"success": True, "count": len(events), "events": events}

        # ── MZone trip events ─────────────────────────────────────────────────
        from app.services.mzone_service import mzone_service

        # Fetch trip events from MZone
        events_data = mzone_service.get_trip_events(trip_id)
        
        if not events_data:
            return {
                "success": False,
                "error": "Failed to fetch trip events from MZone",
                "events": []
            }
        
        events = events_data.get('value', [])
        
        if debug:
            print(f"✅ Returning {len(events)} waypoints")
        
        return {
            "success": True,
            "count": len(events),
            "events": events
        }
    
    except Exception as e:
        if debug:
            print(f"❌ Error in /api/trips/{trip_id}/events: {str(e)}")
        return {
            "success": False,
            "error": str(e),
            "events": []
        }


# ==================== POI / Geofence Management ====================

@app.post("/api/v1/pois", response_model=POIResponse)
def create_poi(
    poi_data: POICreate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Create a new Point of Interest (POI) / Geofence"""
    poi = POI(
        user_id=str(current_user.id),
        name=poi_data.name,
        description=poi_data.description,
        poi_type=poi_data.poi_type,
        latitude=poi_data.latitude,
        longitude=poi_data.longitude,
        radius=poi_data.radius,
        address=poi_data.address,
        destination_latitude=poi_data.destination_latitude,
        destination_longitude=poi_data.destination_longitude,
        destination_radius=poi_data.destination_radius,
        destination_address=poi_data.destination_address,
        is_active=True
    )
    
    db.add(poi)
    db.commit()
    db.refresh(poi)
    
    return POIResponse(
        id=str(poi.id),
        user_id=str(poi.user_id),
        name=poi.name,
        description=poi.description,
        poi_type=poi.poi_type,
        latitude=poi.latitude,
        longitude=poi.longitude,
        radius=poi.radius,
        address=poi.address,
        destination_latitude=poi.destination_latitude,
        destination_longitude=poi.destination_longitude,
        destination_radius=poi.destination_radius,
        destination_address=poi.destination_address,
        is_active=poi.is_active,
        created_at=poi.created_at,
        updated_at=poi.updated_at
    )


@app.get("/api/v1/pois", response_model=List[POIWithArmedStatus])
def list_pois(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """List all POIs for the current user with armed status"""
    pois = db.query(POI).filter(POI.user_id == str(current_user.id)).all()
    
    result = []
    for poi in pois:
        # Get armed trackers for this POI
        armed_links = db.query(POITrackerLink).filter(
            POITrackerLink.poi_id == poi.id,
            POITrackerLink.is_armed == True
        ).all()
        
        armed_tracker_ids = [str(link.tracker_id) for link in armed_links]
        
        result.append(POIWithArmedStatus(
            id=str(poi.id),
            user_id=str(poi.user_id),
            name=poi.name,
            description=poi.description,
            poi_type=poi.poi_type,
            latitude=poi.latitude,
            longitude=poi.longitude,
            radius=poi.radius,
            address=poi.address,
            destination_latitude=poi.destination_latitude,
            destination_longitude=poi.destination_longitude,
            destination_radius=poi.destination_radius,
            destination_address=poi.destination_address,
            is_active=poi.is_active,
            created_at=poi.created_at,
            updated_at=poi.updated_at,
            armed_trackers=armed_tracker_ids
        ))
    
    return result


@app.get("/api/v1/pois/{poi_id}", response_model=POIWithArmedStatus)
def get_poi(
    poi_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Get a specific POI"""
    poi = db.query(POI).filter(
        POI.id == poi_id,
        POI.user_id == str(current_user.id)
    ).first()
    
    if not poi:
        raise HTTPException(status_code=404, detail="POI not found")
    
    # Get armed trackers
    armed_links = db.query(POITrackerLink).filter(
        POITrackerLink.poi_id == poi.id,
        POITrackerLink.is_armed == True
    ).all()
    
    armed_tracker_ids = [str(link.tracker_id) for link in armed_links]
    
    return POIWithArmedStatus(
        id=str(poi.id),
        user_id=str(poi.user_id),
        name=poi.name,
        description=poi.description,
        poi_type=poi.poi_type,
        latitude=poi.latitude,
        longitude=poi.longitude,
        radius=poi.radius,
        address=poi.address,
        destination_latitude=poi.destination_latitude,
        destination_longitude=poi.destination_longitude,
        destination_radius=poi.destination_radius,
        destination_address=poi.destination_address,
        is_active=poi.is_active,
        created_at=poi.created_at,
        updated_at=poi.updated_at,
        armed_trackers=armed_tracker_ids
    )


@app.put("/api/v1/pois/{poi_id}", response_model=POIResponse)
def update_poi(
    poi_id: str,
    poi_update: POIUpdate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Update a POI"""
    poi = db.query(POI).filter(
        POI.id == poi_id,
        POI.user_id == str(current_user.id)
    ).first()
    
    if not poi:
        raise HTTPException(status_code=404, detail="POI not found")
    
    # Update fields if provided
    if poi_update.name is not None:
        poi.name = poi_update.name
    if poi_update.description is not None:
        poi.description = poi_update.description
    if poi_update.radius is not None:
        poi.radius = poi_update.radius
    if poi_update.destination_radius is not None:
        poi.destination_radius = poi_update.destination_radius
    if poi_update.is_active is not None:
        poi.is_active = poi_update.is_active
    
    db.commit()
    db.refresh(poi)
    
    return POIResponse(
        id=str(poi.id),
        user_id=str(poi.user_id),
        name=poi.name,
        description=poi.description,
        poi_type=poi.poi_type,
        latitude=poi.latitude,
        longitude=poi.longitude,
        radius=poi.radius,
        address=poi.address,
        destination_latitude=poi.destination_latitude,
        destination_longitude=poi.destination_longitude,
        destination_radius=poi.destination_radius,
        destination_address=poi.destination_address,
        is_active=poi.is_active,
        created_at=poi.created_at,
        updated_at=poi.updated_at
    )


@app.delete("/api/v1/pois/{poi_id}")
def delete_poi(
    poi_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Delete a POI"""
    poi = db.query(POI).filter(
        POI.id == poi_id,
        POI.user_id == str(current_user.id)
    ).first()
    
    if not poi:
        raise HTTPException(status_code=404, detail="POI not found")
    
    # Delete related links and alerts first
    db.query(POITrackerLink).filter(POITrackerLink.poi_id == poi_id).delete()
    db.query(GeofenceAlert).filter(GeofenceAlert.poi_id == poi_id).delete()
    
    db.delete(poi)
    db.commit()
    
    return {"message": "POI deleted successfully"}


# ==================== POI-Tracker ARM/DISARM ====================

@app.post("/api/v1/pois/{poi_id}/arm/{tracker_id}")
def arm_poi_to_tracker(
    poi_id: str,
    tracker_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """ARM a POI to a tracker (enable geofence monitoring)"""
    # Verify POI belongs to user
    poi = db.query(POI).filter(
        POI.id == poi_id,
        POI.user_id == str(current_user.id)
    ).first()
    
    if not poi:
        raise HTTPException(status_code=404, detail="POI not found")
    
    # Verify tracker belongs to user
    tracker = db.query(BLETag).filter(
        BLETag.id == tracker_id,
        BLETag.user_id == str(current_user.id)
    ).first()
    
    if not tracker:
        raise HTTPException(status_code=404, detail="Tracker not found")
    
    # Get tracker's current GPS position to set initial state
    initial_state = GeofenceState.UNKNOWN
    try:
        # Fetch vehicle location from MZone API
        user_imeis = [tracker.imei]
        vehicles = mzone_service.get_vehicles_with_locations(user_imeis)
        
        if vehicles and len(vehicles) > 0:
            vehicle = vehicles[0]
            last_position = vehicle.get('lastKnownPosition')
            
            if last_position:
                current_lat = last_position.get('latitude')
                current_lon = last_position.get('longitude')
                
                if current_lat is not None and current_lon is not None:
                    # Determine if tracker is currently inside or outside POI
                    is_inside = GeofenceService.is_inside_geofence(
                        current_lat, current_lon,
                        poi.latitude, poi.longitude,
                        poi.radius
                    )
                    initial_state = GeofenceState.INSIDE if is_inside else GeofenceState.OUTSIDE
                    logger.info(f"Armed POI '{poi.name}' to tracker {tracker.imei}: initial state = {initial_state.value}")
    except Exception as e:
        logger.warning(f"Could not determine initial state for POI arming: {str(e)}")
        # Continue with UNKNOWN state
    
    # Check if link already exists
    existing_link = db.query(POITrackerLink).filter(
        POITrackerLink.poi_id == poi_id,
        POITrackerLink.tracker_id == tracker_id
    ).first()
    
    if existing_link:
        # Re-arm if it was disarmed - reset state based on current position
        if not existing_link.is_armed:
            existing_link.is_armed = True
            existing_link.armed_at = datetime.utcnow()
            existing_link.disarmed_at = None
            existing_link.last_known_state = initial_state
            db.commit()
            return {"message": f"POI re-armed to tracker (state: {initial_state.value})"}
        else:
            return {"message": "POI already armed to tracker"}
    
    # Create new link with determined initial state
    link = POITrackerLink(
        poi_id=poi_id,
        tracker_id=tracker_id,
        is_armed=True,
        last_known_state=initial_state
    )
    
    db.add(link)
    db.commit()
    
    return {"message": f"POI armed to tracker successfully (state: {initial_state.value})"}


@app.post("/api/v1/pois/{poi_id}/disarm/{tracker_id}")
def disarm_poi_from_tracker(
    poi_id: str,
    tracker_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """DISARM a POI from a tracker (disable geofence monitoring)"""
    # Verify POI belongs to user
    poi = db.query(POI).filter(
        POI.id == poi_id,
        POI.user_id == str(current_user.id)
    ).first()
    
    if not poi:
        raise HTTPException(status_code=404, detail="POI not found")
    
    # Find the link
    link = db.query(POITrackerLink).filter(
        POITrackerLink.poi_id == poi_id,
        POITrackerLink.tracker_id == tracker_id
    ).first()
    
    if not link:
        raise HTTPException(status_code=404, detail="POI is not armed to this tracker")
    
    # Disarm
    link.is_armed = False
    link.disarmed_at = datetime.utcnow()
    
    db.commit()
    
    return {"message": "POI disarmed from tracker successfully"}


# ==================== Geofence Alerts ====================

@app.get("/api/v1/alerts", response_model=AlertsListResponse)
def get_alerts(
    limit: int = 50,
    offset: int = 0,
    unread_only: bool = False,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Get geofence alerts for the current user"""
    alerts, total, unread_count = GeofenceService.get_user_alerts(
        db, str(current_user.id), limit, offset, unread_only
    )
    
    # Format alerts with POI and tracker names
    formatted_alerts = []
    for alert in alerts:
        poi = db.query(POI).filter(POI.id == alert.poi_id).first()
        tracker = db.query(BLETag).filter(BLETag.id == alert.tracker_id).first()
        
        # Get tracker display name (priority: description > device_name > IMEI last 4)
        if tracker:
            if tracker.description:
                tracker_name = tracker.description
            elif tracker.device_name:
                tracker_name = tracker.device_name
            elif tracker.imei:
                tracker_name = f"GPS Tracker ({tracker.imei[-4:]})"
            else:
                tracker_name = "GPS Tracker"
        else:
            tracker_name = None
        
        formatted_alerts.append(GeofenceAlertResponse(
            id=str(alert.id),
            poi_id=str(alert.poi_id),
            tracker_id=str(alert.tracker_id),
            user_id=str(alert.user_id),
            event_type=alert.event_type,
            latitude=alert.latitude,
            longitude=alert.longitude,
            is_read=alert.is_read,
            created_at=alert.created_at,
            poi_name=poi.name if poi else None,
            tracker_name=tracker_name
        ))
    
    return AlertsListResponse(
        alerts=formatted_alerts,
        total=total,
        unread_count=unread_count
    )


@app.post("/api/v1/alerts/{alert_id}/mark-read")
def mark_alert_read(
    alert_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Mark a specific alert as read"""
    count = GeofenceService.mark_alerts_read(db, [alert_id], str(current_user.id))
    
    if count == 0:
        raise HTTPException(status_code=404, detail="Alert not found")
    
    return {"message": "Alert marked as read"}


@app.post("/api/v1/alerts/mark-all-read")
def mark_all_alerts_read(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Mark all alerts as read for the current user"""
    count = GeofenceService.mark_all_alerts_read(db, str(current_user.id))
    
    return {"message": f"{count} alerts marked as read"}


# ==================== Postcode Search ====================

@app.post("/api/v1/search/postcode", response_model=PostcodeSearchResponse)
async def search_postcode(request: PostcodeSearchRequest):
    """
    Search for a UK postcode using postcodes.io (free UK postcode API)
    Can be upgraded to Google Maps Geocoding API by setting GOOGLE_MAPS_API_KEY
    """
    import httpx
    import os
    
    try:
        # Use postcodes.io as primary option (free, no API key needed)
        postcode = request.postcode.replace(" ", "").upper()
        
        logger.info(f"Searching for postcode: {postcode}")
        
        async with httpx.AsyncClient() as client:
            response = await client.get(
                f"https://api.postcodes.io/postcodes/{postcode}",
                timeout=10.0
            )
            
            if response.status_code == 200:
                data = response.json()
                result = data.get("result", {})
                
                # Format address from postcodes.io data
                address_parts = []
                if result.get('postcode'):
                    address_parts.append(result.get('postcode'))
                if result.get('admin_district'):
                    address_parts.append(result.get('admin_district'))
                if result.get('region'):
                    address_parts.append(result.get('region'))
                address_parts.append('UK')
                
                formatted_address = ', '.join(address_parts)
                
                logger.info(f"Found postcode: {formatted_address}")
                
                return PostcodeSearchResponse(
                    latitude=result.get("latitude"),
                    longitude=result.get("longitude"),
                    address=formatted_address
                )
            elif response.status_code == 404:
                raise HTTPException(status_code=404, detail="Postcode not found")
            else:
                raise HTTPException(status_code=500, detail=f"Postcode API error: {response.status_code}")
    
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Postcode search error: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Error searching postcode: {str(e)}")


@app.post("/api/v1/test/mock-location", tags=["Testing"])
async def mock_location_test(
    request: MockLocationTestRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Mock test endpoint for geofence notifications.
    Simulates a tracker location update to test geofence alerts and email notifications.
    
    Returns details of any alerts triggered, including whether emails were sent.
    """
    try:
        # Verify tracker exists and belongs to user
        tracker = db.query(BLETag).filter(
            BLETag.id == request.tracker_id,
            BLETag.user_id == current_user.id
        ).first()
        
        if not tracker:
            raise HTTPException(status_code=404, detail="Tracker not found")
        
        # Call geofence service to check all armed POIs
        alerts = GeofenceService.check_geofences_for_tracker(
            db,
            request.tracker_id,
            request.latitude,
            request.longitude,
            str(current_user.id)
        )
        
        # Get POI details for each alert
        alert_details = []
        for alert in alerts:
            poi = db.query(POI).filter(POI.id == alert.poi_id).first()
            alert_details.append({
                "alert_id": str(alert.id),
                "poi_id": str(alert.poi_id),
                "poi_name": poi.name if poi else "Unknown",
                "poi_type": poi.poi_type if poi else "Unknown",
                "event_type": alert.event_type.value,
                "latitude": alert.latitude,
                "longitude": alert.longitude,
                "created_at": alert.created_at.isoformat()
            })
        
        # Check if user has email alerts enabled
        user = db.query(User).filter(User.id == current_user.id).first()
        email_enabled = user.email_alerts_enabled if user else False
        
        return {
            "success": True,
            "tracker_id": request.tracker_id,
            "test_location": {
                "latitude": request.latitude,
                "longitude": request.longitude
            },
            "alerts_triggered": len(alerts),
            "email_alerts_enabled": email_enabled,
            "message": f"Test completed. {len(alerts)} alert(s) generated. Email notifications {'sent' if email_enabled and alerts else 'not sent (email alerts disabled or no alerts triggered)'}.",
            "alerts": alert_details,
            "mailhog_url": "http://localhost:8025",
            "instructions": "Check MailHog at http://localhost:8025 to see email notifications if alerts were triggered and email_alerts_enabled is true."
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Mock location test error: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Error running mock test: {str(e)}")


@app.post("/api/v1/trips")
def get_trips_v1(
    request: dict,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Fetch trips (journeys) from MZone API for a specific BLE tag and date range
    Request body:
    {
        'vehicle_id': '88c45ad7-4054-40d8-b530-ed844e1c261a',  # GUID from DB
        'start_date': '2026-01-31T00:00:00',  # ISO format
        'end_date': '2026-03-11T23:59:59'     # ISO format
    }
    """
    import requests
    from datetime import datetime
    
    debug = os.getenv('DEBUG', 'False').lower() == 'true'
    
    try:
        # Extract request data
        vehicle_id = request.get('vehicle_id', '').strip() if isinstance(request, dict) else ''
        start_date_str = request.get('start_date', '').strip() if isinstance(request, dict) else ''
        end_date_str = request.get('end_date', '').strip() if isinstance(request, dict) else ''
        
        # Validate inputs
        if not vehicle_id or not start_date_str or not end_date_str:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="vehicle_id, start_date, and end_date are required"
            )
        
        # Parse dates
        try:
            start_date = datetime.fromisoformat(start_date_str.replace('Z', '+00:00'))
            end_date = datetime.fromisoformat(end_date_str.replace('Z', '+00:00'))
        except ValueError:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Invalid date format. Use ISO format (YYYY-MM-DDTHH:MM:SS)"
            )
        
        # Format dates for MZone API (UTC with Z suffix)
        utc_start = start_date.isoformat().replace('+00:00', 'Z').split('.')[0] + 'Z'
        utc_end = end_date.isoformat().replace('+00:00', 'Z').split('.')[0] + 'Z'
        
        if debug:
            logger.info(f"📍 Fetching trips for vehicle {vehicle_id}")
            logger.info(f"📅 Date range: {utc_start} to {utc_end}")
        
        # Get OAuth token for MZone API using correct password grant flow.
        # NOTE: this duplicates services/mzone_service.py:get_oauth_token —
        # a follow-up should consolidate. Until then we read the same env
        # vars and refuse to fall back to literals (was leaking credentials
        # into public git history). See .github/copilot-instructions.md.
        token_url = os.getenv("MZONE_TOKEN_URL", "https://login.mzoneweb.net/connect/token")
        token_response = requests.post(
            token_url,
            headers={'Content-Type': 'application/x-www-form-urlencoded'},
            data={
                "client_id": os.environ["MZONE_CLIENT_ID"],
                "client_secret": os.environ["MZONE_CLIENT_SECRET"],
                "username": os.environ["MZONE_USERNAME"],
                "password": os.environ["MZONE_PASSWORD"],
                "scope": os.getenv("MZONE_SCOPE", "mz6-api.all mz_username"),
                "grant_type": os.getenv("MZONE_GRANT_TYPE", "password"),
                "response_type": "code id_token"
            },
            timeout=10
        )
        
        if token_response.status_code != 200:
            if debug:
                logger.error(f"❌ Failed to get OAuth token: {token_response.status_code}")
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Failed to obtain access token from MZone"
            )
        
        access_token = token_response.json().get('access_token')
        if not access_token:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid token response from MZone"
            )
        
        # Build Trips API URL with filters
        from urllib.parse import urlencode
        
        # Get vehicle group ID from environment or database
        vehicle_group_id = os.getenv("MZONE_VEHICLE_GROUP_ID", "8e4fe3a7-4d46-474d-bf57-993828f70968")
        
        params = {
            '$format': 'json',
            '$count': 'true',
            '$select': 'vehicle_Description,duration,distance,startLocationDescription,startUtcTimestamp,endLocationDescription,endUtcTimestamp,driver_Description,id,vehicle_Id,driverKeyCode',
            '$orderby': 'startUtcTimestamp desc',
            '$skip': '0',
            '$top': '100',
            'utcStartDate': utc_start,
            'utcEndDate': utc_end,
            'vehicleGroup_Id': vehicle_group_id,
            'vehicle_Id': vehicle_id  # top-level param, not $filter
        }
        
        api_url = f'https://live.mzoneweb.net/mzone62.api/Trips?{urlencode(params)}'
        
        headers = {
            'Authorization': f'Bearer {access_token}',
            'Accept': 'application/json'
        }
        
        if debug:
            logger.info(f"🌐 Calling Trips API...")
            logger.info(f"🔗 URL (truncated): {api_url[:100]}...")
        
        response = requests.get(api_url, headers=headers, timeout=30)
        
        if response.status_code == 200:
            trips_data = response.json()
            trips = trips_data.get('value', [])
            count = trips_data.get('@odata.count', 0)
            
            if debug:
                logger.info(f"✅ Fetched {len(trips)} trips (total available: {count})")
            
            return {
                'success': True,
                'trips': trips,
                'total_count': count,
                'returned_count': len(trips),
                'vehicle_id': vehicle_id,
                'date_range': {
                    'start': utc_start,
                    'end': utc_end
                }
            }
        else:
            if debug:
                logger.error(f"❌ Failed to fetch trips: {response.status_code}")
                logger.error(f"📄 Response: {response.text[:500]}")
            raise HTTPException(
                status_code=response.status_code,
                detail=f"Trips API request failed: {response.status_code}"
            )
            
    except HTTPException:
        raise
    except Exception as e:
        if debug:
            logger.error(f"❌ Exception fetching trips: {str(e)}")
            import traceback
            traceback.print_exc()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error fetching trips: {str(e)}"
        )


# ---------------------------------------------------------------------------
# App Feature Flags (public — mobile app fetches on login)
# ---------------------------------------------------------------------------

@app.get("/api/v1/app-features")
def get_app_features_public(db: Session = Depends(get_db)):
    """Return the global app feature flags. No auth required so the app
    can fetch them before (or immediately after) login."""
    row = db.query(AppFeatures).filter(AppFeatures.id == "global").first()
    if not row:
        row = AppFeatures(id="global")
        db.add(row)
        db.commit()
        db.refresh(row)
    return {
        "show_map":       row.show_map,
        "show_journey":   row.show_journey,
        "show_assets":    row.show_assets,
        "show_scan":      row.show_scan,
        "show_settings":  row.show_settings,
        "show_solutions": row.show_solutions,
    }


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
