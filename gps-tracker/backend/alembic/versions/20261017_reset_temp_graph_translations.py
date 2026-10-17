"""Let dashboard translation sync populate temperature graph languages.

Revision ID: reset_temp_graph_translations
Revises: seed_temp_graph_translations
Create Date: 2026-10-17
"""
from alembic import op
from sqlalchemy.sql import text

revision = "reset_temp_graph_translations"
down_revision = "seed_temp_graph_translations"
branch_labels = None
depends_on = None


def upgrade():
    connection = op.get_bind()
    connection.execute(text(
        "DELETE FROM translations "
        "WHERE key LIKE 'temp_graph.%' AND language_code <> 'en'"
    ))


def downgrade():
    pass
