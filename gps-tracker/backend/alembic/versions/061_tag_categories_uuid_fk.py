"""Align tag category UUID columns with user_groups.

Revision ID: 061_tag_categories_uuid_fk
Revises: reset_temp_graph_translations
Create Date: 2026-10-20
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy import text
from sqlalchemy.dialects.postgresql import UUID


revision = "061_tag_categories_uuid_fk"
down_revision = "reset_temp_graph_translations"
branch_labels = None
depends_on = None


def upgrade():
    connection = op.get_bind()
    table_exists = connection.execute(
        text(
            "SELECT EXISTS (SELECT 1 FROM information_schema.tables "
            "WHERE table_schema = current_schema() AND table_name = 'tag_categories')"
        )
    ).scalar()
    if not table_exists:
        return

    connection.execute(
        text("ALTER TABLE tag_categories DROP CONSTRAINT IF EXISTS tag_categories_usergroup_id_fkey")
    )

    for column_name in ("id", "usergroup_id"):
        column_type = connection.execute(
            text(
                "SELECT data_type FROM information_schema.columns "
                "WHERE table_schema = current_schema() "
                "AND table_name = 'tag_categories' AND column_name = :column_name"
            ),
            {"column_name": column_name},
        ).scalar()
        if column_type != "uuid":
            op.alter_column(
                "tag_categories",
                column_name,
                existing_type=sa.String(length=36),
                type_=UUID(as_uuid=True),
                postgresql_using=f"{column_name}::uuid",
            )

    connection.execute(
        text(
            "ALTER TABLE tag_categories "
            "ADD CONSTRAINT tag_categories_usergroup_id_fkey "
            "FOREIGN KEY (usergroup_id) REFERENCES user_groups (id)"
        )
    )


def downgrade():
    raise NotImplementedError("UUID alignment is intentionally irreversible")