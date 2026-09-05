"""link promoted portal users to Flutter user credentials

Revision ID: link_portal_flutter_users
Revises: add_hive_persistence_columns
Create Date: 2026-09-05
"""
from alembic import op
import sqlalchemy as sa


revision = "link_portal_flutter_users"
down_revision = "add_hive_persistence_columns"
branch_labels = None
depends_on = None


def upgrade():
    connection = op.get_bind()
    columns = {column["name"] for column in sa.inspect(connection).get_columns("portal_users")}
    if "mobile_user_id" not in columns:
        op.add_column("portal_users", sa.Column("mobile_user_id", sa.UUID(), nullable=True))
        op.create_foreign_key("fk_portal_users_mobile_user_id", "portal_users", "users", ["mobile_user_id"], ["id"], ondelete="SET NULL")
        op.create_unique_constraint("uq_portal_users_mobile_user_id", "portal_users", ["mobile_user_id"])
        op.create_index("ix_portal_users_mobile_user_id", "portal_users", ["mobile_user_id"])


def downgrade():
    connection = op.get_bind()
    columns = {column["name"] for column in sa.inspect(connection).get_columns("portal_users")}
    if "mobile_user_id" in columns:
        op.drop_index("ix_portal_users_mobile_user_id", table_name="portal_users")
        op.drop_constraint("uq_portal_users_mobile_user_id", "portal_users", type_="unique")
        op.drop_constraint("fk_portal_users_mobile_user_id", "portal_users", type_="foreignkey")
        op.drop_column("portal_users", "mobile_user_id")