"""QR/NFC asset registration - integrates with existing ble_tags table"""
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from pydantic import BaseModel

from app.database import get_db
from app.models import BLETag
from app.models_admin import TagPackage

router = APIRouter(prefix="/api/qr-assets", tags=["qr-assets"])


class QRAssetRegister(BaseModel):
    imei: str
    type_code: str  # 'Q' for QR, 'N' for NFC


@router.post("/register", status_code=201)
async def register_qr_asset(body: QRAssetRegister, db: Session = Depends(get_db)):
    """
    Register a QR/NFC asset as a series_3 tag (called when QR code is downloaded).
    Creates a ble_tags row so asset appears in Asset List and Asset Management.
    Returns success even if already registered (idempotent).
    """
    # Check if already registered
    existing = db.query(BLETag).filter(BLETag.imei == body.imei).first()
    if existing:
        return {
            "success": True,
            "message": "Already registered",
            "imei": body.imei,
            "tag_id": str(existing.id)
        }
    
    # Get default package
    default_pkg = db.query(TagPackage).filter(
        TagPackage.is_default == True,
        TagPackage.is_active == True,
    ).first()
    
    # Create ble_tags row for series_3 QR asset
    asset_type = 'QR' if body.type_code == 'Q' else 'NFC'
    tag = BLETag(
        imei=body.imei,
        tag_type='series_3',
        device_name=f"{asset_type} Asset {body.imei[:8]}",
        description=f"{asset_type} Asset - Auto-registered",
        is_active=True,
        attributes={
            'category': {'value': 'series_3', 'show_on_map': True},
            '_qr_asset': True,
            '_type_code': body.type_code
        }
    )
    
    # Auto-assign default package if available
    if default_pkg:
        tag.package_id = str(default_pkg.id)
    
    db.add(tag)
    db.commit()
    db.refresh(tag)
    
    return {
        "success": True,
        "message": f"{asset_type} asset registered as series_3 tag",
        "imei": body.imei,
        "tag_id": str(tag.id)
    }
