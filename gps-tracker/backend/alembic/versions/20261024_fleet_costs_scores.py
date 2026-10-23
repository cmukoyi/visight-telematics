"""Fleet costs and scores: fleet settings, cost categories, trip speeding / idle durations.

Back-fills the new trip durations from stored events (trips of the last 120 days).

Revision ID: 084_fleet_costs_scores
Revises: 083_drivers_time_profiles
Create Date: 2026-10-24
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy import text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Session

revision = "084_fleet_costs_scores"
down_revision = "083_drivers_time_profiles"
branch_labels = None
depends_on = None

TRIP_COLUMNS = [
    ("speeding_s", sa.Integer(), "0"), ("idle_s", sa.Integer(), "0"), ("excess_idle_s", sa.Integer(), "0"),
    ("idle_since", sa.DateTime(timezone=True), None), ("last_speed", sa.Integer(), None),
]


def _has_table(name):
    return op.get_bind().execute(text("SELECT to_regclass(:n) IS NOT NULL"), {"n": name}).scalar()


def _has_column(table, column):
    return op.get_bind().execute(text(
        "SELECT 1 FROM information_schema.columns WHERE table_name = :t AND column_name = :c"),
        {"t": table, "c": column}).first() is not None


def upgrade():
    if not _has_table("fleet_settings"):
        op.create_table(
            "fleet_settings",
            sa.Column("usergroup_id", UUID(as_uuid=True), sa.ForeignKey("user_groups.id", ondelete="CASCADE"), primary_key=True),
            sa.Column("values", sa.JSON(), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        )
    if _has_table("maintenance_costs") and not _has_column("maintenance_costs", "category"):
        op.add_column("maintenance_costs", sa.Column("category", sa.String(20), nullable=False, server_default="maintenance"))
    if _has_table("trips"):
        for name, type_, default in TRIP_COLUMNS:
            if not _has_column("trips", name):
                op.add_column("trips", sa.Column(name, type_, nullable=default is None,
                                                 server_default=default))
        from app.services import trip_builder
        trip_builder.recompute_recent(Session(bind=op.get_bind()), days=120)


def downgrade():
    for name, _, _ in TRIP_COLUMNS:
        if _has_column("trips", name):
            op.drop_column("trips", name)
    if _has_column("maintenance_costs", "category"):
        op.drop_column("maintenance_costs", "category")
    if _has_table("fleet_settings"):
        op.drop_table("fleet_settings")
