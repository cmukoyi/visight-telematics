"""add location_description to ble_tags

Revision ID: 008
Revises: 007
Create Date: 2026-03-11

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '008'
down_revision = '007'
branch_labels = None
depends_on = None


def upgrade():
    # Add location_description column to ble_tags table
    op.add_column('ble_tags', sa.Column('location_description', sa.String(length=500), nullable=True))


def downgrade():
    # Remove location_description column from ble_tags table
    op.drop_column('ble_tags', 'location_description')
