"""
Public API v2 - Production-ready endpoints with bearer token authentication.

All endpoints require Bearer token from POST /api/portal/login.
All responses are scoped to the authenticated user's usergroup.
"""
from fastapi import APIRouter, Depends, HTTPException, status, Request, Query
from sqlalchemy.orm import Session
from datetime import datetime
from typing import List, Optional
from pydantic import BaseModel
import logging

from app.database import get_db
from app.models import BLETag, DevicePosition, PortalUser, POI, PortalAlert, User, UserGroup
from app.routes_portal import get_portal_user_from_request
from sqlalchemy import or_

router = APIRouter(prefix="/api/v2", tags=["API v2"])
logger = logging.getLogger(__name__)


def get_current_portal_user(request: Request, db: Session = Depends(get_db)) -> PortalUser:
    """Dependency: Verify bearer token and return authenticated PortalUser."""
    return get_portal_user_from_request(request, db)


def _get_usergroup_device_imeis(usergroup_id: str, db: Session) -> List[str]:
    """
    Get all device IMEIs belonging to a usergroup.
    
    Implements proper multi-tenant isolation by:
    1. Finding mobile-app users linked via the PortalUser table
    2. Querying BLETag where user_id matches OR tag was created by the group
    3. Returning distinct IMEIs for devices owned by the group
    """
    # Get the usergroup
    group = db.query(UserGroup).filter(UserGroup.id == usergroup_id).first()
    if not group:
        return []
    
    group_id = str(group.id)

    # Mobile-app users linked to the group (via PortalUser table)
    portal_user_rows = (
        db.query(User.id)
        .join(PortalUser, User.email == PortalUser.email)
        .filter(PortalUser.usergroup_id == usergroup_id)
        .all()
    )
    portal_user_ids = [str(uid) for (uid,) in portal_user_rows]
    
    all_owner_ids = list(set(portal_user_ids))
    
    # Query BLETag with group scope filter
    tag_scope_filter = (
        or_(
            BLETag.user_id.in_(all_owner_ids),
            BLETag.attributes.op("->>")("_created_usergroup_id") == group_id,
        )
        if all_owner_ids
        else BLETag.attributes.op("->>")("_created_usergroup_id") == group_id
    )
    
    # Get all IMEIs for this group's devices
    tags = (
        db.query(BLETag.imei)
        .filter(
            tag_scope_filter,
            BLETag.is_active == True,
            BLETag.imei.isnot(None),
            BLETag.imei != "",
            or_(BLETag.tag_type.is_(None), BLETag.tag_type.notin_(("series3", "series_3"))),
        )
        .distinct()
        .all()
    )
    
    return [imei for (imei,) in tags]


# =============================================================================
# Response Models
# =============================================================================

class DevicePositionResponse(BaseModel):
    """Device with last known position (position fields are None if device has no GPS data)."""
    imei: str
    latitude: Optional[float]
    longitude: Optional[float]
    timestamp: Optional[datetime]
    battery_level: Optional[int]
    is_indoor: Optional[bool]
    address: Optional[str]

    class Config:
        from_attributes = True


class DeviceListResponse(BaseModel):
    """List of devices with positions."""
    total: int
    devices: List[DevicePositionResponse]


class MovementHistoryItem(BaseModel):
    """Single position in movement history."""
    imei: str
    timestamp: datetime
    latitude: float
    longitude: float
    speed_kmh: Optional[float]
    bearing: Optional[int]
    battery_level: Optional[int]
    address: Optional[str]

    class Config:
        from_attributes = True


class MovementHistoryResponse(BaseModel):
    """Movement history for a device."""
    imei: str
    total_positions: int
    start_date: datetime
    end_date: datetime
    positions: List[MovementHistoryItem]


class GeofenceResponse(BaseModel):
    """Geofence (POI) details."""
    id: str
    name: str
    is_armed: bool
    latitude: float
    longitude: float
    radius_m: float
    created_at: datetime

    class Config:
        from_attributes = True


class AlertResponse(BaseModel):
    """Alert notification."""
    id: str
    alert_type: str
    message: str
    tag_id: Optional[str]
    tag_name: Optional[str]
    geofence_name: Optional[str]
    created_at: datetime
    is_read: bool

    class Config:
        from_attributes = True


# =============================================================================
# API Endpoints
# =============================================================================

