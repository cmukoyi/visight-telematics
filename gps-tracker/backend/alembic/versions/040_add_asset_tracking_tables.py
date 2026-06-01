"""add asset tracking tables

Revision ID: 040_add_asset_tracking
Revises: 039
Create Date: 2026-06-01 10:00:00.000000

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID
from geoalchemy2 import Geography

# revision identifiers, used by Alembic.
revision = '040_add_asset_tracking'
down_revision = '039'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Enable PostGIS if not already enabled
    op.execute('CREATE EXTENSION IF NOT EXISTS postgis')
    
    # Create assets table
    op.create_table(
        'assets',
        sa.Column('id', sa.String(20), primary_key=True),
        sa.Column('type_code', sa.CHAR(1), nullable=False),
        sa.Column('name', sa.String(100), nullable=True),
        sa.Column('category', sa.String(50), nullable=True),
        sa.Column('owner_id', UUID(as_uuid=True), nullable=True),
        sa.Column('notes', sa.Text(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint("type_code IN ('Q', 'N')", name='check_type_code')
    )
    
    # Create scan_events table
    op.create_table(
        'scan_events',
        sa.Column('id', sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column('asset_id', sa.String(20), sa.ForeignKey('assets.id', ondelete='CASCADE'), nullable=False),
        sa.Column('lat', sa.Float(), nullable=False),
        sa.Column('lng', sa.Float(), nullable=False),
        sa.Column('accuracy', sa.Float(), nullable=True),
        sa.Column('location', Geography('POINT', srid=4326), nullable=True),
        sa.Column('source', sa.String(10), server_default='qr', nullable=False),
        sa.Column('scanned_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column('scanner_ip', sa.String(45), nullable=True),
        sa.Column('user_agent', sa.Text(), nullable=True),
        sa.CheckConstraint("source IN ('qr', 'nfc', 'manual')", name='check_source')
    )
    
    # Create indexes for scan_events
    op.create_index('idx_scan_events_asset_id', 'scan_events', ['asset_id'])
    op.create_index('idx_scan_events_scanned_at', 'scan_events', [sa.text('scanned_at DESC')])
    op.execute('CREATE INDEX idx_scan_events_location ON scan_events USING GIST(location)')
    
    # Create asset_locations table
    op.create_table(
        'asset_locations',
        sa.Column('asset_id', sa.String(20), sa.ForeignKey('assets.id', ondelete='CASCADE'), primary_key=True),
        sa.Column('lat', sa.Float(), nullable=False),
        sa.Column('lng', sa.Float(), nullable=False),
        sa.Column('accuracy', sa.Float(), nullable=True),
        sa.Column('location', Geography('POINT', srid=4326), nullable=True),
        sa.Column('source', sa.String(10), server_default='qr', nullable=False),
        sa.Column('last_seen', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column('scan_count', sa.Integer(), server_default='1', nullable=False)
    )
    
    # Create spatial index for asset_locations
    op.execute('CREATE INDEX idx_asset_locations_location ON asset_locations USING GIST(location)')
    
    # Create trigger function for updated_at
    op.execute('''
        CREATE OR REPLACE FUNCTION update_updated_at()
        RETURNS TRIGGER AS $$
        BEGIN
            NEW.updated_at = NOW();
            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql;
    ''')
    
    # Create trigger on assets table
    op.execute('''
        CREATE TRIGGER assets_updated_at
        BEFORE UPDATE ON assets
        FOR EACH ROW
        EXECUTE FUNCTION update_updated_at();
    ''')


def downgrade() -> None:
    op.execute('DROP TRIGGER IF EXISTS assets_updated_at ON assets')
    op.execute('DROP FUNCTION IF EXISTS update_updated_at()')
    op.drop_index('idx_asset_locations_location', table_name='asset_locations')
    op.drop_table('asset_locations')
    op.drop_index('idx_scan_events_location', table_name='scan_events')
    op.drop_index('idx_scan_events_scanned_at', table_name='scan_events')
    op.drop_index('idx_scan_events_asset_id', table_name='scan_events')
    op.drop_table('scan_events')
    op.drop_table('assets')
