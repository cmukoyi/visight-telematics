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

# Admin JWT Configuration
ADMIN_SECRET_KEY = os.getenv("ADMIN_SECRET_KEY", "your-secret-admin-key-change-in-production")
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
