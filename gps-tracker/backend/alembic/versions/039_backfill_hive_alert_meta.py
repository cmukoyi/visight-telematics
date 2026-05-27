"""backfill hive_name into portal_alerts.meta_data for historical hive alerts

Revision ID: 039
Revises: 038
Create Date: 2026-05-28

Hive alerts emitted before commit a28d95c stored only hive_id in meta_data,
so the customer dashboard's Alerts Inbox rendered the Asset column as '—'
for any hive_breach / hive_breach_cleared / hive_resolved_by_transit row.

This migration joins each historical hive alert back to its hive and writes
the hive's name into meta_data.hive_name. It only touches rows that:

  * have alert_type starting with 'hive_'
  * either have NULL meta_data, or have meta_data without a hive_name key
  * carry a hive_id that resolves to an existing row in hives

PortalAlert.meta_data is declared as JSON, but PostgreSQL accepts the JSONB
operators after a cast, which is what we use below. Downgrade is a no-op:
deleting the backfilled key would only re-break the UI for old rows, and the
7-day alert retention job will sweep them away on its own.
"""
from alembic import op


revision = "039"
down_revision = "038"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        UPDATE portal_alerts AS pa
        SET meta_data = jsonb_set(
            pa.meta_data::jsonb,
            '{hive_name}',
            to_jsonb(h.name)
        )::json
        FROM hives AS h
        WHERE pa.alert_type LIKE 'hive\\_%' ESCAPE '\\'
          AND pa.meta_data IS NOT NULL
          AND NOT (pa.meta_data::jsonb ? 'hive_name')
          AND (pa.meta_data::jsonb ->> 'hive_id') = h.id::text;
        """
    )


def downgrade() -> None:
    # Intentional no-op: backfill is purely additive and harmless.
    pass
