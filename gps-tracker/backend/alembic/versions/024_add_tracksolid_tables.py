"""add tracksolid_devices and tracksolid_locations tables

Revision ID: 024
Revises: 023
Create Date: 2026-05-22

Separates TrackSolid data into two tables:
- tracksolid_devices: Static metadata (IMEI, name, model, SIM)
- tracksolid_locations: Location history (lat/lng, battery, speed)

Also adds api_tokens table for caching OAuth access tokens.
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy import text

revision = "024"
down_revision = "023"
branch_labels = None
depends_on = None


def _table_exists(conn, table_name: str) -> bool:
    result = conn.execute(
        text(
            "SELECT EXISTS (SELECT FROM information_schema.tables "
            "WHERE table_name = :table_name)"
        ),
        {"table_name": table_name},
    )
    return result.scalar()


def upgrade():
    conn = op.get_bind()
    
    # ── 1. tracksolid_devices (static metadata) ──────────────────────────────
    if not _table_exists(conn, "tracksolid_devices"):
        op.create_table(
            "tracksolid_devices",
            sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
            sa.Column("imei", sa.String(20), unique=True, nullable=False, index=True),
            sa.Column("device_name", sa.String(100), nullable=True),
            sa.Column("mc_type", sa.String(50), nullable=True),
            sa.Column("sim", sa.String(50), nullable=True),
            sa.Column("vehicle_number", sa.String(50), nullable=True),
            sa.Column("driver_name", sa.String(100), nullable=True),
            sa.Column("driver_phone", sa.String(50), nullable=True),
            sa.Column("activation_time", sa.DateTime(timezone=True), nullable=True),
            sa.Column("expiration", sa.DateTime(timezone=True), nullable=True),
            sa.Column("enabled_flag", sa.SmallInteger, nullable=False, server_default="1"),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
            sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), onupdate=sa.func.now()),
        )
    
    # ── 2. tracksolid_locations (telemetry history) ───────────────────────────
    if not _table_exists(conn, "tracksolid_locations"):
        op.create_table(
            "tracksolid_locations",
            sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
            sa.Column("imei", sa.String(20), nullable=False, index=True),
            sa.Column("lat", sa.Double, nullable=True),
            sa.Column("lng", sa.Double, nullable=True),
            sa.Column("speed", sa.String(10), nullable=True),
            sa.Column("acc_status", sa.String(5), nullable=True),
            sa.Column("gps_time", sa.DateTime(timezone=True), nullable=True),
            sa.Column("hb_time", sa.DateTime(timezone=True), nullable=True),
            sa.Column("pos_type", sa.String(10), nullable=True),
            sa.Column("battery", sa.String(10), nullable=True),
            sa.Column("gps_signal", sa.String(5), nullable=True),
            sa.Column("status", sa.String(5), nullable=True),
            sa.Column("recorded_at", sa.DateTime(timezone=True), server_default=sa.func.now(), index=True),
        )
    
    # ── 3. api_tokens (OAuth token cache) ─────────────────────────────────────
    if not _table_exists(conn, "api_tokens"):
        op.create_table(
            "api_tokens",
            sa.Column("id", sa.Integer, primary_key=True, server_default="1"),
            sa.Column("provider", sa.String(50), nullable=False, unique=True),  # 'tracksolid_open_api'
            sa.Column("access_token", sa.String(200), nullable=True),
            sa.Column("refresh_token", sa.String(200), nullable=True),
            sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), onupdate=sa.func.now()),
        )


def downgrade():
    op.drop_table("tracksolid_locations")
    op.drop_table("tracksolid_devices")
    op.drop_table("api_tokens")
