"""add settle_min_dwell config

Revision ID: 057
Revises: 056
Create Date: 2026-07-18 01:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '057'
down_revision = '056'
branch_labels = None
depends_on = None


def upgrade():
    """Add engine_settle_min_dwell_min to trip_config table."""
    # Add the new column with default value
    op.add_column(
        'trip_config',
        sa.Column('engine_settle_min_dwell_min', sa.Integer(), nullable=False, server_default='3')
    )


def downgrade():
    """Remove engine_settle_min_dwell_min from trip_config table."""
    op.drop_column('trip_config', 'engine_settle_min_dwell_min')
