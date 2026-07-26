"""v2.1.12 E1: Journey uniqueness guard + duplicate cleanup

Revision ID: v2112_e1_journey_unique
Revises: v2111_d1_late_arrivals
Create Date: 2026-07-26

Amendment 2.1.12 E1: Fix journey duplication from D1 replay.

Problem: D1 replay creates new journey rows on each batch instead of updating
existing ones. journeys table missing unique constraint on (device_imei, started_at)
that legs and stationaries already have (B1).

Fix:
1. Re-point legs/stationaries to surviving journeys (latest created_at = most complete)
2. Delete duplicate journey rows
3. Add unique constraint to prevent future duplication
4. Code uses upsert on conflict (separate commit)

Evidence: 976 journeys reduce to 37 real ones (939 duplicates, up to 85× per trip).
Reprocess also accumulates instead of converging (tag 475 had 3 copies from 3 runs).

Reference: features_dev/PinPlot_Trip_Engine_Amendment_2.1.12.md
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID


# revision identifiers, used by Alembic.
revision = 'v2112_e1_journey_unique'
down_revision = 'v2111_d1_late_arrivals'
branch_labels = None
depends_on = None


def upgrade():
    conn = op.get_bind()
    
    # ══════════════════════════════════════════════════════════════════════════
    # STEP 1: Re-point legs to surviving journeys
    # ══════════════════════════════════════════════════════════════════════════
    # Survivor = latest created_at for each (device_imei, started_at) group
    # This preserves the most complete journey (earlier rows may be partial)
    
    conn.execute(sa.text("""
        WITH survivor AS (
          SELECT DISTINCT ON (device_imei, started_at) 
            id, device_imei, started_at
          FROM journeys
          ORDER BY device_imei, started_at, created_at DESC
        ),
        doomed AS (
          SELECT j.id AS old_id, s.id AS new_id
          FROM journeys j
          JOIN survivor s ON s.device_imei = j.device_imei 
                          AND s.started_at = j.started_at
          WHERE j.id <> s.id
        )
        UPDATE legs 
        SET journey_id = doomed.new_id
        FROM doomed 
        WHERE legs.journey_id = doomed.old_id;
    """))
    
    # ══════════════════════════════════════════════════════════════════════════
    # STEP 2: Re-point stationaries to surviving journeys
    # ══════════════════════════════════════════════════════════════════════════
    
    conn.execute(sa.text("""
        WITH survivor AS (
          SELECT DISTINCT ON (device_imei, started_at) 
            id, device_imei, started_at
          FROM journeys
          ORDER BY device_imei, started_at, created_at DESC
        ),
        doomed AS (
          SELECT j.id AS old_id, s.id AS new_id
          FROM journeys j
          JOIN survivor s ON s.device_imei = j.device_imei 
                          AND s.started_at = j.started_at
          WHERE j.id <> s.id
        )
        UPDATE stationaries 
        SET journey_id = doomed.new_id
        FROM doomed 
        WHERE stationaries.journey_id = doomed.old_id;
    """))
    
    # ══════════════════════════════════════════════════════════════════════════
    # STEP 3: Delete duplicate journeys (keep latest created_at survivors)
    # ══════════════════════════════════════════════════════════════════════════
    # This must run AFTER re-pointing or we'd orphan legs/stationaries
    
    result = conn.execute(sa.text("""
        WITH survivor AS (
          SELECT DISTINCT ON (device_imei, started_at) id
          FROM journeys
          ORDER BY device_imei, started_at, created_at DESC
        )
        DELETE FROM journeys
        WHERE id NOT IN (SELECT id FROM survivor)
          AND EXISTS (
            SELECT 1 FROM journeys j2
            WHERE j2.device_imei = journeys.device_imei
              AND j2.started_at = journeys.started_at
              AND j2.id <> journeys.id
          )
        RETURNING id;
    """))
    
    deleted_count = result.rowcount
    if deleted_count > 0:
        print(f"✅ Deleted {deleted_count} duplicate journey rows")
    else:
        print("✅ No duplicate journeys found (already clean)")
    
    # ══════════════════════════════════════════════════════════════════════════
    # STEP 4: Add unique constraint (NOW safe after cleanup)
    # ══════════════════════════════════════════════════════════════════════════
    # This prevents future duplicates from D1 replay or reprocess
    # Code must use ON CONFLICT DO UPDATE to converge (separate commit)
    
    op.create_index(
        'ux_journey_device_start',
        'journeys',
        ['device_imei', 'started_at'],
        unique=True,
    )
    
    print("✅ Added unique constraint on journeys(device_imei, started_at)")


def downgrade():
    # Drop unique constraint
    op.drop_index('ux_journey_device_start', 'journeys')
    
    # WARNING: Cannot restore deleted duplicates
    # This downgrade only removes the guard, not the cleanup
    print("⚠️  Downgrade removed uniqueness guard but cannot restore deleted duplicates")
