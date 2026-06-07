"""add hive outlier attribution audit fields

Revision ID: 047_hive_outlier_audit
Revises: 046_critical_alert_subs
Create Date: 2026-06-07 22:40:00.000000
"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '047_hive_outlier_audit'
down_revision = '046_critical_alert_subs'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column('hive_evaluations', sa.Column('outlier_selection_reason', sa.String(length=40), nullable=True))
    op.add_column('hive_evaluations', sa.Column('breaching_pair_counts', sa.Text(), nullable=True))
    op.add_column('hive_evaluations', sa.Column('pairwise_detail', sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column('hive_evaluations', 'pairwise_detail')
    op.drop_column('hive_evaluations', 'breaching_pair_counts')
    op.drop_column('hive_evaluations', 'outlier_selection_reason')
