"""Add POI and geofence alerts tables

Revision ID: 002
Revises: 001
Create Date: 2026-03-02

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy import text
import os


# revision identifiers, used by Alembic.
revision = '002'
down_revision = '001'
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
    # Determine if we're using SQLite or PostgreSQL
    DATABASE_URL = os.getenv("DATABASE_URL", "")
    use_sqlite = DATABASE_URL.startswith("sqlite")
    
    if use_sqlite:
        id_type = sa.String(36)
        fk_type = sa.String(36)
    else:
        id_type = UUID(as_uuid=True)
        fk_type = UUID(as_uuid=True)
    
    # Create pois table (only if it doesn't exist)
    if not table_exists('pois'):
        op.create_table(
            'pois',
            sa.Column('id', id_type, primary_key=True),
            sa.Column('user_id', fk_type, sa.ForeignKey('users.id'), nullable=False),
            sa.Column('name', sa.String(200), nullable=False),
            sa.Column('description', sa.Text(), nullable=True),
            sa.Column('latitude', sa.Float(), nullable=False),
            sa.Column('longitude', sa.Float(), nullable=False),
            sa.Column('radius', sa.Float(), default=150.0),
            sa.Column('address', sa.String(500), nullable=True),
            sa.Column('is_active', sa.Boolean(), default=True),
            sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now()),
            sa.Column('updated_at', sa.DateTime(timezone=True), onupdate=sa.func.now())
        )
        
        # Create indexes for pois
        op.create_index('idx_pois_user_id', 'pois', ['user_id'])
        op.create_index('idx_pois_is_active', 'pois', ['is_active'])
    
    # Create poi_tracker_links table (only if it doesn't exist)
    if not table_exists('poi_tracker_links'):
        op.create_table(
            'poi_tracker_links',
            sa.Column('id', id_type, primary_key=True),
            sa.Column('poi_id', fk_type, sa.ForeignKey('pois.id'), nullable=False),
            sa.Column('tracker_id', fk_type, sa.ForeignKey('ble_tags.id'), nullable=False),
            sa.Column('is_armed', sa.Boolean(), default=True),
            sa.Column('armed_at', sa.DateTime(timezone=True), server_default=sa.func.now()),
            sa.Column('disarmed_at', sa.DateTime(timezone=True), nullable=True)
        )
        
        # Create indexes for poi_tracker_links
        op.create_index('idx_poi_tracker_links_poi_id', 'poi_tracker_links', ['poi_id'])
        op.create_index('idx_poi_tracker_links_tracker_id', 'poi_tracker_links', ['tracker_id'])
        op.create_index('idx_poi_tracker_links_is_armed', 'poi_tracker_links', ['is_armed'])
    
    # Create geofence_alerts table (only if it doesn't exist)
    if not table_exists('geofence_alerts'):
        op.create_table(
            'geofence_alerts',
            sa.Column('id', id_type, primary_key=True),
            sa.Column('poi_id', fk_type, sa.ForeignKey('pois.id'), nullable=False),
            sa.Column('tracker_id', fk_type, sa.ForeignKey('ble_tags.id'), nullable=False),
            sa.Column('user_id', fk_type, sa.ForeignKey('users.id'), nullable=False),
            sa.Column('event_type', sa.Enum('ENTRY', 'EXIT', name='geofenceeventtype'), nullable=False),
            sa.Column('latitude', sa.Float(), nullable=False),
            sa.Column('longitude', sa.Float(), nullable=False),
            sa.Column('is_read', sa.Boolean(), default=False),
            sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now())
        )
        
        # Create indexes for geofence_alerts
        op.create_index('idx_geofence_alerts_user_id', 'geofence_alerts', ['user_id'])
        op.create_index('idx_geofence_alerts_tracker_id', 'geofence_alerts', ['tracker_id'])
        op.create_index('idx_geofence_alerts_poi_id', 'geofence_alerts', ['poi_id'])
        op.create_index('idx_geofence_alerts_is_read', 'geofence_alerts', ['is_read'])
        op.create_index('idx_geofence_alerts_created_at', 'geofence_alerts', ['created_at'])


def downgrade():
    # Drop indexes
    op.drop_index('idx_geofence_alerts_created_at', 'geofence_alerts')
    op.drop_index('idx_geofence_alerts_is_read', 'geofence_alerts')
    op.drop_index('idx_geofence_alerts_poi_id', 'geofence_alerts')
    op.drop_index('idx_geofence_alerts_tracker_id', 'geofence_alerts')
    op.drop_index('idx_geofence_alerts_user_id', 'geofence_alerts')
    op.drop_index('idx_poi_tracker_links_is_armed', 'poi_tracker_links')
    op.drop_index('idx_poi_tracker_links_tracker_id', 'poi_tracker_links')
    op.drop_index('idx_poi_tracker_links_poi_id', 'poi_tracker_links')
    op.drop_index('idx_pois_is_active', 'pois')
    op.drop_index('idx_pois_user_id', 'pois')
    
    # Drop tables
    op.drop_table('geofence_alerts')
    op.drop_table('poi_tracker_links')
    op.drop_table('pois')
