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
    
    # Step 1: Delete duplicate legs using USING self-join
    # For each duplicate group, keep the leg with:
    # - Longest distance_m, OR
    # - Smallest id (tiebreaker if distance_m equal)
    deleted = conn.execute(text("""
        DELETE FROM legs l1
        USING legs l2
        WHERE l1.device_imei = l2.device_imei
          AND l1.started_at = l2.started_at
          AND (
              l1.distance_m < l2.distance_m
              OR (l1.distance_m = l2.distance_m AND l1.id > l2.id)
          )
    """))
    
    print(f"🗑️  Deleted {deleted.rowcount} duplicate leg rows")
    
    # Step 2: Verify no duplicates remain before creating constraint
    check = conn.execute(text("""
        SELECT device_imei, started_at, COUNT(*) as cnt
        FROM legs
        GROUP BY device_imei, started_at
        HAVING COUNT(*) > 1
        LIMIT 5
    """))
    
    remaining = list(check)
    if remaining:
        for row in remaining:
            print(f"⚠️  Still duplicated: {row.device_imei} at {row.started_at} ({row.cnt} rows)")
        raise Exception(f"Cannot create unique constraint: {len(remaining)} duplicate groups still exist")
    
    print("✅ Verification passed: No duplicates remain")
    
    # Step 3: Add unique constraint to prevent future duplicates
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
