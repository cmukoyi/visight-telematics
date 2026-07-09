# Journey Path Rendering - Test & Validation Plan

## Problem Statement
Journey legs were rendering as **straight lines** (point A → point B) instead of showing the actual GPS path with all intermediate positions. This defeats the purpose of the Trip Engine's position refinement.

---

## Root Causes Found

### 1. **Missing GeoAlchemy2 Import** ❌
- `models.py` was missing `from geoalchemy2 import Geometry`
- SQLAlchemy didn't know about the PostGIS geometry columns
- **Fixed in commit:** 9de1780

### 2. **Commented Out Geometry Columns** ❌  
- `Leg.path` and `Leg.path_simplified` were commented out in models.py
- `Stationary.centroid` was commented out
- Even though migration 056 created these columns in the database!
- **Fixed in commit:** 9de1780

### 3. **Frontend Drawing Logic** ❌
- UI was only using `[start_lat, start_lng]` and `[end_lat, end_lng]` 
- Ignored the full path geometry from the database
- **Fixed in commit:** 4b84e7d

### 4. **Old Journey Data Only Has 2 Points** ⚠️
- Migration 056 backfilled old legs with minimal paths:
  ```sql
  ST_MakeLine(ST_MakePoint(start_lng, start_lat), ST_MakePoint(end_lng, end_lat))
  ```
- These are straight lines by definition!
- **Solution:** Reprocess journeys to rebuild from raw positions

---

## Test Plan

### Phase 1: Verify Database Schema ✅
```bash
# Connect to production database
docker exec -it pinplot_db psql -U beacon_user -d beacon_telematics

# Check PostGIS is enabled
SELECT PostGIS_Version();

# Check columns exist
\d legs
# Should show: path, path_simplified columns

# Check if any legs have multi-point paths
SELECT 
  id,
  ST_NumPoints(path) as num_points,
  ST_Length(path::geography) as length_m
FROM legs
WHERE path IS NOT NULL
ORDER BY started_at DESC
LIMIT 10;
```

**Expected:** Newer legs should have > 2 points, old legs only have 2

---

### Phase 2: Verify Backend API ✅
```bash
cd /Users/carl/Documents/MobileCode/Pinplot/gps-tracker/backend

# Run verification script
python verify_journey_paths.py --imei 781950640095475

# Should output:
# ✅ Legs with geometry: X/Y
# ✅ Total coordinates: Z
# ⚠️  Avg coordinates per leg: 2.0  ← If old data
# ✅ Avg coordinates per leg: 87.3  ← If reprocessed
```

**Expected Results:**

**Old journeys (before reprocess):**
```
Leg 1: ⚠️  2 coordinates, 1234m
       ⚠️  Only 2 points - this is a straight line!
```

**New journeys (after reprocess):**
```
Leg 1: ✅ 87 coordinates, 1234m
Leg 2: ✅ 143 coordinates, 2456m
```

---

### Phase 3: Test API Endpoint 🔍
```bash
# Test the GeoJSON path endpoint
curl -X GET "http://localhost:8000/api/portal/journeys/{JOURNEY_ID}/path" \
  -H "Authorization: Bearer YOUR_TOKEN" | jq

# Expected response:
{
  "type": "FeatureCollection",
  "features": [
    {
      "type": "Feature",
      "geometry": {
        "type": "LineString",
        "coordinates": [
          [-0.1278, 51.5074],  ← Start
          [-0.1280, 51.5076],  ← Position 2
          [-0.1282, 51.5078],  ← Position 3
          ...                  ← Many more
          [-0.1290, 51.5090]   ← End
        ]
      },
      "properties": {
        "type": "leg",
        "distance_m": 1234.5,
        ...
      }
    }
  ]
}
```

**Success Criteria:**
- ✅ Each leg has `coordinates` array
- ✅ Array length > 2 for reprocessed legs
- ✅ Coordinates are `[lng, lat]` format (GeoJSON standard)

---

### Phase 4: Test Frontend Rendering 🗺️

#### Step 1: Open Browser Console
```javascript
// In production: https://your-app.com
// Navigate to Movement History Advanced
// Select an asset
// Select a journey

// Check console logs:
// [MHA] Path data: {features: [...]}
// [MHA] Leg 1 has 87 positions  ← Should see position count
// [MHA] Leg 2 has 143 positions
```

#### Step 2: Inspect Map
**What to look for:**

✅ **Good (Reprocessed Journey):**
- Blue polyline follows roads/paths
- Small blue dots along the path (GPS positions)
- Curved lines matching actual routes
- Popup shows: "Positions: 87"

❌ **Bad (Old Journey):**
- Straight line connecting start/end
- Only 2 blue dots (start, end)
- Ignores roads/terrain
- Popup shows: "Positions: 2"

