"""Vehicle maintenance — schedules, jobs, costs, workshops and their lookups.

Everything is scoped to a user group. The pieces:

- MaintenanceLookup: the group's simple lists, by kind — vehicle types,
  workshop chains, workshop types and cost centres. A vehicle's type is kept
  in its attributes as {"vehicle_type": {"value": "<lookup id>"}}.
- MaintenanceItem: one task or part (e.g. "Change oil filter").
- MaintenanceType: a kind of job (e.g. "Minor service") with its items and an
  expected duration.
- MaintenanceSchedule: when a type falls due — At / Every / Until on odometer
  (km), months and engine hours, whichever comes first — for vehicle types
  and/or individual vehicles (maintenance_service works out each occurrence).
- VehicleMaintenance: a saved job (Booked → In Progress → Completed).
- MaintenanceCost: a cost line, optionally on a job, charged to a cost centre.
- Workshop: where jobs are done (optionally at a Place).
- MaintenanceNotice: due/overdue notifications already sent, so each goes once.
"""
from sqlalchemy import (JSON, BigInteger, Boolean, Column, Date, DateTime, Float, ForeignKey, Index, Integer, Numeric,
                        String, Text)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.sql import func

from app.database import Base
from app.models import get_uuid_column

LOOKUP_KINDS = ("vehicle_type", "workshop_chain", "workshop_type", "cost_centre")
# What a cost item is for: maintenance jobs and parts, or the fleet's other running costs captured by hand
COST_CATEGORIES = {"maintenance": "Maintenance", "fuel": "Fuel", "tracking": "Tracking", "licence": "Licence",
                   "fines": "Fines", "insurance": "Insurance", "other": "Other"}


def _group():
    return Column(UUID(as_uuid=True), ForeignKey("user_groups.id", ondelete="CASCADE"), nullable=False, index=True)


class MaintenanceLookup(Base):
    __tablename__ = "maintenance_lookups"
    __table_args__ = (Index("ix_maintenance_lookups_group_kind", "usergroup_id", "kind"),)

    id           = get_uuid_column()
    usergroup_id = _group()
    kind         = Column(String(20), nullable=False)        # LOOKUP_KINDS
    name         = Column(String(120), nullable=False)
    created_at   = Column(DateTime(timezone=True), server_default=func.now())


class MaintenanceItem(Base):
    __tablename__ = "maintenance_items"

    id           = get_uuid_column()
    usergroup_id = _group()
    name         = Column(String(160), nullable=False)
    is_system    = Column(Boolean, nullable=False, default=False)   # a starter item: can't be renamed or deleted
    created_at   = Column(DateTime(timezone=True), server_default=func.now())


class MaintenanceType(Base):
    __tablename__ = "maintenance_types"

    id             = get_uuid_column()
    usergroup_id   = _group()
    name           = Column(String(160), nullable=False)
    duration_hours = Column(Integer, nullable=False, default=24)    # expected duration (days × 24 + hours)
    item_ids       = Column(JSON, nullable=False, default=list)      # [MaintenanceItem id]
    created_at     = Column(DateTime(timezone=True), server_default=func.now())


class MaintenanceSchedule(Base):
    __tablename__ = "maintenance_schedules"

    id               = get_uuid_column()
    usergroup_id     = _group()
    type_id          = Column(UUID(as_uuid=True), ForeignKey("maintenance_types.id", ondelete="CASCADE"), nullable=False)
    name             = Column(String(160), nullable=False)
    starts_on        = Column(Date, nullable=False)                  # months count from here
    at_km            = Column(Integer, nullable=True)                # odometer reading, km
    at_months        = Column(Integer, nullable=True)
    at_hours         = Column(Integer, nullable=True)                # engine hours
    recurring        = Column(Boolean, nullable=False, default=False)
    every_km         = Column(Integer, nullable=True)
    every_months     = Column(Integer, nullable=True)
    every_hours      = Column(Integer, nullable=True)
    until_km         = Column(Integer, nullable=True)
    until_months     = Column(Integer, nullable=True)
    until_hours      = Column(Integer, nullable=True)
    remind_km        = Column(Integer, nullable=False, default=500)  # Due this close to the threshold
    remind_days      = Column(Integer, nullable=False, default=14)
    remind_hours     = Column(Integer, nullable=False, default=10)
    vehicle_type_ids = Column(JSON, nullable=False, default=list)    # every vehicle of these types …
    imeis            = Column(JSON, nullable=False, default=list)    # … plus these vehicles
    is_active        = Column(Boolean, nullable=False, default=True)
    created_at       = Column(DateTime(timezone=True), server_default=func.now())


class Workshop(Base):
    __tablename__ = "workshops"

    id           = get_uuid_column()
    usergroup_id = _group()
    name         = Column(String(160), nullable=False)
    poi_id       = Column(UUID(as_uuid=True), ForeignKey("pois.id", ondelete="SET NULL"), nullable=True)
    chain_id     = Column(UUID(as_uuid=True), ForeignKey("maintenance_lookups.id", ondelete="SET NULL"), nullable=True)
    phone        = Column(String(50), nullable=True)
    working_hours = Column(String(200), nullable=True)               # e.g. "Mon–Fri 07:30–17:00, Sat 08:00–12:00"
    image_data   = Column(Text, nullable=True)                       # photo as a data URL (≤ 600 KB)
    type_ids     = Column(JSON, nullable=False, default=list)        # workshop_type lookups
    created_at   = Column(DateTime(timezone=True), server_default=func.now())


