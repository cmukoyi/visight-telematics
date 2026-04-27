from pydantic import BaseModel, Field
from typing import Optional, List
from datetime import datetime
from enum import Enum


class GeofenceEventType(str, Enum):
    ENTRY = "entry"
    EXIT = "exit"


class POIType(str, Enum):
    SINGLE = "single"
    ROUTE = "route"


class POICreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=200)
    description: Optional[str] = None
    poi_type: POIType = POIType.SINGLE
    
    # Origin/FROM location (required)
    latitude: float = Field(..., ge=-90, le=90)
    longitude: float = Field(..., ge=-180, le=180)
    radius: float = Field(default=150.0, ge=10, le=5000)  # 10m to 5km
    address: Optional[str] = None
    
    # Destination/TO location (only for ROUTE type)
    destination_latitude: Optional[float] = Field(None, ge=-90, le=90)
    destination_longitude: Optional[float] = Field(None, ge=-180, le=180)
    destination_radius: Optional[float] = Field(None, ge=10, le=5000)
    destination_address: Optional[str] = None


class POIUpdate(BaseModel):
    name: Optional[str] = Field(None, min_length=1, max_length=200)
    description: Optional[str] = None
    radius: Optional[float] = Field(None, ge=10, le=5000)
    destination_radius: Optional[float] = Field(None, ge=10, le=5000)
    is_active: Optional[bool] = None


class POIResponse(BaseModel):
    id: str
    user_id: str
    name: str
    description: Optional[str]
    poi_type: POIType
    
    # Origin/FROM location
    latitude: float
    longitude: float
    radius: float
    address: Optional[str]
    
    # Destination/TO location
    destination_latitude: Optional[float]
    destination_longitude: Optional[float]
    destination_radius: Optional[float]
    destination_address: Optional[str]
    
    is_active: bool
    created_at: datetime
    updated_at: Optional[datetime]
    
    class Config:
        from_attributes = True


class POIWithArmedStatus(POIResponse):
    """POI with information about whether it's armed to specific trackers"""
    armed_trackers: List[str] = []  # List of tracker IDs that this POI is armed to


class POITrackerLinkCreate(BaseModel):
    poi_id: str
    tracker_id: str


class POITrackerLinkResponse(BaseModel):
    id: str
    poi_id: str
    tracker_id: str
    is_armed: bool
    armed_at: datetime
    disarmed_at: Optional[datetime]
    
    class Config:
        from_attributes = True


class GeofenceAlertResponse(BaseModel):
    id: str
    poi_id: str
    tracker_id: str
    user_id: str
    event_type: GeofenceEventType
    latitude: float
    longitude: float
    is_read: bool
    created_at: datetime
    poi_name: Optional[str] = None
    tracker_name: Optional[str] = None
    
    class Config:
        from_attributes = True


class AlertsListResponse(BaseModel):
    alerts: List[GeofenceAlertResponse]
    total: int
    unread_count: int


class PostcodeSearchRequest(BaseModel):
    postcode: str


class PostcodeSearchResponse(BaseModel):
    latitude: float
    longitude: float
    address: str
