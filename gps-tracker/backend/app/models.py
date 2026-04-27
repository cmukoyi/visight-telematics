from sqlalchemy import Column, String, Boolean, DateTime, ForeignKey, Integer, Float, Text, Enum, JSON
from sqlalchemy.sql import func
from sqlalchemy.orm import relationship
import uuid
from app.database import Base
import os
import enum

# Use String for UUIDs in SQLite, PostgreSQL UUID type for PostgreSQL
DATABASE_URL = os.getenv("DATABASE_URL", "")
use_sqlite = DATABASE_URL.startswith("sqlite")

if use_sqlite:
    # For SQLite, use String to store UUIDs
    def get_uuid_column():
        return Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    def get_uuid_fk(table_col):
        return Column(String(36), ForeignKey(table_col), nullable=False)
    def get_uuid_fk_nullable(table_col):
        return Column(String(36), ForeignKey(table_col), nullable=True)
else:
    # For PostgreSQL, use native UUID type
    from sqlalchemy.dialects.postgresql import UUID
    def get_uuid_column():
        return Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    def get_uuid_fk(table_col):
        return Column(UUID(as_uuid=True), ForeignKey(table_col), nullable=False)
    def get_uuid_fk_nullable(table_col):
        return Column(UUID(as_uuid=True), ForeignKey(table_col), nullable=True)

class User(Base):
    __tablename__ = "users"
    
    id = get_uuid_column()
    email = Column(String(255), unique=True, nullable=False, index=True)
    hashed_password = Column(String(255), nullable=True)  # Nullable for passwordless users
    first_name = Column(String(100))
    last_name = Column(String(100))
    phone = Column(String(20))
    is_active = Column(Boolean, default=True)
    is_admin = Column(Boolean, default=False)
    email_verified = Column(Boolean, default=False)
    email_alerts_enabled = Column(Boolean, default=True)  # Enable email alerts for geofence events
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())
    
    # Relationships
    ble_tags = relationship("BLETag", back_populates="user")
    verification_pins = relationship("VerificationPIN", back_populates="user")
    pois = relationship("POI", back_populates="user")
    geofence_alerts = relationship("GeofenceAlert", back_populates="user")
    beacon_sightings = relationship("BeaconSighting", back_populates="user")


class VerificationPIN(Base):
    __tablename__ = "verification_pins"
    
    id = get_uuid_column()
    user_id = get_uuid_fk_nullable("users.id")  # nullable — user is created only at /register
    email = Column(String(255), nullable=False, index=True)
    pin = Column(String(6), nullable=False)
    is_used = Column(Boolean, default=False)
    expires_at = Column(DateTime(timezone=True), nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    
    # Relationship (user_id may be NULL before registration completes)
    user = relationship("User", back_populates="verification_pins", foreign_keys="[VerificationPIN.user_id]")


class PasswordResetToken(Base):
    __tablename__ = "password_reset_tokens"
    
    id = get_uuid_column()
    user_id = get_uuid_fk("users.id")
    email = Column(String(255), nullable=False, index=True)
    token = Column(String(64), nullable=False, unique=True, index=True)
    is_used = Column(Boolean, default=False)
    expires_at = Column(DateTime(timezone=True), nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    
    # Relationship
    user = relationship("User")


class BLETag(Base):
    __tablename__ = "ble_tags"
    
    id = get_uuid_column()
    user_id = get_uuid_fk("users.id")
    imei = Column(String(50), unique=True, nullable=False, index=True)
    device_name = Column(String(100))
    device_model = Column(String(100))
    description = Column(String(255))  # Vehicle description from MZone API
    mzone_vehicle_id = Column(String(100), index=True)  # Cached MZone vehicle_Id for faster trips API
    mac_address = Column(String(17))  # Format: XX:XX:XX:XX:XX:XX
    tag_type = Column(String(50), nullable=True, default='series1')  # 'series2' | 'series1'
    is_active = Column(Boolean, default=True)
    last_seen = Column(DateTime(timezone=True))
    latitude = Column(String(50))
    longitude = Column(String(50))
    location_description = Column(String(500))  # Formatted address from MZone API
    battery_level = Column(Integer)
    attributes = Column(JSON, nullable=True)  # Custom attributes: {field: {value, show_on_map}}
    added_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())
    # Package / subscription
    package_id      = Column(String(36), ForeignKey("tag_packages.id"), nullable=True, index=True)
    expiry_date     = Column(DateTime(timezone=True), nullable=True)  # activation_date + package.validity_days
    activation_date = Column(DateTime(timezone=True), nullable=True)  # set on first GPS fix; expiry calculated from here

    # Relationships
    user = relationship("User", back_populates="ble_tags")
    poi_links = relationship("POITrackerLink", back_populates="tracker")
    geofence_alerts = relationship("GeofenceAlert", back_populates="tracker")


class GeofenceEventType(enum.Enum):
    ENTRY = "entry"
    EXIT = "exit"


class GeofenceState(enum.Enum):
    """Tracks the last known state of a tracker relative to a geofence"""
    UNKNOWN = "unknown"  # Initial state - not yet determined
    INSIDE = "inside"    # Tracker is inside the geofence
    OUTSIDE = "outside"  # Tracker is outside the geofence


class POIType(enum.Enum):
    SINGLE = "single"  # Single location POI (monitor entry/exit)
    ROUTE = "route"    # Delivery route (FROM origin TO destination)


class POI(Base):
    """Point of Interest / Geofence - supports both single locations and delivery routes"""
    __tablename__ = "pois"
    
    id = get_uuid_column()
    user_id = get_uuid_fk("users.id")
    name = Column(String(200), nullable=False)
    description = Column(Text)
    poi_type = Column(String(20), default='single', nullable=False)  # Store as string, not enum
    
    # Origin/FROM location (required for all types)
    latitude = Column(Float, nullable=False)
    longitude = Column(Float, nullable=False)
    radius = Column(Float, default=150.0)  # Default 150 meters
    address = Column(String(500))  # Full address or postcode used
    
    # Destination/TO location (only for ROUTE type)
    destination_latitude = Column(Float, nullable=True)
    destination_longitude = Column(Float, nullable=True)
    destination_radius = Column(Float, nullable=True)
    destination_address = Column(String(500), nullable=True)
    
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())
    
    # Relationships
    user = relationship("User", back_populates="pois")
    tracker_links = relationship("POITrackerLink", back_populates="poi")
    alerts = relationship("GeofenceAlert", back_populates="poi")


