"""034 add last_alert_at to hive_live_state

Tracks the most recent time a breach alert was actually dispatched, so the
poller can re-send a reminder if a hive remains in BREACHING state.

Revision ID: 034
Revises: 033
Create Date: 2026-05-04
"""
from alembic import op
import sqlalchemy as sa


revision = '034'
down_revision = '033'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('hive_live_state',
                  sa.Column('last_alert_at', sa.DateTime(timezone=True), nullable=True))


def downgrade():
    op.drop_column('hive_live_state', 'last_alert_at')
