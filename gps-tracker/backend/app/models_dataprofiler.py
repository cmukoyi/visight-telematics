"""DataProfiler models — resellers, their data exchanges and device inventory.

A Reseller owns a pool of IMEIs, each of a known UnitType (e.g. Teltonika FMC125). Each Reseller has exactly one DataExchange, which is linked 1:1
to the main UserGroup on the customer dashboard. When a device is routed
through the exchange it is provisioned on the customer dashboard as a BLETag
in that group, carrying a TagPackage that sets its validity and visible events.
"""
from sqlalchemy import Column, String, Boolean, DateTime, Text, ForeignKey, Index, text, BigInteger, Integer, Float, JSON
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


class UnitType(Base):
    """A device make/model the platform can ingest, e.g. Teltonika FMC125.

    Managed under DataProfiler → Unit Types and chosen when IMEIs are added.
    """
    __tablename__ = "unit_types"
    __table_args__ = (Index("uq_unit_types_manufacturer_model", "manufacturer", "model", unique=True),)

    id           = get_uuid_column()
    manufacturer = Column(String(100), nullable=False)   # e.g. Teltonika
    model        = Column(String(100), nullable=False)   # e.g. FMC125
    description  = Column(Text, nullable=True)
    is_active    = Column(Boolean, nullable=False, default=True)
    created_at   = Column(DateTime(timezone=True), server_default=func.now())
    updated_at   = Column(DateTime(timezone=True), onupdate=func.now())

    @property
    def name(self) -> str:
        return f"{self.manufacturer} {self.model}"


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
    unit_type_id    = get_uuid_fk_nullable("unit_types.id")
    package_id      = get_uuid_fk_nullable("tag_packages.id")  # NULL = use reseller default
    status          = Column(String(20), nullable=False, default="pending")
    status_detail   = Column(String(255), nullable=True)
    # SET NULL so deleting the tag on the dashboard does not block on this row
    ble_tag_id      = Column(_TagRefType, ForeignKey("ble_tags.id", ondelete="SET NULL"), nullable=True)
    first_routed_at = Column(DateTime(timezone=True), nullable=True)
    last_event_at   = Column(DateTime(timezone=True), nullable=True)
    created_at      = Column(DateTime(timezone=True), server_default=func.now())
    updated_at      = Column(DateTime(timezone=True), onupdate=func.now())

    reseller  = relationship("Reseller", back_populates="devices")
    unit_type = relationship("UnitType")


class DeviceEvent(Base):
    """A decoded device event received from a Data Exchange queue — the customer
    dashboard's permanent copy (DataProfiler itself keeps 30 days).

    dp_event_id is DataProfiler's events_processed.id; it makes delivery idempotent.
    """
    __tablename__ = "device_events"
    __table_args__ = (
        Index("ix_device_events_imei_time", "imei", "recorded_at"),
        Index("ix_device_events_group_time", "usergroup_id", "recorded_at"),
    )

    id           = Column(BigInteger, primary_key=True, autoincrement=True)
    dp_event_id  = Column(BigInteger, nullable=False, unique=True)
    imei         = Column(String(20), nullable=False)
    usergroup_id = get_uuid_fk_nullable("user_groups.id")
    recorded_at  = Column(DateTime(timezone=True), nullable=False)
    received_at  = Column(DateTime(timezone=True), nullable=True)
    event_type   = Column(String(32), nullable=True)
    event_io_id  = Column(Integer, nullable=False)
    priority     = Column(Integer, nullable=True)
    latitude     = Column(Float, nullable=True)
    longitude    = Column(Float, nullable=True)
    altitude     = Column(Integer, nullable=True)
    angle        = Column(Integer, nullable=True)
    satellites   = Column(Integer, nullable=True)
    speed        = Column(Integer, nullable=True)
    io           = Column(JSON, nullable=True)
    trip_id      = get_uuid_fk_nullable("trips.id")  # set by the trip builder
    created_at   = Column(DateTime(timezone=True), server_default=func.now())


