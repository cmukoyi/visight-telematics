"""v2.1.6 B1: Duplicate leg and stationary prevention

Revision ID: v216_b1_dup_prevention
Revises: v22_refinements
Create Date: 2026-07-23

Implements B1 from Trip Engine Amendments 2.1.6:
- Unique constraint on legs (device_imei, started_at)
- Prevents duplicate leg rows from multiple invocations
- Allows upsert pattern for idempotent replays
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'v216_b1_dup_prevention'
down_revision: Union[str, None] = 'v22_refinements'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Add unique constraint to legs table for (device_imei, started_at)
    # Prevents duplicate legs with same start time
    op.create_unique_constraint(
        'ux_leg_device_start',  # Constraint name
        'legs',                  # Table name
        ['device_imei', 'started_at']  # Columns
    )
    
    # Note: stationaries already has uq_stationary_device_started from v22_refinements
    # This completes the duplicate prevention for both tables


def downgrade() -> None:
    op.drop_constraint('ux_leg_device_start', 'legs', type_='unique')
