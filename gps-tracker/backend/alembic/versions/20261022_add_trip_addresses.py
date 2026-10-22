"""Trip start/end street addresses and a geocode cache.

Revision ID: 070_add_trip_addresses
Revises: 069_add_notification_rules
Create Date: 2026-10-22
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy import text

revision = "070_add_trip_addresses"
down_revision = "069_add_notification_rules"
branch_labels = None
depends_on = None


def upgrade():
    op.execute("ALTER TABLE trips ADD COLUMN IF NOT EXISTS start_address VARCHAR(255)")
    op.execute("ALTER TABLE trips ADD COLUMN IF NOT EXISTS end_address VARCHAR(255)")
    if not op.get_bind().execute(text("SELECT to_regclass('geocode_cache') IS NOT NULL")).scalar():
        op.create_table(
            "geocode_cache",
            sa.Column("lat_e4", sa.Integer(), primary_key=True),
            sa.Column("lng_e4", sa.Integer(), primary_key=True),
            sa.Column("address", sa.String(255), nullable=False),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        )


def downgrade():
    op.drop_table("geocode_cache")
    op.execute("ALTER TABLE trips DROP COLUMN IF EXISTS end_address")
    op.execute("ALTER TABLE trips DROP COLUMN IF EXISTS start_address")
