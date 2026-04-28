"""Add usergroup_id to pois and make user_id nullable

Revision ID: 026
Revises: 025
Create Date: 2026-04-28
"""
from alembic import op
import sqlalchemy as sa

revision = '026'
down_revision = '025'
branch_labels = None
depends_on = None


def upgrade():
    # Make user_id nullable on pois (portal-created POIs have no mobile user)
    op.alter_column('pois', 'user_id', nullable=True)

    # Add usergroup_id column (nullable FK to user_groups)
    op.add_column('pois', sa.Column('usergroup_id', sa.String(36), nullable=True))
    op.create_foreign_key(
        'fk_pois_usergroup_id',
        'pois', 'user_groups',
        ['usergroup_id'], ['id'],
        ondelete='CASCADE',
    )
    op.create_index('ix_pois_usergroup_id', 'pois', ['usergroup_id'])


def downgrade():
    op.drop_index('ix_pois_usergroup_id', table_name='pois')
    op.drop_constraint('fk_pois_usergroup_id', 'pois', type_='foreignkey')
    op.drop_column('pois', 'usergroup_id')
    op.alter_column('pois', 'user_id', nullable=False)
