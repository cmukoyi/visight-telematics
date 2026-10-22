"""Portal users' own language.

Revision ID: 075_portal_user_language
Revises: 074_add_analytics
Create Date: 2026-10-23
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy import text

revision = "075_portal_user_language"
down_revision = "074_add_analytics"
branch_labels = None
depends_on = None


def _has_column(table, column):
    return op.get_bind().execute(text(
        "SELECT 1 FROM information_schema.columns WHERE table_name = :t AND column_name = :c"),
        {"t": table, "c": column}).first() is not None


def upgrade():
    if not _has_column("portal_users", "language"):
        op.add_column("portal_users", sa.Column("language", sa.String(10), nullable=True))


def downgrade():
    if _has_column("portal_users", "language"):
        op.drop_column("portal_users", "language")
