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
    def get_uuid_pk_fk(table_col):
        return Column(String(36), ForeignKey(table_col), primary_key=True)
    def get_uuid_nullable():
        return Column(String(36), nullable=True)
else:
    # For PostgreSQL, use native UUID type
    from sqlalchemy.dialects.postgresql import UUID
    def get_uuid_column():
        return Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    def get_uuid_fk(table_col):
        return Column(UUID(as_uuid=True), ForeignKey(table_col), nullable=False)
    def get_uuid_fk_nullable(table_col):
        return Column(UUID(as_uuid=True), ForeignKey(table_col), nullable=True)
    def get_uuid_pk_fk(table_col):
        return Column(UUID(as_uuid=True), ForeignKey(table_col), primary_key=True)
    def get_uuid_nullable():
        return Column(UUID(as_uuid=True), nullable=True)

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
    preferred_language = Column(String(5), nullable=True)  # User language preference (overrides usergroup default)
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
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=True, index=True)  # Nullable for series_3 QR assets
    imei = Column(String(50), unique=True, nullable=True, index=True)  # NULL for tag_type='ble'; NOT NULL for GPS types (enforced by DB check constraint)
    device_name = Column(String(100))
    device_model = Column(String(100))
    description = Column(String(255))  # Vehicle description from MZone API
    mzone_vehicle_id = Column(String(100), index=True)  # Cached MZone vehicle_Id for faster trips API
    mac_address = Column(String(17))  # Format: XX:XX:XX:XX:XX:XX
    tag_type = Column(String(50), nullable=True, default='series1')  # 'series1' | 'series2' | 'series_3' | 'series_4' (DX-Smart indoor BLE) | 'scope' | 'ble'
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
    gdpr_deletion_warned_at = Column(DateTime(timezone=True), nullable=True)  # set when 7-day deletion warning is sent

    # Relationships
    user = relationship("User", back_populates="ble_tags")
    poi_links = relationship("POITrackerLink", back_populates="tracker")
    geofence_alerts = relationship("GeofenceAlert", back_populates="tracker")


class GeofenceEventType(enum.Enum):
    ENTRY = "entry"
    EXIT = "exit"


class TrackSolidDevice(Base):
    """Static metadata for TrackSolid devices (rarely changes)"""
    __tablename__ = "tracksolid_devices"
    
    id = Column(Integer, primary_key=True, autoincrement=True)
    imei = Column(String(20), unique=True, nullable=False, index=True)
    device_name = Column(String(100), nullable=True)
    mc_type = Column(String(50), nullable=True)  # Model/device type
    sim = Column(String(50), nullable=True)
    vehicle_number = Column(String(50), nullable=True)
    driver_name = Column(String(100), nullable=True)
    driver_phone = Column(String(50), nullable=True)
    activation_time = Column(DateTime(timezone=True), nullable=True)
    expiration = Column(DateTime(timezone=True), nullable=True)
    enabled_flag = Column(Integer, nullable=False, default=1)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())


class TrackSolidLocation(Base):
    """Location history for TrackSolid devices (inserts every poll)"""
    __tablename__ = "tracksolid_locations"
    
    id = Column(Integer, primary_key=True, autoincrement=True)
    imei = Column(String(20), nullable=False, index=True)
    lat = Column(Float, nullable=True)
    lng = Column(Float, nullable=True)
    speed = Column(String(10), nullable=True)
    acc_status = Column(String(5), nullable=True)
    gps_time = Column(DateTime(timezone=True), nullable=True)
    hb_time = Column(DateTime(timezone=True), nullable=True)
    pos_type = Column(String(10), nullable=True)
    battery = Column(String(10), nullable=True)
    gps_signal = Column(String(5), nullable=True)
    status = Column(String(5), nullable=True)
    recorded_at = Column(DateTime(timezone=True), server_default=func.now(), index=True)


