"""Add floor plan publish workflow and gateway-room linking

Adds publish tracking to floors (is_published, published_at, published_by)
and links indoor gateways to rooms for better spatial organization.

Revision ID: 054
Revises: 053
Create Date: 2026-06-24
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision = '054'
down_revision = '053'
branch_labels = None
depends_on = None


def upgrade():
    # Add publish tracking to floors
    op.add_column('floors', sa.Column('is_published', sa.Boolean(), server_default='false', nullable=False))
    op.add_column('floors', sa.Column('published_at', sa.DateTime(timezone=True), nullable=True))
    op.add_column('floors', sa.Column('published_by', postgresql.UUID(as_uuid=True), nullable=True))
    op.create_foreign_key('fk_floors_published_by', 'floors', 'portal_users', ['published_by'], ['id'], ondelete='SET NULL')
    
    # Link gateways to rooms for better spatial organization
    op.add_column('indoor_gateways', sa.Column('room_id', postgresql.UUID(as_uuid=True), nullable=True))
    op.create_foreign_key('fk_gateways_room', 'indoor_gateways', 'rooms', ['room_id'], ['id'], ondelete='SET NULL')


def downgrade():
    op.drop_constraint('fk_gateways_room', 'indoor_gateways', type_='foreignkey')
    op.drop_column('indoor_gateways', 'room_id')
    op.drop_constraint('fk_floors_published_by', 'floors', type_='foreignkey')
    op.drop_column('floors', 'published_by')
    op.drop_column('floors', 'published_at')
    op.drop_column('floors', 'is_published')
