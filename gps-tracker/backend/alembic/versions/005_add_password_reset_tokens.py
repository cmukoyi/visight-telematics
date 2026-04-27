"""Add password reset tokens table

Revision ID: 005
Revises: 004
Create Date: 2026-03-08

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy import text
import os

# revision identifiers, used by Alembic.
revision = '005'
down_revision = '004'
branch_labels = None
depends_on = None


def table_exists(table_name):
    """Check if a table exists"""
    bind = op.get_bind()
    result = bind.execute(text(
        """
        SELECT EXISTS (
            SELECT FROM information_schema.tables 
            WHERE table_name = :table_name
        );
        """
    ), {"table_name": table_name})
    return result.scalar()


def upgrade():
    # Determine if we're using PostgreSQL or SQLite
    DATABASE_URL = os.getenv("DATABASE_URL", "")
    use_postgres = DATABASE_URL.startswith("postgresql")
    
    if use_postgres:
        from sqlalchemy.dialects.postgresql import UUID
        uuid_type = UUID(as_uuid=True)
    else:
        uuid_type = sa.String(36)
    
    # Create password_reset_tokens table (only if it doesn't exist)
    if not table_exists('password_reset_tokens'):
        op.create_table(
            'password_reset_tokens',
            sa.Column('id', uuid_type, nullable=False),
            sa.Column('user_id', uuid_type, nullable=False),
            sa.Column('email', sa.String(255), nullable=False, index=True),
            sa.Column('token', sa.String(64), nullable=False, unique=True, index=True),
            sa.Column('is_used', sa.Boolean(), default=False),
            sa.Column('expires_at', sa.DateTime(timezone=True), nullable=False),
            sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now()),
            sa.PrimaryKeyConstraint('id'),
            sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE')
        )


def downgrade():
    # Drop password_reset_tokens table
    op.drop_table('password_reset_tokens')
