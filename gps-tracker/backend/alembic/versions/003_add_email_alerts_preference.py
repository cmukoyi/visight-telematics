"""Add email alerts preference to users

Revision ID: 003
Revises: 002
Create Date: 2026-03-02

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy import text


# revision identifiers, used by Alembic.
revision = '003'
down_revision = '002'
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
    # Add email_alerts_enabled column to users table (only if it doesn't exist)
    if not column_exists('users', 'email_alerts_enabled'):
        op.add_column('users', sa.Column('email_alerts_enabled', sa.Boolean(), default=True))
        
        # Set default value for existing users
        op.execute("UPDATE users SET email_alerts_enabled = TRUE")


def downgrade():
    # Remove email_alerts_enabled column
    op.drop_column('users', 'email_alerts_enabled')
