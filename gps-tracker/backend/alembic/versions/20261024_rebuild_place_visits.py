"""Rebuild place visits from stored positions, so place reports have history.

Revision 078 only recorded entries/exits from then on. This replays every
group's stored GPS fixes against its places (geofence_engine.rebuild_visits).

Revision ID: 080_rebuild_place_visits
Revises: 079_restore_harsh_repeats
Create Date: 2026-10-24
"""
from alembic import op
from sqlalchemy import text
from sqlalchemy.orm import Session

revision = "080_rebuild_place_visits"
down_revision = "079_restore_harsh_repeats"
branch_labels = None
depends_on = None


def upgrade():
    conn = op.get_bind()
    if not conn.execute(text("SELECT to_regclass('place_visits') IS NOT NULL")).scalar():
        return
    from app.services.geofence_engine import rebuild_visits
    db = Session(bind=conn)
    groups = conn.execute(text("SELECT DISTINCT usergroup_id FROM pois WHERE is_active AND usergroup_id IS NOT NULL")).scalars().all()
    for group_id in groups:
        rebuild_visits(db, group_id)
    db.flush()


def downgrade():
    pass