class VehicleMaintenance(Base):
    __tablename__ = "vehicle_maintenance"
    __table_args__ = (
        Index("ix_vehicle_maintenance_group_planned", "usergroup_id", "planned_start"),
        Index("ix_vehicle_maintenance_schedule_vehicle", "schedule_id", "imei"),
    )

    id             = get_uuid_column()
    usergroup_id   = _group()
    imei           = Column(String(20), nullable=False)
    description    = Column(String(200), nullable=False)
    type_id        = Column(UUID(as_uuid=True), ForeignKey("maintenance_types.id", ondelete="SET NULL"), nullable=True)
    schedule_id    = Column(UUID(as_uuid=True), ForeignKey("maintenance_schedules.id", ondelete="SET NULL"), nullable=True)
    planned_start  = Column(DateTime(timezone=True), nullable=False)
    planned_end    = Column(DateTime(timezone=True), nullable=True)
    actual_start   = Column(DateTime(timezone=True), nullable=True)
    actual_end     = Column(DateTime(timezone=True), nullable=True)
    odometer_km    = Column(Integer, nullable=True)                  # at the job (sets the next km threshold)
    engine_hours   = Column(Float, nullable=True)                    # at the job (sets the next hours threshold)
    workshop_id    = Column(UUID(as_uuid=True), ForeignKey("workshops.id", ondelete="SET NULL"), nullable=True)
    reference      = Column(String(100), nullable=True)
    notes          = Column(Text, nullable=True)
    created_by     = Column(String(255), nullable=True)
    created_at     = Column(DateTime(timezone=True), server_default=func.now())
    updated_at     = Column(DateTime(timezone=True), onupdate=func.now())


class MaintenanceCost(Base):
    __tablename__ = "maintenance_costs"
    __table_args__ = (Index("ix_maintenance_costs_group_date", "usergroup_id", "cost_date"),)

    id              = get_uuid_column()
    usergroup_id    = _group()
    imei            = Column(String(20), nullable=False)
    cost_date       = Column(Date, nullable=False)
    maintenance_id  = Column(UUID(as_uuid=True), ForeignKey("vehicle_maintenance.id", ondelete="SET NULL"), nullable=True)
    item_id         = Column(UUID(as_uuid=True), ForeignKey("maintenance_items.id", ondelete="SET NULL"), nullable=True)
    cost_centre_id  = Column(UUID(as_uuid=True), ForeignKey("maintenance_lookups.id", ondelete="SET NULL"), nullable=True)
    description     = Column(String(200), nullable=True)
    category        = Column(String(20), nullable=False, default="maintenance")   # COST_CATEGORIES
    amount          = Column(Numeric(12, 2), nullable=False)
    amortise_from   = Column(Date, nullable=True)
    amortise_to     = Column(Date, nullable=True)
    created_at      = Column(DateTime(timezone=True), server_default=func.now())


class MaintenanceNotice(Base):
    """A due / overdue notification sent for one occurrence of a schedule on a vehicle."""
    __tablename__ = "maintenance_notices"

    id           = Column(BigInteger, primary_key=True, autoincrement=True)
    usergroup_id = _group()
    occurrence   = Column(String(200), nullable=False, unique=True)   # schedule:imei:threshold:status
    sent_at      = Column(DateTime(timezone=True), server_default=func.now())


class VehicleBreakdown(Base):
    """A breakdown a driver logs in the mobile app (Assets → vehicle → Log breakdown).

    It runs as a "Breakdown" maintenance job (job_id), so the vehicle shows in the
    workshop on the Overview and in the Maintenance List while it lasts. Here are
    the parts a job doesn't have: who logged it, where the phone was, the phases
    the driver went through, and the manager's review. The tracker evidence (did
    the vehicle move, was the ignition on) is worked out from its data, see
    app/services/breakdown_service.py.
    """
    __tablename__ = "vehicle_breakdowns"

    id             = get_uuid_column()
    usergroup_id   = _group()
    imei           = Column(String(20), nullable=False, index=True)
    job_id         = Column(UUID(as_uuid=True), ForeignKey("vehicle_maintenance.id", ondelete="SET NULL"), nullable=True)
    reported_by_id = Column(UUID(as_uuid=True), nullable=True)            # portal user who logged it
    reported_by    = Column(String(255), nullable=True)                   # their name when they logged it
    driver         = Column(String(200), nullable=True)                   # the vehicle's assigned driver then
    cause          = Column(String(60), nullable=True)                    # BREAKDOWN_CAUSES
    started_at     = Column(DateTime(timezone=True), nullable=False)
    ended_at       = Column(DateTime(timezone=True), nullable=True)
    start_lat      = Column(Float, nullable=True)                         # the phone's position
    start_lng      = Column(Float, nullable=True)
    start_accuracy = Column(Float, nullable=True)                         # metres
    end_lat        = Column(Float, nullable=True)
    end_lng        = Column(Float, nullable=True)
    phases         = Column(JSON, nullable=False, default=list)           # [{phase, at, lat, lng}]
    notes          = Column(Text, nullable=True)                          # the driver's, when resolving
    review         = Column(String(20), nullable=True)                    # accepted | disputed
    review_note    = Column(Text, nullable=True)
    reviewed_by    = Column(String(255), nullable=True)
    created_at     = Column(DateTime(timezone=True), server_default=func.now())

    __table_args__ = (Index("ix_breakdown_group_started", "usergroup_id", "started_at"),)
