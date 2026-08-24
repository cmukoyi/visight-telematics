"""add reconciliation watermark to engine_state

Revision ID: add_reconciliation_watermark
Revises: add_sensor_data
Create Date: 2026-08-24 16:50:00.000000

"""
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = 'add_reconciliation_watermark'
down_revision = 'add_sensor_data'
branch_labels = None
depends_on = None


def upgrade():
    """
    Add last_reconciled_received_at column to engine_state.
    
    v2.1.19: Reconciliation watermark prevents late-arrival rewind loop.
    Tracks highest received_at seen so late arrivals are detected exactly once.
    """
    # Check if column already exists (idempotent)
    connection = op.get_bind()
    inspector = sa.inspect(connection)
    
    # Check if engine_state table exists
    table_exists = 'engine_state' in inspector.get_table_names()
    
    if table_exists:
        existing_columns = {col['name'] for col in inspector.get_columns('engine_state')}
        
        if 'last_reconciled_received_at' not in existing_columns:
            op.add_column(
                'engine_state',
                sa.Column('last_reconciled_received_at', sa.DateTime(timezone=True), nullable=True)
            )
            print("✅ Added last_reconciled_received_at to engine_state")
        else:
            print("⏭️  Column last_reconciled_received_at already exists, skipping")
    else:
        print("⚠️  Table engine_state does not exist yet, skipping column addition")


def downgrade():
    """Remove last_reconciled_received_at column"""
    connection = op.get_bind()
    inspector = sa.inspect(connection)
    
    table_exists = 'engine_state' in inspector.get_table_names()
    
    if table_exists:
        existing_columns = {col['name'] for col in inspector.get_columns('engine_state')}
        
        if 'last_reconciled_received_at' in existing_columns:
            op.drop_column('engine_state', 'last_reconciled_received_at')
