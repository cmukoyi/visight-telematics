"""Maintenance: system items, workshop working hours and image.

Revision ID: 082_maintenance_brief
Revises: 081_vehicle_maintenance
Create Date: 2026-10-24
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy import text

revision = "082_maintenance_brief"
down_revision = "081_vehicle_maintenance"
branch_labels = None
depends_on = None

STARTER_ITEMS = ["Change engine oil", "Replace oil filter", "Replace air filter", "Replace fuel filter",
                 "Check brakes", "Rotate tyres", "Wheel alignment", "Check lights", "Licence renewal"]


def _has_column(table, column):
    return op.get_bind().execute(text(
        "SELECT 1 FROM information_schema.columns WHERE table_name = :t AND column_name = :c"),
        {"t": table, "c": column}).first() is not None


def upgrade():
    if not _has_column("maintenance_items", "is_system"):
        op.add_column("maintenance_items", sa.Column("is_system", sa.Boolean(), nullable=False, server_default=sa.false()))
        op.get_bind().execute(text("UPDATE maintenance_items SET is_system = true WHERE name = ANY(:n)"), {"n": STARTER_ITEMS})
    if not _has_column("workshops", "working_hours"):
        op.add_column("workshops", sa.Column("working_hours", sa.String(200), nullable=True))
    if not _has_column("workshops", "image_data"):
        op.add_column("workshops", sa.Column("image_data", sa.Text(), nullable=True))


def downgrade():
    for table, column in (("workshops", "image_data"), ("workshops", "working_hours"), ("maintenance_items", "is_system")):
        if _has_column(table, column):
            op.drop_column(table, column)
