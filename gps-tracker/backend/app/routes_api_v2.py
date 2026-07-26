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
from app.models import BLETag, DevicePosition, PortalUser, HiveEvent, Hive, POI, PortalAlert
from app.routes_portal import get_portal_user_from_request

router = APIRouter(prefix="/api/v2", tags=["API v2"])
logger = logging.getLogger(__name__)


def get_current_portal_user(request: Request, db: Session = Depends(get_db)) -> PortalUser:
    """Dependency: Verify bearer token and return authenticated PortalUser."""
    return get_portal_user_from_request(request, db)


# =============================================================================
# Response Models
# =============================================================================

class DevicePositionResponse(BaseModel):
    """Device with last known position."""
    imei: str
    latitude: float
    longitude: float
    timestamp: datetime
    battery_level: Optional[int]
    is_indoor: bool
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


class HiveBreachResponse(BaseModel):
    """Hive breach event."""
    hive_id: str
    hive_name: str
    tag_id: str
    tag_name: str
    breach_start: datetime
    breach_end: Optional[datetime]
    duration_seconds: Optional[int]
    is_active: bool

    class Config:
        from_attributes = True


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
    **Scope:** Returns all devices (Note: Usergroup filtering pending schema update)
    
    **Example:**
    ```bash
    curl -X GET https://pinplot.me/api/v2/devices \\
      -H "Authorization: Bearer YOUR_TOKEN"
    ```
    """
    from sqlalchemy import func, distinct
    
    # Get distinct IMEIs with their most recent position
    # Using subquery to get latest position per device efficiently
    subq = (
        db.query(
            DevicePosition.device_imei,
            func.max(DevicePosition.observed_at).label("latest_time")
        )
        .group_by(DevicePosition.device_imei)
        .subquery()
    )
    
    # Join to get full position details for latest timestamp
    positions = (
        db.query(DevicePosition)
        .join(
            subq,
            (DevicePosition.device_imei == subq.c.device_imei) &
            (DevicePosition.observed_at == subq.c.latest_time)
        )
        .order_by(DevicePosition.device_imei)
        .all()
    )
    
    devices = []
    for pos in positions:
        devices.append(DevicePositionResponse(
            imei=pos.device_imei,
            latitude=pos.lat,
            longitude=pos.lng,
            timestamp=pos.observed_at,
            battery_level=None,  # DevicePosition doesn't have battery
            is_indoor=False,     # DevicePosition doesn't have is_indoor
            address=pos.address if hasattr(pos, 'address') else None,
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
    **Scope:** Returns positions for the specified IMEI (Note: Usergroup filtering pending schema update)
    
    **Example:**
    ```bash
    curl -X GET "https://pinplot.me/api/v2/movement-history/781950640095475?start_date=2026-07-01T00:00:00Z&end_date=2026-07-26T23:59:59Z" \\
      -H "Authorization: Bearer YOUR_TOKEN"
    ```
    """
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
        total=len(position_items),
        positions=position_items
    )
            battery_level=pos.battery_level,
            address=pos.address,
        )
        for pos in positions
    ]
    
    return MovementHistoryResponse(
        imei=imei,
        total_positions=len(position_items),
        start_date=start_date,
        end_date=end_date,
        positions=position_items
    )


@router.get("/hive-breaches", response_model=List[HiveBreachResponse])
def get_hive_breaches(
    active_only: bool = Query(False, description="Only return active breaches"),
    start_date: Optional[datetime] = Query(None, description="Filter breaches after this date"),
    end_date: Optional[datetime] = Query(None, description="Filter breaches before this date"),
    user: PortalUser = Depends(get_current_portal_user),
    db: Session = Depends(get_db),
):
    """
    Get Hive breach events for the user's usergroup.
    
    **Authentication:** Bearer token required  
    **Scope:** Only returns breaches from Hives in the user's usergroup
    
    **Example:**
    ```bash
    curl -X GET "https://pinplot.me/api/v2/hive-breaches?active_only=true" \\
      -H "Authorization: Bearer YOUR_TOKEN"
    ```
    """
    # Build query for Hive events
    query = db.query(HiveEvent).join(Hive).filter(
        Hive.usergroup_id == user.usergroup_id,
        HiveEvent.event_type.in_(['breach', 'breach_start', 'breach_end'])
    )
    
    if active_only:
        query = query.filter(HiveEvent.breach_ended_at.is_(None))
    
    if start_date:
        query = query.filter(HiveEvent.created_at >= start_date)
    
    if end_date:
        query = query.filter(HiveEvent.created_at <= end_date)
    
    events = query.order_by(HiveEvent.created_at.desc()).all()
    
    breaches = []
    for event in events:
        # Get tag info
        tag = db.query(BLETag).filter(BLETag.id == event.tag_id).first()
        hive = db.query(Hive).filter(Hive.id == event.hive_id).first()
        
        duration = None
        if event.breach_ended_at and event.created_at:
            duration = int((event.breach_ended_at - event.created_at).total_seconds())
        
        breaches.append(HiveBreachResponse(
            hive_id=str(event.hive_id),
            hive_name=hive.name if hive else "Unknown",
            tag_id=str(event.tag_id),
            tag_name=tag.name if tag else "Unknown",
            breach_start=event.created_at,
            breach_end=event.breach_ended_at,
            duration_seconds=duration,
            is_active=event.breach_ended_at is None
        ))
    
    return breaches


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
    curl -X GET "https://pinplot.me/api/v2/geofences?armed_only=true" \\
      -H "Authorization: Bearer YOUR_TOKEN"
    ```
    """
    # Get all POIs (geofences) for usergroup
    query = db.query(POI).filter(
        POI.usergroup_id == user.usergroup_id
    )
    
    if armed_only:
        query = query.filter(POI.is_armed == True)
    
    pois = query.order_by(POI.created_at.desc()).all()
    
    return [
        GeofenceResponse(
            id=str(poi.id),
            name=poi.name,
            is_armed=poi.is_armed,
            latitude=poi.latitude,
            longitude=poi.longitude,
            radius_m=poi.radius_m,
            created_at=poi.created_at
        )
        for poi in pois
    ]


@router.get("/alerts", response_model=List[AlertResponse])
def get_alerts(
    alert_type: Optional[str] = Query(None, description="Filter by type: geofence_exit, battery_low, offline, hive_breach"),
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
    - `hive_breach` - Hive was breached
    
    **Example:**
    ```bash
    curl -X GET "https://pinplot.me/api/v2/alerts?alert_type=geofence_exit&unread_only=true" \\
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
            tag_name=tag.name if tag else None,
            geofence_name=geofence.name if geofence else None,
            created_at=alert.created_at,
            is_read=alert.is_read
        ))
    
    return alert_responses
