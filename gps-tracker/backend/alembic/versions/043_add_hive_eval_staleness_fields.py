"""add explicit v1.2 staleness-aware hive evaluation fields

Revision ID: 043_add_hive_eval_staleness_fields
Revises: 042_nullable_user_id_for_qr
Create Date: 2026-06-02 23:30:00.000000
"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '043_add_hive_eval_staleness_fields'
down_revision = '042_nullable_user_id_for_qr'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column('hive_evaluations', sa.Column('positions_used', sa.Text(), nullable=True))
    op.add_column('hive_evaluations', sa.Column('max_pair_dt_s', sa.Float(), nullable=True))
    op.add_column('hive_evaluations', sa.Column('coherent_pair_count', sa.Integer(), nullable=True))
    op.add_column('hive_evaluations', sa.Column('incoherent_pair_count', sa.Integer(), nullable=True))
    op.add_column('hive_evaluations', sa.Column('breach_evidence', sa.String(length=30), nullable=True))


def downgrade() -> None:
    op.drop_column('hive_evaluations', 'breach_evidence')
    op.drop_column('hive_evaluations', 'incoherent_pair_count')
    op.drop_column('hive_evaluations', 'coherent_pair_count')
    op.drop_column('hive_evaluations', 'max_pair_dt_s')
    op.drop_column('hive_evaluations', 'positions_used')