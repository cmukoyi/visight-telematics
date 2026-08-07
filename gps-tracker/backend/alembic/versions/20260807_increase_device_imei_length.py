"""Increase device_imei column length to support Series 5 Hubble UUIDs

Series 5 (Hubble Platform) tags use UUIDs as device identifiers (36 characters),
but the existing device_imei columns were VARCHAR(20), designed for 15-digit IMEIs.

This migration increases device_imei from VARCHAR(20) to VARCHAR(100) across
all tables to support Hubble UUIDs and future device ID formats.

Affected tables:
- device_state (PRIMARY KEY)
- position_history (PRIMARY KEY)
- location_history_row
- tracksolid_track_query
- tracksolid_track_history
- engine_state (PRIMARY KEY)
- stationaries
- legs
- journeys

Revision ID: v2113_series5_imei_length
Revises: v2112_e1_journey_unique
Create Date: 2026-08-07
"""
from alembic import op
import sqlalchemy as sa


revision = 'v2113_series5_imei_length'
down_revision = 'v2112_e1_journey_unique'
branch_labels = None
depends_on = None


def upgrade():
    # Increase device_imei column length from VARCHAR(20) to VARCHAR(100)
    # to support Series 5 Hubble Platform UUIDs (36 characters)
    
    op.alter_column('device_state', 'device_imei',
                    existing_type=sa.String(20),
                    type_=sa.String(100),
                    existing_nullable=False)
    
    op.alter_column('position_history', 'device_imei',
                    existing_type=sa.String(20),
                    type_=sa.String(100),
                    existing_nullable=False)
    
    op.alter_column('location_history_row', 'device_imei',
                    existing_type=sa.String(20),
                    type_=sa.String(100),
                    existing_nullable=False)
    
    op.alter_column('tracksolid_track_query', 'device_imei',
                    existing_type=sa.String(20),
                    type_=sa.String(100),
                    existing_nullable=False)
    
    op.alter_column('tracksolid_track_history', 'device_imei',
                    existing_type=sa.String(20),
                    type_=sa.String(100),
                    existing_nullable=False)
    
    op.alter_column('engine_state', 'device_imei',
                    existing_type=sa.String(20),
                    type_=sa.String(100),
                    existing_nullable=False)
    
    op.alter_column('stationaries', 'device_imei',
                    existing_type=sa.String(20),
                    type_=sa.String(100),
                    existing_nullable=False)
    
    op.alter_column('legs', 'device_imei',
                    existing_type=sa.String(20),
                    type_=sa.String(100),
                    existing_nullable=False)
    
    op.alter_column('journeys', 'device_imei',
                    existing_type=sa.String(20),
                    type_=sa.String(100),
                    existing_nullable=False)


def downgrade():
    # Downgrade back to VARCHAR(20)
    # WARNING: This will fail if any device_imei values are longer than 20 characters!
    
    op.alter_column('journeys', 'device_imei',
                    existing_type=sa.String(100),
                    type_=sa.String(20),
                    existing_nullable=False)
    
    op.alter_column('legs', 'device_imei',
                    existing_type=sa.String(100),
                    type_=sa.String(20),
                    existing_nullable=False)
    
    op.alter_column('stationaries', 'device_imei',
                    existing_type=sa.String(100),
                    type_=sa.String(20),
                    existing_nullable=False)
    
    op.alter_column('engine_state', 'device_imei',
                    existing_type=sa.String(100),
                    type_=sa.String(20),
                    existing_nullable=False)
    
    op.alter_column('tracksolid_track_history', 'device_imei',
                    existing_type=sa.String(100),
                    type_=sa.String(20),
                    existing_nullable=False)
    
    op.alter_column('tracksolid_track_query', 'device_imei',
                    existing_type=sa.String(100),
                    type_=sa.String(20),
                    existing_nullable=False)
    
    op.alter_column('location_history_row', 'device_imei',
                    existing_type=sa.String(100),
                    type_=sa.String(20),
                    existing_nullable=False)
    
    op.alter_column('position_history', 'device_imei',
                    existing_type=sa.String(100),
                    type_=sa.String(20),
                    existing_nullable=False)
    
    op.alter_column('device_state', 'device_imei',
                    existing_type=sa.String(100),
                    type_=sa.String(20),
                    existing_nullable=False)
