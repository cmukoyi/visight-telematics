"""
Admin authentication and authorization utilities
"""
from datetime import datetime, timedelta
from typing import Optional
import secrets
import hashlib
import jwt
import os
from functools import lru_cache
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from sqlalchemy.orm import Session

from app.database import get_db

# Admin JWT Configuration
# Required — must be set in gps-tracker/backend/.env. Raises KeyError at
# import if unset (intentional: better to fail container start than to sign
# admin JWTs with the public literal we used to fall back to). See
# .github/copilot-instructions.md.
ADMIN_SECRET_KEY = os.environ["ADMIN_SECRET_KEY"]
ADMIN_ALGORITHM = "HS256"
ADMIN_ACCESS_TOKEN_EXPIRE_HOURS = 24


def hash_password(password: str) -> str:
    """Hash password using PBKDF2"""
    salt = secrets.token_hex(16)
    pwd_hash = hashlib.pbkdf2_hmac('sha256', password.encode(), salt.encode(), 100000)
    return f"{salt}${pwd_hash.hex()}"


def verify_password(stored_password: str, provided_password: str) -> bool:
    """Verify password against stored hash"""
    try:
        salt, pwd_hash = stored_password.split('$')
        provided_hash = hashlib.pbkdf2_hmac('sha256', provided_password.encode(), salt.encode(), 100000)
        return provided_hash.hex() == pwd_hash
    except Exception:
        return False


def create_admin_access_token(admin_id: str, username: str, role: str) -> str:
    """Create JWT token for admin"""
    payload = {
        "admin_id": admin_id,
        "username": username,
        "role": role,
        "exp": datetime.utcnow() + timedelta(hours=ADMIN_ACCESS_TOKEN_EXPIRE_HOURS),
        "iat": datetime.utcnow(),
        "type": "admin"
    }
    return jwt.encode(payload, ADMIN_SECRET_KEY, algorithm=ADMIN_ALGORITHM)


def decode_admin_token(token: str) -> Optional[dict]:
    """Decode and verify admin JWT token"""
    try:
        payload = jwt.decode(token, ADMIN_SECRET_KEY, algorithms=[ADMIN_ALGORITHM])
        if payload.get("type") != "admin":
            return None
        return payload
    except jwt.ExpiredSignatureError:
        return None
    except jwt.InvalidTokenError:
        return None


def get_admin_by_token(token: str) -> Optional[dict]:
    """Get admin info from token"""
    return decode_admin_token(token)


def require_admin_role(min_role: str = "viewer") -> bool:
    """Check if role has required permission"""
    roles = {"viewer": 1, "manager": 2, "admin": 3}
    return min_role in roles


def check_role_permission(user_role: str, required_role: str = "viewer") -> bool:
    """Check if user role meets requirement"""
    roles = {"viewer": 1, "manager": 2, "admin": 3}
    return roles.get(user_role, 0) >= roles.get(required_role, 0)


# FastAPI security scheme for Bearer token
admin_security = HTTPBearer()


def get_current_admin_user(
    credentials: HTTPAuthorizationCredentials = Depends(admin_security),
    db: Session = Depends(get_db),
):
    """
    FastAPI dependency: Get current authenticated admin user from JWT token.
    Requires 'Authorization: Bearer <token>' header.
    
    Returns the AdminUser model instance. Uses the request-scoped session so
    FastAPI closes it when the request ends.
    """
    # Import here to avoid circular dependency at module load time
    from app.models_admin import AdminUser
    
    token = credentials.credentials
    payload = decode_admin_token(token)
    
    if payload is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired admin token",
            headers={"WWW-Authenticate": "Bearer"},
        )
    
    admin_id = payload.get("admin_id")
    if admin_id is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid token payload",
            headers={"WWW-Authenticate": "Bearer"},
        )
    
    admin_user = db.query(AdminUser).filter(AdminUser.id == admin_id).first()
    if admin_user is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Admin user not found"
        )
    
    if not admin_user.is_active:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Inactive admin account"
        )
    
    return admin_user
