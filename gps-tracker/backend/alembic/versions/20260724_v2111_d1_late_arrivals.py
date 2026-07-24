"""v2.1.11 D1: Fix 50% data loss from late-arriving positions

Revision ID: v2111_d1_late_arrivals
Revises: v216_b5_terminal_stops
Create Date: 2026-07-24

Implements D1 from Trip Engine Amendment 2.1.11:
- Adds positions.received_at timestamp (when row arrived in database)
- Adds engine_states.last_received_at checkpoint column
- Fixes permanent data loss where 50% of positions were skipped

Problem:
Tags buffer positions and upload later (Data Type = Buffer). Positions arrive
out of chronological order. Engine checkpoints on observed_at, so late-arriving
positions with old observed_at timestamps are permanently skipped.

Evidence:
- Device 767: 258 API positions → 128 processed (50% lost)
- Device 907: 238 API positions → 124 processed (48% lost)
- Reprocess recovers all lost data, confirming engine logic is correct

Solution:
Checkpoint on received_at (arrival time) instead of observed_at (observation time).
Late positions are now captured regardless of observed_at timestamp.

Schema changes:
- positions.received_at: timestamptz NOT NULL DEFAULT now()
- engine_states.last_received_at: timestamptz (replaces last_processed_at for checkpointing)
- Index: ix_positions_received_at (device_id, received_at)
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy import text


# revision identifiers, used by Alembic.
revision: str = 'v2111_d1_late_arrivals'
down_revision: Union[str, None] = 'v216_b5_terminal_stops'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    conn = op.get_bind()
    
    print("[D1] Adding positions.received_at column...")
    
    # Step 1: Add received_at column to positions table
    # This tracks when the position arrived in our database (not when it was observed)
    op.add_column('positions', 
        sa.Column('received_at', sa.TIMESTAMP(timezone=True), nullable=True)
    )
    
    # Set default for future inserts
    op.alter_column('positions', 'received_at',
        server_default=sa.text('now()')
    )
    
    print("[D1] Backfilling positions.received_at from observed_at...")
    
    # Step 2: Backfill existing rows
    # Use observed_at as estimate - this understates arrival for buffered rows (safe)
    result = conn.execute(text("""
        UPDATE positions 
        SET received_at = observed_at 
        WHERE received_at IS NULL
    """))
    print(f"[D1] Backfilled {result.rowcount} positions")
    
    # Step 3: Make column NOT NULL now that all rows are populated
    op.alter_column('positions', 'received_at',
        nullable=False
    )
    
    print("[D1] Creating index on (device_id, received_at)...")
    
    # Step 4: Create index for efficient querying
    op.create_index(
        'ix_positions_received_at',
        'positions',
        ['device_id', 'received_at'],
        unique=False
    )
    
    print("[D1] Adding engine_states.last_received_at checkpoint column...")
    
    # Step 5: Add checkpoint column to engine_states
    op.add_column('engine_states',
        sa.Column('last_received_at', sa.TIMESTAMP(timezone=True), nullable=True)
    )
    
    print("[D1] Backfilling engine_states.last_received_at from last_processed_at...")
    
    # Step 6: Backfill from existing checkpoint
    result = conn.execute(text("""
        UPDATE engine_states 
        SET last_received_at = last_processed_at 
        WHERE last_received_at IS NULL
    """))
    print(f"[D1] Backfilled {result.rowcount} engine states")
    
    print("[D1] Migration complete. Engine will now checkpoint on arrival time.")
    print("[D1] Note: Engine code must be updated to query WHERE received_at > last_received_at")


def downgrade() -> None:
    """Downgrade not supported - data would be lost."""
    # Drop index
    op.drop_index('ix_positions_received_at', table_name='positions')
    
    # Drop columns
    op.drop_column('engine_states', 'last_received_at')
    op.drop_column('positions', 'received_at')
