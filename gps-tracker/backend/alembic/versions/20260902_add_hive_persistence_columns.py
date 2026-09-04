"""add missing Hive persistence columns

Revision ID: add_hive_persistence_columns
Revises: add_reconciliation_watermark
Create Date: 2026-09-02

The Hive model uses these fields for duration-based breach confirmation. Older
standalone migrations were not on the active Alembic chain, leaving existing
deployments with model/schema drift.
"""
from alembic import op
import sqlalchemy as sa


revision = "add_hive_persistence_columns"
down_revision = "add_reconciliation_watermark"
branch_labels = None
depends_on = None


def upgrade():
    connection = op.get_bind()
    columns = {column["name"] for column in sa.inspect(connection).get_columns("hive_live_state")}

    if "breach_persistence_eval_count" not in columns:
        op.add_column(
            "hive_live_state",
            sa.Column("breach_persistence_eval_count", sa.Integer(), nullable=False, server_default="0"),
        )
    if "breach_persistence_first_fingerprint" not in columns:
        op.add_column(
            "hive_live_state",
            sa.Column("breach_persistence_first_fingerprint", sa.String(length=64), nullable=True),
        )


def downgrade():
    connection = op.get_bind()
    columns = {column["name"] for column in sa.inspect(connection).get_columns("hive_live_state")}

    if "breach_persistence_first_fingerprint" in columns:
        op.drop_column("hive_live_state", "breach_persistence_first_fingerprint")
    if "breach_persistence_eval_count" in columns:
        op.drop_column("hive_live_state", "breach_persistence_eval_count")