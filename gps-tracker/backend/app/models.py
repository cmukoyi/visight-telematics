from sqlalchemy import Column, String, Boolean, DateTime, ForeignKey, Integer, BigInteger, Float, Text, Enum, JSON, UniqueConstraint, Index
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
    pois = relationship("POI", back_populates="user")
    geofence_alerts = relationship("GeofenceAlert", back_populates="user")


class BLETag(Base):
    __tablename__ = "ble_tags"
    
    id = get_uuid_column()
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=True, index=True)
    imei = Column(String(50), unique=True, nullable=True, index=True)
    device_name = Column(String(100))
    device_model = Column(String(100))  # unit type, e.g. "Teltonika FMC125"
    description = Column(String(255))
    tag_type = Column(String(50), nullable=True, default='teltonika')
    is_active = Column(Boolean, default=True)
    last_seen = Column(DateTime(timezone=True))
    latitude = Column(String(50))
    longitude = Column(String(50))
    location_description = Column(String(500))  # formatted address
    battery_level = Column(Integer)
    attributes = Column(JSON, nullable=True)  # Custom attributes: {field: {value, show_on_map}}
    added_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())
    # Package / subscription
    package_id      = Column(String(36), ForeignKey("tag_packages.id"), nullable=True, index=True)
    expiry_date     = Column(DateTime(timezone=True), nullable=True)  # package.expiry_from(activation_date)
    activation_date = Column(DateTime(timezone=True), nullable=True)  # set on first GPS fix; expiry calculated from here
    gdpr_deletion_warned_at = Column(DateTime(timezone=True), nullable=True)  # set when 7-day deletion warning is sent

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
    place_group_id = Column(UUID(as_uuid=True), ForeignKey("place_groups.id", ondelete="SET NULL"), nullable=True, index=True)

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
    notes        = Column(Text, nullable=True)           # added by whoever processed (read) the alert
    read_at      = Column(DateTime(timezone=True), nullable=True)
    read_by      = Column(String(255), nullable=True)    # the portal user's name, kept as text

    tag       = relationship("BLETag", foreign_keys=[tag_id])


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
    # White-label look: menu/background colours, default colour scheme, font, corners, platform name
    # (keys validated by routes_portal.THEME_SETTINGS)
    theme_settings        = Column(JSON, nullable=True)
    report_logo_data      = Column(Text, nullable=True)          # base64 data-URL used on reports
    timezone              = Column(String(64), nullable=True)    # IANA name, e.g. 'Africa/Johannesburg'
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
    
    # v2.2 A1: Per-tenant trip engine config
    # Coalesce floor: min interval between track.list pulls per device
    # NULL = use global default (120 min)
    coalesce_floor_minutes = Column(Integer, nullable=True)

    portal_users = relationship("PortalUser", back_populates="usergroup",
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
    # Security group whose users can see this vehicle group's vehicles (migration 068)
    security_group_id = Column(UUID(as_uuid=True), ForeignKey("security_groups.id", ondelete="SET NULL"), nullable=True, index=True)
    created_at   = Column(DateTime(timezone=True), server_default=func.now())
    updated_at   = Column(DateTime(timezone=True), onupdate=func.now())

    usergroup = relationship("UserGroup", back_populates="tag_categories")


class SecurityGroup(Base):
    """A set of vehicle groups that a set of users may see, within one UserGroup."""
    __tablename__ = "security_groups"
    __table_args__ = (UniqueConstraint("usergroup_id", "name", name="uq_security_group_name"),)

    id           = get_uuid_column()
    usergroup_id = get_uuid_fk("user_groups.id")
    name         = Column(String(100), nullable=False)
    description  = Column(String(255), nullable=True)
    created_at   = Column(DateTime(timezone=True), server_default=func.now())
    updated_at   = Column(DateTime(timezone=True), onupdate=func.now())


class PortalRole(Base):
    """A named set of permissions (access_service.PERMISSIONS) within one UserGroup.

    The default roles are created per group by access_service.ensure_defaults;
    is_admin roles see every vehicle regardless of security group.
    """
    __tablename__ = "portal_roles"
    __table_args__ = (UniqueConstraint("usergroup_id", "name", name="uq_portal_role_name"),)

    id           = get_uuid_column()
    usergroup_id = get_uuid_fk("user_groups.id")
    name         = Column(String(100), nullable=False)
    description  = Column(String(255), nullable=True)
    permissions  = Column(JSON, nullable=False, default=list)
    is_admin     = Column(Boolean, nullable=False, default=False)
    is_system    = Column(Boolean, nullable=False, default=False)   # a default role; can't be deleted
    created_at   = Column(DateTime(timezone=True), server_default=func.now())
    updated_at   = Column(DateTime(timezone=True), onupdate=func.now())


class PortalUserRole(Base):
    """A role held by a portal user; a user's permissions are the union of their roles'."""
    __tablename__ = "portal_user_roles"

    user_id = Column(UUID(as_uuid=True), ForeignKey("portal_users.id", ondelete="CASCADE"), primary_key=True)
    role_id = Column(UUID(as_uuid=True), ForeignKey("portal_roles.id", ondelete="CASCADE"), primary_key=True, index=True)


class PortalAuditLog(Base):
    """Audit trail of what customer-portal users did in their user group (Configuration → Security → Audit Trail)."""
    __tablename__ = "portal_audit_logs"
    __table_args__ = (Index("ix_portal_audit_group_created", "usergroup_id", "created_at"),)

    id           = get_uuid_column()
    usergroup_id = Column(UUID(as_uuid=True), ForeignKey("user_groups.id", ondelete="CASCADE"), nullable=False)
    user_id      = Column(UUID(as_uuid=True), ForeignKey("portal_users.id", ondelete="SET NULL"), nullable=True)
    user_email   = Column(String(255), nullable=True)      # kept when the user is deleted
    user_name    = Column(String(255), nullable=True)
    action       = Column(String(30), nullable=False)      # Added / Updated / Deleted / Signed in / ...
    area         = Column(String(50), nullable=False)      # Users, Roles, Vehicles, Places, ...
    summary      = Column(String(500), nullable=False)
    resource_id  = Column(String(100), nullable=True)
    details      = Column(JSON, nullable=True)             # the request (passwords and images removed)
    outcome      = Column(String(20), nullable=False, default="success")   # success | denied | failed
    ip_address   = Column(String(45), nullable=True)
    created_at   = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class NotificationRule(Base):
    """Configuration → Misc → Notification Rules.

    rule_type 'geofence': vehicles in `category` (a vehicle group; NULL = all
    vehicles) raise one alert when they enter and one when they leave any of
    `place_ids` (NULL = every place). Alerts go to the inbox; with
    email_enabled, `email_message` (placeholders such as {vehicle},
    {registration}, {event}, {time}) is also emailed to email_recipients.
    """
    __tablename__ = "notification_rules"

    id               = get_uuid_column()
    usergroup_id     = get_uuid_fk("user_groups.id")
    name             = Column(String(120), nullable=False)
    rule_type        = Column(String(30), nullable=False, default="geofence")
    category         = Column(String(100), nullable=True)
    place_ids        = Column(JSON, nullable=True)
    place_group_ids  = Column(JSON, nullable=True)        # places in these groups too
    event_group_id   = Column(UUID(as_uuid=True), ForeignKey("event_type_groups.id", ondelete="SET NULL"), nullable=True)
    event_codes      = Column(JSON, nullable=True)        # rule_type 'event': these event types too (dictionary.EVENTS codes)
    on_entry         = Column(Boolean, nullable=False, default=True)
    on_exit          = Column(Boolean, nullable=False, default=True)
    email_enabled    = Column(Boolean, nullable=False, default=False)
    email_recipients = Column(JSON, nullable=True)
    email_message    = Column(Text, nullable=True)
    is_active        = Column(Boolean, nullable=False, default=True)
    created_by       = Column(UUID(as_uuid=True), ForeignKey("portal_users.id", ondelete="SET NULL"), nullable=True)
    created_at       = Column(DateTime(timezone=True), server_default=func.now())
    updated_at       = Column(DateTime(timezone=True), onupdate=func.now())


class PlaceGroup(Base):
    """A named set of places (e.g. Depots, Customer sites), for organising places and notification rules."""
    __tablename__ = "place_groups"
    __table_args__ = (UniqueConstraint("usergroup_id", "name", name="uq_place_group_name"),)

    id           = get_uuid_column()
    usergroup_id = get_uuid_fk("user_groups.id")
    name         = Column(String(100), nullable=False)
    color        = Column(String(20), nullable=True)
    created_at   = Column(DateTime(timezone=True), server_default=func.now())


class EventTypeSetting(Base):
    """A user group's own name and map marker colour for one of our event codes (dictionary.EVENTS)."""
    __tablename__ = "event_type_settings"

    usergroup_id = Column(UUID(as_uuid=True), ForeignKey("user_groups.id", ondelete="CASCADE"), primary_key=True)
    code         = Column(String(40), primary_key=True)
    label        = Column(String(120), nullable=True)
    color        = Column(String(20), nullable=True)


class EventTypeGroup(Base):
    """A named set of event codes; a notification rule can fire on any event in the group."""
    __tablename__ = "event_type_groups"
    __table_args__ = (UniqueConstraint("usergroup_id", "name", name="uq_event_type_group_name"),)

    id           = get_uuid_column()
    usergroup_id = get_uuid_fk("user_groups.id")
    name         = Column(String(100), nullable=False)
    codes        = Column(JSON, nullable=False, default=list)
    created_at   = Column(DateTime(timezone=True), server_default=func.now())


class GeofenceStatus(Base):
    """Whether a vehicle is inside or outside a place, as of its last checked fix (geofence_engine)."""
    __tablename__ = "geofence_states"

    tag_id     = Column(UUID(as_uuid=True), ForeignKey("ble_tags.id", ondelete="CASCADE"), primary_key=True)
    poi_id     = Column(UUID(as_uuid=True), ForeignKey("pois.id", ondelete="CASCADE"), primary_key=True)
    inside     = Column(Boolean, nullable=False)
    checked_at = Column(DateTime(timezone=True), nullable=False)   # device time of the fix


class PlaceVisit(Base):
    """A vehicle's stay in a place: entered … exited (geofence_engine), for place reports.

    Recorded for every active place of the group, watched or not. entered_at is
    None when the vehicle was already inside when tracking began; exited_at is
    None while it is still inside.
    """
    __tablename__ = "place_visits"
    __table_args__ = (
        Index("ix_place_visits_group_entered", "usergroup_id", "entered_at"),
        Index("ix_place_visits_group_exited", "usergroup_id", "exited_at"),
        Index("ix_place_visits_open", "tag_id", "poi_id", "exited_at"),
    )

    id           = Column(BigInteger, primary_key=True, autoincrement=True)
    usergroup_id = Column(UUID(as_uuid=True), ForeignKey("user_groups.id", ondelete="CASCADE"), nullable=False)
    tag_id       = Column(UUID(as_uuid=True), ForeignKey("ble_tags.id", ondelete="CASCADE"), nullable=False)
    imei         = Column(String(20), nullable=False)
    poi_id       = Column(UUID(as_uuid=True), ForeignKey("pois.id", ondelete="CASCADE"), nullable=False)
    entered_at   = Column(DateTime(timezone=True), nullable=True)
    exited_at    = Column(DateTime(timezone=True), nullable=True)
    entry_speed  = Column(Integer, nullable=True)
    exit_speed   = Column(Integer, nullable=True)


class TenantFeature(Base):
    """Tenant-wide feature toggles for customer dashboard.
    
    Controls which features are available to ALL users in a tenant.
    Managed via Admin Portal → Tenant Features page.
    
    Logic:
    - Tenant features = master switch (all users in tenant)
    - User custom_features = per-user refinement  
    - effective_features = intersection(tenant_features, user_features)
    
    Feature names: livemap, history, history-advanced, alerts, geofences,
    reports, management, floorplan, settings, hive
    """
    __tablename__ = "tenant_features"
    
    id = get_uuid_column()
    usergroup_id = get_uuid_fk("user_groups.id")
    feature_name = Column(String(50), nullable=False)
    enabled = Column(Boolean, nullable=False, server_default='true')
    updated_by = Column(UUID(as_uuid=True), ForeignKey("admin_users.id", ondelete="SET NULL"), nullable=True)
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    
    __table_args__ = (
        UniqueConstraint('usergroup_id', 'feature_name', name='uq_tenant_feature'),
        Index('ix_tenant_features_usergroup_id', 'usergroup_id'),
        Index('ix_tenant_features_enabled', 'enabled'),
    )


class PortalUser(Base):
    """A user who can log in to the customer portal.

    Every UserGroup gets at least one PortalUser (the group admin) created
    automatically when the group is provisioned from the admin portal. More
    portal users can be added to the same group later.
    """
    __tablename__ = "portal_users"

    id              = get_uuid_column()
    usergroup_id    = get_uuid_fk("user_groups.id")
    mobile_user_id  = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), unique=True, nullable=True, index=True)
    email           = Column(String(255), unique=True, nullable=False, index=True)
    hashed_password = Column(String(255), nullable=False)
    first_name      = Column(String(100))
    last_name       = Column(String(100))
    is_active       = Column(Boolean, nullable=False, default=True)
    is_group_admin  = Column(Boolean, nullable=False, default=False)
    expires_at      = Column(DateTime(timezone=True), nullable=True)
    # Portal RBAC
    # role: 'admin' | 'manager' | 'reporter' | 'custom' | 'api_only'
    # admin    – all features allowed by the usergroup
    # manager  – tracking + management sections only
    # reporter – reports section only
    # custom   – exactly the keys in custom_features (intersected with usergroup)
    # api_only – API access only (no dashboard), can use bearer token for API v2 endpoints
    role            = Column(String(20), nullable=False, default='admin')
    custom_features = Column(JSON, nullable=True)  # only used when role = 'custom'
    # Access control (migration 068): the user's role and the security group
    # whose vehicles they see. Users whose role is an admin role see everything.
    role_id           = Column(UUID(as_uuid=True), ForeignKey("portal_roles.id", ondelete="SET NULL"), nullable=True, index=True)
    security_group_id = Column(UUID(as_uuid=True), ForeignKey("security_groups.id", ondelete="SET NULL"), nullable=True, index=True)
    last_login_at     = Column(DateTime(timezone=True), nullable=True)
    last_active_at    = Column(DateTime(timezone=True), nullable=True)
    language          = Column(String(10), nullable=True)   # e.g. 'fr'; None = the user group's default_language
    created_at      = Column(DateTime(timezone=True), server_default=func.now())
    updated_at      = Column(DateTime(timezone=True), onupdate=func.now())
    # Notification preferences (per-user)
    alerts_enabled       = Column(Boolean, nullable=False, default=True)
    notify_geofence_exit = Column(Boolean, nullable=False, default=True)
    notify_battery_low   = Column(Boolean, nullable=False, default=True)
    notify_offline       = Column(Boolean, nullable=False, default=True)
    notify_hive_breach   = Column(Boolean, nullable=False, default=True)
    notify_temperature    = Column(Boolean, nullable=False, default=True)
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
    mobile_user = relationship("User", foreign_keys=[mobile_user_id])


