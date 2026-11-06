"""Long-lived device tokens: how the mobile app gets a new 12-hour access token without the password.

A driver can be on a breakdown for longer than an access token lasts, so a sign-in from the app also
gets one of these. Only its hash is stored, so a database leak can't be replayed. The app keeps it in
the phone's encrypted storage. Each use extends it; a phone that stays away for DEVICE_TOKEN_DAYS has
to sign in again. Signing out removes it; a password change removes all of the user's.
"""
import hashlib
import os
import secrets
from datetime import datetime, timedelta, timezone
from typing import Optional

from sqlalchemy.orm import Session

from app.models import PortalDeviceToken

DEVICE_TOKEN_DAYS = int(os.getenv("DEVICE_TOKEN_DAYS", "30"))


def _hash(raw: str) -> str:
    return hashlib.sha256(raw.encode()).hexdigest()


def issue(db: Session, user_id) -> str:
    """A new token for this user (the caller commits); also clears their expired ones."""
    now = datetime.now(timezone.utc)
    db.query(PortalDeviceToken).filter(PortalDeviceToken.user_id == user_id, PortalDeviceToken.expires_at < now).delete()
    raw = secrets.token_urlsafe(32)
    db.add(PortalDeviceToken(user_id=user_id, token_hash=_hash(raw), last_used_at=now,
                             expires_at=now + timedelta(days=DEVICE_TOKEN_DAYS)))
    return raw


def find(db: Session, raw: str) -> Optional[PortalDeviceToken]:
    """The unexpired token row, or None."""
    row = db.query(PortalDeviceToken).filter(PortalDeviceToken.token_hash == _hash(raw)).first()
    return row if row and row.expires_at > datetime.now(timezone.utc) else None


def touch(row: PortalDeviceToken) -> None:
    """Record a use and extend the token (the caller commits)."""
    now = datetime.now(timezone.utc)
    row.last_used_at = now
    row.expires_at = now + timedelta(days=DEVICE_TOKEN_DAYS)


def revoke(db: Session, raw: str) -> None:
    """Remove this token (the caller commits)."""
    db.query(PortalDeviceToken).filter(PortalDeviceToken.token_hash == _hash(raw)).delete()


def revoke_all(db: Session, user_id) -> None:
    """Remove every token of this user, e.g. when their password changes (the caller commits)."""
    db.query(PortalDeviceToken).filter(PortalDeviceToken.user_id == user_id).delete()
