"""Add tag_fix_history field for enhanced HIVE position logging

Revision ID: 053_add_tag_fix_history
Revises: 052_add_persistence_tracking
Create Date: 2026-06-20

Adds tag_fix_history field to hive_evaluations to capture per-tag recent
position history for trajectory analysis. This is diagnostic/export only
and does not change evaluation or alert behavior.

New field:
- tag_fix_history: JSON storing last N fixes per tag with coordinates

Part of HIVE Position Logging Additions for testers.
"""
from alembic import op
import sqlalchemy as sa

revision = '053_add_tag_fix_history'
down_revision = '052_add_persistence_tracking'
branch_labels = None
depends_on = None


def upgrade():
    # Add tag_fix_history field for per-tag recent position tracking
    op.add_column('hive_evaluations',
        sa.Column('tag_fix_history', sa.Text(), nullable=True)
    )


def downgrade():
    # Remove tag_fix_history field
    op.drop_column('hive_evaluations', 'tag_fix_history')
