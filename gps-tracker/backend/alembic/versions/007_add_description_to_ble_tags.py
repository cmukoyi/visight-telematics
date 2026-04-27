"""Add description column to ble_tags table

Revision ID: 007
Revises: 006
Create Date: 2026-03-08

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy import text


# revision identifiers, used by Alembic.
revision = '007'
down_revision = '006'
branch_labels = None
depends_on = None


def column_exists(table_name, column_name):
    """Check if a column exists in a table"""
    bind = op.get_bind()
    result = bind.execute(text(
        """
        SELECT EXISTS (
            SELECT FROM information_schema.columns 
            WHERE table_name = :table_name 
            AND column_name = :column_name
        );
        """
    ), {"table_name": table_name, "column_name": column_name})
    return result.scalar()


def upgrade():
    # Add description column to ble_tags table (only if it doesn't exist)
    if not column_exists('ble_tags', 'description'):
        op.add_column('ble_tags', 
            sa.Column('description', sa.String(255), nullable=True, 
                     comment='Vehicle description from MZone API'))


def downgrade():
    # Remove description column from ble_tags table
    op.drop_column('ble_tags', 'description')
