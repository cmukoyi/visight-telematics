"""add tag_type column to ble_tags for multi-provider BLE tag support

Revision ID: 012
Revises: 011_make_verification_pin_user_id_nullable
Create Date: 2026-03-21

Adds a tag_type column to ble_tags so each tag knows which vendor
platform it belongs to (e.g. 'tracksolid', 'scope').

Existing rows default to 'scope' to maintain backwards compatibility
with the MZone / Scope integration that was in place before this change.
"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '012'
down_revision = '011'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        'ble_tags',
        sa.Column(
            'tag_type',
            sa.String(50),
            nullable=True,
            server_default='scope',
        )
    )
    # Back-fill existing rows so the column is consistent
    op.execute("UPDATE ble_tags SET tag_type = 'scope' WHERE tag_type IS NULL")


def downgrade():
    op.drop_column('ble_tags', 'tag_type')
