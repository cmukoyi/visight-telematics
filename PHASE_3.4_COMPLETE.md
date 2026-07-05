# Phase 3.4 Complete: PostGIS Integration

**Date:** 2026-07-05  
**Status:** ✅ Complete  
**Branch:** main

---

## What Was Delivered

Integrated PostGIS spatial extension for geographic data storage and processing. The Trip Engine now stores full-resolution leg paths as LineString geometry and stationary centroids as Point geometry, with spatial indexes for fast geographic queries.

## Why PostGIS?

**PostgreSQL** = Standard database (what you had)  
**PostGIS** = PostgreSQL extension adding spatial superpowers

### Benefits Over Plain lat/lng Columns:

1. **Path Storage**: Store entire leg as connected LineString (not just start/end points)
2. **Spatial Functions**: Built-in distance, simplification, proximity queries
3. **Performance**: GiST spatial indexes for fast geographic lookups
4. **Rendering**: Simplified paths (Douglas-Peucker) for zoom-level rendering
5. **Standards**: Industry-standard OGC geometry types (WGS84 SRID 4326)

## Implementation Details

### 1. Docker Image Update

Changed from standard PostgreSQL to PostGIS-enabled image:

```yaml
# Before
image: postgres:15-alpine

# After
image: postgis/postgis:15-alpine
```

**Files Updated:**
- `gps-tracker/docker-compose.yml` (production)
- `gps-tracker/docker-compose.local.yml` (local dev)

### 2. Python Dependencies

Added GeoAlchemy2 for PostGIS support in SQLAlchemy:

```txt
sqlalchemy==2.0.25
geoalchemy2==0.14.3  ← NEW
```

### 3. Database Migration (056)

**Enables PostGIS Extension:**
```sql
CREATE EXTENSION IF NOT EXISTS postgis;
```

**Adds Geometry Columns:**
```sql
-- Legs: Full and simplified paths
ALTER TABLE legs ADD COLUMN path GEOMETRY(LineString, 4326);
ALTER TABLE legs ADD COLUMN path_simplified GEOMETRY(LineString, 4326);

-- Stationaries: Centroid point
ALTER TABLE stationaries ADD COLUMN centroid GEOMETRY(Point, 4326);
```

**Adds Lat/Lng Columns to Legs:**
```sql
-- For non-spatial queries and as source for geometry
ALTER TABLE legs ADD COLUMN start_lat FLOAT;
ALTER TABLE legs ADD COLUMN start_lng FLOAT;
ALTER TABLE legs ADD COLUMN end_lat FLOAT;
ALTER TABLE legs ADD COLUMN end_lng FLOAT;
```

**Creates Spatial Indexes (GiST):**
```sql
CREATE INDEX idx_legs_path_gist ON legs USING GIST(path);
CREATE INDEX idx_legs_path_simplified_gist ON legs USING GIST(path_simplified);
CREATE INDEX idx_stationaries_centroid_gist ON stationaries USING GIST(centroid);
```

**Backfills Existing Records:**
```sql
-- Convert existing stationaries' anchor lat/lng to Point geometry
UPDATE stationaries 
SET centroid = ST_SetSRID(ST_MakePoint(anchor_lng, anchor_lat), 4326)
WHERE centroid IS NULL;

-- Convert existing legs' start/end points to LineString (straight line)
UPDATE legs 
SET path = ST_SetSRID(
    ST_MakeLine(
        ST_MakePoint(start_lng, start_lat),
        ST_MakePoint(end_lng, end_lat)
    ), 4326
)
WHERE path IS NULL;
```

### 4. Trip Engine Geometry Builders

#### Leg Path Construction (`_create_leg`)

After leg record is created, build PostGIS geometry from all points in leg_buffer:

```python
# Build array of points: ARRAY[ST_MakePoint(lng, lat), ...]
# Note: PostGIS uses (lng, lat) order
points_array = ", ".join([
    f"ST_MakePoint({p[1]}, {p[0]})"  # lng, lat
    for p in leg_buffer
])

# Full-resolution path (all GPS points)
UPDATE legs 
SET path = ST_SetSRID(ST_MakeLine(ARRAY[{points_array}]), 4326)
WHERE id = :leg_id

# Simplified path (Douglas-Peucker, tolerance 0.0001° ≈ 11m)
UPDATE legs 
SET path_simplified = ST_Simplify(
    ST_SetSRID(ST_MakeLine(ARRAY[{points_array}]), 4326),
    0.0001
)
WHERE id = :leg_id
```

**Simplification Tolerance:**
- `0.0001°` ≈ 11 meters at equator
- Optimized for zoom levels 12-15 (city/neighborhood view)
- Frontend can switch: simplified at low zoom, full-res at high zoom

#### Stationary Centroid (`_create_stationary`)

Convert calculated centroid to PostGIS Point:

