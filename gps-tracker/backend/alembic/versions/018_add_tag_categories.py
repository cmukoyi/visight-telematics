"""add tag_categories table

Revision ID: 018
Revises: 017
Create Date: 2026-04-24

Creates the tag_categories table introduced by the asset categories feature.
This table was previously only created by SQLAlchemy's create_all() on startup;
this migration makes it explicit and idempotent.
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy import text


revision = '018'
down_revision = '017'
branch_labels = None
depends_on = None


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


def upgrade():
    conn = op.get_bind()

    if not _table_exists(conn, "tag_categories"):
        op.create_table(
            "tag_categories",
            sa.Column("id",           sa.String(36),  primary_key=True),
            sa.Column("usergroup_id", sa.String(36),  sa.ForeignKey("user_groups.id"), nullable=False),
            sa.Column("name",         sa.String(100), nullable=False),
            sa.Column("icon",         sa.String(50),  nullable=True),
            sa.Column("color",        sa.String(20),  nullable=True),
            sa.Column("is_active",    sa.Boolean(),   nullable=False, server_default="true"),
            sa.Column("created_at",   sa.DateTime(timezone=True), server_default=sa.func.now()),
            sa.Column("updated_at",   sa.DateTime(timezone=True), nullable=True),
        )
        op.create_index("ix_tag_categories_usergroup", "tag_categories", ["usergroup_id"])
    else:
        # Table exists — ensure all columns are present (handles partial creates)
        for col_name, col_def in [
            ("icon",  sa.Column("icon",  sa.String(50), nullable=True)),
            ("color", sa.Column("color", sa.String(20), nullable=True)),
        ]:
            if not _column_exists(conn, "tag_categories", col_name):
                op.add_column("tag_categories", col_def)


def downgrade():
    # Leave tag_categories in place — dropping it could destroy user data.
    pass