class Trip(Base):
    """A journey built from a device's events: trip_start … positions/alerts … trip_end.

    Opened by trip_start (or, if that was missed, by the first driving
    position); closed by trip_end, ignition off, a parked position, or a gap
    longer than trip_builder.MAX_GAP. status: open | closed.
    """
    __tablename__ = "trips"
    __table_args__ = (
        Index("ix_trips_imei_started", "imei", "started_at"),
        Index("ix_trips_group_started", "usergroup_id", "started_at"),
    )

    id               = get_uuid_column()
    imei             = Column(String(20), nullable=False)
    usergroup_id     = get_uuid_fk_nullable("user_groups.id")
    status           = Column(String(10), nullable=False, default="open")
    start_reason     = Column(String(20), nullable=False)   # trip_start | implicit
    close_reason     = Column(String(20), nullable=True)    # trip_end | ignition_off | parked | gap | restarted | stale
    started_at       = Column(DateTime(timezone=True), nullable=False)
    ended_at         = Column(DateTime(timezone=True), nullable=True)
    last_event_at    = Column(DateTime(timezone=True), nullable=False)
    start_latitude   = Column(Float, nullable=True)
    start_longitude  = Column(Float, nullable=True)
    end_latitude     = Column(Float, nullable=True)
    end_longitude    = Column(Float, nullable=True)
    start_address    = Column(String(255), nullable=True)   # reverse geocoded (address_service)
    end_address      = Column(String(255), nullable=True)
    start_odometer_m = Column(BigInteger, nullable=True)
    end_odometer_m   = Column(BigInteger, nullable=True)
    distance_m       = Column(Integer, nullable=False, default=0)
    duration_s       = Column(Integer, nullable=False, default=0)
    max_speed        = Column(Integer, nullable=False, default=0)
    avg_speed        = Column(Float, nullable=True)
    point_count      = Column(Integer, nullable=False, default=0)
    speeding_count   = Column(Integer, nullable=False, default=0)
    harsh_acceleration_count = Column(Integer, nullable=False, default=0)
    harsh_braking_count      = Column(Integer, nullable=False, default=0)
    harsh_cornering_count    = Column(Integer, nullable=False, default=0)
    idling_count     = Column(Integer, nullable=False, default=0)
    created_at       = Column(DateTime(timezone=True), server_default=func.now())
    updated_at       = Column(DateTime(timezone=True), onupdate=func.now())


class TripBuilderState(Base):
    """Per-device bookmark: the trip builder has processed device_events up to last_event_id."""
    __tablename__ = "trip_builder_state"

    imei          = Column(String(20), primary_key=True)
    last_event_id = Column(BigInteger, nullable=False, default=0)
    updated_at    = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())


class ReportSchedule(Base):
    """A report emailed on a schedule to a list of recipients.

    Each run covers the previous whole period in the schedule's timezone
    (yesterday / last Monday–Sunday / last month) and is sent at send_hour.
    """
    __tablename__ = "report_schedules"
    __table_args__ = (Index("ix_report_schedules_due", "is_active", "next_run_at"),)

    id             = get_uuid_column()
    usergroup_id   = get_uuid_fk("user_groups.id")
    created_by     = get_uuid_fk_nullable("portal_users.id")
    report_key     = Column(String(40), nullable=False)    # reports_service.REPORTS key
    name           = Column(String(120), nullable=True)
    frequency      = Column(String(10), nullable=False)    # daily | weekly | monthly
    file_format    = Column(String(10), nullable=False, default="xlsx")  # xlsx | csv
    recipients     = Column(JSON, nullable=False)          # list of emails
    params         = Column(JSON, nullable=True)           # {"imei": ..., "category": ...}
    timezone       = Column(String(40), nullable=False, default="Africa/Johannesburg")
    send_hour      = Column(Integer, nullable=False, default=6)
    is_active      = Column(Boolean, nullable=False, default=True)
    next_run_at    = Column(DateTime(timezone=True), nullable=False)
    last_run_at    = Column(DateTime(timezone=True), nullable=True)
    last_status    = Column(String(255), nullable=True)
    created_at     = Column(DateTime(timezone=True), server_default=func.now())
    updated_at     = Column(DateTime(timezone=True), onupdate=func.now())


class GeocodeCache(Base):
    """Street addresses by position, rounded to 4 decimals (~11 m), so each spot is looked up once."""
    __tablename__ = "geocode_cache"

    lat_e4     = Column(Integer, primary_key=True)
    lng_e4     = Column(Integer, primary_key=True)
    address    = Column(String(255), nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