```python
UPDATE stationaries 
SET centroid = ST_SetSRID(ST_MakePoint(:lng, :lat), 4326)
WHERE id = :stationary_id
```

### 5. Error Handling

Geometry creation is **non-blocking**:
- If PostGIS geometry fails, leg/stationary creation still succeeds
- Logs warning but doesn't fail the transaction
- Ensures backward compatibility if PostGIS is disabled

```python
try:
    # Build geometry
    self.db.execute(text("UPDATE legs SET path = ..."))
except Exception as exc:
    logger.warning("⚠️  Failed to create geometry: %s", exc)
    # Continue without geometry
```

## Database Schema

### Legs Table (After Migration 056)
```sql
CREATE TABLE legs (
    id UUID PRIMARY KEY,
    device_imei VARCHAR(20),
    journey_id UUID,
    
    -- Position references
    start_position_id INTEGER,
    end_position_id INTEGER,
    
    -- Start/End coordinates (for non-spatial queries)
    start_lat FLOAT,
    start_lng FLOAT,
    end_lat FLOAT,
    end_lng FLOAT,
    
    -- PostGIS Geometry (full resolution + simplified)
    path GEOMETRY(LineString, 4326),
    path_simplified GEOMETRY(LineString, 4326),
    
    -- Metrics
    distance_m FLOAT,
    duration_seconds INTEGER,
    point_count INTEGER,
    is_air_leg BOOLEAN,
    
    -- Timestamps
    started_at TIMESTAMPTZ,
    ended_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ
);

CREATE INDEX idx_legs_path_gist ON legs USING GIST(path);
CREATE INDEX idx_legs_path_simplified_gist ON legs USING GIST(path_simplified);
```

### Stationaries Table (After Migration 056)
```sql
CREATE TABLE stationaries (
    id UUID PRIMARY KEY,
    device_imei VARCHAR(20),
    journey_id UUID,
    
    -- Anchor coordinates (for non-spatial queries)
    anchor_lat FLOAT,
    anchor_lng FLOAT,
    
    -- PostGIS Geometry (centroid)
    centroid GEOMETRY(Point, 4326),
    
    -- Metrics
    duration_seconds INTEGER,
    point_count INTEGER,
    
    -- Timestamps
    started_at TIMESTAMPTZ,
    ended_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ
);

CREATE INDEX idx_stationaries_centroid_gist ON stationaries USING GIST(centroid);
```

## PostGIS Spatial Functions Used

| Function | Purpose | Example |
|----------|---------|---------|
| `ST_MakePoint(lng, lat)` | Create Point geometry | `ST_MakePoint(-0.1278, 51.5074)` |
| `ST_MakeLine(points[])` | Create LineString from array | `ST_MakeLine(ARRAY[pt1, pt2, pt3])` |
| `ST_Simplify(geom, tolerance)` | Douglas-Peucker simplification | `ST_Simplify(path, 0.0001)` |
| `ST_SetSRID(geom, srid)` | Set spatial reference system | `ST_SetSRID(geom, 4326)` (WGS84) |
| `ST_Length(geography)` | Calculate distance | `ST_Length(path::geography)` |
| `ST_DWithin(geom1, geom2, dist)` | Proximity query | `ST_DWithin(path, point, 5000)` |

**SRID 4326 = WGS84** (standard GPS coordinate system)

## Example Queries Enabled

### 1. Get Full-Resolution Path for Rendering
```sql
SELECT ST_AsGeoJSON(path) as path_geojson
FROM legs
WHERE id = '550e8400-e29b-41d4-a716-446655440000';

-- Returns GeoJSON LineString for frontend
-- {"type":"LineString","coordinates":[[-0.1278,51.5074],[-0.1265,51.5082],...]}
```

### 2. Get Simplified Path (Zoom Level 12)
```sql
SELECT ST_AsGeoJSON(path_simplified) as path_geojson
FROM legs
WHERE journey_id = '...';

-- Returns simplified paths for faster rendering at low zoom
```

### 3. Find Legs Within 5km of Location
```sql
SELECT id, device_imei, distance_m
FROM legs
WHERE ST_DWithin(
    path::geography, 
    ST_MakePoint(-0.1278, 51.5074)::geography,
    5000  -- 5km radius
);

-- Uses GiST index for fast spatial lookup
```

### 4. Calculate Actual Path Distance (vs Haversine)
```sql
SELECT 
    id,
    distance_m as haversine_distance,
    ST_Length(path::geography) as actual_path_length
FROM legs
WHERE device_imei = '780901807676441';

-- Compare Haversine sum vs actual curved path
```

### 5. Find All Stationaries in Geofence
```sql
SELECT s.id, s.device_imei, s.duration_seconds
FROM stationaries s
JOIN geofences g ON ST_Contains(g.polygon, s.centroid)
WHERE g.name = 'London Office';

-- Fast spatial index lookup
```

## Frontend Integration