class APIToken(Base):
    """OAuth token cache for external APIs"""
    __tablename__ = "api_tokens"
    
    id = Column(Integer, primary_key=True)
    provider = Column(String(50), nullable=False, unique=True)  # e.g. 'tracksolid_open_api'
    access_token = Column(String(200), nullable=True)
    refresh_token = Column(String(200), nullable=True)
    expires_at = Column(DateTime(timezone=True), nullable=True)
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())


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
    user_id = Column(String(36), ForeignKey("users.id"), nullable=True)   # nullable for portal-created POIs
    usergroup_id = get_uuid_fk_nullable("user_groups.id")
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
    
    # Shape info for drawn geofences (migration 028)
    shape_type = Column(String(20), default='circle')   # circle | polygon | rectangle
    coordinates = Column(Text, nullable=True)           # JSON [[lat,lng], ...] for polygon/rectangle
    notes = Column(Text, nullable=True)                 # free-text notes

    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())
    
    # Relationships
    user = relationship("User", back_populates="pois")
    usergroup = relationship("UserGroup", foreign_keys=[usergroup_id])
    tracker_links = relationship("POITrackerLink", back_populates="poi")
    alerts = relationship("GeofenceAlert", back_populates="poi")


class POITrackerLink(Base):
    """Links POIs to trackers (ARM/DISARM)"""
    __tablename__ = "poi_tracker_links"
    
    id = get_uuid_column()
    poi_id = get_uuid_fk("pois.id")
    tracker_id = get_uuid_fk_nullable("ble_tags.id")  # nullable: old rows pre-date this FK
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
    tracker_id = get_uuid_fk_nullable("ble_tags.id")  # nullable: old rows pre-date this FK
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


class PortalAlert(Base):
    """Unified alert inbox for portal users — covers geofence, battery, and offline events.

    One row per alert event, scoped to a usergroup_id so all users in a group
    share the same alert feed.  Alerts older than 7 days are purged by the poller.
    """
    __tablename__ = "portal_alerts"

    id           = get_uuid_column()
    usergroup_id = get_uuid_fk("user_groups.id")
    tag_id       = get_uuid_fk_nullable("ble_tags.id")
    alert_type   = Column(String(50), nullable=False)   # 'geofence_exit','geofence_entry','battery_low','tag_offline'
    title        = Column(String(200), nullable=False)
    message      = Column(Text, nullable=True)
    is_read      = Column(Boolean, nullable=False, default=False)
    created_at   = Column(DateTime(timezone=True), server_default=func.now())
    meta_data    = Column(JSON, nullable=True)           # e.g. {'poi_name': 'Depot', 'battery': 2}

    tag       = relationship("BLETag", foreign_keys=[tag_id])


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
    default_language = Column(String(5), nullable=False, server_default='en')  # Default language for usergroup
    is_active    = Column(Boolean, nullable=False, default=True)
    created_at   = Column(DateTime(timezone=True), server_default=func.now())
    updated_at   = Column(DateTime(timezone=True), onupdate=func.now())
    # Branding / appearance (group admin configurable)
    logo_data             = Column(Text, nullable=True)          # base64 data-URL (light mode)
    logo_dark_data        = Column(Text, nullable=True)          # base64 data-URL (dark mode)
    theme_primary         = Column(String(20), nullable=True)    # hex e.g. '#3b82f6'
    theme_accent          = Column(String(20), nullable=True)    # secondary hex
    # Data retention
    history_retention_days = Column(Integer, nullable=True, default=365)  # days to keep tag history
    # SMS add-on
    sms_enabled       = Column(Boolean, nullable=False, default=False)  # tenant-level SMS on/off
    sms_monthly_limit = Column(Integer, nullable=True)                  # NULL = no limit
    # Feature access control (portal RBAC)
    # List of section keys enabled for this tenant: 'tracking', 'management', 'reports'
    # NULL means all sections are enabled (default — backward-compatible).
    allowed_sections = Column(JSON, nullable=True)
    # Tag type restrictions: list of allowed tag types ['series1', 'series2', 'series3']
    # NULL means all types allowed (default — backward-compatible).
    allowed_tag_types = Column(JSON, nullable=True)

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
    notify_hive_breach   = Column(Boolean, nullable=False, default=True)
    notify_via_email     = Column(Boolean, nullable=False, default=True)
    notification_emails  = Column(JSON, nullable=True)               # extra notification addresses (list of strings)
    # SMS notification preferences
    phone_number         = Column(String(30), nullable=True)          # E.164 number, e.g. +447700123456
    sms_enabled          = Column(Boolean, nullable=False, default=False)
    notify_geofence_sms  = Column(Boolean, nullable=False, default=True)
    notify_battery_sms   = Column(Boolean, nullable=False, default=True)
    notify_offline_sms   = Column(Boolean, nullable=False, default=True)
    notify_hive_breach_sms = Column(Boolean, nullable=False, default=True)

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

    id           = get_uuid_column()
    building_id  = get_uuid_fk("buildings.id")
    label        = Column(String(100), nullable=False, default="Ground Floor")
    floor_order  = Column(Integer, nullable=False, default=0)
    floor_plan   = Column(Text, nullable=True)   # base64 data-URL PNG
    map_w        = Column(Integer, nullable=False, default=800)
    map_h        = Column(Integer, nullable=False, default=500)
    # Publish workflow (draft vs live floor plans)
    is_published = Column(Boolean, nullable=False, default=False)
    published_at = Column(DateTime(timezone=True), nullable=True)
    published_by = get_uuid_fk_nullable("portal_users.id")
    created_at   = Column(DateTime(timezone=True), server_default=func.now())
    updated_at   = Column(DateTime(timezone=True), onupdate=func.now())

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
    room_id     = get_uuid_fk_nullable("rooms.id")  # Link gateway to specific room
    receiver_id = Column(String(50), nullable=False, index=True)  # lowercase hex, no colons
    label       = Column(String(100), nullable=True)
    x           = Column(Float, nullable=False, default=0.0)
    y           = Column(Float, nullable=False, default=0.0)
    created_at  = Column(DateTime(timezone=True), server_default=func.now())
    updated_at  = Column(DateTime(timezone=True), onupdate=func.now())

    floor = relationship("Floor", back_populates="gateways")
    room  = relationship("Room", foreign_keys=[room_id])


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


