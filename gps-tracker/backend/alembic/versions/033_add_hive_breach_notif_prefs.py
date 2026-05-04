"""033 add hive breach notification preferences

Revision ID: 033
Revises: 032
Create Date: 2026-05-15
"""
from alembic import op
import sqlalchemy as sa


revision = '033'
down_revision = '032'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('portal_users',
                  sa.Column('notify_hive_breach', sa.Boolean(), nullable=False, server_default=sa.true()))
    op.add_column('portal_users',
                  sa.Column('notify_hive_breach_sms', sa.Boolean(), nullable=False, server_default=sa.true()))


def downgrade():
    op.drop_column('portal_users', 'notify_hive_breach_sms')
    op.drop_column('portal_users', 'notify_hive_breach')
