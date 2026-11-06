"""Device tokens: the mobile app renews its 12-hour access token without the password.

Revision ID: 090_portal_device_tokens
Revises: 089_portal_user_app_version
Create Date: 2026-11-06
"""
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import UUID

revision = "090_portal_device_tokens"
down_revision = "089_portal_user_app_version"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "portal_device_tokens",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("user_id", UUID(as_uuid=True), sa.ForeignKey("portal_users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("token_hash", sa.String(64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("last_used_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_portal_device_tokens_user_id", "portal_device_tokens", ["user_id"])
    op.create_index("ix_portal_device_tokens_token_hash", "portal_device_tokens", ["token_hash"], unique=True)


def downgrade():
    op.drop_table("portal_device_tokens")
