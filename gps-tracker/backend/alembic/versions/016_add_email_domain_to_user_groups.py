"""add email_domain to user_groups

Revision ID: 016
Revises: 015
Create Date: 2026-04-20
"""
from alembic import op
import sqlalchemy as sa

revision = '016'
down_revision = '015'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        'user_groups',
        sa.Column('email_domain', sa.String(255), nullable=True),
    )
    op.create_index('ix_user_groups_email_domain', 'user_groups', ['email_domain'])


def downgrade():
    op.drop_index('ix_user_groups_email_domain', table_name='user_groups')
    op.drop_column('user_groups', 'email_domain')
