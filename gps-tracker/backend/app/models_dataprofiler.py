"""DataProfiler models — resellers, their data exchanges and device inventory.

A Reseller is a technology provider (e.g. a Teltonika supplier) that owns a
pool of IMEIs. Each Reseller has exactly one DataExchange, which is linked 1:1
to the main UserGroup on the customer dashboard. When a device is routed
through the exchange it is provisioned on the customer dashboard as a BLETag
in that group, carrying a TagPackage that sets its validity and visible events.
"""
from sqlalchemy import Column, String, Boolean, DateTime, Text, ForeignKey, Index, text
from sqlalchemy.sql import func
from sqlalchemy.orm import relationship

from app.database import Base
from app.models import get_uuid_column, get_uuid_fk, get_uuid_fk_nullable, use_sqlite

if use_sqlite:
    _TagRefType = String(36)
else:
    from sqlalchemy.dialects.postgresql import UUID
    _TagRefType = UUID(as_uuid=True)


class Reseller(Base):
    __tablename__ = "resellers"

    id                 = get_uuid_column()
    name               = Column(String(200), nullable=False, unique=True)
    code               = Column(String(50), nullable=False, unique=True)   # short URL-safe identifier
    provider           = Column(String(50), nullable=False, default="teltonika")  # device technology provider
    contact_name       = Column(String(200), nullable=True)
    contact_email      = Column(String(255), nullable=True)
    contact_phone      = Column(String(50), nullable=True)
    notes              = Column(Text, nullable=True)
    default_package_id = get_uuid_fk_nullable("tag_packages.id")  # applied to new IMEIs unless overridden
    is_active          = Column(Boolean, nullable=False, default=True)
    created_at         = Column(DateTime(timezone=True), server_default=func.now())
    updated_at         = Column(DateTime(timezone=True), onupdate=func.now())

    exchange = relationship("DataExchange", back_populates="reseller", uselist=False,
                            cascade="all, delete-orphan")
    devices  = relationship("ResellerDevice", back_populates="reseller",
                            cascade="all, delete-orphan")


class DataExchange(Base):
    """Routing endpoint for a reseller's events.

    exchange_key is the public identifier a customer enters on the dashboard;
    secret_hash is the PBKDF2 hash of the one-time link secret. usergroup_id is
    NULL until the exchange is linked to a customer dashboard group.
    """
    __tablename__ = "data_exchanges"
    __table_args__ = (
        Index("uq_data_exchanges_reseller", "reseller_id", unique=True),
        Index("uq_data_exchanges_usergroup", "usergroup_id", unique=True,
              postgresql_where=text("usergroup_id IS NOT NULL")),
    )

    id           = get_uuid_column()
    reseller_id  = get_uuid_fk("resellers.id")
    exchange_key = Column(String(64), nullable=False, unique=True, index=True)
    secret_hash  = Column(String(255), nullable=False)
    usergroup_id = get_uuid_fk_nullable("user_groups.id")
    status       = Column(String(20), nullable=False, default="pending")  # pending | linked | disabled
    linked_at    = Column(DateTime(timezone=True), nullable=True)
    linked_by    = Column(String(255), nullable=True)  # email of admin / portal user who linked it
    created_at   = Column(DateTime(timezone=True), server_default=func.now())
    updated_at   = Column(DateTime(timezone=True), onupdate=func.now())

    reseller  = relationship("Reseller", back_populates="exchange")
    usergroup = relationship("UserGroup")


class ResellerDevice(Base):
    """One IMEI in a reseller's inventory and its routing state.

    status: pending  – known to DataProfiler, not yet on the customer dashboard
            routed   – provisioned as ble_tag_id in the exchange's usergroup
            conflict – IMEI already exists on the dashboard outside this exchange
    """
    __tablename__ = "reseller_devices"
    __table_args__ = (Index("ix_reseller_devices_reseller", "reseller_id"),)

    id              = get_uuid_column()
    reseller_id     = get_uuid_fk("resellers.id")
    imei            = Column(String(50), nullable=False, unique=True, index=True)
    label           = Column(String(100), nullable=True)
    device_model    = Column(String(100), nullable=True)   # e.g. FMC130
    package_id      = get_uuid_fk_nullable("tag_packages.id")  # NULL = use reseller default
    status          = Column(String(20), nullable=False, default="pending")
    status_detail   = Column(String(255), nullable=True)
    # SET NULL so deleting the tag on the dashboard does not block on this row
    ble_tag_id      = Column(_TagRefType, ForeignKey("ble_tags.id", ondelete="SET NULL"), nullable=True)
    first_routed_at = Column(DateTime(timezone=True), nullable=True)
    last_event_at   = Column(DateTime(timezone=True), nullable=True)
    created_at      = Column(DateTime(timezone=True), server_default=func.now())
    updated_at      = Column(DateTime(timezone=True), onupdate=func.now())

    reseller = relationship("Reseller", back_populates="devices")
