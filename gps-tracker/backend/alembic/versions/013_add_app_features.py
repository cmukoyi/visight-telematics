"""add app_features table for admin-controlled feature flags

Revision ID: 013
Revises: 012
Create Date: 2026-04-08

Adds a single-row table that the admin portal writes and the mobile app
reads to determine which tabs/features are visible.
"""
from alembic import op
import sqlalchemy as sa


revision = '013'
down_revision = '012'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        'app_features',
        sa.Column('id',             sa.String(36),  primary_key=True),
        sa.Column('show_map',       sa.Boolean(),   nullable=False, server_default='true'),
        sa.Column('show_journey',   sa.Boolean(),   nullable=False, server_default='true'),
        sa.Column('show_assets',    sa.Boolean(),   nullable=False, server_default='true'),
        sa.Column('show_scan',      sa.Boolean(),   nullable=False, server_default='true'),
        sa.Column('show_settings',  sa.Boolean(),   nullable=False, server_default='true'),
        sa.Column('show_solutions', sa.Boolean(),   nullable=False, server_default='false'),
        sa.Column('updated_at',     sa.DateTime(timezone=True), nullable=True),
    )
    # Seed the single global row
    op.execute("""
        INSERT INTO app_features (id, show_map, show_journey, show_assets, show_scan, show_settings, show_solutions)
        VALUES ('global', true, true, true, true, true, false)
    """)


def downgrade():
    op.drop_table('app_features')
