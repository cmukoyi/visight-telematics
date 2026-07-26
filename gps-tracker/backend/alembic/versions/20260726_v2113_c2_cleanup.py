"""v2.1.13 C2: Cleanup orphaned legs and zero-leg journeys

Revision ID: v2113_c2_cleanup
Revises: v2112_e1_journey_unique
Create Date: 2026-07-26

Implements cleanup from Trip Engine Amendment 2.1.13 C2:
- Detaches orphaned legs (legs pointing to non-existent journeys)
- Deletes zero-leg journeys (pre-existing from B5/C3 era)

Evidence from spec:
- One orphaned leg: 475, 26 Jul 09:14, journey c3a1b5c0 does not exist
- Two zero-leg journeys: 563 and 475, both 26 Jul ~09:38, 0.00 km / same-second span
"""

from alembic import op
from sqlalchemy import text


# revision identifiers, used by Alembic.
revision = 'v2113_c2_cleanup'
down_revision = 'v2112_e1_journey_unique'
branch_labels = None
depends_on = None


def upgrade() -> None:
    conn = op.get_bind()
    
    # Step 1: Detach orphaned legs (legs with journey_id pointing to non-existent journey)
    orphaned_legs = conn.execute(text("""
        UPDATE legs l
        SET journey_id = NULL
        WHERE l.journey_id IS NOT NULL
          AND NOT EXISTS (
            SELECT 1 FROM journeys j WHERE j.id = l.journey_id
          )
        RETURNING id
    """))
    
    orphaned_count = len(orphaned_legs.fetchall())
    print(f"Detached {orphaned_count} orphaned legs")
    
    # Step 2: Delete zero-leg journeys (journeys with no legs)
    # These are pre-existing from B5/C3 area - a journey is defined by movement
    zero_leg_journeys = conn.execute(text("""
        DELETE FROM journeys j
        WHERE NOT EXISTS (
            SELECT 1 FROM legs l WHERE l.journey_id = j.id
        )
        RETURNING id, device_imei, started_at, ended_at
    """))
    
    deleted_journeys = zero_leg_journeys.fetchall()
    print(f"Deleted {len(deleted_journeys)} zero-leg journeys:")
    for j in deleted_journeys:
        print(f"  - {j.device_imei}: {j.started_at} → {j.ended_at} (span: {j.ended_at - j.started_at})")
    
    # Step 3: Also detach any stationaries that were attached to deleted journeys
    orphaned_stats = conn.execute(text("""
        UPDATE stationaries s
        SET journey_id = NULL
        WHERE s.journey_id IS NOT NULL
          AND NOT EXISTS (
            SELECT 1 FROM journeys j WHERE j.id = s.journey_id
          )
        RETURNING id
    """))
    
    orphaned_stat_count = len(orphaned_stats.fetchall())
    if orphaned_stat_count > 0:
        print(f"Detached {orphaned_stat_count} orphaned stationaries (from deleted journeys)")


def downgrade() -> None:
    # Cannot reliably restore orphaned legs or deleted journeys
    # This is a cleanup migration - no downgrade
    pass
