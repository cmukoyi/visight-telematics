"""DataProfiler: unit types, package validity in months, drop reseller provider.

Revision ID: 063_dataprofiler_unit_types
Revises: 062_add_dataprofiler
Create Date: 2026-10-21

Existing day-based packages keep validity_days (now nullable) until an admin
edits them; new packages store validity_months.
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy import text
from sqlalchemy.dialects.postgresql import UUID

revision = "063_dataprofiler_unit_types"
down_revision = "062_add_dataprofiler"
branch_labels = None
depends_on = None


def _table_exists(conn, table_name: str) -> bool:
    return conn.execute(
        text("SELECT EXISTS (SELECT 1 FROM information_schema.tables WHERE table_name = :t)"),
        {"t": table_name},
    ).scalar()


def _column_exists(conn, table_name: str, column_name: str) -> bool:
    return conn.execute(
        text("SELECT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name = :t AND column_name = :c)"),
        {"t": table_name, "c": column_name},
    ).scalar()


def upgrade():
    conn = op.get_bind()

    if not _column_exists(conn, "tag_packages", "validity_months"):
        op.add_column("tag_packages", sa.Column("validity_months", sa.Integer(), nullable=True))
    op.alter_column("tag_packages", "validity_days", existing_type=sa.Integer(), nullable=True)

    if not _table_exists(conn, "unit_types"):
        op.create_table(
            "unit_types",
            sa.Column("id", UUID(as_uuid=True), primary_key=True),
            sa.Column("manufacturer", sa.String(100), nullable=False),
            sa.Column("model", sa.String(100), nullable=False),
            sa.Column("description", sa.Text(), nullable=True),
            sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        )
    op.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS uq_unit_types_manufacturer_model "
        "ON unit_types (manufacturer, model)"
    )

    if not _column_exists(conn, "reseller_devices", "unit_type_id"):
        op.add_column("reseller_devices", sa.Column(
            "unit_type_id", UUID(as_uuid=True), sa.ForeignKey("unit_types.id"), nullable=True))
    if _column_exists(conn, "reseller_devices", "device_model"):
        op.drop_column("reseller_devices", "device_model")
    if _column_exists(conn, "resellers", "provider"):
        op.drop_column("resellers", "provider")


def downgrade():
    conn = op.get_bind()
    op.add_column("resellers", sa.Column("provider", sa.String(50), nullable=False, server_default="teltonika"))
    op.add_column("reseller_devices", sa.Column("device_model", sa.String(100), nullable=True))
    op.drop_column("reseller_devices", "unit_type_id")
    op.drop_table("unit_types")
    # Month-based packages need a day value before validity_days can be NOT NULL again.
    conn.execute(text(
        "UPDATE tag_packages SET validity_days = validity_months * 30 "
        "WHERE validity_days IS NULL AND validity_months IS NOT NULL"
    ))
    op.alter_column("tag_packages", "validity_days", existing_type=sa.Integer(), nullable=False)
    op.drop_column("tag_packages", "validity_months")
