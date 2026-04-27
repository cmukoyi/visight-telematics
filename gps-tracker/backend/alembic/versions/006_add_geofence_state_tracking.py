"""Add state tracking to POI tracker links

Revision ID: 006
Revises: 005
Create Date: 2026-03-08

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy import text

# revision identifiers, used by Alembic.
revision = '006'
down_revision = '005'
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


def type_exists(type_name):
    """Check if a PostgreSQL type exists"""
    bind = op.get_bind()
    result = bind.execute(text(
        """
        SELECT EXISTS (
            SELECT FROM pg_type 
            WHERE typname = :type_name
        );
        """
    ), {"type_name": type_name})
    return result.scalar()


def upgrade():
    """Add last_known_state column to track tracker position state"""
    # Add last_known_state enum column to poi_tracker_links
    # States: 'unknown' (initial), 'inside' (within geofence), 'outside' (outside geofence)
    
    # Create enum type only if it doesn't exist
    if not type_exists('geofence_state'):
        op.execute("""
            CREATE TYPE geofence_state AS ENUM ('unknown', 'inside', 'outside')
        """)
    
    # Add last_known_state column only if it doesn't exist
    if not column_exists('poi_tracker_links', 'last_known_state'):
        op.add_column('poi_tracker_links', 
            sa.Column('last_known_state', 
                      sa.Enum('unknown', 'inside', 'outside', name='geofence_state'),
                      nullable=False,
                      server_default='unknown')
        )
    
    # Add timestamp for when state was last checked/updated
    if not column_exists('poi_tracker_links', 'last_state_check'):
        op.add_column('poi_tracker_links',
            sa.Column('last_state_check', 
                      sa.DateTime(timezone=True),
                      nullable=True)
        )


def downgrade():
    """Remove state tracking columns"""
    op.drop_column('poi_tracker_links', 'last_state_check')
    op.drop_column('poi_tracker_links', 'last_known_state')
    op.execute("DROP TYPE geofence_state")
