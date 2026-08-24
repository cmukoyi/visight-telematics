"""Add webhook_logs table for debugging webhook deliveries

This migration creates the webhook_logs table to store all incoming webhook
payloads for debugging and audit purposes. Admins can view these logs via
the admin portal to see which devices were included in each webhook delivery.

This is particularly useful for troubleshooting issues like the MST03 device
not receiving webhook updates while other devices (E9, MTB02) were updating
successfully.

Revision ID: add_webhook_logs
Revises: v2113_series5_imei_length
Create Date: 2026-08-09
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID, JSON
import uuid


revision = 'add_webhook_logs'
down_revision = 'v2113_series5_imei_length'
branch_labels = None
depends_on = None


def upgrade():
    # Check if table already exists (idempotent migration)
    connection = op.get_bind()
    result = connection.execute(sa.text("""
        SELECT EXISTS (
            SELECT 1 FROM information_schema.tables 
            WHERE table_name = 'webhook_logs'
        )
    """))
    table_exists = result.scalar()
    
    if not table_exists:
        op.create_table(
            'webhook_logs',
            sa.Column('id', UUID(as_uuid=True), primary_key=True, default=uuid.uuid4),
            sa.Column('source', sa.String(50), nullable=False, index=True),
            sa.Column('received_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False, index=True),
            sa.Column('payload', JSON, nullable=False),
            sa.Column('packet_count', sa.Integer, nullable=False, default=0),
            sa.Column('device_ids', JSON, nullable=True),
            sa.Column('status_code', sa.Integer, nullable=False, default=200),
            sa.Column('error_message', sa.Text, nullable=True),
        )
        
        # Create composite index for efficient querying
        op.create_index(
            'idx_webhook_logs_source_received',
            'webhook_logs',
            ['source', 'received_at']
        )


def downgrade():
    op.drop_index('idx_webhook_logs_source_received', table_name='webhook_logs')
    op.drop_table('webhook_logs')