class TagIndoorPosition(Base):
    """Latest known indoor position of a BLE tag, derived from the nearest
    XIAO gateway that heard it via Pareto Anywhere.

    One row per tag id (BLE MAC, normalised to lowercase no-colons). The
    row is upserted on every raddec event by `app.services.pareto_bridge`;
    floor_id / x / y / zone are copied from the strongest gateway in the
    raddec's rssiSignature.

    Separate from `beacon_sightings` (mobile-phone GPS crowdsourcing) —
    different write path, different tenant scope, no shared fields.
    See features_dev/Pinplot floorplan spec.md §6.
    """
    __tablename__ = "tag_indoor_positions"

    tag_id       = Column(String(64), primary_key=True)
    floor_id     = get_uuid_fk("floors.id")
    gateway_id   = Column(ForeignKey("indoor_gateways.id", ondelete="SET NULL"),
                          nullable=True)
    usergroup_id = get_uuid_fk("user_groups.id")
    x            = Column(Float, nullable=False)
    y            = Column(Float, nullable=False)
    zone         = Column(String(100), nullable=True)
    rssi         = Column(Integer, nullable=True)
    battery      = Column(Integer, nullable=True)
    status       = Column(String(20), nullable=False, default="offline")
    last_seen    = Column(DateTime(timezone=True), nullable=True)

    floor   = relationship("Floor")
    gateway = relationship("IndoorGateway")


# ═══════════════════════════════════════════════════════════════════════════════
# HIVE TRACKING — proximity group monitoring
# ═══════════════════════════════════════════════════════════════════════════════

class HiveStatus(str, enum.Enum):
    ACTIVE   = "active"
    ARCHIVED = "archived"
    PURGED   = "purged"


class HiveAlertState(str, enum.Enum):
    OK              = "OK"
    BREACH_PENDING  = "BREACH_PENDING"
    BREACHING       = "BREACHING"
    RESOLVING       = "RESOLVING"


class HiveMotionState(str, enum.Enum):
    """Four-state motion machine per spec v1.1 §11.2.

    User-facing labels: PRE_TRANSIT shows as "Starting", SETTLING as
    "Stopping". Internal names are kept verbatim so engineers can grep
    unambiguously.
    """
    STATIONARY  = "STATIONARY"
    PRE_TRANSIT = "PRE_TRANSIT"
    IN_TRANSIT  = "IN_TRANSIT"
    SETTLING    = "SETTLING"


class MobilityProfile(str, enum.Enum):
    STATIONARY = "stationary"
    SLOW       = "slow"
    MOBILE     = "mobile"
    CUSTOM     = "custom"


