"""rollback asset tracking tables - use ble_tags instead

Revision ID: 041_rollback_asset_tables
Revises: 040_add_asset_tracking
Create Date: 2026-06-01 14:00:00.000000

QR/NFC assets are now registered as series_3 tags in the ble_tags table,
so they appear in Asset List/Management alongside series_1/series_2 tags.
The separate assets/scan_events/asset_locations tables are no longer needed.
"""
from alembic import op


# revision identifiers, used by Alembic.
revision = '041_rollback_asset_tables'
down_revision = '040_add_asset_tracking'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Drop the asset tracking tables (no longer needed)
    op.drop_table('scan_events')
    op.drop_table('asset_locations')
    op.drop_table('assets')


def downgrade() -> None:
    # Recreate tables if needed (from 040 migration)
    import sqlalchemy as sa
    from sqlalchemy.dialects.postgresql import UUID
    
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
    
    op.create_table(
        'scan_events',
        sa.Column('id', sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column('asset_id', sa.String(20), sa.ForeignKey('assets.id', ondelete='CASCADE'), nullable=False),
        sa.Column('lat', sa.Float(), nullable=False),
        sa.Column('lng', sa.Float(), nullable=False),
        sa.Column('accuracy', sa.Float(), nullable=True),
        sa.Column('source', sa.String(10), server_default='qr', nullable=False),
        sa.Column('scanned_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column('scanner_ip', sa.String(45), nullable=True),
        sa.Column('user_agent', sa.Text(), nullable=True),
        sa.CheckConstraint("source IN ('qr', 'nfc', 'manual')", name='check_source')
    )
    
    op.create_index('idx_scan_events_asset_id', 'scan_events', ['asset_id'])
    op.create_index('idx_scan_events_scanned_at', 'scan_events', ['scanned_at'])
    
    op.create_table(
        'asset_locations',
        sa.Column('asset_id', sa.String(20), sa.ForeignKey('assets.id', ondelete='CASCADE'), primary_key=True),
        sa.Column('lat', sa.Float(), nullable=False),
        sa.Column('lng', sa.Float(), nullable=False),
        sa.Column('accuracy', sa.Float(), nullable=True),
        sa.Column('last_seen', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column('scan_count', sa.Integer(), server_default='0', nullable=False)
    )