#### Step 3: Visual Comparison
Open reference design side-by-side:
```bash
open /Users/carl/Documents/MobileCode/Pinplot/features_dev/MovementHistoryAdvancedLayout.html
```

**Compare:**
- Journey card layout ✅
- Idle connectors (orange dashed) ✅  
- Map path rendering (should match reference curves)

---

### Phase 5: Reprocess Test Journey 🔄

```bash
cd /Users/carl/Documents/MobileCode/Pinplot/gps-tracker/backend

# Reprocess a test device
python reprocess_trip_engine.py --imei 781950640095475

# Verify it worked
python verify_journey_paths.py --imei 781950640095475
```

**Before reprocess:**
```
Leg 1: ⚠️  2 coordinates (straight line)
Total coordinates: 12 (6 legs × 2)
```

**After reprocess:**
```
Leg 1: ✅ 87 coordinates  
Leg 2: ✅ 143 coordinates
Total coordinates: 876 (6 legs × avg 146)
```

---

## Validation Checklist

### Backend ✅
- [ ] PostGIS extension enabled
- [ ] `geoalchemy2` package installed
- [ ] `Geometry` type imported in models.py
- [ ] `Leg.path` column uncommented
- [ ] `Leg.path_simplified` column uncommented
- [ ] `Stationary.centroid` column uncommented
- [ ] Trip engine populates path with `ST_MakeLine`
- [ ] `/api/portal/journeys/{id}/path` returns GeoJSON with coordinates

### Frontend ✅
- [ ] Fetches `/api/portal/journeys/{id}/path` endpoint
- [ ] Extracts LineString coordinates from GeoJSON
- [ ] Converts `[lng, lat]` to Leaflet `[lat, lng]`
- [ ] Draws polyline with ALL coordinates (not just start/end)
- [ ] Adds position dots (2px circles) along path
- [ ] Shows position count in popup
- [ ] Falls back to straight line if no geometry

### Data Quality ⚠️
- [ ] **Old journeys:** Only have 2 points (backfilled by migration)
- [ ] **New journeys:** Have full multi-point paths (created by trip engine)
- [ ] **Reprocessed journeys:** Rebuilt from positions with full paths

---

## How to Verify a Fix Actually Works

### DON'T ❌
```bash
# Make changes
git add -A
git commit -m "fix stuff"
git push
# 🤞 Hope it works in production
```

### DO ✅
```bash
# 1. Run local verification first
python verify_journey_paths.py

# 2. Check if paths have > 2 points
# If NO: Need to reprocess journey data

# 3. Test API response
curl localhost:8000/api/portal/journeys/{id}/path | jq '.features[0].geometry.coordinates | length'
# Should return > 2

# 4. Test frontend locally
# Open http://localhost:3000
# Open browser console
# Look for: "[MHA] Leg 1 has 87 positions"

# 5. THEN commit and deploy
git add -A
git commit -m "fix: verified working with 87+ positions per leg"
git push
```

---

## Current Status

### Commits
1. **4b84e7d** - Frontend: Fetch path GeoJSON and render full coordinates
2. **9de1780** - Backend: Uncomment geometry columns and add import

### Known Issues
- ❌ **Old journeys still show straight lines** 
  - Reason: Backfilled with only 2 points in migration 056
  - Solution: Run `reprocess_trip_engine.py` for each device

### Next Steps
1. ✅ Verify script exists: `verify_journey_paths.py`
2. ⏳ Run verification on production data
3. ⏳ Reprocess key test devices
4. ⏳ Confirm paths render correctly in browser
5. ⏳ Document which devices have been reprocessed

---

## Test Commands Quick Reference

```bash
# Verify database
docker exec -it pinplot_db psql -U beacon_user -d beacon_telematics -c "SELECT id, ST_NumPoints(path) FROM legs LIMIT 5;"

# Verify backend
cd gps-tracker/backend
python verify_journey_paths.py --imei 781950640095475

# Reprocess device
python reprocess_trip_engine.py --imei 781950640095475

# Test API
curl http://localhost:8000/api/portal/journeys/{ID}/path | jq '.features[].geometry.coordinates | length'

# Check frontend console (browser)
# [MHA] Leg 1 has 87 positions  ← Success!
# [MHA] Leg 1 has no path geometry, using straight line  ← Needs reprocess
```

---

## Success Metrics

**Before Fix:**
- 100% of journey legs rendered as straight lines
- Average 2 coordinates per leg
- Map showed "teleportation" between waypoints

**After Fix (Reprocessed Data):**
- 0% straight lines (all legs follow actual paths)
- Average 50-200 coordinates per leg
- Map shows realistic routes following roads

**Current Reality:**
- Frontend code: ✅ Fixed
- Backend models: ✅ Fixed  
- Old data: ❌ Still only 2 points (needs reprocessing)
- New data: ✅ Will have full paths automatically
