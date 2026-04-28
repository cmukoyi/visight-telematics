"""add logo_dark_data to user_groups; add notification_emails to portal_users

Revision ID: 024
Revises: 023_add_portal_roles_and_features
Create Date: 2026-04-28
"""
from alembic import op
import sqlalchemy as sa

revision = '024'
down_revision = '023'
branch_labels = None
depends_on = None


def upgrade():
    # Add dark-mode logo column to user_groups
    op.add_column('user_groups', sa.Column('logo_dark_data', sa.Text(), nullable=True))
    # Add extra notification email list to portal_users
    op.add_column('portal_users', sa.Column('notification_emails', sa.JSON(), nullable=True))


def downgrade():
    op.drop_column('user_groups', 'logo_dark_data')
    op.drop_column('portal_users', 'notification_emails')
