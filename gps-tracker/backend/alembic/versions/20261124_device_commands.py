"""Device commands: GPRS commands (Teltonika Codec 12) sent to a vehicle's tracker from the portal.

Revision ID: 091_device_commands
Revises: 090_portal_device_tokens
Create Date: 2026-11-24
"""
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import UUID

revision = "091_device_commands"
down_revision = "090_portal_device_tokens"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "device_commands",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("vehicle_id", UUID(as_uuid=True), sa.ForeignKey("ble_tags.id", ondelete="CASCADE"), nullable=False),
        sa.Column("usergroup_id", UUID(as_uuid=True), sa.ForeignKey("user_groups.id", ondelete="CASCADE"), nullable=True),
        sa.Column("imei", sa.String(20), nullable=False),
        sa.Column("command", sa.String(256), nullable=False),
        sa.Column("status", sa.String(12), nullable=False, server_default="queued"),
        sa.Column("created_by", UUID(as_uuid=True), sa.ForeignKey("portal_users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("created_by_name", sa.String(200), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("sent_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("responded_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("response", sa.Text(), nullable=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("error", sa.String(255), nullable=True),
    )
    op.create_index("ix_device_commands_queued", "device_commands", ["imei", "created_at"],
                    postgresql_where=sa.text("status = 'queued'"))
    op.create_index("ix_device_commands_vehicle", "device_commands", ["vehicle_id", "created_at"])


def downgrade():
    op.drop_table("device_commands")
