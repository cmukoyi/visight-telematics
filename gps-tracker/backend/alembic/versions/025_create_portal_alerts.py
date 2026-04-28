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
    # IF NOT EXISTS guards against partial re-runs
    op.execute("""
        CREATE TABLE IF NOT EXISTS portal_alerts (
            id VARCHAR(36) PRIMARY KEY,
            usergroup_id VARCHAR(36) NOT NULL REFERENCES user_groups(id) ON DELETE CASCADE,
            tag_id VARCHAR(36) REFERENCES ble_tags(id) ON DELETE CASCADE,
            alert_type VARCHAR(50) NOT NULL,
            title VARCHAR(200) NOT NULL,
            message TEXT,
            is_read BOOLEAN NOT NULL DEFAULT false,
            created_at TIMESTAMPTZ DEFAULT now(),
            meta_data JSON
        )
    """)
    op.execute("""
        CREATE INDEX IF NOT EXISTS ix_portal_alerts_usergroup_created
        ON portal_alerts (usergroup_id, created_at)
    """)
    op.execute("""
        CREATE INDEX IF NOT EXISTS ix_portal_alerts_tag_id
        ON portal_alerts (tag_id)
    """)


def downgrade():
    op.drop_index('ix_portal_alerts_tag_id', table_name='portal_alerts')
    op.drop_index('ix_portal_alerts_usergroup_created', table_name='portal_alerts')
    op.drop_table('portal_alerts')
