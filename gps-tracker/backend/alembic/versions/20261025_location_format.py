"""Location description format per user group; address parts in the geocode cache.

Revision ID: 086_location_format
Revises: 085_custom_reports
Create Date: 2026-10-25
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy import text

revision = "086_location_format"
down_revision = "085_custom_reports"
branch_labels = None
depends_on = None


def _has_column(table, column):
    return op.get_bind().execute(text(
        "SELECT 1 FROM information_schema.columns WHERE table_name = :t AND column_name = :c"),
        {"t": table, "c": column}).first() is not None


def upgrade():
    if not _has_column("user_groups", "location_format"):
        op.add_column("user_groups", sa.Column("location_format", sa.JSON(), nullable=True))
    if not _has_column("geocode_cache", "parts"):
        op.add_column("geocode_cache", sa.Column("parts", sa.JSON(), nullable=True))


def downgrade():
    op.drop_column("geocode_cache", "parts")
    op.drop_column("user_groups", "location_format")
