"""Trips built from Teltonika events, and a link from each device event to its trip.

Revision ID: 066_add_trips
Revises: 065_remove_legacy_integrations
Create Date: 2026-10-22
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy import text
from sqlalchemy.dialects.postgresql import UUID

revision = "066_add_trips"
down_revision = "065_remove_legacy_integrations"
branch_labels = None
depends_on = None


def _table_exists(conn, name: str) -> bool:
    return conn.execute(text(
        "SELECT EXISTS (SELECT 1 FROM information_schema.tables WHERE table_name = :t)"), {"t": name}).scalar()


def upgrade():
    conn = op.get_bind()
    if not _table_exists(conn, "trips"):
        op.create_table(
            "trips",
            sa.Column("id", UUID(as_uuid=True), primary_key=True),
            sa.Column("imei", sa.String(20), nullable=False),
            sa.Column("usergroup_id", UUID(as_uuid=True), sa.ForeignKey("user_groups.id"), nullable=True),
            sa.Column("status", sa.String(10), nullable=False, server_default="open"),
            sa.Column("start_reason", sa.String(20), nullable=False),
            sa.Column("close_reason", sa.String(20), nullable=True),
            sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("ended_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("last_event_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("start_latitude", sa.Float(), nullable=True),
            sa.Column("start_longitude", sa.Float(), nullable=True),
            sa.Column("end_latitude", sa.Float(), nullable=True),
            sa.Column("end_longitude", sa.Float(), nullable=True),
            sa.Column("start_odometer_m", sa.BigInteger(), nullable=True),
            sa.Column("end_odometer_m", sa.BigInteger(), nullable=True),
            sa.Column("distance_m", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("duration_s", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("max_speed", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("avg_speed", sa.Float(), nullable=True),
            sa.Column("point_count", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("speeding_count", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("harsh_acceleration_count", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("harsh_braking_count", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("harsh_cornering_count", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("idling_count", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        )
    op.execute("CREATE INDEX IF NOT EXISTS ix_trips_imei_started ON trips (imei, started_at)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_trips_group_started ON trips (usergroup_id, started_at)")

    if not _table_exists(conn, "trip_builder_state"):
        op.create_table(
            "trip_builder_state",
            sa.Column("imei", sa.String(20), primary_key=True),
            sa.Column("last_event_id", sa.BigInteger(), nullable=False, server_default="0"),
            sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        )

    op.execute("ALTER TABLE device_events ADD COLUMN IF NOT EXISTS trip_id UUID REFERENCES trips(id) ON DELETE SET NULL")
    op.execute("CREATE INDEX IF NOT EXISTS ix_device_events_trip ON device_events (trip_id)")


def downgrade():
    op.execute("ALTER TABLE device_events DROP COLUMN IF EXISTS trip_id")
    op.drop_table("trip_builder_state")
    op.drop_table("trips")