### GeoJSON Export for Leaflet/Mapbox

```python
# In API endpoint
from sqlalchemy import func

leg = db.query(Leg).filter(Leg.id == leg_id).first()

# Return GeoJSON for frontend
geojson = {
    "type": "Feature",
    "geometry": db.scalar(func.ST_AsGeoJSON(leg.path)),
    "properties": {
        "distance_m": leg.distance_m,
        "duration_seconds": leg.duration_seconds,
        "is_air_leg": leg.is_air_leg
    }
}
```

### Zoom-Level Rendering

```javascript
// Frontend logic
if (map.getZoom() < 14) {
    // Use simplified path
    fetch(`/api/legs/${legId}/path?simplified=true`)
} else {
    // Use full-resolution path
    fetch(`/api/legs/${legId}/path?simplified=false`)
}
```

## Testing Strategy

### Unit Tests

1. **PostGIS extension enabled:**
   - Query: `SELECT PostGIS_Version()`
   - Verify returns version string

2. **Geometry creation:**
   - Create leg with 10 points
   - Verify `path` column contains LineString
   - Verify `path_simplified` has fewer points

3. **Simplification:**
   - Create leg with 100 points on straight line
   - Verify `path_simplified` reduces to ~2 points

4. **Spatial queries:**
   - Create legs in different locations
   - Query legs within 5km of point
   - Verify only nearby legs returned

5. **GeoJSON export:**
   - Query `ST_AsGeoJSON(path)`
   - Verify valid GeoJSON LineString format

### Integration Test

```bash
# Test with real device data
python -m app.services.trip_engine
# Process 100 positions
# Verify:
# - All legs have non-null path column
# - All stationaries have non-null centroid column
# - Simplified paths have fewer points than full paths
# - ST_Length(path) ≈ distance_m
```

## Example Log Output

```
📐 IMEI 780901807676441: Leg 550e8400-... geometry created (45 points → simplified)
🔵 IMEI 780901807676441: Leg created: 12.34 km over 15 min (45 points)
📐 IMEI 780901807676441: Stationary 661e9511-... geometry created
🟠 IMEI 780901807676441: Stationary created at (51.5074, -0.1278) for 5 min (8 points)
```

## Files Modified

- `gps-tracker/docker-compose.yml` (PostGIS image)
- `gps-tracker/docker-compose.local.yml` (PostGIS image)
- `gps-tracker/backend/requirements.txt` (+geoalchemy2)
- `gps-tracker/backend/alembic/versions/056_add_postgis_geometry.py` (new migration)
- `gps-tracker/backend/app/services/trip_engine.py` (+geometry builders, +60 lines)
- `gps-tracker/backend/app/models.py` (geometry column comments)

## Success Criteria

✅ PostGIS extension enabled  
✅ Leg paths stored as LineString geometry  
✅ Simplified paths created for rendering  
✅ Stationary centroids stored as Point geometry  
✅ GiST indexes created for spatial queries  
✅ Geometry built automatically when creating legs/stationaries  
✅ Error handling for geometry failures  
⏳ End-to-end testing with real data (pending)

## Migration Steps (Deployment)

When deploying to production:

1. **Pull latest code with PostGIS changes**
2. **Restart containers** (automatically pulls `postgis/postgis:15-alpine`)
3. **Run migration:**
   ```bash
   docker exec pinplot_backend alembic upgrade head
   ```
4. **Verify PostGIS enabled:**
   ```sql
   SELECT PostGIS_Version();
   -- Should return: "3.x USE_GEOS=1 USE_PROJ=1 ..."
   ```
5. **Check backfill:**
   ```sql
   SELECT COUNT(*) FROM legs WHERE path IS NOT NULL;
   SELECT COUNT(*) FROM stationaries WHERE centroid IS NOT NULL;
   ```

## Next Steps

**Phase 4: Admin Configuration**
- Global config UI for trip engine parameters
- Per-tenant overrides for coalesce_floor_minutes
- Subscription management UI (trip_subscribed toggle)

**Phase 5: Frontend UI**
- Movement History Advanced page
- Map component with journey visualization
- GeoJSON path rendering (simplified at low zoom, full-res at high zoom)
- Journey cards with "Plot all" button

**Phase 6: Backend API Endpoints**
- `GET /api/devices/{imei}/journeys` - List journeys with date filter
- `GET /api/journeys/{id}/path` - Get GeoJSON path (with ?simplified=true)
- `GET /api/devices/{imei}/positions` - Raw positions for timeline
- `POST /api/trip-engine/process` - Manual trigger for testing

---

**Commit:** `feat: Add PostGIS integration (Phase 3.4)`  
**Lines Added:** ~200  
**Docker Images Changed:** postgres:15-alpine → postgis/postgis:15-alpine  
**Dependencies Added:** geoalchemy2==0.14.3  
**Migration:** 056_add_postgis_geometry.py