# Preset parameters per mobility profile (spec v1.1 Appendix A).
# Calibrated for 5–10 minute crowdsourced reporting cadence.
# Fast profile deprecated in v1.1 — merged into Mobile.
MOBILITY_PRESETS = {
    "stationary": {
        "fresh_window_s":    1800,   # <30 min
        "recent_window_s":   14400,  # 30 min – 4 hr
        "stale_window_s":    86400,  # 4 – 24 hr
        "lost_threshold_s":  86400,  # >24 hr
        "meaningful_change_m": 2.5,
        "distance_threshold_m": 150.0,
        "hysteresis_pct":    90.0,
        "confirmation_count": 1,
        # Motion detection disabled — stationary hives shouldn't move; if they
        # do, the user wants the alert (spec §2.3 / §11.5).
        "motion_speed_threshold_kmh": None,
        "motion_settling_time_s":     None,
        "coherence_speed_tol_kmh":    None,
        "coherence_bearing_tol_deg":  None,
    },
    "slow": {
        "fresh_window_s":    1200,   # <20 min
        "recent_window_s":   7200,   # 20 min – 2 hr
        "stale_window_s":    28800,  # 2 – 8 hr
        "lost_threshold_s":  28800,  # >8 hr
        "meaningful_change_m": 15.0,
        "distance_threshold_m": 450.0,
        "hysteresis_pct":    85.0,
        "confirmation_count": 1,
        "motion_speed_threshold_kmh": 10.0,
        "motion_settling_time_s":     600,   # 10 min
        "coherence_speed_tol_kmh":    5.0,
        "coherence_bearing_tol_deg":  60.0,
    },
    "mobile": {
        "fresh_window_s":    900,    # <15 min
        "recent_window_s":   3600,   # 15 min – 1 hr
        "stale_window_s":    14400,  # 1 – 4 hr
        "lost_threshold_s":  7200,   # >2 hr
        "meaningful_change_m": 30.0,
        "distance_threshold_m": 1000.0,
        "hysteresis_pct":    75.0,
        "confirmation_count": 1,
        "motion_speed_threshold_kmh": 15.0,
        "motion_settling_time_s":     600,   # 10 min
        "coherence_speed_tol_kmh":    10.0,
        "coherence_bearing_tol_deg":  45.0,
    },
}


class Hive(Base):
    __tablename__ = "hives"

    id               = get_uuid_column()
    usergroup_id     = get_uuid_fk("user_groups.id")
    created_by       = get_uuid_fk_nullable("portal_users.id")
    name             = Column(String(200), nullable=False)
    status           = Column(String(20), nullable=False, default="active")
    created_at       = Column(DateTime(timezone=True), server_default=func.now())
    expires_at       = Column(DateTime(timezone=True), nullable=False)
    archived_at      = Column(DateTime(timezone=True), nullable=True)
    archived_reason  = Column(String(50), nullable=True)      # expired | user_deleted
    archive_expires_at = Column(DateTime(timezone=True), nullable=True)
    purged_at        = Column(DateTime(timezone=True), nullable=True)
    purged_reason    = Column(String(50), nullable=True)      # auto_retention | user_purged
    parent_hive_id   = get_uuid_fk_nullable("hives.id")
    settling_until   = Column(DateTime(timezone=True), nullable=True)

    config_versions  = relationship("HiveConfigVersion", back_populates="hive",
                                    order_by="HiveConfigVersion.version_number")
    memberships      = relationship("HiveTagMembership", back_populates="hive",
                                    cascade="all, delete-orphan")
    evaluations      = relationship("HiveEvaluation", back_populates="hive",
                                    order_by="HiveEvaluation.evaluated_at.desc()")
    events           = relationship("HiveEvent", back_populates="hive",
                                    order_by="HiveEvent.occurred_at.desc()")
    live_state       = relationship("HiveLiveState", back_populates="hive", uselist=False)


