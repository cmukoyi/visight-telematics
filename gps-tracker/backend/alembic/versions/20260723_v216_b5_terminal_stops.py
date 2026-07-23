"""v2.1.6 B5: Journey ends at arrival, terminal stops detached

Revision ID: v216_b5_terminal_stops  
Revises: v216_b1_dup_prevention
Create Date: 2026-07-23

Implements B5 from Trip Engine Amendments 2.1.6:
- Detaches terminal stationaries (those after final leg of journey)
- Makes origin and terminal stops symmetric (both unattached)
- Prevents journeys reporting departure time instead of arrival
- Fixes 34-318 minute padding on journey end times

Forward-only migration:
- Detaches existing terminal stationaries
- Recalculates journey aggregates to use legs-only for ended_at
- Stationary_count now reflects waypoints only (terminal stops excluded)

Evidence from spec:
- All 8 journeys in scope show 34-318 min padding
- Example: Journey 16:41:17 should be 10:11:13 (6h30m error)
- Terminal stop dwells were included in journey duration
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy import text


# revision identifiers, used by Alembic.
revision: str = 'v216_b5_terminal_stops'
down_revision: Union[str, None] = 'v216_b1_dup_prevention'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    conn = op.get_bind()
    
    # Step 1: Detach terminal stationaries
    # A stationary is terminal if it starts at or after the last leg of its journey
    detached = conn.execute(text("""
        UPDATE stationaries s
        SET journey_id = NULL
        WHERE s.journey_id IS NOT NULL
          AND s.id IN (
            SELECT st.id
            FROM stationaries st
            INNER JOIN (
                SELECT l.journey_id, MAX(l.ended_at) as last_leg_ended
                FROM legs l
                WHERE l.journey_id IS NOT NULL
                GROUP BY l.journey_id
            ) last_legs ON last_legs.journey_id = st.journey_id
            WHERE st.started_at >= last_legs.last_leg_ended
          )
    """))
    
    print(f"Detached {detached.rowcount} terminal stationaries")
    
    # Step 2: Recalculate journey aggregates
    # Update ended_at to use max(legs.ended_at) instead of max(legs+stationaries)
    # Update stationary_count to count only attached waypoints
    updated = conn.execute(text("""
        UPDATE journeys j
        SET 
            ended_at = leg_agg.max_leg_ended,
            total_duration_seconds = EXTRACT(EPOCH FROM (leg_agg.max_leg_ended - j.started_at))::integer,
            stationary_count = COALESCE(stat_agg.waypoint_count, 0)
        FROM (
            SELECT 
                l.journey_id,
                MAX(l.ended_at) as max_leg_ended
            FROM legs l
            WHERE l.journey_id IS NOT NULL
            GROUP BY l.journey_id
        ) leg_agg
        LEFT JOIN (
            SELECT 
                st.journey_id,
                COUNT(*) as waypoint_count
            FROM stationaries st
            WHERE st.journey_id IS NOT NULL
            GROUP BY st.journey_id
        ) stat_agg ON stat_agg.journey_id = leg_agg.journey_id
        WHERE j.id = leg_agg.journey_id
    """))
    
    print(f"Updated {updated.rowcount} journey aggregates")
    
    # Step 3: Verify no journey has ended_at > max(legs.ended_at)
    check = conn.execute(text("""
        SELECT COUNT(*)
        FROM journeys j
        INNER JOIN (
            SELECT l.journey_id, MAX(l.ended_at) as max_leg_ended
            FROM legs l
            WHERE l.journey_id IS NOT NULL
            GROUP BY l.journey_id
        ) leg_max ON leg_max.journey_id = j.id
        WHERE j.ended_at > leg_max.max_leg_ended
    """)).scalar()
    
    if check > 0:
        raise Exception(f"Migration verification failed: {check} journeys still have ended_at > max(legs.ended_at)")
    
    print("✅ B5 migration complete: All journeys end at arrival")


def downgrade() -> None:
    # Downgrade not supported - would require re-attaching terminal stops
    # and recalculating with stationary end times, losing information about
    # which stops were originally terminal vs waypoints
    pass
