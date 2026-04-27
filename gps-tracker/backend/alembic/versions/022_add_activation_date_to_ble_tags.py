"""add activation_date to ble_tags

Activation date records when a tag first receives a GPS location.
Package expiry is calculated from this date (activation_date + validity_days)
instead of from when the package was assigned.

Revision ID: 022
Revises: 021
Create Date: 2026-05-01
"""
from alembic import op
import sqlalchemy as sa

revision = "022"
down_revision = "021"
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table("ble_tags") as batch_op:
        batch_op.add_column(
            sa.Column(
                "activation_date",
                sa.DateTime(timezone=True),
                nullable=True,
                comment="Timestamp of first GPS fix; package expiry = activation_date + validity_days",
            )
        )


def downgrade():
    with op.batch_alter_table("ble_tags") as batch_op:
        batch_op.drop_column("activation_date")