class HiveConfigVersion(Base):
    __tablename__ = "hive_config_versions"

    id               = get_uuid_column()
    hive_id          = get_uuid_fk("hives.id")
    version_number   = Column(Integer, nullable=False)
    valid_from       = Column(DateTime(timezone=True), server_default=func.now())
    valid_to         = Column(DateTime(timezone=True), nullable=True)    # null = current
    mobility_profile = Column(String(30), nullable=False)
    distance_threshold_m  = Column(Float, nullable=False)
    fresh_window_s        = Column(Integer, nullable=False)
    recent_window_s       = Column(Integer, nullable=False)
    stale_window_s        = Column(Integer, nullable=False)
    lost_threshold_s      = Column(Integer, nullable=False)
    meaningful_change_m   = Column(Float, nullable=False)
    hysteresis_pct        = Column(Float, nullable=False)
    confirmation_count    = Column(Integer, nullable=False)
    # Phase 3 motion-detection tuning (nullable; null = profile disables motion
    # detection, e.g. Stationary profile). Persisted per config version so
    # historical evaluations can be audited against the exact tuning.
    motion_speed_threshold_kmh = Column(Float, nullable=True)
    motion_settling_time_s     = Column(Integer, nullable=True)
    coherence_speed_tol_kmh    = Column(Float, nullable=True)
    coherence_bearing_tol_deg  = Column(Float, nullable=True)
    changed_by            = get_uuid_fk_nullable("portal_users.id")

    hive = relationship("Hive", back_populates="config_versions")


class HiveTagMembership(Base):
    __tablename__ = "hive_tag_membership"

    tag_id    = get_uuid_pk_fk("ble_tags.id")  # PK — enforces one-hive-per-tag
    hive_id   = get_uuid_fk("hives.id")
    joined_at = Column(DateTime(timezone=True), server_default=func.now())
    label     = Column(String(100), nullable=True)   # per-tag display label within hive
    # Phase 3: per-tag velocity vector used by the group coherence check
    # (spec §11.4). Derived from previous_* anchor → current tag position;
    # the anchor is rolled forward each evaluation cycle.
    velocity_speed_kmh   = Column(Float, nullable=True)
    velocity_bearing_deg = Column(Float, nullable=True)
    velocity_computed_at = Column(DateTime(timezone=True), nullable=True)
    previous_lat         = Column(Float, nullable=True)
    previous_lng         = Column(Float, nullable=True)
    previous_seen_at     = Column(DateTime(timezone=True), nullable=True)

    hive = relationship("Hive", back_populates="memberships")
    tag  = relationship("BLETag")


class HiveEvaluation(Base):
    __tablename__ = "hive_evaluations"

    id                    = get_uuid_column()
    hive_id               = get_uuid_fk("hives.id")
    evaluated_at          = Column(DateTime(timezone=True), server_default=func.now())
    config_version_number = Column(Integer, nullable=False)
    diameter_m            = Column(Float, nullable=True)
    threshold_m           = Column(Float, nullable=False)
    outlier_tag_id        = get_uuid_nullable()
    outlier_selection_reason = Column(String(40), nullable=True)
    breaching_pair_counts = Column(Text, nullable=True)  # JSON map: tag_id -> breaching pair count
    pairwise_detail       = Column(Text, nullable=True)  # JSON array; populated on state-changing evaluations
    freshness_composition = Column(Text, nullable=True)   # JSON
    alert_state           = Column(String(30), nullable=False, default="OK")
    breach_confidence     = Column(String(10), nullable=True)  # high | low
    # Phase 3: motion state active at evaluation time. Lets analysts
    # distinguish a suppressed evaluation (in transit) from a real OK.
    motion_state          = Column(String(20), nullable=True)
    centroid_speed_kmh    = Column(Float, nullable=True)
    positions_used        = Column(Text, nullable=True)   # JSON array of (tag_id, observed_at)
    max_pair_dt_s         = Column(Float, nullable=True)
    coherent_pair_count   = Column(Integer, nullable=True)
    incoherent_pair_count = Column(Integer, nullable=True)
    breach_evidence       = Column(String(30), nullable=True)
    tag_fix_history       = Column(Text, nullable=True)   # JSON map: tag_id -> array of recent fixes for trajectory analysis

    hive = relationship("Hive", back_populates="evaluations")


class HiveEvent(Base):
    __tablename__ = "hive_events"

    id                    = get_uuid_column()
    hive_id               = get_uuid_fk("hives.id")
    occurred_at           = Column(DateTime(timezone=True), server_default=func.now())
    event_type            = Column(String(50), nullable=False)
    config_version_number = Column(Integer, nullable=True)
    from_state            = Column(String(30), nullable=True)
    to_state              = Column(String(30), nullable=True)
    triggering_tag_id     = get_uuid_nullable()
    details               = Column(Text, nullable=True)   # JSON

    hive = relationship("Hive", back_populates="events")


