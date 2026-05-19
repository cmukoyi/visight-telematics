"""035 add motion awareness fields (HIVE Phase 3 / spec v1.1)

Adds motion-detection columns to support the four-state motion machine
(STATIONARY / PRE_TRANSIT / IN_TRANSIT / SETTLING) per
features_dev/HIVE_Architecture_Specification_v1.1.md sections 2.3, 3.x,
and 11.

All new columns are nullable (or have safe defaults) so existing rows
remain valid without backfill — motion state defaults to 'STATIONARY'
on first evaluation.

Revision ID: 035
Revises: 034
Create Date: 2026-05-19
"""
from alembic import op
import sqlalchemy as sa


revision = '035'
down_revision = '034'
branch_labels = None
depends_on = None


def upgrade():
    # ── hive_config_versions: persist the profile-derived motion thresholds
    #    so historical evaluations can be audited against the exact tuning
    #    that was active at the time.
    op.add_column('hive_config_versions',
                  sa.Column('motion_speed_threshold_kmh', sa.Float, nullable=True))
    op.add_column('hive_config_versions',
                  sa.Column('motion_settling_time_s', sa.Integer, nullable=True))
    op.add_column('hive_config_versions',
                  sa.Column('coherence_speed_tol_kmh', sa.Float, nullable=True))
    op.add_column('hive_config_versions',
                  sa.Column('coherence_bearing_tol_deg', sa.Float, nullable=True))

    # ── hive_evaluations: annotate each evaluation with the motion state
    #    that was active when it ran (so suppressed evaluations are
    #    distinguishable from real OK results during analysis).
    op.add_column('hive_evaluations',
                  sa.Column('motion_state', sa.String(20), nullable=True))
    op.add_column('hive_evaluations',
                  sa.Column('centroid_speed_kmh', sa.Float, nullable=True))

    # ── hive_live_state: motion state machine + centroid tracking.
    #    centroid_anchor_* is the older snapshot we measure velocity
    #    against (rolling ~5 min window per spec §11.3).
    op.add_column('hive_live_state',
                  sa.Column('motion_state', sa.String(20), nullable=False,
                            server_default='STATIONARY'))
    op.add_column('hive_live_state',
                  sa.Column('motion_state_since', sa.DateTime(timezone=True), nullable=True))
    op.add_column('hive_live_state',
                  sa.Column('pending_motion_change_since', sa.DateTime(timezone=True), nullable=True))
    op.add_column('hive_live_state',
                  sa.Column('centroid_lat', sa.Float, nullable=True))
    op.add_column('hive_live_state',
                  sa.Column('centroid_lng', sa.Float, nullable=True))
    op.add_column('hive_live_state',
                  sa.Column('centroid_speed_kmh', sa.Float, nullable=True))
    op.add_column('hive_live_state',
                  sa.Column('centroid_bearing_deg', sa.Float, nullable=True))
    op.add_column('hive_live_state',
                  sa.Column('centroid_anchor_lat', sa.Float, nullable=True))
    op.add_column('hive_live_state',
                  sa.Column('centroid_anchor_lng', sa.Float, nullable=True))
    op.add_column('hive_live_state',
                  sa.Column('centroid_anchor_at', sa.DateTime(timezone=True), nullable=True))

    # ── hive_tag_membership: per-tag velocity vector (for the group
    #    coherence check, spec §11.4). Kept here rather than a new table
    #    because membership is 1:1 with active tag and the vector is
    #    meaningless once the tag leaves the hive.
    op.add_column('hive_tag_membership',
                  sa.Column('velocity_speed_kmh', sa.Float, nullable=True))
    op.add_column('hive_tag_membership',
                  sa.Column('velocity_bearing_deg', sa.Float, nullable=True))
    op.add_column('hive_tag_membership',
                  sa.Column('velocity_computed_at', sa.DateTime(timezone=True), nullable=True))
    op.add_column('hive_tag_membership',
                  sa.Column('previous_lat', sa.Float, nullable=True))
    op.add_column('hive_tag_membership',
                  sa.Column('previous_lng', sa.Float, nullable=True))
    op.add_column('hive_tag_membership',
                  sa.Column('previous_seen_at', sa.DateTime(timezone=True), nullable=True))


def downgrade():
    op.drop_column('hive_tag_membership', 'previous_seen_at')
    op.drop_column('hive_tag_membership', 'previous_lng')
    op.drop_column('hive_tag_membership', 'previous_lat')
    op.drop_column('hive_tag_membership', 'velocity_computed_at')
    op.drop_column('hive_tag_membership', 'velocity_bearing_deg')
    op.drop_column('hive_tag_membership', 'velocity_speed_kmh')

    op.drop_column('hive_live_state', 'centroid_anchor_at')
    op.drop_column('hive_live_state', 'centroid_anchor_lng')
    op.drop_column('hive_live_state', 'centroid_anchor_lat')
    op.drop_column('hive_live_state', 'centroid_bearing_deg')
    op.drop_column('hive_live_state', 'centroid_speed_kmh')
    op.drop_column('hive_live_state', 'centroid_lng')
    op.drop_column('hive_live_state', 'centroid_lat')
    op.drop_column('hive_live_state', 'pending_motion_change_since')
    op.drop_column('hive_live_state', 'motion_state_since')
    op.drop_column('hive_live_state', 'motion_state')

    op.drop_column('hive_evaluations', 'centroid_speed_kmh')
    op.drop_column('hive_evaluations', 'motion_state')

    op.drop_column('hive_config_versions', 'coherence_bearing_tol_deg')
    op.drop_column('hive_config_versions', 'coherence_speed_tol_kmh')
    op.drop_column('hive_config_versions', 'motion_settling_time_s')
    op.drop_column('hive_config_versions', 'motion_speed_threshold_kmh')
