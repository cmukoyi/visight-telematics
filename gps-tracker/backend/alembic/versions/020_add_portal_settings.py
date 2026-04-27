"""add portal settings: branding, data retention, notification prefs

Revision ID: 020
Revises: 019
Create Date: 2026-04-25

Adds:
  user_groups: logo_data, theme_primary, theme_accent, history_retention_days
  portal_users: alerts_enabled, notify_geofence_exit, notify_battery_low,
                notify_offline, notify_via_email
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy import text


revision = '020'
down_revision = '019'
branch_labels = None
depends_on = None


def _column_exists(conn, table_name: str, column_name: str) -> bool:
    result = conn.execute(
        text(
            "SELECT EXISTS (SELECT 1 FROM information_schema.columns "
            "WHERE table_name = :t AND column_name = :c)"
        ),
        {"t": table_name, "c": column_name},
    )
    return result.scalar()


def upgrade():
    conn = op.get_bind()

    # ── user_groups: branding + retention ────────────────────────────────
    if not _column_exists(conn, "user_groups", "logo_data"):
        op.add_column("user_groups", sa.Column("logo_data", sa.Text(), nullable=True))
    if not _column_exists(conn, "user_groups", "theme_primary"):
        op.add_column("user_groups", sa.Column("theme_primary", sa.String(20), nullable=True))
    if not _column_exists(conn, "user_groups", "theme_accent"):
        op.add_column("user_groups", sa.Column("theme_accent", sa.String(20), nullable=True))
    if not _column_exists(conn, "user_groups", "history_retention_days"):
        op.add_column("user_groups", sa.Column(
            "history_retention_days", sa.Integer(), nullable=True,
            server_default="365",
        ))

    # ── portal_users: notification prefs ─────────────────────────────────
    for col_name in ("alerts_enabled", "notify_geofence_exit",
                     "notify_battery_low", "notify_offline", "notify_via_email"):
        if not _column_exists(conn, "portal_users", col_name):
            op.add_column("portal_users", sa.Column(
                col_name, sa.Boolean(), nullable=False, server_default="true",
            ))


def downgrade():
    # Additive only — do not drop
    pass
