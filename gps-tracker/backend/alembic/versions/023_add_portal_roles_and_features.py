"""Add portal roles and feature access control

- user_groups.allowed_sections  (JSON) – which top-level sections
  (tracking / management / reports) are enabled for this tenant.
  NULL means all sections are enabled (default, backward-compatible).

- portal_users.role  (VARCHAR 20) – system role for the user.
  Values: 'admin' | 'manager' | 'reporter' | 'custom'.
  Default 'admin' keeps all existing users fully privileged.

- portal_users.custom_features  (JSON) – list of tab keys visible when
  role = 'custom'. Ignored for other roles.

Revision ID: 023
Revises: 022
Create Date: 2026-04-26
"""
from alembic import op
import sqlalchemy as sa
import json

revision = "023"
down_revision = "022"
branch_labels = None
depends_on = None


def upgrade():
    # ── user_groups: allowed_sections ─────────────────────────────────────
    with op.batch_alter_table("user_groups") as batch_op:
        batch_op.add_column(
            sa.Column(
                "allowed_sections",
                sa.JSON(),
                nullable=True,
                comment="List of enabled section keys: tracking|management|reports. NULL = all.",
            )
        )

    # ── portal_users: role + custom_features ──────────────────────────────
    with op.batch_alter_table("portal_users") as batch_op:
        batch_op.add_column(
            sa.Column(
                "role",
                sa.String(20),
                nullable=False,
                server_default="admin",
                comment="admin|manager|reporter|custom",
            )
        )
        batch_op.add_column(
            sa.Column(
                "custom_features",
                sa.JSON(),
                nullable=True,
                comment="Tab keys visible when role=custom.",
            )
        )


def downgrade():
    with op.batch_alter_table("portal_users") as batch_op:
        batch_op.drop_column("custom_features")
        batch_op.drop_column("role")

    with op.batch_alter_table("user_groups") as batch_op:
        batch_op.drop_column("allowed_sections")
