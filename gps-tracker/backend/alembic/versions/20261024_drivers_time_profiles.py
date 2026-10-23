"""Drivers, time profiles (working hours) and the trip's driver.

Existing free-text drivers on vehicles (attributes.driver) become driver
records, linked to their vehicles (attributes.driver_id).

Revision ID: 083_drivers_time_profiles
Revises: 082_maintenance_brief
Create Date: 2026-10-24
"""
import json
import uuid

from alembic import op
import sqlalchemy as sa
from sqlalchemy import text
from sqlalchemy.dialects.postgresql import UUID

revision = "083_drivers_time_profiles"
down_revision = "082_maintenance_brief"
branch_labels = None
depends_on = None


def _has_table(name):
    return op.get_bind().execute(text("SELECT to_regclass(:n) IS NOT NULL"), {"n": name}).scalar()


def _has_column(table, column):
    return op.get_bind().execute(text(
        "SELECT 1 FROM information_schema.columns WHERE table_name = :t AND column_name = :c"),
        {"t": table, "c": column}).first() is not None


def upgrade():
    conn = op.get_bind()
    if not _has_table("drivers"):
        op.create_table(
            "drivers",
            sa.Column("id", UUID(as_uuid=True), primary_key=True),
            sa.Column("usergroup_id", UUID(as_uuid=True), sa.ForeignKey("user_groups.id", ondelete="CASCADE"), nullable=False, index=True),
            sa.Column("first_name", sa.String(100), nullable=False),
            sa.Column("last_name", sa.String(100), nullable=True),
            sa.Column("employee_number", sa.String(50), nullable=True),
            sa.Column("key_code", sa.String(40), nullable=True),
            sa.Column("phone", sa.String(50), nullable=True),
            sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        )
    if not _has_table("time_profiles"):
        op.create_table(
            "time_profiles",
            sa.Column("id", UUID(as_uuid=True), primary_key=True),
            sa.Column("usergroup_id", UUID(as_uuid=True), sa.ForeignKey("user_groups.id", ondelete="CASCADE"), nullable=False, index=True),
            sa.Column("name", sa.String(120), nullable=False),
            sa.Column("windows", sa.JSON(), nullable=False),
            sa.Column("is_default", sa.Boolean(), nullable=False, server_default=sa.false()),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        )
    if _has_table("trips") and not _has_column("trips", "driver_id"):
        op.add_column("trips", sa.Column("driver_id", UUID(as_uuid=True), sa.ForeignKey("drivers.id", ondelete="SET NULL"), nullable=True))

    # Free-text drivers on vehicles → driver records
    made = {}
    for tag_id, attrs in conn.execute(text("SELECT id, attributes FROM ble_tags WHERE attributes IS NOT NULL")).all():
        attrs = attrs if isinstance(attrs, dict) else json.loads(attrs or "{}")
        name = ((attrs.get("driver") or {}).get("value") or "").strip() if isinstance(attrs.get("driver"), dict) else ""
        group = attrs.get("_created_usergroup_id")
        if not name or not group or attrs.get("driver_id"):
            continue
        key = (group, name.lower())
        if key not in made:
            first, _, last = name.partition(" ")   # "Peter van der Merwe" → Peter / van der Merwe
            made[key] = str(uuid.uuid4())
            conn.execute(text("INSERT INTO drivers (id, usergroup_id, first_name, last_name, is_active) VALUES (:i, :g, :f, :l, true)"),
                         {"i": made[key], "g": group, "f": first or name, "l": last or None})
        attrs["driver_id"] = {"value": made[key]}
        conn.execute(text("UPDATE ble_tags SET attributes = CAST(:a AS json) WHERE id = :i"), {"a": json.dumps(attrs), "i": tag_id})


def downgrade():
    if _has_column("trips", "driver_id"):
        op.drop_column("trips", "driver_id")
    for t in ("time_profiles", "drivers"):
        if _has_table(t):
            op.drop_table(t)
