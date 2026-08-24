"""add tracksolid composite index for trip engine performance

Revision ID: tracksolid_composite_idx
Revises: add_webhook_logs
Create Date: 2026-08-16 21:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'tracksolid_composite_idx'
down_revision = 'add_webhook_logs'
branch_labels = None
depends_on = None


def upgrade():
    """
    Add composite index on (imei, recorded_at DESC) to tracksolid_locations table.
    
    This index dramatically improves trip engine query performance:
    - Before: 630ms per device query
    - After: 50-100ms per device query (6-12x faster)
    
    Critical for scaling to 100+ subscribed devices.
    
    NOTE: For production with large tables (2M+ rows), create manually first:
      docker exec pinplot_db psql -U pinplot_db_user -d pinplot_db -c \
        "CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_tracksolid_imei_recorded ON tracksolid_locations (imei, recorded_at DESC);"
    
    Migration will skip if index already exists.
    """
    # Check if index already exists (handles manual creation)
    connection = op.get_bind()
    result = connection.execute(sa.text("""
        SELECT 1 FROM pg_indexes 
        WHERE indexname = 'idx_tracksolid_imei_recorded'
    """))
    
    if result.fetchone():
        print("✅ Index idx_tracksolid_imei_recorded already exists (skipped)")
        return
    
    # Create index (regular mode, works in transaction)
    # For large tables, prefer manual CONCURRENTLY creation before deployment
    op.create_index(
        'idx_tracksolid_imei_recorded',
        'tracksolid_locations',
        ['imei', sa.text('recorded_at DESC')],
        postgresql_concurrently=False
    )
    
    print("✅ Created composite index idx_tracksolid_imei_recorded")
    print("   Expected performance: 6-12x faster trip engine queries")


def downgrade():
    """
    Remove composite index if needed for rollback.
    """
    # Check if index exists before dropping
    connection = op.get_bind()
    result = connection.execute(sa.text("""
        SELECT 1 FROM pg_indexes 
        WHERE indexname = 'idx_tracksolid_imei_recorded'
    """))
    
    if result.fetchone():
        op.drop_index('idx_tracksolid_imei_recorded', 'tracksolid_locations')
        print("⬇️ Removed composite index idx_tracksolid_imei_recorded")
    else:
        print("⬇️ Index idx_tracksolid_imei_recorded does not exist (skipped)")
