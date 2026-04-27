"""add buildings, floors, indoor_gateways, rooms and beacon_sightings tables

Revision ID: 015
Revises: 014
Create Date: 2026-05-01

buildings        — physical building per tenant (UserGroup)
floors           — one floor / level per building, holds a floor-plan image
indoor_gateways  — BLE ESP32 readers placed on a floor plan
rooms            — named rectangular zones on a floor plan
beacon_sightings — crowdsourced BLE tag sightings from mobile app users

Tables are created with IF NOT EXISTS semantics so the migration is safe
to run even if init_db() / create_all already created them on the server.
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect
from sqlalchemy.dialects.postgresql import UUID


revision = '015'
down_revision = '014'
branch_labels = None
depends_on = None


def _table_exists(conn, table_name: str) -> bool:
    return inspect(conn).has_table(table_name)


def upgrade():
    conn = op.get_bind()

    # ── buildings ─────────────────────────────────────────────────────────────
    if not _table_exists(conn, 'buildings'):
        op.create_table(
            'buildings',
            sa.Column('id',           UUID(as_uuid=True), primary_key=True,
                      server_default=sa.text('gen_random_uuid()')),
            sa.Column('usergroup_id', UUID(as_uuid=True),
                      sa.ForeignKey('user_groups.id', ondelete='CASCADE'),
                      nullable=False),
            sa.Column('name',         sa.String(200), nullable=False),
            sa.Column('mqtt_url',     sa.String(500), nullable=True),
            sa.Column('mqtt_topic',   sa.String(200), nullable=False,
                      server_default='position/#'),
            sa.Column('created_at',   sa.DateTime(timezone=True),
                      server_default=sa.func.now()),
            sa.Column('updated_at',   sa.DateTime(timezone=True), nullable=True),
        )

    # ── floors ────────────────────────────────────────────────────────────────
    if not _table_exists(conn, 'floors'):
        op.create_table(
            'floors',
            sa.Column('id',          UUID(as_uuid=True), primary_key=True,
                      server_default=sa.text('gen_random_uuid()')),
            sa.Column('building_id', UUID(as_uuid=True),
                      sa.ForeignKey('buildings.id', ondelete='CASCADE'),
                      nullable=False),
            sa.Column('label',       sa.String(100), nullable=False,
                      server_default='Ground Floor'),
            sa.Column('floor_order', sa.Integer(), nullable=False,
                      server_default='0'),
            sa.Column('floor_plan',  sa.Text(), nullable=True),   # base64 data-URL
            sa.Column('map_w',       sa.Integer(), nullable=False,
                      server_default='800'),
            sa.Column('map_h',       sa.Integer(), nullable=False,
                      server_default='500'),
            sa.Column('created_at',  sa.DateTime(timezone=True),
                      server_default=sa.func.now()),
            sa.Column('updated_at',  sa.DateTime(timezone=True), nullable=True),
        )

    # ── indoor_gateways ───────────────────────────────────────────────────────
    if not _table_exists(conn, 'indoor_gateways'):
        op.create_table(
            'indoor_gateways',
            sa.Column('id',          UUID(as_uuid=True), primary_key=True,
                      server_default=sa.text('gen_random_uuid()')),
            sa.Column('floor_id',    UUID(as_uuid=True),
                      sa.ForeignKey('floors.id', ondelete='CASCADE'),
                      nullable=False),
            sa.Column('receiver_id', sa.String(50), nullable=False),
            sa.Column('label',       sa.String(100), nullable=True),
            sa.Column('x',           sa.Float(), nullable=False,
                      server_default='0'),
            sa.Column('y',           sa.Float(), nullable=False,
                      server_default='0'),
            sa.Column('created_at',  sa.DateTime(timezone=True),
                      server_default=sa.func.now()),
            sa.Column('updated_at',  sa.DateTime(timezone=True), nullable=True),
        )
        op.create_index('ix_indoor_gateways_receiver_id',
                        'indoor_gateways', ['receiver_id'])

    # ── rooms ─────────────────────────────────────────────────────────────────
    if not _table_exists(conn, 'rooms'):
        op.create_table(
            'rooms',
            sa.Column('id',       UUID(as_uuid=True), primary_key=True,
                      server_default=sa.text('gen_random_uuid()')),
            sa.Column('floor_id', UUID(as_uuid=True),
                      sa.ForeignKey('floors.id', ondelete='CASCADE'),
                      nullable=False),
            sa.Column('name',     sa.String(100), nullable=False),
            sa.Column('x',        sa.Float(), nullable=False, server_default='0'),
            sa.Column('y',        sa.Float(), nullable=False, server_default='0'),
            sa.Column('w',        sa.Float(), nullable=False, server_default='100'),
            sa.Column('h',        sa.Float(), nullable=False, server_default='80'),
            sa.Column('created_at', sa.DateTime(timezone=True),
                      server_default=sa.func.now()),
            sa.Column('updated_at', sa.DateTime(timezone=True), nullable=True),
        )

    # ── beacon_sightings ──────────────────────────────────────────────────────
    if not _table_exists(conn, 'beacon_sightings'):
        op.create_table(
            'beacon_sightings',
            sa.Column('id',         UUID(as_uuid=True), primary_key=True,
                      server_default=sa.text('gen_random_uuid()')),
            sa.Column('user_id',    UUID(as_uuid=True),
                      sa.ForeignKey('users.id', ondelete='CASCADE'),
                      nullable=False),
            sa.Column('tag_id',     sa.String(64), nullable=False),
            sa.Column('tag_name',   sa.String(255), nullable=True),
            sa.Column('latitude',   sa.Float(), nullable=False),
            sa.Column('longitude',  sa.Float(), nullable=False),
            sa.Column('rssi',       sa.Integer(), nullable=True),
            sa.Column('sighted_at', sa.DateTime(timezone=True), nullable=False),
            sa.Column('created_at', sa.DateTime(timezone=True),
                      server_default=sa.func.now()),
        )
        op.create_index('ix_beacon_sightings_tag_id',
                        'beacon_sightings', ['tag_id'])


def downgrade():
    op.drop_index('ix_beacon_sightings_tag_id', table_name='beacon_sightings')
    op.drop_table('beacon_sightings')
    op.drop_table('rooms')
    op.drop_index('ix_indoor_gateways_receiver_id', table_name='indoor_gateways')
    op.drop_table('indoor_gateways')
    op.drop_table('floors')
    op.drop_table('buildings')
