"""widen email_domain to support comma-separated multiple domains

Revision ID: 021
Revises: 020
Create Date: 2026-05-01
"""
from alembic import op
import sqlalchemy as sa

revision = "021"
down_revision = "020"
branch_labels = None
depends_on = None


def upgrade():
    # Widen the column from 255 → 500 characters to accommodate comma-separated domain lists
    with op.batch_alter_table("user_groups") as batch_op:
        batch_op.alter_column(
            "email_domain",
            existing_type=sa.String(255),
            type_=sa.String(500),
            existing_nullable=True,
        )


def downgrade():
    with op.batch_alter_table("user_groups") as batch_op:
        batch_op.alter_column(
            "email_domain",
            existing_type=sa.String(500),
            type_=sa.String(255),
            existing_nullable=True,
        )
