"""
Authentication API - Get bearer token for API access.
"""
from fastapi import APIRouter, Depends, HTTPException, status, Request
from sqlalchemy.orm import Session
from pydantic import BaseModel, EmailStr
from datetime import datetime, timedelta
from typing import Optional
import jwt
import os
import logging

from app.database import get_db
from app.models import User, UserGroup, PortalUser
from app.admin_auth import verify_password
from app.services import device_tokens
from app.auth import verify_password as verify_mobile_password

router = APIRouter(prefix="/api/auth", tags=["Authentication"])
logger = logging.getLogger(__name__)

# JWT Configuration
PORTAL_SECRET_KEY = os.environ.get("PORTAL_SECRET_KEY") or os.environ["ADMIN_SECRET_KEY"]
PORTAL_ALGORITHM = "HS256"
PORTAL_TOKEN_EXPIRE_HOURS = 12

# Rate limiting (from routes_portal.py)
_LOGIN_MAX_ATTEMPTS = int(os.getenv("PORTAL_LOGIN_MAX_ATTEMPTS", "5"))
_LOGIN_WINDOW_SECONDS = int(os.getenv("PORTAL_LOGIN_WINDOW_SECONDS", "60"))
_LOGIN_LOCKOUT_SECONDS = int(os.getenv("PORTAL_LOGIN_LOCKOUT_SECONDS", "900"))
_login_attempts: dict = {}
_login_lockouts: dict = {}


def _client_ip(request: "Request") -> str:
    """Best-effort client IP."""
    xff = request.headers.get("x-forwarded-for")
    if xff:
        return xff.split(",")[0].strip()
    try:
        return request.client.host  # type: ignore
    except Exception:
        return "unknown"


def _login_check_rate(ip: str) -> None:
    """Raise HTTP 429 if locked out."""
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
    """Record failed login attempt."""
    import time
    now = time.time()
    window_start = now - _LOGIN_WINDOW_SECONDS
    bucket = [t for t in _login_attempts.get(ip, []) if t >= window_start]
    bucket.append(now)
    _login_attempts[ip] = bucket
    if len(bucket) >= _LOGIN_MAX_ATTEMPTS:
        _login_lockouts[ip] = now + _LOGIN_LOCKOUT_SECONDS
        _login_attempts.pop(ip, None)
        logger.warning("Locking out %s for %ds after %d failures", ip, _LOGIN_LOCKOUT_SECONDS, len(bucket))


# Request/Response Models
class LoginRequest(BaseModel):
    """Login credentials."""
    email: EmailStr
    password: str
    remember_device: bool = False  # the mobile app: also return a refresh_token for POST /api/auth/refresh


class RefreshRequest(BaseModel):
    refresh_token: str


class TokenResponse(BaseModel):
    """Bearer token response."""
    access_token: str
    token_type: str = "bearer"
    expires_in: int = PORTAL_TOKEN_EXPIRE_HOURS * 3600
    usergroup_id: str
    portal_user_id: str
    refresh_token: Optional[str] = None


def _access_token(user: PortalUser) -> str:
    return jwt.encode({
        "type": "portal",  # Required by _decode_portal_token verification
        "portal_user_id": str(user.id),
        "usergroup_id": str(user.usergroup_id),
        "email": user.email,
        "exp": datetime.utcnow() + timedelta(hours=PORTAL_TOKEN_EXPIRE_HOURS),
    }, PORTAL_SECRET_KEY, algorithm=PORTAL_ALGORITHM)


