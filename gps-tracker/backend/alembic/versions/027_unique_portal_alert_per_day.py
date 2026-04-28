"""Add unique partial index on portal_alerts to prevent duplicate alerts
on the same day for the same tag+group+type.

This is a defence-in-depth guard against race conditions (e.g. two poller
processes running simultaneously). The functional dedup still happens in
Python (_recent_alert_exists), but the DB now also enforces it.

Revision ID: 027
Revises: 026
Create Date: 2026-04-28
"""
from alembic import op
from sqlalchemy import text


revision = '027'
down_revision = '026'
branch_labels = None
depends_on = None


def upgrade():
    conn = op.get_bind()

    # ── Step 1: delete duplicate rows, keeping the oldest per day ────────────
    # The 2-worker bug may have created multiple rows for the same
    # (usergroup_id, tag_id, alert_type, day). Keep the one with the lowest id
    # (earliest insert) and delete the rest.
    conn.execute(
        text(
            """
            DELETE FROM portal_alerts
            WHERE id IN (
                SELECT id FROM (
                    SELECT id,
                           ROW_NUMBER() OVER (
                               PARTITION BY usergroup_id,
                                            tag_id,
                                            alert_type,
                                            DATE(created_at AT TIME ZONE 'UTC')
                               ORDER BY created_at ASC
                           ) AS rn
                    FROM portal_alerts
                    WHERE tag_id IS NOT NULL
                ) ranked
                WHERE rn > 1
            )
            """
        )
    )

    # ── Step 2: create the unique index (safe now) ────────────────────────────
    existing = conn.execute(
        text(
            "SELECT EXISTS (SELECT 1 FROM pg_indexes "
            "WHERE indexname = 'uq_portal_alert_per_day')"
        )
    ).scalar()

    if not existing:
        op.execute(
            """
            CREATE UNIQUE INDEX uq_portal_alert_per_day
            ON portal_alerts (
                usergroup_id,
                tag_id,
                alert_type,
                DATE(created_at AT TIME ZONE 'UTC')
            )
            WHERE tag_id IS NOT NULL
            """
        )


def downgrade():
    op.execute("DROP INDEX IF EXISTS uq_portal_alert_per_day")
