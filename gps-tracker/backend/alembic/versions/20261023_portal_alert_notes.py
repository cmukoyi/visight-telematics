"""Inbox: notes on an alert, and who processed (read) it and when.

Revision ID: 077_portal_alert_notes
Revises: 076_green_driving_io
Create Date: 2026-10-23
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy import text

revision = "077_portal_alert_notes"
down_revision = "076_green_driving_io"
branch_labels = None
depends_on = None

COLUMNS = [
    ("notes", sa.Text()),
    ("read_at", sa.DateTime(timezone=True)),
    ("read_by", sa.String(255)),
]


def _has_column(table, column):
    return op.get_bind().execute(text(
        "SELECT 1 FROM information_schema.columns WHERE table_name = :t AND column_name = :c"),
        {"t": table, "c": column}).first() is not None


def upgrade():
    for name, type_ in COLUMNS:
        if not _has_column("portal_alerts", name):
            op.add_column("portal_alerts", sa.Column(name, type_, nullable=True))


def downgrade():
    for name, _ in COLUMNS:
        if _has_column("portal_alerts", name):
            op.drop_column("portal_alerts", name)
