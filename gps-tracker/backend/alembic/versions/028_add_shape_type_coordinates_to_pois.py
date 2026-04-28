"""Add shape_type and coordinates columns to pois table for drawn geofences.

Revision ID: 028
Revises: 027
Create Date: 2025-01-01
"""
from alembic import op
import sqlalchemy as sa

revision = '028'
down_revision = '027'
branch_labels = None
depends_on = None


def column_exists(table_name, column_name):
    bind = op.get_bind()
    insp = sa.inspect(bind)
    return column_name in [c["name"] for c in insp.get_columns(table_name)]


def upgrade():
    # shape_type: 'circle' | 'polygon' | 'rectangle' — defaults to 'circle'
    if not column_exists('pois', 'shape_type'):
        op.add_column('pois', sa.Column(
            'shape_type', sa.String(20), nullable=False,
            server_default='circle'
        ))

    # coordinates: JSON string storing [[lat,lng], ...] for polygon/rectangle shapes
    if not column_exists('pois', 'coordinates'):
        op.add_column('pois', sa.Column(
            'coordinates', sa.Text(), nullable=True
        ))

    # notes: free-text notes about the location (optional)
    if not column_exists('pois', 'notes'):
        op.add_column('pois', sa.Column(
            'notes', sa.Text(), nullable=True
        ))


def downgrade():
    op.drop_column('pois', 'notes')
    op.drop_column('pois', 'coordinates')
    op.drop_column('pois', 'shape_type')
