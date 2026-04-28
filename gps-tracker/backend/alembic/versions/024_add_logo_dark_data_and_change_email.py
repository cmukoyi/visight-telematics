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
    # Use raw SQL with IF NOT EXISTS so re-runs on a partially-applied DB are safe
    op.execute("ALTER TABLE user_groups ADD COLUMN IF NOT EXISTS logo_dark_data TEXT")
    op.execute("ALTER TABLE portal_users ADD COLUMN IF NOT EXISTS notification_emails JSON")


def downgrade():
    op.drop_column('user_groups', 'logo_dark_data')
    op.drop_column('portal_users', 'notification_emails')
