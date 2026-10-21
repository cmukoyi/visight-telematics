"""DataProfiler: resellers, data exchanges, reseller devices, package event filters.

Revision ID: 062_add_dataprofiler
Revises: 061_tag_categories_uuid_fk
Create Date: 2026-10-21
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy import text
from sqlalchemy.dialects.postgresql import UUID

revision = "062_add_dataprofiler"
down_revision = "061_tag_categories_uuid_fk"
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

    if not _column_exists(conn, "tag_packages", "allowed_event_types"):
        op.add_column("tag_packages", sa.Column("allowed_event_types", sa.JSON(), nullable=True))

    # init_db() may already have created these tables on startup.
    if not _table_exists(conn, "resellers"):
        op.create_table(
            "resellers",
            sa.Column("id", UUID(as_uuid=True), primary_key=True),
            sa.Column("name", sa.String(200), nullable=False, unique=True),
            sa.Column("code", sa.String(50), nullable=False, unique=True),
            sa.Column("provider", sa.String(50), nullable=False, server_default="teltonika"),
            sa.Column("contact_name", sa.String(200), nullable=True),
            sa.Column("contact_email", sa.String(255), nullable=True),
            sa.Column("contact_phone", sa.String(50), nullable=True),
            sa.Column("notes", sa.Text(), nullable=True),
            sa.Column("default_package_id", UUID(as_uuid=True), sa.ForeignKey("tag_packages.id"), nullable=True),
            sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        )

    if not _table_exists(conn, "data_exchanges"):
        op.create_table(
            "data_exchanges",
            sa.Column("id", UUID(as_uuid=True), primary_key=True),
            sa.Column("reseller_id", UUID(as_uuid=True), sa.ForeignKey("resellers.id"), nullable=False),
            sa.Column("exchange_key", sa.String(64), nullable=False),
            sa.Column("secret_hash", sa.String(255), nullable=False),
            sa.Column("usergroup_id", UUID(as_uuid=True), sa.ForeignKey("user_groups.id"), nullable=True),
            sa.Column("status", sa.String(20), nullable=False, server_default="pending"),
            sa.Column("linked_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("linked_by", sa.String(255), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        )
        op.create_index("ix_data_exchanges_exchange_key", "data_exchanges", ["exchange_key"], unique=True)

    # Enforce the 1:1 mappings at the DB level, including tables created by init_db().
    op.execute("CREATE UNIQUE INDEX IF NOT EXISTS uq_data_exchanges_reseller ON data_exchanges (reseller_id)")
    op.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS uq_data_exchanges_usergroup "
        "ON data_exchanges (usergroup_id) WHERE usergroup_id IS NOT NULL"
    )

    if not _table_exists(conn, "reseller_devices"):
        op.create_table(
            "reseller_devices",
            sa.Column("id", UUID(as_uuid=True), primary_key=True),
            sa.Column("reseller_id", UUID(as_uuid=True), sa.ForeignKey("resellers.id"), nullable=False),
            sa.Column("imei", sa.String(50), nullable=False),
            sa.Column("label", sa.String(100), nullable=True),
            sa.Column("device_model", sa.String(100), nullable=True),
            sa.Column("package_id", UUID(as_uuid=True), sa.ForeignKey("tag_packages.id"), nullable=True),
            sa.Column("status", sa.String(20), nullable=False, server_default="pending"),
            sa.Column("status_detail", sa.String(255), nullable=True),
            sa.Column("ble_tag_id", UUID(as_uuid=True),
                      sa.ForeignKey("ble_tags.id", ondelete="SET NULL"), nullable=True),
            sa.Column("first_routed_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("last_event_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        )
        op.create_index("ix_reseller_devices_imei", "reseller_devices", ["imei"], unique=True)
    op.execute("CREATE INDEX IF NOT EXISTS ix_reseller_devices_reseller ON reseller_devices (reseller_id)")


def downgrade():
    op.drop_table("reseller_devices")
    op.drop_table("data_exchanges")
    op.drop_table("resellers")
    op.drop_column("tag_packages", "allowed_event_types")