class HiveLiveState(Base):
    """Denormalised live state — replaces Redis for MVP."""
    __tablename__ = "hive_live_state"

    hive_id               = get_uuid_pk_fk("hives.id")
    alert_state           = Column(String(30), nullable=False, default="OK")
    breach_confidence     = Column(String(10), nullable=True)
    last_evaluated_at     = Column(DateTime(timezone=True), nullable=True)
    current_diameter_m    = Column(Float, nullable=True)
    outlier_tag_id        = get_uuid_nullable()
    pending_breach_since  = Column(DateTime(timezone=True), nullable=True)
    pending_clear_since   = Column(DateTime(timezone=True), nullable=True)
    consecutive_confirms  = Column(Integer, nullable=False, default=0)  # DEPRECATED — kept for compatibility
    # Most recent time a hive_breach alert was actually dispatched. Used to
    # re-notify if a hive stays in BREACHING for a long time without a state
    # change (e.g. when the original notification failed silently).
    last_alert_at         = Column(DateTime(timezone=True), nullable=True)

    # ─── Duration-based breach persistence (v1.2 confirmation fix) ────────
    # Replaces "two consecutive fixes from separated tag" with duration-based
    # persistence backed by fresh evidence from any tag.
    persistence_eval_count              = Column(Integer, nullable=False, default=0)
    persistence_snapshot_fp_at_start    = Column(String(500), nullable=True)
    persistence_has_new_evidence        = Column(Boolean, nullable=False, default=False)

    # ─── Phase 3: motion awareness ────────────────────────────────────────
    # Four-state machine: STATIONARY ↔ PRE_TRANSIT ↔ IN_TRANSIT ↔ SETTLING.
    # Proximity alerts are suppressed in any non-STATIONARY state.
    motion_state                = Column(String(20), nullable=False, default="STATIONARY")
    motion_state_since          = Column(DateTime(timezone=True), nullable=True)
    pending_motion_change_since = Column(DateTime(timezone=True), nullable=True)
    # Current centroid (geometric mean of Fresh-tier tag positions) and its
    # derived velocity. centroid_anchor_* is the older snapshot we measure
    # velocity against — rolled forward when older than ~5 min (spec §11.3).
    centroid_lat            = Column(Float, nullable=True)
    centroid_lng            = Column(Float, nullable=True)
    centroid_speed_kmh      = Column(Float, nullable=True)
    centroid_bearing_deg    = Column(Float, nullable=True)
    centroid_anchor_lat     = Column(Float, nullable=True)
    centroid_anchor_lng     = Column(Float, nullable=True)
    centroid_anchor_at      = Column(DateTime(timezone=True), nullable=True)

    hive = relationship("Hive", back_populates="live_state")


# ═══════════════════════════════════════════════════════════════════════════
# TRIP ENGINE MODELS (Movement History Advanced)
# ═══════════════════════════════════════════════════════════════════════════

class DevicePosition(Base):
    """
    Single source of truth for GPS breadcrumbs from TrackSolid.
    
    Section 1 (Ingestion): Raw positions from batch sweep + track.list calls.
    Unique constraint on (device_imei, observed_at) prevents duplicates.
    """
    __tablename__ = "device_positions"
    
    id = Column(Integer, primary_key=True, autoincrement=True)
    device_imei = Column(String(20), nullable=False, index=True)
    
    # Core position data
    lat = Column(Float, nullable=False)
    lng = Column(Float, nullable=False)
    observed_at = Column(DateTime(timezone=True), nullable=False, index=True)
    
    # Movement metadata
    direction = Column(Integer, nullable=True)           # 0-360 degrees
    gps_speed = Column(Float, nullable=True)             # km/h
    pos_type = Column(Integer, nullable=True)            # 1=GPS, 2=LBS, 3=WIFI, 5=unknown
    satellite = Column(Integer, nullable=True)           # GPS satellite count
    ignition = Column(String(10), nullable=True)         # ON/OFF
    acc_status = Column(String(10), nullable=True)       # ON/OFF
    gps_mode = Column(Integer, nullable=True)
    confidence = Column(Integer, nullable=True)          # 1-3 (NEVER use for classification per spec)
    
    # Trip engine linkage (Section 3.4 - journey/leg/stationary linking)
    leg_id = get_uuid_nullable()                         # Which leg this position belongs to
    stationary_id = get_uuid_nullable()                  # Which stationary this position belongs to
    
    # Reverse geocoding (Section 3.6 - cached at ingest)
    address = Column(Text, nullable=True)                # Human-readable location
    
    # Metadata
    source = Column(String(20), nullable=False, default="batch")  # 'batch' or 'tracklist'
    created_at = Column(DateTime(timezone=True), server_default=func.now(), index=True)


