"""QR/NFC asset registration - integrates with existing ble_tags table."""
import os
from typing import Optional, Tuple

import jwt
from fastapi import APIRouter, Depends
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from sqlalchemy import func
from sqlalchemy.orm import Session
from pydantic import BaseModel

from app.database import get_db
from app.models import BLETag, User, PortalUser
from app.models_admin import TagPackage
from app.auth import decode_token

router = APIRouter(prefix="/api/qr-assets", tags=["qr-assets"])

_bearer = HTTPBearer(auto_error=False)


class QRAssetRegister(BaseModel):
    imei: str
    type_code: str  # 'Q' for QR, 'N' for NFC


def _decode_portal_token(token: str) -> Optional[dict]:
    """Decode a portal JWT. Returns payload when valid, else None."""
    secret = os.getenv("PORTAL_SECRET_KEY") or os.getenv("ADMIN_SECRET_KEY")
    if not secret:
        return None
    try:
        payload = jwt.decode(token, secret, algorithms=["HS256"])
    except jwt.InvalidTokenError:
        return None
    if payload.get("type") != "portal":
        return None
    return payload


def _find_mobile_user_by_email(email: str, db: Session) -> Optional[User]:
    """Find a mobile-app User by email (case-insensitive)."""
    if not email:
        return None
    return db.query(User).filter(func.lower(User.email) == email.strip().lower()).first()


def _create_mobile_user_from_portal(portal_user: PortalUser, db: Session) -> Optional[User]:
    """Create a mobile-app User row for a portal account if one does not exist."""
    email = (portal_user.email or "").strip().lower()
    if not email:
        return None
    user = User(
        email=email,
        hashed_password=None,
        first_name=portal_user.first_name,
        last_name=portal_user.last_name,
        is_active=True,
        email_verified=True,
    )
    db.add(user)
    db.flush()
    return user


def _resolve_registration_identity(
    credentials: Optional[HTTPAuthorizationCredentials],
    db: Session,
) -> Tuple[Optional[User], Optional[str]]:
    """Resolve owner identity from either user-token or portal-token.

    Returns:
      (mobile_user, usergroup_id_for_audit)
    """
    if not credentials:
        return None, None

    token = credentials.credentials

    # 1) Standard user JWT (/api/v1 auth)
    payload = decode_token(token)
    if payload:
        user_id = payload.get("sub")
        if user_id:
            user = db.query(User).filter(User.id == user_id).first()
            if user:
                return user, None

    # 2) Portal JWT (/api/portal auth)
    portal_payload = _decode_portal_token(token)
    if not portal_payload:
        return None, None

    portal_user_id = portal_payload.get("portal_user_id")
    if not portal_user_id:
        return None, None

    portal_user = db.query(PortalUser).filter(PortalUser.id == portal_user_id).first()
    if not portal_user or not portal_user.is_active:
        return None, None

    mobile_user = _find_mobile_user_by_email(portal_user.email, db)
    if not mobile_user:
        mobile_user = _create_mobile_user_from_portal(portal_user, db)

    return mobile_user, str(portal_user.usergroup_id)


@router.post("/register", status_code=201)
async def register_qr_asset(
    body: QRAssetRegister,
    db: Session = Depends(get_db),
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(_bearer),
):
    """
    Register a QR/NFC asset as a series_3 tag (called when QR code is downloaded).
    If a valid auth token is supplied, the tag is assigned to that owner.
    Portal-created tags are stamped with creator usergroup metadata.
    Returns success even if already registered (idempotent).
    """
    current_user, creator_usergroup_id = _resolve_registration_identity(credentials, db)

    # Check if already registered
    existing = db.query(BLETag).filter(BLETag.imei == body.imei).first()
    if existing:
        changed = False
        if existing.user_id is None and current_user:
            existing.user_id = current_user.id
            changed = True
        if creator_usergroup_id:
            attrs = dict(existing.attributes or {})
            if attrs.get("_created_usergroup_id") != creator_usergroup_id:
                attrs["_created_usergroup_id"] = creator_usergroup_id
                attrs.setdefault("_created_by", "portal")
                existing.attributes = attrs
                changed = True
        if changed:
            db.commit()
        return {
            "success": True,
            "message": "Already registered",
            "imei": body.imei,
            "tag_id": str(existing.id),
            "user_id": str(existing.user_id) if existing.user_id else None,
            "usergroup_id": creator_usergroup_id,
        }

    # Get default package
    default_pkg = db.query(TagPackage).filter(
        TagPackage.is_default == True,
        TagPackage.is_active == True,
    ).first()

    # Create ble_tags row for series_3 QR asset
    asset_type = 'QR' if body.type_code == 'Q' else 'NFC'
    attrs = {
        'category': {'value': 'series_3', 'show_on_map': True},
        '_qr_asset': True,
        '_type_code': body.type_code,
    }
    if creator_usergroup_id:
        attrs['_created_usergroup_id'] = creator_usergroup_id
        attrs['_created_by'] = 'portal'

    tag = BLETag(
        user_id=current_user.id if current_user else None,
        imei=body.imei,
        tag_type='series_3',
        device_name=f"{asset_type} Asset {body.imei[:8]}",
        description=f"{asset_type} Asset - Auto-registered",
        is_active=True,
        attributes=attrs,
    )

    if default_pkg:
        tag.package_id = str(default_pkg.id)

    db.add(tag)
    db.commit()
    db.refresh(tag)

    return {
        "success": True,
        "message": f"{asset_type} asset registered as series_3 tag",
        "imei": body.imei,
        "tag_id": str(tag.id),
        "user_id": str(tag.user_id) if tag.user_id else None,
        "usergroup_id": creator_usergroup_id,
    }
