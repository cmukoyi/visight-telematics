"""Notification rules on chosen event types; white-label theme settings per user group.

Revision ID: 072_event_rule_codes_theme
Revises: 071_add_place_and_event_groups
Create Date: 2026-10-22
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy import text

revision = "072_event_rule_codes_theme"
down_revision = "071_add_place_and_event_groups"
branch_labels = None
depends_on = None


def _has_column(table, column):
    return op.get_bind().execute(text(
        "SELECT 1 FROM information_schema.columns WHERE table_name = :t AND column_name = :c"),
        {"t": table, "c": column}).first() is not None


def upgrade():
    if not _has_column("notification_rules", "event_codes"):
        op.add_column("notification_rules", sa.Column("event_codes", sa.JSON(), nullable=True))
    if not _has_column("user_groups", "theme_settings"):
        op.add_column("user_groups", sa.Column("theme_settings", sa.JSON(), nullable=True))


def downgrade():
    if _has_column("user_groups", "theme_settings"):
        op.drop_column("user_groups", "theme_settings")
    if _has_column("notification_rules", "event_codes"):
        op.drop_column("notification_rules", "event_codes")