class DeviceState(Base):
    """
    Per-device trigger tracking for smart API calling.
    
    Section 1 (Ingestion): Implements 3-condition trigger logic:
    - last_batch_ts: Latest batch sweep timestamp (new data detection)
    - last_position_ts: Latest GPS point (forward-only window boundary)
    - last_tracklist_pull_at: Last track.list call (coalesce throttling)
    """
    __tablename__ = "device_state"
    
    device_imei = Column(String(20), primary_key=True)
    
    # Trigger detection timestamps
    last_batch_ts = Column(DateTime(timezone=True), nullable=True)
    last_position_ts = Column(DateTime(timezone=True), nullable=True)
    last_tracklist_pull_at = Column(DateTime(timezone=True), nullable=True)
    
    # Subscription model (premium opt-in)
    trip_subscribed = Column(Boolean, nullable=False, default=False, index=True)
    
    # Per-device config override (NULL = use global/tenant default)
    coalesce_floor_minutes = Column(Integer, nullable=True)
    
    # Metadata
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())


class TrackSolidSyncState(Base):
    """
    Global sync metadata (singleton row).
    
    Section 1 (Ingestion): Rate limiting counters and sweep timestamps.
    """
    __tablename__ = "tracksolid_sync_state"
    
    id = Column(Integer, primary_key=True, default=1)
    
    # Last sync timestamps
    last_batch_sweep_at = Column(DateTime(timezone=True), nullable=True)
    last_selective_sweep_at = Column(DateTime(timezone=True), nullable=True)
    
    # Rate limiting (TrackSolid limit: 86,400 calls/day)
    api_calls_today = Column(Integer, nullable=False, default=0)
    api_calls_reset_at = Column(DateTime(timezone=True), nullable=True)
    
    # Metadata
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())


class EngineState(Base):
    """
    Per-device state machine (STATIONARY ↔ MOVE).
    
    Section 2 (Engine): Maintains rolling anchor and current trip context.
    """
    __tablename__ = "engine_state"
    
    device_imei = Column(String(20), primary_key=True)
    
    # State machine
    current_state = Column(String(20), nullable=False, default="STATIONARY")  # STATIONARY or MOVE
    
    # Rolling anchor (for STATIONARY state)
    anchor_lat = Column(Float, nullable=True)
    anchor_lng = Column(Float, nullable=True)
    anchor_count = Column(Integer, nullable=False, default=0)
    
    # Current trip context (for MOVE state)
    current_leg_id = get_uuid_nullable()
    current_journey_id = get_uuid_nullable()
    
    # Processing watermark
    last_processed_at = Column(DateTime(timezone=True), nullable=True)
    
    # Metadata
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())


class Stationary(Base):
    """
    Idle periods with anchor centroids.
    
    Section 2 (Engine): Created when device remains within R=100m radius.
    """
    __tablename__ = "stationaries"
    
    id = get_uuid_column()
    device_imei = Column(String(20), nullable=False, index=True)
    journey_id = get_uuid_nullable()  # NULL if ungrouped
    
    # Position references (nullable for reconstructed state)
    start_position_id = Column(Integer, nullable=True)
    end_position_id = Column(Integer, nullable=True)
    
    # Time window
    started_at = Column(DateTime(timezone=True), nullable=False, index=True)
    ended_at = Column(DateTime(timezone=True), nullable=False)
    
    # Geometry
    anchor_lat = Column(Float, nullable=False)
    anchor_lng = Column(Float, nullable=False)
    # centroid = Column(Geometry('Point', srid=4326), nullable=True)  # PostGIS Point geometry (added in migration 056)
    point_count = Column(Integer, nullable=False)
    
    # Metrics
    duration_seconds = Column(Integer, nullable=False)
    
    # Metadata
    created_at = Column(DateTime(timezone=True), server_default=func.now())


