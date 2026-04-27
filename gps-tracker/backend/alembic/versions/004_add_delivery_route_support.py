"""add delivery route support to POI

Revision ID: 004
Revises: 003
Create Date: 2026-03-02

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy import text


# revision identifiers, used by Alembic.
revision = '004'
down_revision = '003'
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
    # Add POI type column (only if it doesn't exist)
    if not column_exists('pois', 'poi_type'):
        op.add_column('pois', sa.Column('poi_type', sa.String(20), nullable=False, server_default='single'))
    
    # Add destination fields for delivery routes (only if they don't exist)
    if not column_exists('pois', 'destination_latitude'):
        op.add_column('pois', sa.Column('destination_latitude', sa.Float(), nullable=True))
    
    if not column_exists('pois', 'destination_longitude'):
        op.add_column('pois', sa.Column('destination_longitude', sa.Float(), nullable=True))
    
    if not column_exists('pois', 'destination_radius'):
        op.add_column('pois', sa.Column('destination_radius', sa.Float(), nullable=True))
    
    if not column_exists('pois', 'destination_address'):
        op.add_column('pois', sa.Column('destination_address', sa.String(500), nullable=True))


def downgrade():
    op.drop_column('pois', 'destination_address')
    op.drop_column('pois', 'destination_radius')
    op.drop_column('pois', 'destination_longitude')
    op.drop_column('pois', 'destination_latitude')
    op.drop_column('pois', 'poi_type')
