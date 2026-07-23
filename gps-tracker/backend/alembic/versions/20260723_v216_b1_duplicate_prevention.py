"""v2.1.6 B1: Duplicate leg and stationary prevention

Revision ID: v216_b1_dup_prevention
Revises: v22_refinements
Create Date: 2026-07-23

Implements B1 from Trip Engine Amendments 2.1.6:
- Deduplicates existing legs (keeps longer leg per spec)
- Unique constraint on legs (device_imei, started_at)
- Prevents duplicate leg rows from multiple invocations
- Allows upsert pattern for idempotent replays

Evidence from production:
- 23 duplicate leg groups (20% of dataset)
- Inflated journey distances by 57-100%
- Example: Device 780901807707502, 2026-07-17 05:23:13+00
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy import text


# revision identifiers, used by Alembic.
revision: str = 'v216_b1_dup_prevention'
down_revision: Union[str, None] = 'v22_refinements'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    conn = op.get_bind()
    
    # Step 1: Delete existing duplicate legs
    # Keep the longer leg (max distance_m) for each (device_imei, started_at) group
    # This matches the upsert behavior in trip_engine.py
    deleted = conn.execute(text("""
        DELETE FROM legs
        WHERE id IN (
            -- Find all duplicate legs
            SELECT l.id
            FROM legs l
            INNER JOIN (
                -- Group by device + start time
                SELECT device_imei, started_at, MAX(distance_m) as max_distance
                FROM legs
                GROUP BY device_imei, started_at
                HAVING COUNT(*) > 1
            ) dupes ON dupes.device_imei = l.device_imei 
                   AND dupes.started_at = l.started_at
            -- Delete the shorter legs (keep the longer one)
            WHERE l.distance_m < dupes.max_distance
        )
    """))
    
    print(f"Deleted {deleted.rowcount} duplicate leg rows (kept longer leg per group)")
    
    # Step 2: Add unique constraint to prevent future duplicates
    # This enables the upsert pattern in trip_engine.py
    op.create_unique_constraint(
        'ux_leg_device_start',  # Constraint name
        'legs',                  # Table name
        ['device_imei', 'started_at']  # Columns
    )
    
    print("✅ B1 migration complete: Unique constraint created")
    
    # Note: stationaries already has uq_stationary_device_started from v22_refinements
    # This completes the duplicate prevention for both tables


def downgrade() -> None:
    op.drop_constraint('ux_leg_device_start', 'legs', type_='unique')
