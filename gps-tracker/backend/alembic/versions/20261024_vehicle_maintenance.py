"""Vehicle Maintenance: lookups, items, types, schedules, workshops, jobs, costs and sent notices.

Revision ID: 081_vehicle_maintenance
Revises: 080_rebuild_place_visits
Create Date: 2026-10-24
"""
from alembic import op

revision = "081_vehicle_maintenance"
down_revision = "080_rebuild_place_visits"
branch_labels = None
depends_on = None


def _tables():
    from app import models_maintenance as m
    # In dependency order (lookups and types before what points at them)
    return [m.MaintenanceLookup.__table__, m.MaintenanceItem.__table__, m.MaintenanceType.__table__,
            m.MaintenanceSchedule.__table__, m.Workshop.__table__, m.VehicleMaintenance.__table__,
            m.MaintenanceCost.__table__, m.MaintenanceNotice.__table__]


def upgrade():
    bind = op.get_bind()
    for table in _tables():
        table.create(bind, checkfirst=True)


def downgrade():
    bind = op.get_bind()
    for table in reversed(_tables()):
        table.drop(bind, checkfirst=True)
