"""v2.2 refinements: add is_open and unique constraint to stationaries

Revision ID: v22_refinements
Revises: 059_add_async_jobs
Create Date: 2026-07-20

Changes:
- Add is_open BOOLEAN column to stationaries (default FALSE) for R4c open stationary flushing
- Add unique constraint on (device_imei, started_at) for R2 duplicate prevention
"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'v22_refinements'
down_revision = '059_add_async_jobs'
branch_labels = None
depends_on = None


def upgrade():
    # R4c: Add is_open column for open stationary tracking
    op.add_column('stationaries', 
        sa.Column('is_open', sa.Boolean(), nullable=False, server_default='false'))
    
    # R2: Add unique constraint on (device_imei, started_at)
    # Note: This may fail if duplicate records exist
    # Clean duplicates first if needed
    op.create_unique_constraint(
        'uq_stationary_device_started',  # Constraint name
        'stationaries',  # Table name
        ['device_imei', 'started_at']  # Columns
    )


def downgrade():
    # Remove unique constraint
    op.drop_constraint('uq_stationary_device_started', 'stationaries', type_='unique')
    
    # Remove is_open column
    op.drop_column('stationaries', 'is_open')