@router.post("/login", response_model=TokenResponse, response_model_exclude_none=True)
def login(
    data: LoginRequest,
    request: Request,
    db: Session = Depends(get_db)
):
    """
    Authenticate and receive a bearer token for API access.
    
    **Supported Roles:**
    - `admin` - Full dashboard + API access
    - `manager` - Dashboard tracking/management + API access
    - `reporter` - Dashboard reports + API access
    - `api_only` - **API access ONLY** (no dashboard login)
    
    **Rate Limit:** 5 failed attempts per 60 seconds → 15 minute lockout
    
    **Token Expiry:** 12 hours
    
    **Example:**
    ```bash
    curl -X POST https://track.visighttelematics.co.za/api/auth/login \\
      -H "Content-Type: application/json" \\
      -d '{
        "email": "user@example.com",
        "password": "your-password"
      }'
    ```
    
    **Response:**
    ```json
    {
      "access_token": "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9...",
      "token_type": "bearer",
      "expires_in": 43200,
      "usergroup_id": "abc-123",
      "portal_user_id": "xyz-789"
    }
    ```
    
    **Usage:**
    Include the token in the `Authorization` header for all API requests:
    ```
    Authorization: Bearer eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9...
    ```
    
    **Note:** Users with `api_only` role can authenticate here and use API v2 endpoints,
    but cannot access the customer dashboard at /customer/
    """
    ip = _client_ip(request)
    _login_check_rate(ip)
    
    user = db.query(PortalUser).filter(
        PortalUser.email == data.email.lower().strip(),
        PortalUser.is_active == True,
    ).first()
    
    credential_user = db.query(User).filter(User.id == user.mobile_user_id).first() if user and user.mobile_user_id else None
    password_is_valid = (
        verify_mobile_password(data.password, credential_user.hashed_password)
        if credential_user and credential_user.hashed_password
        else bool(user and user.hashed_password and verify_password(user.hashed_password, data.password))
    )
    if not user or not password_is_valid:
        _login_record_failure(ip)
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid email or password"
        )
    
    # Auto-deactivate if expired
    if user.expires_at and user.expires_at < datetime.now(user.expires_at.tzinfo):
        user.is_active = False
        db.commit()
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="This account has expired"
        )
    if credential_user and not credential_user.is_active:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Linked account is inactive")
    
    # Verify usergroup is active
    group = db.query(UserGroup).filter(
        UserGroup.id == user.usergroup_id,
        UserGroup.is_active == True,
    ).first()
    
    if not group:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Your organization account is not active"
        )
    
    refresh_token = None
    if data.remember_device:
        refresh_token = device_tokens.issue(db, user.id)
        db.commit()

    logger.info("User %s logged in from %s", user.email, ip)
    
    return TokenResponse(
        access_token=_access_token(user),
        usergroup_id=str(user.usergroup_id),
        portal_user_id=str(user.id),
        refresh_token=refresh_token,
    )


@router.post("/refresh", response_model=TokenResponse, response_model_exclude_none=True, include_in_schema=False)
def refresh(data: RefreshRequest, db: Session = Depends(get_db)):
    """A new access token for the mobile app, without the password, as long as the account can still sign in."""
    row = device_tokens.find(db, data.refresh_token)
    user = db.query(PortalUser).filter(PortalUser.id == row.user_id, PortalUser.is_active == True).first() if row else None
    credential_user = db.query(User).filter(User.id == user.mobile_user_id).first() if user and user.mobile_user_id else None
    group = db.query(UserGroup).filter(UserGroup.id == user.usergroup_id, UserGroup.is_active == True).first() if user else None
    expired = bool(user and user.expires_at and user.expires_at < datetime.now(user.expires_at.tzinfo))
    if not user or not group or expired or (credential_user and not credential_user.is_active):
        if row:
            db.delete(row)
            db.commit()
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Please sign in again")
    device_tokens.touch(row)
    db.commit()
    return TokenResponse(access_token=_access_token(user), usergroup_id=str(user.usergroup_id), portal_user_id=str(user.id))


@router.post("/logout", status_code=204, include_in_schema=False)
def logout(data: RefreshRequest, db: Session = Depends(get_db)):
    """Forget this phone: its refresh token stops working."""
    device_tokens.revoke(db, data.refresh_token)
    db.commit()
