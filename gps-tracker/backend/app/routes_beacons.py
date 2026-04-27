"""
Beacon Sighting Router
======================
Handles crowdsourced BLE tag location data reported by mobile phones.

Endpoints:
  POST /api/v1/beacons/sighting   — record a tag sighting with phone GPS
  GET  /api/v1/beacons/locations  — last known location per tag (this user)
"""

from datetime import datetime
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel, Field, confloat
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.auth import decode_token
from app.database import get_db
from app.models import BeaconSighting, User

router = APIRouter(prefix="/api/v1/beacons", tags=["beacons"])
_security = HTTPBearer()


# ── Auth dependency ────────────────────────────────────────────────────────────

def _get_current_user(
    credentials: HTTPAuthorizationCredentials = Depends(_security),
    db: Session = Depends(get_db),
) -> User:
    payload = decode_token(credentials.credentials)
    if payload is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED,
                            detail="Invalid authentication credentials")
    user_id = payload.get("sub")
    if user_id is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED,
                            detail="Invalid token payload")
    user = db.query(User).filter(User.id == user_id).first()
    if user is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND,
                            detail="User not found")
    if not user.is_active:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN,
                            detail="Inactive user")
    return user


# ── Schemas ────────────────────────────────────────────────────────────────────

class BeaconSightingCreate(BaseModel):
    tag_id: str = Field(..., max_length=64, description="BLE device MAC or UUID")
    tag_name: Optional[str] = Field(None, max_length=255)
    lat: float = Field(..., ge=-90, le=90)
    lon: float = Field(..., ge=-180, le=180)
    rssi: Optional[int] = Field(None, ge=-120, le=0)
    timestamp: Optional[datetime] = None


class BeaconLocationResponse(BaseModel):
    tag_id: str
    tag_name: Optional[str]
    lat: float
    lon: float
    rssi: Optional[int]
    last_seen: datetime

    class Config:
        from_attributes = True


# ── Endpoints ──────────────────────────────────────────────────────────────────

@router.post("/sighting", status_code=201)
def record_sighting(
    payload: BeaconSightingCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(_get_current_user),
):
    """
    Record a BLE tag sighting reported by a phone.
    The phone's GPS coordinates are stored as the tag's last known location.
    """
    sighting = BeaconSighting(
        user_id=current_user.id,
        tag_id=payload.tag_id,
        tag_name=payload.tag_name,
        latitude=payload.lat,
        longitude=payload.lon,
        rssi=payload.rssi,
        sighted_at=payload.timestamp or datetime.utcnow(),
    )
    db.add(sighting)
    db.commit()
    return {"status": "ok"}


@router.get("/locations", response_model=List[BeaconLocationResponse])
def get_beacon_locations(
    db: Session = Depends(get_db),
    current_user: User = Depends(_get_current_user),
):
    """
    Return the most recent sighting for every unique BLE tag seen by this user.
    Used by the mobile app to plot last known positions on a map.
    """
    # Subquery: latest sighted_at per tag for this user.
    sub = (
        db.query(
            BeaconSighting.tag_id,
            func.max(BeaconSighting.sighted_at).label("latest"),
        )
        .filter(BeaconSighting.user_id == current_user.id)
        .group_by(BeaconSighting.tag_id)
        .subquery()
    )

    rows = (
        db.query(BeaconSighting)
        .join(
            sub,
            (BeaconSighting.tag_id == sub.c.tag_id)
            & (BeaconSighting.sighted_at == sub.c.latest),
        )
        .filter(BeaconSighting.user_id == current_user.id)
        .all()
    )

    return [
        BeaconLocationResponse(
            tag_id=s.tag_id,
            tag_name=s.tag_name,
            lat=s.latitude,
            lon=s.longitude,
            rssi=s.rssi,
            last_seen=s.sighted_at,
        )
        for s in rows
    ]
