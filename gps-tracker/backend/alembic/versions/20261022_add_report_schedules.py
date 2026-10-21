"""Scheduled, emailed reports.

Revision ID: 067_add_report_schedules
Revises: 066_add_trips
Create Date: 2026-10-22
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy import text
from sqlalchemy.dialects.postgresql import UUID

revision = "067_add_report_schedules"
down_revision = "066_add_trips"
branch_labels = None
depends_on = None


def upgrade():
    conn = op.get_bind()
    exists = conn.execute(text(
        "SELECT EXISTS (SELECT 1 FROM information_schema.tables WHERE table_name = 'report_schedules')")).scalar()
    if not exists:
        op.create_table(
            "report_schedules",
            sa.Column("id", UUID(as_uuid=True), primary_key=True),
            sa.Column("usergroup_id", UUID(as_uuid=True), sa.ForeignKey("user_groups.id"), nullable=False),
            sa.Column("created_by", UUID(as_uuid=True), sa.ForeignKey("portal_users.id", ondelete="SET NULL"), nullable=True),
            sa.Column("report_key", sa.String(40), nullable=False),
            sa.Column("name", sa.String(120), nullable=True),
            sa.Column("frequency", sa.String(10), nullable=False),
            sa.Column("file_format", sa.String(10), nullable=False, server_default="xlsx"),
            sa.Column("recipients", sa.JSON(), nullable=False),
            sa.Column("params", sa.JSON(), nullable=True),
            sa.Column("timezone", sa.String(40), nullable=False, server_default="Africa/Johannesburg"),
            sa.Column("send_hour", sa.Integer(), nullable=False, server_default="6"),
            sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
            sa.Column("next_run_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("last_run_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("last_status", sa.String(255), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        )
    op.execute("CREATE INDEX IF NOT EXISTS ix_report_schedules_due ON report_schedules (is_active, next_run_at)")


def downgrade():
    op.drop_table("report_schedules")
