"""Breakdown alerts can happen more than once a day for a vehicle (exempt them from uq_portal_alert_per_day).

The second breakdown logged for a vehicle on the same day failed: its inbox
alert broke the one-alert-per-vehicle-per-type-per-day index.

Revision ID: 088_breakdown_alerts_per_day
Revises: 087_vehicle_breakdowns
Create Date: 2026-10-27
"""
from alembic import op

revision = "088_breakdown_alerts_per_day"
down_revision = "087_vehicle_breakdowns"
branch_labels = None
depends_on = None


def upgrade():
    op.execute("DROP INDEX IF EXISTS uq_portal_alert_per_day")
    op.execute(
        "CREATE UNIQUE INDEX uq_portal_alert_per_day ON portal_alerts "
        "(usergroup_id, tag_id, alert_type, DATE(created_at AT TIME ZONE 'UTC')) "
        "WHERE tag_id IS NOT NULL AND alert_type NOT IN ('geofence_entry', 'geofence_exit', 'breakdown') "
        "AND alert_type NOT LIKE 'event\\_%'"
    )


def downgrade():
    # (keeps the breakdown exemption: re-adding it could fail on existing rows)
    pass
