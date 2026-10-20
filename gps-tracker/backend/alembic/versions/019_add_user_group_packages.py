"""add user_group_packages many-to-many join table

Revision ID: 019
Revises: 018
Create Date: 2026-04-24

A UserGroup can now have multiple TagPackages (e.g. 80-day, 120-day, 300-day).
Creates the user_group_packages join table and migrates any existing
user_groups.default_package_id values into it with is_default=True.
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy import text
from sqlalchemy.dialects.postgresql import UUID
import uuid


revision = '019'
down_revision = '018'
branch_labels = None
depends_on = None


def _table_exists(conn, table_name: str) -> bool:
    result = conn.execute(
        text("SELECT EXISTS (SELECT 1 FROM information_schema.tables WHERE table_name = :t)"),
        {"t": table_name},
    )
    return result.scalar()


def _column_exists(conn, table_name: str, column_name: str) -> bool:
    result = conn.execute(
        text("SELECT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name = :t AND column_name = :c)"),
        {"t": table_name, "c": column_name},
    )
    return result.scalar()


def upgrade():
    conn = op.get_bind()

    # Older installs may have created this table from revision 017 while its
    # primary key was still VARCHAR(36). The model and join-table FK use UUID.
    if _table_exists(conn, "tag_packages"):
        package_id_type = conn.execute(
            text(
                "SELECT data_type FROM information_schema.columns "
                "WHERE table_schema = current_schema() "
                "AND table_name = 'tag_packages' AND column_name = 'id'"
            )
        ).scalar()
        if package_id_type != "uuid":
            op.alter_column(
                "tag_packages",
                "id",
                existing_type=sa.String(length=36),
                type_=UUID(as_uuid=False),
                postgresql_using="id::uuid",
            )

    # 1. Create user_group_packages join table
    if not _table_exists(conn, "user_group_packages"):
        op.create_table(
            "user_group_packages",
            sa.Column("id",           UUID(as_uuid=False), primary_key=True),
            sa.Column("usergroup_id", UUID(as_uuid=False), sa.ForeignKey("user_groups.id", ondelete="CASCADE"), nullable=False),
            sa.Column("package_id",   UUID(as_uuid=False), sa.ForeignKey("tag_packages.id", ondelete="CASCADE"), nullable=False),
            sa.Column("is_default",   sa.Boolean(),  nullable=False, server_default="false"),
            sa.Column("created_at",   sa.DateTime(timezone=True), server_default=sa.func.now()),
        )
        op.create_index("ix_ugp_usergroup", "user_group_packages", ["usergroup_id"])
        op.create_unique_constraint("uq_ugp_usergroup_package", "user_group_packages", ["usergroup_id", "package_id"])

    # 2. Migrate existing default_package_id rows into the join table
    if _column_exists(conn, "user_groups", "default_package_id"):
        rows = conn.execute(
            text("SELECT id, default_package_id FROM user_groups WHERE default_package_id IS NOT NULL")
        ).fetchall()
        for group_id, pkg_id in rows:
            # Check not already migrated
            exists = conn.execute(
                text("SELECT 1 FROM user_group_packages WHERE usergroup_id = :g AND package_id = :p"),
                {"g": str(group_id), "p": str(pkg_id)},
            ).fetchone()
            if not exists:
                conn.execute(
                    text(
                        "INSERT INTO user_group_packages (id, usergroup_id, package_id, is_default) "
                        "VALUES (CAST(:id AS uuid), CAST(:g AS uuid), CAST(:p AS uuid), true)"
                    ),
                    {"id": str(uuid.uuid4()), "g": str(group_id), "p": str(pkg_id)},
                )


def downgrade():
    # Leave user_group_packages — dropping it could destroy data
    pass
