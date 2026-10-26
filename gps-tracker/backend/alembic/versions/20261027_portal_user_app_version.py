"""The mobile app build each portal user last used (sent by the app as X-App-Version).

Revision ID: 089_portal_user_app_version
Revises: 088_breakdown_alerts_per_day
Create Date: 2026-10-27
"""
from alembic import op

revision = "089_portal_user_app_version"
down_revision = "088_breakdown_alerts_per_day"
branch_labels = None
depends_on = None


def upgrade():
    op.execute("ALTER TABLE portal_users ADD COLUMN IF NOT EXISTS app_version VARCHAR(120)")


def downgrade():
    op.execute("ALTER TABLE portal_users DROP COLUMN IF EXISTS app_version")
