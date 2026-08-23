"""Add sensor data columns to device_position table

Revision ID: add_sensor_data
Revises: tracksolid_composite_idx
Create Date: 2026-08-22 12:00:00.000000

Purpose: Add temperature, battery_pct, altitude, and rssi columns to device_positions
         table to support Series 5 (Hubble/Minew) sensor history tracking.
         
         These columns are nullable because TrackSolid positions won't have sensor data,
         only Hubble webhook positions will populate them.
"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'add_sensor_data'
down_revision = 'tracksolid_composite_idx'
branch_labels = None
depends_on = None


def upgrade():
    # Check if columns already exist (idempotent migration)
    connection = op.get_bind()
    inspector = sa.inspect(connection)
    existing_columns = {col['name'] for col in inspector.get_columns('device_positions')}
    
    # Add sensor data columns only if they don't exist
    if 'temperature' not in existing_columns:
        op.add_column('device_positions', sa.Column('temperature', sa.Float(), nullable=True, comment='°C (canonical, always Celsius)'))
    if 'battery_pct' not in existing_columns:
        op.add_column('device_positions', sa.Column('battery_pct', sa.Integer(), nullable=True, comment='% (0-100)'))
    if 'altitude' not in existing_columns:
        op.add_column('device_positions', sa.Column('altitude', sa.Float(), nullable=True, comment='meters (canonical)'))
    if 'rssi' not in existing_columns:
        op.add_column('device_positions', sa.Column('rssi', sa.Integer(), nullable=True, comment='dBm (signal strength)'))


def downgrade():
    # Remove sensor data columns
    op.drop_column('device_positions', 'rssi')
    op.drop_column('device_positions', 'altitude')
    op.drop_column('device_positions', 'battery_pct')
    op.drop_column('device_positions', 'temperature')
