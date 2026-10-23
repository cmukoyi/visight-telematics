"""Place visits (entry … exit per vehicle and place), for place reports.

Revision ID: 078_place_visits
Revises: 077_portal_alert_notes
Create Date: 2026-10-24
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy import text
from sqlalchemy.dialects.postgresql import UUID

revision = "078_place_visits"
down_revision = "077_portal_alert_notes"
branch_labels = None
depends_on = None


def _has_table(name):
    return op.get_bind().execute(text("SELECT to_regclass(:n) IS NOT NULL"), {"n": name}).scalar()


def upgrade():
    if _has_table("place_visits"):
        return
    op.create_table(
        "place_visits",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("usergroup_id", UUID(as_uuid=True), sa.ForeignKey("user_groups.id", ondelete="CASCADE"), nullable=False),
        sa.Column("tag_id", UUID(as_uuid=True), sa.ForeignKey("ble_tags.id", ondelete="CASCADE"), nullable=False),
        sa.Column("imei", sa.String(20), nullable=False),
        sa.Column("poi_id", UUID(as_uuid=True), sa.ForeignKey("pois.id", ondelete="CASCADE"), nullable=False),
        sa.Column("entered_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("exited_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("entry_speed", sa.Integer(), nullable=True),
        sa.Column("exit_speed", sa.Integer(), nullable=True),
    )
    op.create_index("ix_place_visits_group_entered", "place_visits", ["usergroup_id", "entered_at"])
    op.create_index("ix_place_visits_group_exited", "place_visits", ["usergroup_id", "exited_at"])
    op.create_index("ix_place_visits_open", "place_visits", ["tag_id", "poi_id", "exited_at"])


def downgrade():
    if _has_table("place_visits"):
        op.drop_table("place_visits")
