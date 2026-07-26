"""Add breach persistence tracking fields for duration-based confirmation

Revision ID: 052_add_persistence_tracking
Revises: 051_add_translation_keys
Create Date: 2026-06-20

Adds persistence tracking fields to hive_live_state to support duration-based
breach confirmation (v1.2 confirmation fix). Replaces "two consecutive coherent
fixes from separated tag" with "6 minutes AND 3 evaluations AND fresh evidence
from any tag".

New fields:
- persistence_eval_count: Number of consecutive evaluations in BREACH_PENDING
- persistence_snapshot_fp_at_start: Fingerprint when BREACH_PENDING started
- persistence_has_new_evidence: True if new position data arrived during window

This migration is additive-only and safe to run on production.
"""
from alembic import op
import sqlalchemy as sa

revision = '052_add_persistence_tracking'
down_revision = '051_add_translation_keys'
branch_labels = None
depends_on = None


def upgrade():
    # Add persistence tracking fields to hive_live_state
    op.add_column('hive_live_state', 
        sa.Column('persistence_eval_count', sa.Integer(), nullable=False, server_default='0')
    )
    op.add_column('hive_live_state',
        sa.Column('persistence_snapshot_fp_at_start', sa.String(500), nullable=True)
    )
    op.add_column('hive_live_state',
        sa.Column('persistence_has_new_evidence', sa.Boolean(), nullable=False, server_default='false')
    )


def downgrade():
    # Remove persistence tracking fields
    op.drop_column('hive_live_state', 'persistence_has_new_evidence')
    op.drop_column('hive_live_state', 'persistence_snapshot_fp_at_start')
    op.drop_column('hive_live_state', 'persistence_eval_count')
