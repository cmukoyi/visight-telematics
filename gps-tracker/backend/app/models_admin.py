"""
Admin-specific database models: admin users, logs, audit, packages, critical alerts
"""
from sqlalchemy import Column, String, Boolean, DateTime, ForeignKey, Integer, Float, Text, Enum, JSON, Index
from sqlalchemy.sql import func
from sqlalchemy.orm import relationship
import calendar
import uuid
from datetime import datetime, timedelta
from app.database import Base
import os
import enum

# Use String for UUIDs in SQLite, PostgreSQL UUID type for PostgreSQL
DATABASE_URL = os.getenv("DATABASE_URL", "")
use_sqlite = DATABASE_URL.startswith("sqlite")

if use_sqlite:
    def get_uuid_column():
        return Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    def get_uuid_fk(table_col):
        return Column(String(36), ForeignKey(table_col), nullable=False)
else:
    from sqlalchemy.dialects.postgresql import UUID
    def get_uuid_column():
        return Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    def get_uuid_fk(table_col):
        return Column(UUID(as_uuid=True), ForeignKey(table_col), nullable=False)


class AdminUser(Base):
    """Admin portal users with role-based access control"""
    __tablename__ = "admin_users"
    
    id = get_uuid_column()
    username = Column(String(50), unique=True, nullable=False, index=True)
    email = Column(String(255), unique=True, nullable=False, index=True)
    hashed_password = Column(String(255), nullable=False)
    full_name = Column(String(100))
    role = Column(String(20), default="viewer")  # admin, manager, viewer
    is_active = Column(Boolean, default=True)
    last_login = Column(DateTime(timezone=True))
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())
    
    # Relationships
    logs = relationship("AppLog", back_populates="admin_user")
    audit_logs = relationship("AuditLog", back_populates="admin_user")


class AppLog(Base):
    """Centralized application logging (backend WARNING+ via db_log_handler)"""
    __tablename__ = "app_logs"
    
    id = get_uuid_column()
    user_id = Column(String(36), nullable=True, index=True)  # Optional: which app user generated this
    admin_user_id = get_uuid_fk("admin_users.id")
    level = Column(String(10), default="INFO", index=True)  # DEBUG, INFO, WARNING, ERROR, CRITICAL
    category = Column(String(50), index=True)  # auth, location, api, ui, device, etc.
    message = Column(Text, nullable=False)
    context = Column(JSON)  # Additional metadata (device, version, network, etc.)
    stack_trace = Column(Text)  # For errors
    source = Column(String(100))  # Where the log came from (device, app version, etc.)
    ip_address = Column(String(45))  # IPv4 or IPv6
    created_at = Column(DateTime(timezone=True), server_default=func.now(), index=True)
    
    # Relationship
    admin_user = relationship("AdminUser", back_populates="logs")
    
    __table_args__ = (
        Index('ix_app_logs_created_level', 'created_at', 'level'),
        Index('ix_app_logs_user_created', 'user_id', 'created_at'),
        Index('ix_app_logs_category_created', 'category', 'created_at'),
    )


class AuditLog(Base):
    """Audit trail for admin actions"""
    __tablename__ = "audit_logs"
    
    id = get_uuid_column()
    admin_user_id = get_uuid_fk("admin_users.id")
    action = Column(String(100), nullable=False)  # created_admin, deleted_admin, viewed_logs, etc.
    resource_type = Column(String(50))  # AdminUser, AppLog, BillingData, etc.
    resource_id = Column(String(100))
    old_value = Column(JSON)  # Previous state
    new_value = Column(JSON)  # New state
    ip_address = Column(String(45))
    description = Column(Text)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), index=True)
    
    # Relationship
    admin_user = relationship("AdminUser", back_populates="audit_logs")
    
    __table_args__ = (
        Index('ix_audit_logs_admin_created', 'admin_user_id', 'created_at'),
        Index('ix_audit_logs_resource', 'resource_type', 'resource_id'),
    )


