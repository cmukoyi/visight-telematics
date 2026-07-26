"""add tenant trip config and journey versioning

Revision ID: 058_add_tenant_trip_config
Revises: 057_add_settle_min_dwell_config
Create Date: 2026-07-18 02:00:00.000000

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision = '058_add_tenant_trip_config'
down_revision = '057_add_settle_min_dwell_config'
branch_labels = None
depends_on = None


def upgrade():
    """Add per-tenant trip config and journey versioning fields."""
    
    # A1: Per-tenant coalesce floor (NULL = use global default 120 min)
    op.add_column(
        'user_groups',
        sa.Column('coalesce_floor_minutes', sa.Integer(), nullable=True)
    )
    
    # A4: Journey versioning - track which engine version/params created each journey
    op.add_column(
        'journeys',
        sa.Column('engine_version', sa.String(20), nullable=True)
    )
    
    op.add_column(
        'journeys',
        sa.Column('engine_params', postgresql.JSONB(astext_type=sa.Text()), nullable=True)
    )


def downgrade():
    """Remove tenant trip config and journey versioning fields."""
    op.drop_column('journeys', 'engine_params')
    op.drop_column('journeys', 'engine_version')
    op.drop_column('user_groups', 'coalesce_floor_minutes')
