"""Notification rules and per-vehicle geofence state.

Revision ID: 069_add_notification_rules
Revises: 068_add_access_control
Create Date: 2026-10-22
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy import text
from sqlalchemy.dialects.postgresql import UUID

revision = "069_add_notification_rules"
down_revision = "068_add_access_control"
branch_labels = None
depends_on = None


def _has_table(conn, name):
    return conn.execute(text("SELECT to_regclass(:n) IS NOT NULL"), {"n": name}).scalar()


def upgrade():
    conn = op.get_bind()
    if not _has_table(conn, "notification_rules"):
        op.create_table(
            "notification_rules",
            sa.Column("id", UUID(as_uuid=True), primary_key=True),
            sa.Column("usergroup_id", UUID(as_uuid=True), sa.ForeignKey("user_groups.id", ondelete="CASCADE"), nullable=False, index=True),
            sa.Column("name", sa.String(120), nullable=False),
            sa.Column("rule_type", sa.String(30), nullable=False, server_default="geofence"),
            sa.Column("category", sa.String(100), nullable=True),
            sa.Column("place_ids", sa.JSON(), nullable=True),
            sa.Column("on_entry", sa.Boolean(), nullable=False, server_default=sa.true()),
            sa.Column("on_exit", sa.Boolean(), nullable=False, server_default=sa.true()),
            sa.Column("email_enabled", sa.Boolean(), nullable=False, server_default=sa.false()),
            sa.Column("email_recipients", sa.JSON(), nullable=True),
            sa.Column("email_message", sa.Text(), nullable=True),
            sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
            sa.Column("created_by", UUID(as_uuid=True), sa.ForeignKey("portal_users.id", ondelete="SET NULL"), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        )
    if not _has_table(conn, "geofence_states"):
        op.create_table(
            "geofence_states",
            sa.Column("tag_id", UUID(as_uuid=True), sa.ForeignKey("ble_tags.id", ondelete="CASCADE"), primary_key=True),
            sa.Column("poi_id", UUID(as_uuid=True), sa.ForeignKey("pois.id", ondelete="CASCADE"), primary_key=True),
            sa.Column("inside", sa.Boolean(), nullable=False),
            sa.Column("checked_at", sa.DateTime(timezone=True), nullable=False),
        )


def downgrade():
    op.drop_table("geofence_states")
    op.drop_table("notification_rules")
