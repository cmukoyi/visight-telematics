"""Add gdpr_deletion_warned_at column to ble_tags.

Records the timestamp when the 7-day GDPR deletion warning was sent for a tag
whose subscription has expired. NULL means no warning has been sent yet.
The daily cleanup loop uses this to ensure the notification fires exactly once,
then hard-deletes the tag and all associated data 7 days after expiry_date.

Revision ID: 030
Revises: 029
Create Date: 2026-04-30
"""
from alembic import op
import sqlalchemy as sa

revision = "030"
down_revision = "029"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        "ble_tags",
        sa.Column("gdpr_deletion_warned_at", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade():
    op.drop_column("ble_tags", "gdpr_deletion_warned_at")
