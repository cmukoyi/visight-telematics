"""Add sensor data columns to device_position table

Revision ID: 043
Revises: 042
Create Date: 2026-08-22 12:00:00.000000

Purpose: Add temperature, battery_pct, altitude, and rssi columns to device_positions
         table to support Series 5 (Hubble/Minew) sensor history tracking.
         
         These columns are nullable because TrackSolid positions won't have sensor data,
         only Hubble webhook positions will populate them.
"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '043'
down_revision = '042'
branch_labels = None
depends_on = None


def upgrade():
    # Add sensor data columns (nullable for TrackSolid positions)
    op.add_column('device_positions', sa.Column('temperature', sa.Float(), nullable=True, comment='°C (canonical, always Celsius)'))
    op.add_column('device_positions', sa.Column('battery_pct', sa.Integer(), nullable=True, comment='% (0-100)'))
    op.add_column('device_positions', sa.Column('altitude', sa.Float(), nullable=True, comment='meters (canonical)'))
    op.add_column('device_positions', sa.Column('rssi', sa.Integer(), nullable=True, comment='dBm (signal strength)'))


def downgrade():
    # Remove sensor data columns
    op.drop_column('device_positions', 'rssi')
    op.drop_column('device_positions', 'altitude')
    op.drop_column('device_positions', 'battery_pct')
    op.drop_column('device_positions', 'temperature')
