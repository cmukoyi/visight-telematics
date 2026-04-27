"""
Admin-specific database models: Admin Users, Logs, Billing
"""
from sqlalchemy import Column, String, Boolean, DateTime, ForeignKey, Integer, Float, Text, Enum, JSON, Index
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
    """Centralized application logging from mobile app"""
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


class BillingData(Base):
    """Billing summary - calculated daily"""
    __tablename__ = "billing_data"
    
    id = get_uuid_column()
    date = Column(DateTime(timezone=True), nullable=False, unique=True, index=True)
    total_users = Column(Integer, default=0)  # Total registered users
    active_users = Column(Integer, default=0)  # Users with at least one IMEI
    total_imeis = Column(Integer, default=0)  # Total active IMEIs
    active_devices_by_user = Column(JSON)  # {user_id: [imei_list]}
    imei_to_user = Column(JSON)  # {imei: user_id}
    user_device_count = Column(JSON)  # {user_id: count}
    meta_data = Column(JSON)  # Additional billing metadata
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())
    
    __table_args__ = (
        Index('ix_billing_data_date', 'date'),
    )


class BillingTransaction(Base):
    """Individual billing events/transactions"""
    __tablename__ = "billing_transactions"
    
    id = get_uuid_column()
    user_id = Column(String(36), nullable=True, index=True)
    transaction_type = Column(String(50))  # user_registered, imei_assigned, imei_removed, etc.
    imei = Column(String(50), nullable=True, index=True)
    amount = Column(Float, default=0)
    currency = Column(String(3), default="USD")
    description = Column(Text)
    meta_data = Column(JSON)  # Transaction metadata
    created_at = Column(DateTime(timezone=True), server_default=func.now(), index=True)
    
    __table_args__ = (
        Index('ix_billing_transactions_user_date', 'user_id', 'created_at'),
        Index('ix_billing_transactions_type_date', 'transaction_type', 'created_at'),
    )


class TagPackage(Base):
    """Subscription package that gates how long a BLE tag may report location data.

    Admin creates packages (e.g. 'Basic 80', validity_days=80).
    A package is assigned to a BLETag when the tag is added via the portal.
    Self-registered mobile-app tags get the package marked is_default=True.

    expiry_date on the tag = added_at + validity_days.
    After expiry, location updates are blocked.
    After expiry + GDPR_GRACE_DAYS (40), beacon sighting rows are purged automatically.
    """
    __tablename__ = "tag_packages"

    id            = get_uuid_column()
    name          = Column(String(100), nullable=False, unique=True)
    description   = Column(Text, nullable=True)
    validity_days = Column(Integer, nullable=False)   # e.g. 80, 120, 300
    auto_delete_days = Column(Integer, nullable=True)  # days after expiry to hard-delete tag; NULL = never
    is_default    = Column(Boolean, nullable=False, default=False)  # applied to self-registered tags
    is_active     = Column(Boolean, nullable=False, default=True)
    created_at    = Column(DateTime(timezone=True), server_default=func.now())
    updated_at    = Column(DateTime(timezone=True), onupdate=func.now())