@router.get("/devices", response_model=DeviceListResponse)
def get_devices(
    user: PortalUser = Depends(get_current_portal_user),
    db: Session = Depends(get_db),
):
    """
    Get all devices (IMEIs) with their last known positions.
    
    **Authentication:** Bearer token required  
    **Scope:** ✅ Only returns devices in the authenticated user's usergroup (multi-tenant isolation)
    
    **Returns:** All devices in your usergroup, even if they haven't sent GPS data yet.
    Position fields will be `null` for devices without GPS data.
    
    **Example:**
    ```bash
    curl -X GET https://track.visighttelematics.co.za/api/v2/devices \\
      -H "Authorization: Bearer YOUR_TOKEN"
    ```
    """
    from sqlalchemy import func
    
    # Get IMEIs for this usergroup ONLY (multi-tenant isolation)
    allowed_imeis = _get_usergroup_device_imeis(str(user.usergroup_id), db)
    
    if not allowed_imeis:
        return DeviceListResponse(total=0, devices=[])
    
    # Build position lookup: IMEI -> latest position
    position_map = {}
    
    # Source 1: device_positions table (for GPS trackers - Series 2)
    subq = (
        db.query(
            DevicePosition.device_imei,
            func.max(DevicePosition.observed_at).label("latest_time")
        )
        .filter(DevicePosition.device_imei.in_(allowed_imeis))
        .group_by(DevicePosition.device_imei)
        .subquery()
    )
    
    gps_positions = (
        db.query(DevicePosition)
        .join(
            subq,
            (DevicePosition.device_imei == subq.c.device_imei) &
            (DevicePosition.observed_at == subq.c.latest_time)
        )
        .all()
    )
    
    for pos in gps_positions:
        position_map[pos.device_imei] = {
            'latitude': pos.lat,
            'longitude': pos.lng,
            'timestamp': pos.observed_at,
            'address': pos.address if hasattr(pos, 'address') else None,
        }
    
    # Source 2: ble_tags table (for Series 3 QR and BLE devices)
    # These store position directly on the tag record
    tags_with_positions = (
        db.query(BLETag)
        .filter(
            BLETag.imei.in_(allowed_imeis),
            BLETag.latitude.isnot(None),
            BLETag.longitude.isnot(None),
        )
        .all()
    )
    
    for tag in tags_with_positions:
        # Only use ble_tags position if not already found in device_positions
        if tag.imei not in position_map:
            try:
                position_map[tag.imei] = {
                    'latitude': float(tag.latitude) if tag.latitude else None,
                    'longitude': float(tag.longitude) if tag.longitude else None,
                    'timestamp': tag.last_seen,
                    'address': tag.location_description,
                }
            except (ValueError, TypeError):
                # Skip if latitude/longitude can't be converted to float
                pass
    
    # Return ALL devices in usergroup (with or without positions)
    devices = []
    for imei in allowed_imeis:
        pos_data = position_map.get(imei)
        
        if pos_data:
            # Device has GPS data (from either source)
            devices.append(DevicePositionResponse(
                imei=imei,
                latitude=pos_data['latitude'],
                longitude=pos_data['longitude'],
                timestamp=pos_data['timestamp'],
                battery_level=None,
                is_indoor=False,
                address=pos_data['address'],
            ))
        else:
            # Device exists but no GPS data yet
            devices.append(DevicePositionResponse(
                imei=imei,
                latitude=None,
                longitude=None,
                timestamp=None,
                battery_level=None,
                is_indoor=None,
                address=None,
            ))
    
    return DeviceListResponse(
        total=len(devices),
        devices=devices
    )


@router.get("/movement-history/{imei}", response_model=MovementHistoryResponse)
def get_movement_history(
    imei: str,
    start_date: datetime = Query(..., description="Start date (ISO 8601)"),
    end_date: datetime = Query(..., description="End date (ISO 8601)"),
    limit: int = Query(1000, ge=1, le=10000, description="Max positions to return"),
    user: PortalUser = Depends(get_current_portal_user),
    db: Session = Depends(get_db),
):
    """
    Get movement history for a specific IMEI within a date range.
    
    **Authentication:** Bearer token required  
    **Scope:** ✅ Only returns data if the IMEI belongs to the user's usergroup (multi-tenant isolation)
    
    **Example:**
    ```bash
    curl -X GET "https://track.visighttelematics.co.za/api/v2/movement-history/781950640095475?start_date=2026-07-01T00:00:00Z&end_date=2026-07-26T23:59:59Z" \\
      -H "Authorization: Bearer YOUR_TOKEN"
    ```
    """
    # 🔒 SECURITY: Verify IMEI belongs to user's usergroup
    allowed_imeis = _get_usergroup_device_imeis(str(user.usergroup_id), db)
    
    if imei not in allowed_imeis:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Device not found or not accessible"
        )
    
    # Query positions within date range
    positions = db.query(DevicePosition).filter(
        DevicePosition.device_imei == imei,
        DevicePosition.observed_at >= start_date,
        DevicePosition.observed_at <= end_date
    ).order_by(DevicePosition.observed_at.desc()).limit(limit).all()
    
    position_items = [
        MovementHistoryItem(
            imei=pos.device_imei,
            timestamp=pos.observed_at,
            latitude=pos.lat,
            longitude=pos.lng,
            speed_kmh=pos.gps_speed,
            bearing=pos.direction,
            battery_level=None,  # DevicePosition doesn't have battery
            address=pos.address if hasattr(pos, 'address') else None,
        )
        for pos in positions
    ]
    
    return MovementHistoryResponse(
        imei=imei,
        start_date=start_date,
        end_date=end_date,
        total_positions=len(position_items),
        positions=position_items
    )


