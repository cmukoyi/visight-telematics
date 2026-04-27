"""add package management columns to existing tables

Revision ID: 017
Revises: 016
Create Date: 2026-04-24

Adds columns and the tag_packages table that were introduced by the
package-management feature but shipped without a migration:

  • tag_packages table (new)  – with auto_delete_days
  • ble_tags.package_id       – FK to tag_packages
  • ble_tags.expiry_date      – datetime when the tag subscription expires
  • portal_users.expires_at   – when the portal-user account expires
  • user_groups.default_package_id – FK to tag_packages

All operations are idempotent (column_exists / table_exists guards) so the
migration is safe to run against a DB that already has some of these objects.
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy import text
from sqlalchemy.dialects.postgresql import UUID


revision = '017'
down_revision = ('016', 'add_admin_models')   # merges main chain + admin branch into one head
branch_labels = None
depends_on = None


# ── helpers ───────────────────────────────────────────────────────────────────

def _table_exists(conn, table_name: str) -> bool:
    result = conn.execute(
        text(
            "SELECT EXISTS (SELECT 1 FROM information_schema.tables "
            "WHERE table_name = :t)"
        ),
        {"t": table_name},
    )
    return result.scalar()


def _column_exists(conn, table_name: str, column_name: str) -> bool:
    result = conn.execute(
        text(
            "SELECT EXISTS (SELECT 1 FROM information_schema.columns "
            "WHERE table_name = :t AND column_name = :c)"
        ),
        {"t": table_name, "c": column_name},
    )
    return result.scalar()


# ── upgrade ───────────────────────────────────────────────────────────────────

def upgrade():
    conn = op.get_bind()

    # ── 1. tag_packages table ─────────────────────────────────────────────────
    if not _table_exists(conn, "tag_packages"):
        op.create_table(
            "tag_packages",
            sa.Column("id",               sa.String(36),  primary_key=True),
            sa.Column("name",             sa.String(100), nullable=False, unique=True),
            sa.Column("description",      sa.Text(),      nullable=True),
            sa.Column("validity_days",    sa.Integer(),   nullable=False),
            sa.Column("auto_delete_days", sa.Integer(),   nullable=True),
            sa.Column("is_default",       sa.Boolean(),   nullable=False, server_default="false"),
            sa.Column("is_active",        sa.Boolean(),   nullable=False, server_default="true"),
            sa.Column("created_at",       sa.DateTime(timezone=True), server_default=sa.func.now()),
            sa.Column("updated_at",       sa.DateTime(timezone=True), nullable=True),
        )
    else:
        # Table already exists — make sure auto_delete_days is present
        if not _column_exists(conn, "tag_packages", "auto_delete_days"):
            op.add_column(
                "tag_packages",
                sa.Column("auto_delete_days", sa.Integer(), nullable=True),
            )

    # ── 2. ble_tags.package_id ────────────────────────────────────────────────
    # No FK: tag_packages.id is UUID but this column is VARCHAR — type mismatch.
    # The application resolves packages via str() comparisons, not DB-level FK.
    if not _column_exists(conn, "ble_tags", "package_id"):
        op.add_column(
            "ble_tags",
            sa.Column("package_id", sa.String(36), nullable=True),
        )
        op.create_index("ix_ble_tags_package_id", "ble_tags", ["package_id"])

    # ── 3. ble_tags.expiry_date ───────────────────────────────────────────────
    if not _column_exists(conn, "ble_tags", "expiry_date"):
        op.add_column(
            "ble_tags",
            sa.Column("expiry_date", sa.DateTime(timezone=True), nullable=True),
        )

    # ── 4. portal_users.expires_at ────────────────────────────────────────────
    if not _column_exists(conn, "portal_users", "expires_at"):
        op.add_column(
            "portal_users",
            sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        )

    # ── 5. user_groups.default_package_id ────────────────────────────────────
    # No FK: same UUID vs VARCHAR mismatch as above.
    if not _column_exists(conn, "user_groups", "default_package_id"):
        op.add_column(
            "user_groups",
            sa.Column("default_package_id", sa.String(36), nullable=True),
        )


# ── downgrade ─────────────────────────────────────────────────────────────────

def downgrade():
    conn = op.get_bind()

    if _column_exists(conn, "user_groups", "default_package_id"):
        op.drop_column("user_groups", "default_package_id")

    if _column_exists(conn, "portal_users", "expires_at"):
        op.drop_column("portal_users", "expires_at")

    if _column_exists(conn, "ble_tags", "expiry_date"):
        op.drop_column("ble_tags", "expiry_date")

    if _column_exists(conn, "ble_tags", "package_id"):
        try:
            op.drop_index("ix_ble_tags_package_id", table_name="ble_tags")
        except Exception:
            pass
        op.drop_column("ble_tags", "package_id")

    # Leave tag_packages in place on downgrade — dropping it could cascade
    # and destroy production data.
