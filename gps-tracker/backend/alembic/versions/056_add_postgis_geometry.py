"""Add PostGIS geometry columns for leg paths

Revision ID: 056_add_postgis_geometry
Revises: 055_trip_engine_schema
Create Date: 2026-07-05

Implements PostGIS spatial features from PinPlot_Trip_Engine_Spec_v2.md Section 2.5:

Geometry (PostGIS):
- Enable PostGIS extension
- Add LineString geometry columns to legs table for path storage
- Add Point geometry columns to stationaries table for centroid
- Add GiST spatial indexes for fast geographic queries
- Store full-resolution paths and simplified render copies

Benefits:
- ST_Length(geography) for accurate distance calculation
- ST_MakeLine for path construction from points
- ST_Simplify (Douglas-Peucker) for zoom-level rendering
- ST_DWithin for proximity queries
- Spatial indexing with GiST
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy import text

revision = '056_add_postgis_geometry'
down_revision = '055_trip_engine_schema'
branch_labels = None
depends_on = None


def upgrade():
    # Enable PostGIS extension
    op.execute(text('CREATE EXTENSION IF NOT EXISTS postgis'))
    
    # Add lat/lng columns to legs table (if not exists)
    # These are needed for non-spatial queries and as source for geometry
    conn = op.get_bind()
    inspector = sa.inspect(conn)
    legs_columns = [col['name'] for col in inspector.get_columns('legs')]
    
    if 'start_lat' not in legs_columns:
        op.add_column('legs', sa.Column('start_lat', sa.Float, nullable=True))
    if 'start_lng' not in legs_columns:
        op.add_column('legs', sa.Column('start_lng', sa.Float, nullable=True))
    if 'end_lat' not in legs_columns:
        op.add_column('legs', sa.Column('end_lat', sa.Float, nullable=True))
    if 'end_lng' not in legs_columns:
        op.add_column('legs', sa.Column('end_lng', sa.Float, nullable=True))
    
    # Add geometry columns to legs table
    # Using Geography type (SRID 4326 = WGS84) for accurate distance calculations
    op.execute(text("""
        ALTER TABLE legs 
        ADD COLUMN IF NOT EXISTS path GEOMETRY(LineString, 4326)
    """))
    
    op.execute(text("""
        ALTER TABLE legs 
        ADD COLUMN IF NOT EXISTS path_simplified GEOMETRY(LineString, 4326)
    """))
    
    # Add geometry column to stationaries table (centroid as Point)
    op.execute(text("""
        ALTER TABLE stationaries 
        ADD COLUMN IF NOT EXISTS centroid GEOMETRY(Point, 4326)
    """))
    
    # Create GiST spatial indexes for fast geographic queries
    op.execute(text("""
        CREATE INDEX IF NOT EXISTS idx_legs_path_gist 
        ON legs USING GIST(path)
    """))
    
    op.execute(text("""
        CREATE INDEX IF NOT EXISTS idx_legs_path_simplified_gist 
        ON legs USING GIST(path_simplified)
    """))
    
    op.execute(text("""
        CREATE INDEX IF NOT EXISTS idx_stationaries_centroid_gist 
        ON stationaries USING GIST(centroid)
    """))
    
    # Backfill existing records with geometry from lat/lng columns
    # For stationaries: convert anchor_lat/lng to Point geometry
    op.execute(text("""
        UPDATE stationaries 
        SET centroid = ST_SetSRID(ST_MakePoint(anchor_lng, anchor_lat), 4326)
        WHERE centroid IS NULL AND anchor_lat IS NOT NULL AND anchor_lng IS NOT NULL
    """))
    
    # For legs: create minimal LineString from start/end points
    # (Full path reconstruction will be done by trip engine for new legs)
    op.execute(text("""
        UPDATE legs 
        SET path = ST_SetSRID(
            ST_MakeLine(
                ST_MakePoint(start_lng, start_lat),
                ST_MakePoint(end_lng, end_lat)
            ), 4326
        ),
        path_simplified = ST_SetSRID(
            ST_MakeLine(
                ST_MakePoint(start_lng, start_lat),
                ST_MakePoint(end_lng, end_lat)
            ), 4326
        )
        WHERE path IS NULL AND start_lat IS NOT NULL AND end_lat IS NOT NULL
    """))


def downgrade():
    # Drop GiST indexes
    op.execute(text('DROP INDEX IF EXISTS idx_stationaries_centroid_gist'))
    op.execute(text('DROP INDEX IF EXISTS idx_legs_path_simplified_gist'))
    op.execute(text('DROP INDEX IF EXISTS idx_legs_path_gist'))
    
    # Drop geometry columns
    op.execute(text('ALTER TABLE stationaries DROP COLUMN IF EXISTS centroid'))
    op.execute(text('ALTER TABLE legs DROP COLUMN IF EXISTS path_simplified'))
    op.execute(text('ALTER TABLE legs DROP COLUMN IF EXISTS path'))
    
    # Note: We don't drop the PostGIS extension as other tables might use it
    # op.execute(text('DROP EXTENSION IF EXISTS postgis'))