class POITrackerLink(Base):
    """Links POIs to trackers (ARM/DISARM)"""
    __tablename__ = "poi_tracker_links"
    
    id = get_uuid_column()
    poi_id = get_uuid_fk("pois.id")
    tracker_id = get_uuid_fk("ble_tags.id")
    is_armed = Column(Boolean, default=True)
    armed_at = Column(DateTime(timezone=True), server_default=func.now())
    disarmed_at = Column(DateTime(timezone=True), nullable=True)
    
    # State tracking for alert generation
    last_known_state = Column(Enum(GeofenceState, values_callable=lambda x: [e.value for e in x]), default=GeofenceState.UNKNOWN, nullable=False)
    last_state_check = Column(DateTime(timezone=True), nullable=True)
    
    # Relationships
    poi = relationship("POI", back_populates="tracker_links")
    tracker = relationship("BLETag", back_populates="poi_links")


class GeofenceAlert(Base):
    """Entry/Exit alerts for geofences"""
    __tablename__ = "geofence_alerts"
    
    id = get_uuid_column()
    poi_id = get_uuid_fk("pois.id")
    tracker_id = get_uuid_fk("ble_tags.id")
    user_id = get_uuid_fk("users.id")
    event_type = Column(Enum(GeofenceEventType), nullable=False)
    latitude = Column(Float, nullable=False)
    longitude = Column(Float, nullable=False)
    is_read = Column(Boolean, default=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    
    # Relationships
    poi = relationship("POI", back_populates="alerts")
    tracker = relationship("BLETag", back_populates="geofence_alerts")
    user = relationship("User")


class AppFeatures(Base):
    """Global feature flags that control which tabs/features are visible
    in the mobile app. There is exactly one row (id='global').

    The admin portal reads and writes this row via the /api/v1/admin/app-features
    endpoint. The mobile app fetches it on login and caches locally.
    """
    __tablename__ = "app_features"

    id = Column(String(36), primary_key=True, default='global')
    show_map       = Column(Boolean, nullable=False, default=True)
    show_journey   = Column(Boolean, nullable=False, default=True)
    show_assets    = Column(Boolean, nullable=False, default=True)
    show_scan      = Column(Boolean, nullable=False, default=True)
    show_settings  = Column(Boolean, nullable=False, default=True)
    show_solutions = Column(Boolean, nullable=False, default=False)
    updated_at     = Column(DateTime(timezone=True), onupdate=func.now())


class UserGroupPackage(Base):
    """Many-to-many link between a UserGroup and its allowed TagPackages.

    A group can have multiple packages (e.g. 80-day, 120-day, 300-day).
    is_default marks the one auto-applied by bulk-import and any flow that
    needs a fallback; exactly one row per group should have is_default=True.
    """
    __tablename__ = "user_group_packages"

    id           = get_uuid_column()
    usergroup_id = get_uuid_fk("user_groups.id")
    package_id   = get_uuid_fk("tag_packages.id")
    is_default   = Column(Boolean, nullable=False, default=False)
    created_at   = Column(DateTime(timezone=True), server_default=func.now())


class UserGroup(Base):
    """A tenant / company on the customer portal.

    Each UserGroup has one or more PortalUsers who can log in to the customer
    portal and see data scoped to that group. Created via the admin portal.
    """
    __tablename__ = "user_groups"

    id           = get_uuid_column()
    name         = Column(String(200), nullable=False, unique=True)
    slug         = Column(String(100), nullable=False, unique=True)  # URL-safe identifier
    email_domain = Column(String(500), nullable=True, index=True)   # comma-separated list of domains e.g. "acme.com,acme.co.uk"
    default_package_id = Column(String(36), ForeignKey("tag_packages.id"), nullable=True)  # kept for bulk-import fallback
    is_active    = Column(Boolean, nullable=False, default=True)
    created_at   = Column(DateTime(timezone=True), server_default=func.now())
    updated_at   = Column(DateTime(timezone=True), onupdate=func.now())
    # Branding / appearance (group admin configurable)
    logo_data             = Column(Text, nullable=True)          # base64 data-URL
    theme_primary         = Column(String(20), nullable=True)    # hex e.g. '#3b82f6'
    theme_accent          = Column(String(20), nullable=True)    # secondary hex
    # Data retention
    history_retention_days = Column(Integer, nullable=True, default=365)  # days to keep tag history
    # Feature access control (portal RBAC)
    # List of section keys enabled for this tenant: 'tracking', 'management', 'reports'
    # NULL means all sections are enabled (default — backward-compatible).
    allowed_sections = Column(JSON, nullable=True)

    portal_users = relationship("PortalUser", back_populates="usergroup",
                                cascade="all, delete-orphan")
    buildings    = relationship("Building", back_populates="usergroup",
                                cascade="all, delete-orphan")
    tag_categories = relationship("TagCategory", back_populates="usergroup",
                                  cascade="all, delete-orphan")
    group_packages = relationship("UserGroupPackage", foreign_keys=[UserGroupPackage.usergroup_id],
                                  cascade="all, delete-orphan")


class TagCategory(Base):
    """A user-defined asset category scoped to a UserGroup.

    Admins create categories (e.g. 'Vehicles', 'Equipment', 'Containers') from
    the Settings tab.  The category name is stored on BLETag.attributes as
    {'category': {'value': '<name>', ...}} so no schema migration is needed
    on the ble_tags table itself.
    """
    __tablename__ = "tag_categories"

    id           = get_uuid_column()
    usergroup_id = get_uuid_fk("user_groups.id")
    name         = Column(String(100), nullable=False)
    icon         = Column(String(50), nullable=True)   # font-awesome icon name, e.g. 'fa-car'
    color        = Column(String(20), nullable=True)   # hex color, e.g. '#3b82f6'
    is_active    = Column(Boolean, nullable=False, default=True)
    created_at   = Column(DateTime(timezone=True), server_default=func.now())
    updated_at   = Column(DateTime(timezone=True), onupdate=func.now())

    usergroup = relationship("UserGroup", back_populates="tag_categories")




class PortalUser(Base):
    """A user who can log in to the customer portal.

    Every UserGroup gets at least one PortalUser (the group admin) created
    automatically when the group is provisioned from the admin portal. More
    portal users can be added to the same group later.
    """
    __tablename__ = "portal_users"

    id              = get_uuid_column()
    usergroup_id    = get_uuid_fk("user_groups.id")
    email           = Column(String(255), unique=True, nullable=False, index=True)
    hashed_password = Column(String(255), nullable=False)
    first_name      = Column(String(100))
    last_name       = Column(String(100))
    is_active       = Column(Boolean, nullable=False, default=True)
    is_group_admin  = Column(Boolean, nullable=False, default=False)
    expires_at      = Column(DateTime(timezone=True), nullable=True)
    # Portal RBAC
    # role: 'admin' | 'manager' | 'reporter' | 'custom'
    # admin    – all features allowed by the usergroup
    # manager  – tracking + management sections only
    # reporter – reports section only
    # custom   – exactly the keys in custom_features (intersected with usergroup)
    role            = Column(String(20), nullable=False, default='admin')
    custom_features = Column(JSON, nullable=True)  # only used when role = 'custom'
    created_at      = Column(DateTime(timezone=True), server_default=func.now())
    updated_at      = Column(DateTime(timezone=True), onupdate=func.now())
    # Notification preferences (per-user)
    alerts_enabled       = Column(Boolean, nullable=False, default=True)
    notify_geofence_exit = Column(Boolean, nullable=False, default=True)
    notify_battery_low   = Column(Boolean, nullable=False, default=True)
    notify_offline       = Column(Boolean, nullable=False, default=True)
    notify_via_email     = Column(Boolean, nullable=False, default=True)

    usergroup = relationship("UserGroup", back_populates="portal_users")


class Building(Base):
    """A physical building associated with a UserGroup (tenant).

    Holds one or more Floors, each with a floor-plan image, gateways
    (ESP32 BLE readers positioned on the plan) and named Rooms.
    """
    __tablename__ = "buildings"

    id           = get_uuid_column()
    usergroup_id = get_uuid_fk("user_groups.id")
    name         = Column(String(200), nullable=False)
    mqtt_url     = Column(String(500), nullable=True)     # e.g. wss://pinplot.me/mqtt
    mqtt_topic   = Column(String(200), default="position/#")
    created_at   = Column(DateTime(timezone=True), server_default=func.now())
    updated_at   = Column(DateTime(timezone=True), onupdate=func.now())

    usergroup = relationship("UserGroup", back_populates="buildings")
    floors    = relationship("Floor", back_populates="building",
                             cascade="all, delete-orphan",
                             order_by="Floor.floor_order")


class Floor(Base):
    """One floor / level of a building."""
    __tablename__ = "floors"

    id          = get_uuid_column()
    building_id = get_uuid_fk("buildings.id")
    label       = Column(String(100), nullable=False, default="Ground Floor")
    floor_order = Column(Integer, nullable=False, default=0)
    floor_plan  = Column(Text, nullable=True)   # base64 data-URL PNG
    map_w       = Column(Integer, nullable=False, default=800)
    map_h       = Column(Integer, nullable=False, default=500)
    created_at  = Column(DateTime(timezone=True), server_default=func.now())
    updated_at  = Column(DateTime(timezone=True), onupdate=func.now())

    building = relationship("Building", back_populates="floors")
    gateways = relationship("IndoorGateway", back_populates="floor",
                            cascade="all, delete-orphan")
    rooms    = relationship("Room", back_populates="floor",
                            cascade="all, delete-orphan")


class IndoorGateway(Base):
    """A BLE gateway (ESP32) physically placed on a floor plan."""
    __tablename__ = "indoor_gateways"

    id          = get_uuid_column()
    floor_id    = get_uuid_fk("floors.id")
    receiver_id = Column(String(50), nullable=False, index=True)  # lowercase hex, no colons
    label       = Column(String(100), nullable=True)
    x           = Column(Float, nullable=False, default=0.0)
    y           = Column(Float, nullable=False, default=0.0)
    created_at  = Column(DateTime(timezone=True), server_default=func.now())
    updated_at  = Column(DateTime(timezone=True), onupdate=func.now())

    floor = relationship("Floor", back_populates="gateways")


class Room(Base):
    """A named rectangular zone drawn on a floor plan."""
    __tablename__ = "rooms"

    id         = get_uuid_column()
    floor_id   = get_uuid_fk("floors.id")
    name       = Column(String(100), nullable=False)
    x          = Column(Float, nullable=False, default=0.0)
    y          = Column(Float, nullable=False, default=0.0)
    w          = Column(Float, nullable=False, default=100.0)
    h          = Column(Float, nullable=False, default=80.0)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())

    floor = relationship("Floor", back_populates="rooms")


class BeaconSighting(Base):
    """Crowdsourced BLE tag sighting reported by a user's phone.

    Each row is one sighting: phone detected [tag_id] at [latitude, longitude]
    with signal strength [rssi] at [sighted_at]. Multiple sightings per tag
    accumulate over time; the latest per tag is used as last known location.
    """
    __tablename__ = "beacon_sightings"

    id = get_uuid_column()
    user_id = get_uuid_fk("users.id")
    tag_id = Column(String(64), nullable=False, index=True)    # BLE MAC / UUID
    tag_name = Column(String(255), nullable=True)              # Advertised name
    latitude = Column(Float, nullable=False)
    longitude = Column(Float, nullable=False)
    rssi = Column(Integer, nullable=True)                      # dBm, e.g. -65
    sighted_at = Column(DateTime(timezone=True), nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    # Relationships
    user = relationship("User", back_populates="beacon_sightings")
