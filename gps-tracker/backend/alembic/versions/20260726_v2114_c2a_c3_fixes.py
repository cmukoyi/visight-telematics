"""v2.1.14 C2a+C3: Journey break on flush + journey end at arrival

Revision ID: v2114_c2a_c3
Revises: v2113_c2_cleanup
Create Date: 2026-07-26

Implements Trip Engine Amendment 2.1.14:

C2a: Journey break on open stops (code-only, no schema change)
- Added journey break evaluation during stationary flush (every 15 min)
- When open stationary crosses 30 min threshold, close journey
- Guard against re-firing on subsequent flushes

C3: Journey end = arrival time (backfill existing data)
- journey.ended_at must derive from legs only (arrival), not legs + stationaries (departure)
- Fixes journeys reporting end time as departure from final stop
- Evidence: 17/22 journeys on tags 475+767 showed padding up to 356 minutes

This migration backfills existing journeys to correct ended_at timestamps.
"""

from alembic import op
from sqlalchemy import text


# revision identifiers, used by Alembic.
revision = 'v2114_c2a_c3'
down_revision = 'v2113_c2_cleanup'
branch_labels = None
depends_on = None


def upgrade() -> None:
    conn = op.get_bind()
    
    # C3: Backfill journey.ended_at to use legs only (arrival time, not departure)
    # Before: ended_at = max(legs.ended_at, stationaries.ended_at) -- includes parked time
    # After:  ended_at = max(legs.ended_at) -- journey ends at arrival
    
    print("C3: Correcting journey end timestamps (arrival vs departure)...")
    
    result = conn.execute(text("""
        UPDATE journeys j
        SET 
            ended_at = (SELECT max(l.ended_at) FROM legs l WHERE l.journey_id = j.id),
            total_duration_seconds = EXTRACT(EPOCH FROM (
                (SELECT max(l.ended_at) FROM legs l WHERE l.journey_id = j.id) - j.started_at
            ))::INTEGER
        WHERE EXISTS (SELECT 1 FROM legs l WHERE l.journey_id = j.id)
        RETURNING id, device_imei, started_at, ended_at
    """))
    
    updated_journeys = result.fetchall()
    print(f"Updated {len(updated_journeys)} journeys to end at arrival (legs only)")
    
    # Show sample of corrected journeys
    if updated_journeys:
        print("\nSample corrections:")
        for i, j in enumerate(updated_journeys[:5]):
            duration_min = (j.ended_at - j.started_at).total_seconds() / 60
            print(f"  - {j.device_imei}: {j.started_at} → {j.ended_at} ({duration_min:.0f} min)")
        if len(updated_journeys) > 5:
            print(f"  ... and {len(updated_journeys) - 5} more")


def downgrade() -> None:
    # Cannot reliably restore previous ended_at values (they were incorrect)
    # This is a data quality fix - no downgrade
    pass
