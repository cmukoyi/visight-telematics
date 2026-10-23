"""Custom reports (categories, reports, runs) and Analytics "Recently deleted" pages.

Revision ID: 085_custom_reports
Revises: 084_fleet_costs_scores
Create Date: 2026-10-24
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy import text

revision = "085_custom_reports"
down_revision = "084_fleet_costs_scores"
branch_labels = None
depends_on = None


def _has_column(table, column):
    return op.get_bind().execute(text(
        "SELECT 1 FROM information_schema.columns WHERE table_name = :t AND column_name = :c"),
        {"t": table, "c": column}).first() is not None


def _tables():
    from app import models_reports as m
    return [m.CustomReportCategory.__table__, m.CustomReport.__table__, m.CustomReportRun.__table__]


def upgrade():
    if not _has_column("analytics_pages", "deleted_at"):
        op.add_column("analytics_pages", sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True))
    bind = op.get_bind()
    for table in _tables():
        table.create(bind, checkfirst=True)


def downgrade():
    bind = op.get_bind()
    for table in reversed(_tables()):
        table.drop(bind, checkfirst=True)
    if _has_column("analytics_pages", "deleted_at"):
        op.drop_column("analytics_pages", "deleted_at")