class TagPackage(Base):
    """Subscription package that gates how long a BLE tag may report location data.

    Admin creates packages (e.g. 'Fleet 12', validity_months=12).
    A package is assigned to a BLETag when the tag is added via the portal.
    Self-registered mobile-app tags get the package marked is_default=True.

    Validity is in calendar months. Packages created before months were
    introduced keep validity_days until edited; expiry_from() handles both.
    expiry_date on the tag = expiry_from(added_at or activation_date).
    After expiry, location updates are blocked.
    After expiry + GDPR_GRACE_DAYS (40), beacon sighting rows are purged automatically.
    """
    __tablename__ = "tag_packages"

    id            = get_uuid_column()
    name          = Column(String(100), nullable=False, unique=True)
    description   = Column(Text, nullable=True)
    validity_months = Column(Integer, nullable=True)  # e.g. 1, 6, 12 — authoritative when set
    validity_days = Column(Integer, nullable=True)    # legacy day-based packages (80, 120, 300)
    auto_delete_days = Column(Integer, nullable=True)  # days after expiry to hard-delete tag; NULL = never
    is_default    = Column(Boolean, nullable=False, default=False)  # applied to self-registered tags
    is_active     = Column(Boolean, nullable=False, default=True)
    sms_addon     = Column(Boolean, nullable=False, default=False)  # whether this package includes SMS alerts
    # DataProfiler: event types forwarded to the customer dashboard, e.g. ["ignition", "overspeed"].
    # NULL means all events are visible.
    allowed_event_types = Column(JSON, nullable=True)
    created_at    = Column(DateTime(timezone=True), server_default=func.now())
    updated_at    = Column(DateTime(timezone=True), onupdate=func.now())

    def expiry_from(self, start: datetime) -> datetime:
        """Return the expiry for a tag whose validity starts at `start`."""
        if self.validity_months:
            return add_months(start, self.validity_months)
        return start + timedelta(days=self.validity_days or 0)

    @property
    def validity_label(self) -> str:
        if self.validity_months:
            return f"{self.validity_months} month{'s' if self.validity_months != 1 else ''}"
        return f"{self.validity_days or 0} days"

    @property
    def validity_sort_key(self) -> float:
        return self.validity_months * 30.44 if self.validity_months else float(self.validity_days or 0)


def add_months(start: datetime, months: int) -> datetime:
    """Add calendar months, clamping to the month's last day (Jan 31 + 1 → Feb 28/29)."""
    month_index = start.month - 1 + months
    year, month = start.year + month_index // 12, month_index % 12 + 1
    return start.replace(year=year, month=month, day=min(start.day, calendar.monthrange(year, month)[1]))


class CriticalServiceCategory(str, enum.Enum):
    # Retired values still exist in the Postgres enum type (poller_core,
    # tracksolid, mzone, pareto_bridge); migration 065 removed their rows.
    EMAIL_DELIVERY = "email_delivery"
    DATABASE_ERRORS = "database_errors"
    CONTAINER_HEALTH = "container_health"


class CriticalServiceAlertSubscription(Base):
    """Admin-configured email subscriptions for critical backend service failures.

    A category must be explicitly enabled from the admin UI before notifications
    are sent. Recipient emails are category-specific.
    """

    __tablename__ = "critical_service_alert_subscriptions"

    id = get_uuid_column()
    category = Column(
        Enum(
            CriticalServiceCategory,
            name="critical_service_category",
            values_callable=lambda enum_cls: [member.value for member in enum_cls],
            validate_strings=True,
        ),
        nullable=False,
        unique=True,
        index=True,
    )
    is_enabled = Column(Boolean, nullable=False, default=False)
    failure_threshold = Column(Integer, nullable=False, default=5)
    window_minutes = Column(Integer, nullable=False, default=15)
    cooldown_minutes = Column(Integer, nullable=False, default=60)
    recipient_emails = Column(JSON, nullable=True)  # list[str]
    last_alert_sent_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())
