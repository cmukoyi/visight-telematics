"""add async jobs table

Revision ID: 059_add_async_jobs
Revises: 058_add_tenant_trip_config
Create Date: 2026-07-18 03:00:00.000000

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision = '059_add_async_jobs'
down_revision = '058_add_tenant_trip_config'
branch_labels = None
depends_on = None


def upgrade():
    """Add async_jobs table for background operations (v2.2 A5)."""
    
    op.create_table(
        'async_jobs',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column('job_type', sa.String(50), nullable=False, index=True),  # batch_backfill | batch_reprocess
        sa.Column('status', sa.String(20), nullable=False, index=True),    # pending | running | completed | failed | cancelled
        sa.Column('created_by', sa.String(255), nullable=False),           # Admin email
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column('started_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('completed_at', sa.DateTime(timezone=True), nullable=True),
        
        # Job parameters (JSONB for flexibility)
        sa.Column('params', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        # Example for batch_backfill: {"tenant_id": "uuid", "preset": "last_7_days"}
        # Example for batch_reprocess: {"tenant_id": "uuid", "device_imeis": ["imei1", "imei2"]}
        
        # Progress tracking
        sa.Column('total_devices', sa.Integer(), nullable=True),
        sa.Column('completed_devices', sa.Integer(), default=0, nullable=False),
        sa.Column('failed_devices', sa.Integer(), default=0, nullable=False),
        
        # Results (JSONB - accumulated stats)
        sa.Column('results', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        # Example: {"positions_fetched": 10000, "journeys_created": 150, "errors": [...]}
        
        # Error tracking
        sa.Column('error_message', sa.Text(), nullable=True),
        
        # Resumability
        sa.Column('last_processed_imei', sa.String(20), nullable=True),  # For resuming
        
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.func.now(), onupdate=sa.func.now(), nullable=False)
    )
    
    # Index for status queries
    op.create_index('ix_async_jobs_status_created', 'async_jobs', ['status', 'created_at'])


def downgrade():
    """Remove async_jobs table."""
    op.drop_index('ix_async_jobs_status_created', table_name='async_jobs')
    op.drop_table('async_jobs')
