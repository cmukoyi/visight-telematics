"""036 add tag_indoor_positions for Pareto/XIAO BLE indoor tracking

Adds a single table for the floor-plan MVP. Rows are upserted by the
Pareto Anywhere bridge whenever a raddec is received from one of the
tenant's registered XIAO gateways. One row per BLE tag id; the
nearest-gateway derived xy / zone / floor reflects the latest sighting.

Kept separate from `beacon_sightings` (which is the mobile-phone
crowdsourced GPS flow) — the two share no fields and have different
write paths and tenant scoping.

See features_dev/Pinplot floorplan spec.md §6 (assets table).

Revision ID: 036
Revises: 035
Create Date: 2026-05-19
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID


revision = '036'
down_revision = '035'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        'tag_indoor_positions',
        sa.Column('tag_id', sa.String(64), primary_key=True),
        # Floor / gateway / tenant — denormalised so the asset endpoint is one query.
        sa.Column('floor_id', UUID(as_uuid=True),
                  sa.ForeignKey('floors.id', ondelete='CASCADE'),
                  nullable=False),
        sa.Column('gateway_id', UUID(as_uuid=True),
                  sa.ForeignKey('indoor_gateways.id', ondelete='SET NULL'),
                  nullable=True),
        sa.Column('usergroup_id', UUID(as_uuid=True),
                  sa.ForeignKey('user_groups.id', ondelete='CASCADE'),
                  nullable=False),
        # Position copied from the nearest gateway's canvas coords.
        sa.Column('x', sa.Float, nullable=False),
        sa.Column('y', sa.Float, nullable=False),
        sa.Column('zone', sa.String(100), nullable=True),
        # Signal / battery / liveness.
        sa.Column('rssi', sa.Integer, nullable=True),
        sa.Column('battery', sa.Integer, nullable=True),
        sa.Column('status', sa.String(20), nullable=False, server_default='offline'),
        sa.Column('last_seen', sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index('ix_tag_indoor_positions_usergroup_floor',
                    'tag_indoor_positions', ['usergroup_id', 'floor_id'])
    op.create_index('ix_tag_indoor_positions_last_seen',
                    'tag_indoor_positions', ['last_seen'])


def downgrade():
    op.drop_index('ix_tag_indoor_positions_last_seen',
                  table_name='tag_indoor_positions')
    op.drop_index('ix_tag_indoor_positions_usergroup_floor',
                  table_name='tag_indoor_positions')
    op.drop_table('tag_indoor_positions')
