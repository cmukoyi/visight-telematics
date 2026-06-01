"""Asset tracking schemas for QR/NFC asset tracking"""
from pydantic import BaseModel, field_validator
from typing import Optional
from datetime import datetime
from uuid import UUID


class AssetCreate(BaseModel):
    """Request body for creating a new asset"""
    id: str
    type_code: str
    name: Optional[str] = None
    category: Optional[str] = None
    owner_id: Optional[UUID] = None
    notes: Optional[str] = None

    @field_validator("type_code")
    @classmethod
    def validate_type_code(cls, v):
        if v not in ("Q", "N"):
            raise ValueError("type_code must be Q (QR) or N (NFC)")
        return v

    @field_validator("id")
    @classmethod
    def validate_id(cls, v):
        if not v or not v.strip():
            raise ValueError("id is required")
        return v.strip()


class AssetResponse(BaseModel):
    """Response model for asset with optional location data"""
    id: str
    type_code: str
    name: Optional[str] = None
    category: Optional[str] = None
    owner_id: Optional[UUID] = None
    created_at: datetime
    # Optional location fields from asset_locations join
    lat: Optional[float] = None
    lng: Optional[float] = None
    accuracy: Optional[float] = None
    last_seen: Optional[datetime] = None
    scan_count: Optional[int] = None

    class Config:
        from_attributes = True


class ScanRequest(BaseModel):
    """Request body for recording a GPS scan"""
    asset_id: str
    lat: float
    lng: float
    accuracy: Optional[float] = None
    source: Optional[str] = "qr"

    @field_validator("asset_id")
    @classmethod
    def validate_asset_id(cls, v):
        if not v or not v.strip():
            raise ValueError("asset_id is required")
        return v.strip()

    @field_validator("lat")
    @classmethod
    def validate_lat(cls, v):
        if not (-90 <= v <= 90):
            raise ValueError("lat must be between -90 and 90")
        return v

    @field_validator("lng")
    @classmethod
    def validate_lng(cls, v):
        if not (-180 <= v <= 180):
            raise ValueError("lng must be between -180 and 180")
        return v

    @field_validator("source")
    @classmethod
    def validate_source(cls, v):
        if v not in ("qr", "nfc", "manual"):
            raise ValueError("source must be qr, nfc, or manual")
        return v


class ScanResponse(BaseModel):
    """Response model after successful scan recording"""
    success: bool
    asset_id: str
    asset_name: Optional[str] = None
    scan_count: int
    message: str


class ScanEventResponse(BaseModel):
    """Individual scan event in history"""
    id: int
    asset_id: str
    lat: float
    lng: float
    accuracy: Optional[float] = None
    source: str
    scanned_at: datetime
    scanner_ip: Optional[str] = None

    class Config:
        from_attributes = True


class AssetHistoryResponse(BaseModel):
    """Full history response for an asset"""
    asset_id: str
    total: int
    limit: int
    offset: int
    history: list[ScanEventResponse]