@router.get("/geofences", response_model=List[GeofenceResponse])
def get_geofences(
    armed_only: bool = Query(False, description="Only return armed geofences"),
    user: PortalUser = Depends(get_current_portal_user),
    db: Session = Depends(get_db),
):
    """
    Get all geofences (POIs) for the user's usergroup.
    
    **Authentication:** Bearer token required  
    **Scope:** Only returns geofences from the user's usergroup
    
    **Example:**
    ```bash
    curl -X GET "https://track.visighttelematics.co.za/api/v2/geofences?armed_only=true" \\
      -H "Authorization: Bearer YOUR_TOKEN"
    ```
    """
    # Get all POIs (geofences) for usergroup
    query = db.query(POI).filter(
        POI.usergroup_id == user.usergroup_id
    )
    
    if armed_only:
        query = query.filter(POI.is_active == True)
    
    pois = query.order_by(POI.created_at.desc()).all()
    
    return [
        GeofenceResponse(
            id=str(poi.id),
            name=poi.name,
            is_armed=poi.is_active,
            latitude=poi.latitude,
            longitude=poi.longitude,
            radius_m=poi.radius,
            created_at=poi.created_at
        )
        for poi in pois
    ]


@router.get("/alerts", response_model=List[AlertResponse])
def get_alerts(
    alert_type: Optional[str] = Query(None, description="Filter by type: geofence_exit, battery_low, offline"),
    start_date: Optional[datetime] = Query(None, description="Filter alerts after this date"),
    end_date: Optional[datetime] = Query(None, description="Filter alerts before this date"),
    unread_only: bool = Query(False, description="Only return unread alerts"),
    limit: int = Query(100, ge=1, le=1000, description="Max alerts to return"),
    user: PortalUser = Depends(get_current_portal_user),
    db: Session = Depends(get_db),
):
    """
    Get alerts for the user's usergroup.
    
    **Authentication:** Bearer token required  
    **Scope:** Only returns alerts from the user's usergroup
    
    **Alert Types:**
    - `geofence_exit` - Asset left a geofence
    - `battery_low` - Asset battery is low
    - `offline` - Asset went offline
    
    **Example:**
    ```bash
    curl -X GET "https://track.visighttelematics.co.za/api/v2/alerts?alert_type=geofence_exit&unread_only=true" \\
      -H "Authorization: Bearer YOUR_TOKEN"
    ```
    """
    query = db.query(PortalAlert).filter(
        PortalAlert.usergroup_id == user.usergroup_id
    )
    
    if alert_type:
        query = query.filter(PortalAlert.alert_type == alert_type)
    
    if start_date:
        query = query.filter(PortalAlert.created_at >= start_date)
    
    if end_date:
        query = query.filter(PortalAlert.created_at <= end_date)
    
    if unread_only:
        query = query.filter(PortalAlert.is_read == False)
    
    alerts = query.order_by(PortalAlert.created_at.desc()).limit(limit).all()
    
    alert_responses = []
    for alert in alerts:
        # Get tag info if alert has tag_id
        tag = None
        if alert.tag_id:
            tag = db.query(BLETag).filter(BLETag.id == alert.tag_id).first()
        
        # Get geofence info if alert has geofence_id
        geofence = None
        if hasattr(alert, 'geofence_id') and alert.geofence_id:
            geofence = db.query(POI).filter(POI.id == alert.geofence_id).first()
        
        alert_responses.append(AlertResponse(
            id=str(alert.id),
            alert_type=alert.alert_type,
            message=alert.message,
            tag_id=str(alert.tag_id) if alert.tag_id else None,
            tag_name=tag.device_name if tag else None,
            geofence_name=geofence.name if geofence else None,
            created_at=alert.created_at,
            is_read=alert.is_read
        ))
    
    return alert_responses
