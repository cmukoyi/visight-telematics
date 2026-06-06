"""add allowed_tag_types column to user_groups

Revision ID: 044_allowed_tag_types
Revises: 043_hive_eval_v12
Create Date: 2025-01-22 22:15:00.000000
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSON


# revision identifiers, used by Alembic.
revision = '044_allowed_tag_types'
down_revision = '043_hive_eval_v12'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column('user_groups', sa.Column('allowed_tag_types', JSON, nullable=True))


def downgrade() -> None:
    op.drop_column('user_groups', 'allowed_tag_types')
