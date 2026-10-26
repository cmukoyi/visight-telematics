"""Breakdowns logged from the mobile app (each also runs as a "Breakdown" maintenance job).

Revision ID: 087_vehicle_breakdowns
Revises: 086_location_format
Create Date: 2026-10-26
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy import text
from sqlalchemy.dialects.postgresql import UUID

revision = "087_vehicle_breakdowns"
down_revision = "086_location_format"
branch_labels = None
depends_on = None


def _has_table(name):
    return op.get_bind().execute(text("SELECT to_regclass(:n) IS NOT NULL"), {"n": name}).scalar()


def upgrade():
    if _has_table("vehicle_breakdowns"):
        return
    op.create_table(
        "vehicle_breakdowns",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("usergroup_id", UUID(as_uuid=True), sa.ForeignKey("user_groups.id", ondelete="CASCADE"), nullable=False, index=True),
        sa.Column("imei", sa.String(20), nullable=False, index=True),
        sa.Column("job_id", UUID(as_uuid=True), sa.ForeignKey("vehicle_maintenance.id", ondelete="SET NULL"), nullable=True),
        sa.Column("reported_by_id", UUID(as_uuid=True), nullable=True),
        sa.Column("reported_by", sa.String(255), nullable=True),
        sa.Column("driver", sa.String(200), nullable=True),
        sa.Column("cause", sa.String(60), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("ended_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("start_lat", sa.Float(), nullable=True),
        sa.Column("start_lng", sa.Float(), nullable=True),
        sa.Column("start_accuracy", sa.Float(), nullable=True),
        sa.Column("end_lat", sa.Float(), nullable=True),
        sa.Column("end_lng", sa.Float(), nullable=True),
        sa.Column("phases", sa.JSON(), nullable=False, server_default="[]"),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("review", sa.String(20), nullable=True),
        sa.Column("review_note", sa.Text(), nullable=True),
        sa.Column("reviewed_by", sa.String(255), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("ix_breakdown_group_started", "vehicle_breakdowns", ["usergroup_id", "started_at"])


def downgrade():
    op.drop_table("vehicle_breakdowns")
