"""Reports → Analytics pages and Expressions.

Revision ID: 074_add_analytics
Revises: 073_roles_audit_domain
Create Date: 2026-10-23
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy import text
from sqlalchemy.dialects.postgresql import UUID

revision = "074_add_analytics"
down_revision = "073_roles_audit_domain"
branch_labels = None
depends_on = None


def _has_table(name):
    return op.get_bind().execute(text("SELECT to_regclass(:n) IS NOT NULL"), {"n": name}).scalar()


def upgrade():
    if not _has_table("analytics_expressions"):
        op.create_table(
            "analytics_expressions",
            sa.Column("id", UUID(as_uuid=True), primary_key=True),
            sa.Column("usergroup_id", UUID(as_uuid=True), sa.ForeignKey("user_groups.id", ondelete="CASCADE"), nullable=False, index=True),
            sa.Column("name", sa.String(120), nullable=False),
            sa.Column("category", sa.String(60), nullable=True),
            sa.Column("expression", sa.Text(), nullable=False),
            sa.Column("description", sa.String(255), nullable=True),
            sa.Column("unit", sa.String(20), nullable=True),
            sa.Column("decimals", sa.Integer(), nullable=False, server_default="2"),
            sa.Column("created_by", UUID(as_uuid=True), sa.ForeignKey("portal_users.id", ondelete="SET NULL"), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
            sa.UniqueConstraint("usergroup_id", "name", name="uq_analytics_expression_name"),
        )
    if not _has_table("analytics_pages"):
        op.create_table(
            "analytics_pages",
            sa.Column("id", UUID(as_uuid=True), primary_key=True),
            sa.Column("usergroup_id", UUID(as_uuid=True), sa.ForeignKey("user_groups.id", ondelete="CASCADE"), nullable=False, index=True),
            sa.Column("name", sa.String(120), nullable=False),
            sa.Column("position", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("date_preset", sa.String(30), nullable=False, server_default="this_month"),
            sa.Column("visuals", sa.JSON(), nullable=False),
            sa.Column("created_by", UUID(as_uuid=True), sa.ForeignKey("portal_users.id", ondelete="SET NULL"), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        )


def downgrade():
    for t in ("analytics_pages", "analytics_expressions"):
        if _has_table(t):
            op.drop_table(t)
