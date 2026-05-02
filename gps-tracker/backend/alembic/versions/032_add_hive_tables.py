"""032 add hive tracking tables

Revision ID: 032
Revises: 031
Create Date: 2026-05-02
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = '032'
down_revision = '031'
branch_labels = None
depends_on = None


def upgrade():
    uid = postgresql.UUID(as_uuid=True)

    # ─── hives ───────────────────────────────────────────────────────────────
    op.create_table(
        'hives',
        sa.Column('id', uid, primary_key=True),
        sa.Column('usergroup_id', uid, sa.ForeignKey('user_groups.id'), nullable=False, index=True),
        sa.Column('created_by', uid, sa.ForeignKey('portal_users.id'), nullable=True),
        sa.Column('name', sa.String(200), nullable=False),
        sa.Column('status', sa.String(20), nullable=False, server_default='active'),  # active|archived|purged
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column('expires_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('archived_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('archived_reason', sa.String(50), nullable=True),   # expired|user_deleted
        sa.Column('archive_expires_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('purged_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('purged_reason', sa.String(50), nullable=True),     # auto_retention|user_purged
        sa.Column('parent_hive_id', uid, sa.ForeignKey('hives.id'), nullable=True),
        sa.Column('settling_until', sa.DateTime(timezone=True), nullable=True),
    )

    # ─── hive_config_versions ────────────────────────────────────────────────
    op.create_table(
        'hive_config_versions',
        sa.Column('id', uid, primary_key=True),
        sa.Column('hive_id', uid, sa.ForeignKey('hives.id'), nullable=False, index=True),
        sa.Column('version_number', sa.Integer, nullable=False),
        sa.Column('valid_from', sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column('valid_to', sa.DateTime(timezone=True), nullable=True),   # null = current
        sa.Column('mobility_profile', sa.String(30), nullable=False),        # stationary|slow|mobile|fast|custom
        sa.Column('distance_threshold_m', sa.Float, nullable=False),
        sa.Column('fresh_window_s', sa.Integer, nullable=False),
        sa.Column('recent_window_s', sa.Integer, nullable=False),
        sa.Column('stale_window_s', sa.Integer, nullable=False),
        sa.Column('lost_threshold_s', sa.Integer, nullable=False),
        sa.Column('meaningful_change_m', sa.Float, nullable=False),
        sa.Column('hysteresis_pct', sa.Float, nullable=False),
        sa.Column('confirmation_count', sa.Integer, nullable=False),
        sa.Column('changed_by', uid, sa.ForeignKey('portal_users.id'), nullable=True),
    )

    # ─── hive_tag_membership ─────────────────────────────────────────────────
    # tag_id is PK → enforces "one active hive per tag" at DB level
    op.create_table(
        'hive_tag_membership',
        sa.Column('tag_id', uid, sa.ForeignKey('ble_tags.id'), primary_key=True),
        sa.Column('hive_id', uid, sa.ForeignKey('hives.id'), nullable=False, index=True),
        sa.Column('joined_at', sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column('label', sa.String(100), nullable=True),  # per-tag display label within this hive
    )

    # ─── hive_evaluations ────────────────────────────────────────────────────
    op.create_table(
        'hive_evaluations',
        sa.Column('id', uid, primary_key=True),
        sa.Column('hive_id', uid, sa.ForeignKey('hives.id'), nullable=False, index=True),
        sa.Column('evaluated_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column('config_version_number', sa.Integer, nullable=False),
        sa.Column('diameter_m', sa.Float, nullable=True),
        sa.Column('threshold_m', sa.Float, nullable=False),
        sa.Column('outlier_tag_id', uid, nullable=True),  # soft ref — no FK constraint
        sa.Column('freshness_composition', sa.Text, nullable=True),   # JSON: {fresh,recent,stale,lost}
        sa.Column('alert_state', sa.String(30), nullable=False),       # OK|BREACH_PENDING|BREACHING|RESOLVING
        sa.Column('breach_confidence', sa.String(10), nullable=True),  # high|low
    )
    op.create_index('ix_hive_evaluations_hive_id_evaluated_at',
                    'hive_evaluations', ['hive_id', 'evaluated_at'])

    # ─── hive_events ─────────────────────────────────────────────────────────
    op.create_table(
        'hive_events',
        sa.Column('id', uid, primary_key=True),
        sa.Column('hive_id', uid, sa.ForeignKey('hives.id'), nullable=False, index=True),
        sa.Column('occurred_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column('event_type', sa.String(50), nullable=False),
        sa.Column('config_version_number', sa.Integer, nullable=True),
        sa.Column('from_state', sa.String(30), nullable=True),
        sa.Column('to_state', sa.String(30), nullable=True),
        sa.Column('triggering_tag_id', uid, nullable=True),  # soft ref — no FK constraint
        sa.Column('details', sa.Text, nullable=True),   # JSON
    )
    op.create_index('ix_hive_events_hive_id_occurred_at',
                    'hive_events', ['hive_id', 'occurred_at'])

    # ─── hive_live_state ─────────────────────────────────────────────────────
    # Denormalised live state (replaces Redis for MVP)
    op.create_table(
        'hive_live_state',
        sa.Column('hive_id', uid, sa.ForeignKey('hives.id'), primary_key=True),
        sa.Column('alert_state', sa.String(30), nullable=False, server_default='OK'),
        sa.Column('breach_confidence', sa.String(10), nullable=True),
        sa.Column('last_evaluated_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('current_diameter_m', sa.Float, nullable=True),
        sa.Column('outlier_tag_id', uid, nullable=True),  # soft ref — no FK constraint
        sa.Column('pending_breach_since', sa.DateTime(timezone=True), nullable=True),
        sa.Column('pending_clear_since', sa.DateTime(timezone=True), nullable=True),
        sa.Column('consecutive_confirms', sa.Integer, nullable=False, server_default='0'),
    )


def downgrade():
    op.drop_table('hive_live_state')
    op.drop_index('ix_hive_events_hive_id_occurred_at', table_name='hive_events')
    op.drop_table('hive_events')
    op.drop_index('ix_hive_evaluations_hive_id_evaluated_at', table_name='hive_evaluations')
    op.drop_table('hive_evaluations')
    op.drop_table('hive_tag_membership')
    op.drop_table('hive_config_versions')
    op.drop_table('hives')