# ═══════════════════════════════════════════════════════════════════════════════
# HIVE TRACKING — proximity group monitoring
# ═══════════════════════════════════════════════════════════════════════════════


class DevicePosition(Base):
    """GPS history for a device, written by the DataProfiler dashboard ingest.

    Unique constraint on (device_imei, observed_at) prevents duplicates.
    """
    __tablename__ = "device_positions"
    
    id = Column(Integer, primary_key=True, autoincrement=True)
    device_imei = Column(String(100), nullable=False, index=True)
    
    # Core position data
    lat = Column(Float, nullable=False)
    lng = Column(Float, nullable=False)
    observed_at = Column(DateTime(timezone=True), nullable=False, index=True)
    
    # v2.1.11 D1: Track arrival time (for late-arriving buffered positions)
    received_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now(), index=True)
    
    # Movement metadata
    direction = Column(Integer, nullable=True)           # 0-360 degrees
    gps_speed = Column(Float, nullable=True)             # km/h
    pos_type = Column(Integer, nullable=True)            # 1=GPS, 2=LBS, 3=WIFI, 5=unknown
    satellite = Column(Integer, nullable=True)           # GPS satellite count
    ignition = Column(String(10), nullable=True)         # ON/OFF
    acc_status = Column(String(10), nullable=True)       # ON/OFF
    gps_mode = Column(Integer, nullable=True)
    confidence = Column(Integer, nullable=True)          # 1-3 (NEVER use for classification per spec)
    
    # Reverse geocoding (Section 3.6 - cached at ingest)
    address = Column(Text, nullable=True)                # Human-readable location
    
    # Sensor data (optional, from device IO elements)
    temperature = Column(Float, nullable=True)       # °C (canonical, always Celsius)
    battery_pct = Column(Integer, nullable=True)     # % (0-100)
    altitude = Column(Float, nullable=True)          # meters (canonical)
    rssi = Column(Integer, nullable=True)            # dBm (signal strength)
    
    # Metadata
    source = Column(String(20), nullable=False, default="teltonika")
    created_at = Column(DateTime(timezone=True), server_default=func.now(), index=True)




