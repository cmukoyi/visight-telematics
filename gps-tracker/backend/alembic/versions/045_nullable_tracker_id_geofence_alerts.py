"""make geofence_alerts.tracker_id nullable

Old rows created before the tracker_id FK was added have NULL in this column.
SQLAlchemy was crashing trying to bulk-UPDATE those rows with tracker_id=None
against the NOT NULL constraint.

Revision ID: 045_nullable_tracker_id_geofence_alerts
Revises: 044_allowed_tag_types
Create Date: 2026-06-07 12:00:00.000000
"""
from alembic import op


# revision identifiers, used by Alembic.
revision = '045_nullable_tracker_id'
down_revision = '044_allowed_tag_types'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.alter_column('geofence_alerts', 'tracker_id', nullable=True)
    op.alter_column('poi_tracker_links', 'tracker_id', nullable=True)


def downgrade() -> None:
    # Only safe if all rows actually have tracker_id values.
    op.alter_column('geofence_alerts', 'tracker_id', nullable=False)
    op.alter_column('poi_tracker_links', 'tracker_id', nullable=False)
