"""add hive persistence tracking fields

Revision ID: 049_hive_persistence
Revises: 048_ble_tag_imei_nullable
Create Date: 2026-06-24 19:30:00.000000
"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '049_hive_persistence'
down_revision = '048_ble_tag_imei_nullable'
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Add duration-based persistence tracking to HiveLiveState.
    
    Tracks evaluations in BREACH_PENDING and position fingerprint to implement
    v1.2 confirmation fix (duration-based persistence vs two-fixes-from-tag).
    """
    op.add_column('hive_live_state', 
                  sa.Column('breach_persistence_eval_count', sa.Integer(), nullable=False, server_default='0'))
    op.add_column('hive_live_state', 
                  sa.Column('breach_persistence_first_fingerprint', sa.String(length=64), nullable=True))


def downgrade() -> None:
    op.drop_column('hive_live_state', 'breach_persistence_first_fingerprint')
    op.drop_column('hive_live_state', 'breach_persistence_eval_count')