class AnalyticsExpression(Base):
    """Reports → Expressions: a named calculation over analytics measures, e.g. m.Trip_distance_km / m.Trip_count."""
    __tablename__ = "analytics_expressions"
    __table_args__ = (UniqueConstraint("usergroup_id", "name", name="uq_analytics_expression_name"),)

    id           = get_uuid_column()
    usergroup_id = get_uuid_fk("user_groups.id")
    name         = Column(String(120), nullable=False)
    category     = Column(String(60), nullable=True)
    expression   = Column(Text, nullable=False)
    description  = Column(String(255), nullable=True)
    unit         = Column(String(20), nullable=True)
    decimals     = Column(Integer, nullable=False, default=2)
    created_by   = Column(UUID(as_uuid=True), ForeignKey("portal_users.id", ondelete="SET NULL"), nullable=True)
    created_at   = Column(DateTime(timezone=True), server_default=func.now())
    updated_at   = Column(DateTime(timezone=True), onupdate=func.now())


class AnalyticsPage(Base):
    """Reports → Analytics: a page of visuals (charts, tables, KPIs) with its default period."""
    __tablename__ = "analytics_pages"

    id           = get_uuid_column()
    usergroup_id = get_uuid_fk("user_groups.id")
    name         = Column(String(120), nullable=False)
    position     = Column(Integer, nullable=False, default=0)
    date_preset  = Column(String(30), nullable=False, default="this_month")
    visuals      = Column(JSON, nullable=False, default=list)
    created_by   = Column(UUID(as_uuid=True), ForeignKey("portal_users.id", ondelete="SET NULL"), nullable=True)
    created_at   = Column(DateTime(timezone=True), server_default=func.now())
    updated_at   = Column(DateTime(timezone=True), onupdate=func.now())
