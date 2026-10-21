"""DataProfiler: device_events — the dashboard's permanent copy of delivered events.

Revision ID: 064_add_device_events
Revises: 063_dataprofiler_unit_types
Create Date: 2026-10-22
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy import text
from sqlalchemy.dialects.postgresql import UUID, JSONB

revision = "064_add_device_events"
down_revision = "063_dataprofiler_unit_types"
branch_labels = None
depends_on = None


def upgrade():
    conn = op.get_bind()
    exists = conn.execute(text(
        "SELECT EXISTS (SELECT 1 FROM information_schema.tables WHERE table_name = 'device_events')"
    )).scalar()
    if not exists:
        op.create_table(
            "device_events",
            sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
            sa.Column("dp_event_id", sa.BigInteger(), nullable=False, unique=True),
            sa.Column("imei", sa.String(20), nullable=False),
            sa.Column("usergroup_id", UUID(as_uuid=True), sa.ForeignKey("user_groups.id"), nullable=True),
            sa.Column("recorded_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("received_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("event_type", sa.String(32), nullable=True),
            sa.Column("event_io_id", sa.Integer(), nullable=False),
            sa.Column("priority", sa.Integer(), nullable=True),
            sa.Column("latitude", sa.Float(), nullable=True),
            sa.Column("longitude", sa.Float(), nullable=True),
            sa.Column("altitude", sa.Integer(), nullable=True),
            sa.Column("angle", sa.Integer(), nullable=True),
            sa.Column("satellites", sa.Integer(), nullable=True),
            sa.Column("speed", sa.Integer(), nullable=True),
            sa.Column("io", JSONB(), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        )
    op.execute("CREATE INDEX IF NOT EXISTS ix_device_events_imei_time ON device_events (imei, recorded_at)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_device_events_group_time ON device_events (usergroup_id, recorded_at)")


def downgrade():
    op.drop_table("device_events")
