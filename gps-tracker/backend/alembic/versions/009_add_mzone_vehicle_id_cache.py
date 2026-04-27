"""add mzone_vehicle_id cache to ble_tags

Revision ID: 009
Revises: 008
Create Date: 2026-03-11

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '009'
down_revision = '008'
branch_labels = None
depends_on = None


def upgrade():
    # Add mzone_vehicle_id column to ble_tags table
    # This caches the MZone vehicle_Id to avoid repeated IMEI lookups
    op.add_column('ble_tags', sa.Column('mzone_vehicle_id', sa.String(length=100), nullable=True))
    op.create_index('ix_ble_tags_mzone_vehicle_id', 'ble_tags', ['mzone_vehicle_id'], unique=False)


def downgrade():
    # Remove mzone_vehicle_id column from ble_tags table
    op.drop_index('ix_ble_tags_mzone_vehicle_id', table_name='ble_tags')
    op.drop_column('ble_tags', 'mzone_vehicle_id')
