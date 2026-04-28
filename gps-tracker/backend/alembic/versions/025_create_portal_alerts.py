"""create portal_alerts table

Revision ID: 025
Revises: 024
Create Date: 2026-04-28
"""
from alembic import op
import sqlalchemy as sa

revision = '025'
down_revision = '024'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        'portal_alerts',
        sa.Column('id', sa.String(36), primary_key=True),
        sa.Column('usergroup_id', sa.String(36), sa.ForeignKey('user_groups.id', ondelete='CASCADE'), nullable=False),
        sa.Column('tag_id', sa.String(36), sa.ForeignKey('ble_tags.id', ondelete='CASCADE'), nullable=True),
        sa.Column('alert_type', sa.String(50), nullable=False),
        sa.Column('title', sa.String(200), nullable=False),
        sa.Column('message', sa.Text(), nullable=True),
        sa.Column('is_read', sa.Boolean(), nullable=False, server_default='false'),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column('meta_data', sa.JSON(), nullable=True),
    )
    op.create_index('ix_portal_alerts_usergroup_created', 'portal_alerts',
                    ['usergroup_id', 'created_at'])
    op.create_index('ix_portal_alerts_tag_id', 'portal_alerts', ['tag_id'])


def downgrade():
    op.drop_index('ix_portal_alerts_tag_id', table_name='portal_alerts')
    op.drop_index('ix_portal_alerts_usergroup_created', table_name='portal_alerts')
    op.drop_table('portal_alerts')
