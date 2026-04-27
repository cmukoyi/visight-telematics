"""add attributes column to ble_tags for custom field storage

Revision ID: 010
Revises: add_admin_models
Create Date: 2026-03-12

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '010'
down_revision = 'add_admin_models'
branch_labels = None
depends_on = None


def upgrade():
    # Add attributes column to ble_tags table for storing custom attributes
    # Stores JSON data like: {"job_accessories": {"value": "...", "show_on_map": true}, ...}
    op.add_column('ble_tags', sa.Column('attributes', sa.JSON(), nullable=True, server_default='{}'))


def downgrade():
    # Remove attributes column from ble_tags table
    op.drop_column('ble_tags', 'attributes')
