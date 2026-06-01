"""make ble_tags.user_id nullable for public QR assets

Revision ID: 042_nullable_user_id_for_qr
Revises: 041_rollback_asset_tables
Create Date: 2026-06-01 21:00:00.000000

Series 3 QR/NFC assets are public (no user authentication when scanning),
so they need user_id to be nullable. Series 1 and 2 tags still require a user.
"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '042_nullable_user_id_for_qr'
down_revision = '041_rollback_asset_tables'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Make user_id nullable so QR assets (series_3) can exist without a user
    op.alter_column('ble_tags', 'user_id',
                    existing_type=sa.UUID(),
                    nullable=True)


def downgrade() -> None:
    # Revert user_id to NOT NULL
    # Note: This will fail if there are series_3 tags with NULL user_id
    op.alter_column('ble_tags', 'user_id',
                    existing_type=sa.UUID(),
                    nullable=False)