class Leg(Base):
    """
    Movement segments between stationaries.
    
    Section 2 (Engine): Created when device moves >150m from anchor.
    """
    __tablename__ = "legs"
    
    id = get_uuid_column()
    device_imei = Column(String(20), nullable=False, index=True)
    journey_id = get_uuid_nullable()  # NULL if ungrouped
    
    # Position references
    start_position_id = Column(Integer, nullable=False)
    end_position_id = Column(Integer, nullable=False)
    
    # Time window
    started_at = Column(DateTime(timezone=True), nullable=False, index=True)
    ended_at = Column(DateTime(timezone=True), nullable=False)
    
    # Start/End coordinates (for non-spatial queries)
    start_lat = Column(Float, nullable=True)
    start_lng = Column(Float, nullable=True)
    end_lat = Column(Float, nullable=True)
    end_lng = Column(Float, nullable=True)
    
    # Geometry (PostGIS) - Added in migration 056
    # path = Column(Geometry('LineString', srid=4326), nullable=True)  # Full resolution path
    # path_simplified = Column(Geometry('LineString', srid=4326), nullable=True)  # Simplified for rendering
    
    # Metrics
    distance_m = Column(Float, nullable=False)
    duration_seconds = Column(Integer, nullable=False)
    point_count = Column(Integer, nullable=False)
    
    # Classification
    is_air_leg = Column(Boolean, nullable=False, default=False, index=True)
    
    # Metadata
    created_at = Column(DateTime(timezone=True), server_default=func.now())


class Journey(Base):
    """
    Grouped trips (legs + stationaries within 30-min dwell threshold).
    
    Section 2 (Engine): Journey grouping with aggregate metrics.
    """
    __tablename__ = "journeys"
    
    id = get_uuid_column()
    device_imei = Column(String(20), nullable=False, index=True)
    
    # Time window
    started_at = Column(DateTime(timezone=True), nullable=False, index=True)
    ended_at = Column(DateTime(timezone=True), nullable=False)
    
    # Journey structure references
    first_leg_id = get_uuid_nullable()
    last_leg_id = get_uuid_nullable()
    
    # Metrics
    leg_count = Column(Integer, nullable=False, default=0)
    stationary_count = Column(Integer, nullable=False, default=0)
    total_distance_m = Column(Float, nullable=False, default=0)
    total_duration_seconds = Column(Integer, nullable=False)
    
    # Classification
    is_air_journey = Column(Boolean, nullable=False, default=False, index=True)
    
    # Metadata
    created_at = Column(DateTime(timezone=True), server_default=func.now())


class TripConfig(Base):
    """
    Admin configuration (global + per-tenant overrides).
    
    Configuration hierarchy: Global (tenant_id=NULL) → Tenant → Device
    """
    __tablename__ = "trip_config"
    
    id = Column(Integer, primary_key=True, autoincrement=True)
    tenant_id = get_uuid_nullable()  # NULL = global default
    
    # Ingestion parameters
    batch_sweep_interval_minutes = Column(Integer, nullable=False, default=10)
    tracklist_delay_minutes = Column(Integer, nullable=False, default=5)
    coalesce_floor_minutes = Column(Integer, nullable=False, default=120)
    
    # Engine geometry parameters
    engine_anchor_radius_m = Column(Integer, nullable=False, default=100)
    engine_min_leg_distance_m = Column(Integer, nullable=False, default=300)
    engine_move_confirm_m = Column(Integer, nullable=False, default=150)
    
    # Engine thresholds
    engine_max_speed_kmh = Column(Integer, nullable=False, default=200)
    engine_gap_timeout_min = Column(Integer, nullable=False, default=30)
    engine_smoothing_window = Column(Integer, nullable=False, default=3)
    
    # Air leg detection
    engine_air_speed_kmh = Column(Integer, nullable=False, default=300)
    engine_air_min_distance_km = Column(Integer, nullable=False, default=150)
    
    # Journey grouping
    engine_journey_break_dwell_min = Column(Integer, nullable=False, default=30)
    
    # Metadata
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
