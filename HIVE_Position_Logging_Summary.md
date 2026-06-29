# HIVE Enhanced Position Logging — Implementation Summary

**Deployed:** 2026-06-20  
**Branch:** main  
**Commit:** d5ee0a8  
**Status:** ✅ DEPLOYED to pinplot.me (auto-deploy via GitHub Actions)

---

## What Was Implemented

Per the requirements in `HIVE_Position_Logging_Additions.md`, we've added enhanced position logging to HIVE evaluations for trajectory analysis.

### ✅ Implemented (Available Now)

#### 1. Coordinates in `positions_used` ✅
**Before:**
```json
{
  "tag_id": "1573199d-...",
  "observed_at": "2026-06-13T13:18:24+00:00"
}
```

**Now:**
```json
{
  "tag_id": "1573199d-...",
  "observed_at": "2026-06-13T13:18:24+00:00",
  "lat": 51.3757,
  "lon": -0.1953
}
```

- ✅ Latitude and longitude included in every position
- ✅ Rounded to 6 decimal places (~0.11m precision)
- ✅ Sorted by tag_id, then timestamp

#### 2. Tag Fix History ✅ (Current Fix Only)
**New field:** `tag_fix_history` in evaluation records

**Structure:**
```json
{
  "tag_fix_history": {
    "1573199d-...": [
      {
        "observed_at": "2026-06-13T13:18:24+00:00",
        "lat": 51.3757,
        "lon": -0.1953
      }
    ],
    "1b9fc188-...": [
      {
        "observed_at": "2026-06-13T13:20:15+00:00",
        "lat": 51.3762,
        "lon": -0.1948
      }
    ]
  }
}
```

**Current Limitation:**
- ⚠️ Only captures **current fix** per tag (1 position)
- ❌ Does NOT yet capture "last 5 fixes or 30 minutes" as specified
- **Reason:** No dedicated position history table exists yet
- **TODO:** Will be expanded when position history table is implemented

#### 3. Metadata Flags ✅
Added explicit availability flags in `freshness_composition.meta`:

```json
{
  "freshness_composition": {
    "fresh": 2,
    "recent": 1,
    "stale": 0,
    "lost": 0,
    "meta": {
      "snapshot_fingerprint": "...",
      "coherence_window_s": 300,
      ...existing fields...,
      "accuracy_available": false,
      "source_id_available": false,
      "position_history_available": false
    }
  }
}
```

These flags make it clear what data is and isn't available.

---

## ❌ Not Yet Implemented

### Per-Fix Source Identifier (`source_id`)
**Status:** ❌ Not available  
**Reason:** Not tracked in BLETag model, upstream ingestion doesn't provide it  
**What's needed:**
- Add `source_id` column to `ble_tags` table
- Update position ingestion to capture reporting phone/gateway identifier
- Modify evaluation code to include source_id in positions_used and tag_fix_history

### Per-Fix Accuracy (`accuracy_m`)
**Status:** ❌ Not available  
**Reason:** Upstream crowdsourced data doesn't provide GPS accuracy  
**What's needed:**
- Upstream sources must provide accuracy/precision figures
- Add `accuracy_m` column to `ble_tags` table
- Include in position payloads

### Full Position History (Last 5 Fixes / 30 Minutes)
**Status:** ⚠️ Partially implemented (current fix only)  
**Reason:** No dedicated position history table  
**What's needed:**
1. Create `ble_tag_positions` history table:
   ```sql
   CREATE TABLE ble_tag_positions (
     tag_id UUID,
     observed_at TIMESTAMP WITH TIME ZONE,
     latitude FLOAT,
     longitude FLOAT,
     source_id VARCHAR(100),
     accuracy_m FLOAT,
     PRIMARY KEY (tag_id, observed_at)
   );
   ```
2. Update position ingestion to persist to history table
3. Modify `_tag_fix_history_payload()` to query last 5 fixes or 30 min
4. Set `position_history_available: true` once implemented

---

## How to Access the New Logging

### In Evaluation Records
Query `hive_evaluations` table:

```sql
SELECT 
  id,
  evaluated_at,
  hive_id,
  positions_used,      -- Now includes lat/lon
  tag_fix_history,     -- New field
  freshness_composition -- Check meta.accuracy_available etc
FROM hive_evaluations
WHERE hive_id = 'your-hive-id'
  AND evaluated_at > NOW() - INTERVAL '1 day'
ORDER BY evaluated_at DESC;
```

### In Log Exports
When exporting evaluation logs, parse the JSON fields:

```python
import json

eval_data = get_evaluation_from_db(eval_id)

# Parse enhanced positions
positions = json.loads(eval_data.positions_used)
for pos in positions:
    print(f"Tag {pos['tag_id']} at ({pos['lat']}, {pos['lon']}) @ {pos['observed_at']}")

# Parse fix history
history = json.loads(eval_data.tag_fix_history) if eval_data.tag_fix_history else {}
for tag_id, fixes in history.items():
    print(f"Tag {tag_id}: {len(fixes)} fix(es)")
    for fix in fixes:
        print(f"  {fix['observed_at']}: ({fix['lat']}, {fix['lon']})")

# Check metadata
composition = json.loads(eval_data.freshness_composition)
meta = composition.get("meta", {})
print(f"Accuracy available: {meta.get('accuracy_available')}")
print(f"Source ID available: {meta.get('source_id_available')}")
print(f"Position history available: {meta.get('position_history_available')}")
```

---

## What Testers Can Analyze NOW

### ✅ Spatial Analysis (Available)
- Tag positions at evaluation time (lat/lon)
- Distance calculations between tags
- Outlier identification verification
- Diameter computation validation
- Coordinate precision assessment

### ✅ Temporal Analysis (Limited)
- Current position timestamp per tag
- Freshness tier classification
- Coherence window compliance
- ⚠️ **Cannot yet analyze trajectories** (need historical positions)

### ❌ Trajectory Analysis (Not Yet Possible)
**Requires full position history (last 5 fixes / 30 min):**
- Tag movement patterns
- Velocity vectors
- Heading/bearing analysis
- Diverging path detection
- ⚠️ **Will be available once position history table implemented**

### ❌ Source Attribution (Not Yet Possible)
**Requires source_id:**
- Which phone/gateway reported each position
- Cross-source consistency checks
- Reporter-based filtering

### ❌ Quality Analysis (Not Yet Possible)
**Requires accuracy_m:**
- GPS precision assessment
- Low-accuracy fix filtering
- Quality-based weighting

---

## Migration Status

### Migration 053 ✅
**File:** `053_add_tag_fix_history.py`  
**Status:** Created and ready to deploy  
**Action:** Adds `tag_fix_history` column to `hive_evaluations`

**To apply manually (if needed):**
```bash
cd gps-tracker/backend
alembic upgrade head
```

**Auto-deployment:** Will run automatically when pushed to main

---

## Testing

### Verify Enhanced Logging Works

#### 1. Check Latest Evaluation Has Coordinates
```sql
SELECT 
  id,
  evaluated_at,
  positions_used
FROM hive_evaluations
ORDER BY evaluated_at DESC
LIMIT 1;
```

**Expected:** `positions_used` JSON includes `lat` and `lon` fields

#### 2. Check Tag Fix History Exists
```sql
SELECT 
  id,
  evaluated_at,
  tag_fix_history
FROM hive_evaluations
WHERE tag_fix_history IS NOT NULL
ORDER BY evaluated_at DESC
LIMIT 1;
```

**Expected:** `tag_fix_history` JSON with per-tag position arrays

#### 3. Check Metadata Flags
```sql
SELECT 
  id,
  evaluated_at,
  freshness_composition
FROM hive_evaluations
ORDER BY evaluated_at DESC
LIMIT 1;
```

**Expected:** `freshness_composition.meta` includes:
- `accuracy_available: false`
- `source_id_available: false`
- `position_history_available: false`

### Run Unit Tests
```bash
cd gps-tracker/backend
pytest tests/test_hive_position_logging.py -v
```

**Expected:** All tests pass

---

## Next Steps for Full Implementation

### Priority 1: Position History Table (High Priority)
**Enables:** Trajectory analysis, movement patterns, velocity vectors

**Tasks:**
1. Create migration for `ble_tag_positions` table
2. Update position ingestion to persist history
3. Add retention policy (e.g., keep 7 days)
4. Modify `_tag_fix_history_payload()` to query last 5 / 30 min
5. Set `position_history_available: true`

**Estimated effort:** 2-3 days

### Priority 2: Source Identifier (Medium Priority)
**Enables:** Reporter attribution, cross-source validation

**Tasks:**
1. Identify upstream source identifier format
2. Add `source_id` to BLETag and position history tables
3. Update ingestion to capture source_id
4. Include in all position payloads
5. Set `source_id_available: true`

**Estimated effort:** 1-2 days

### Priority 3: GPS Accuracy (Low Priority)
**Enables:** Quality-based filtering, precision assessment

**Tasks:**
1. Verify upstream sources provide accuracy
2. Add `accuracy_m` to position tables
3. Include in position payloads
4. Set `accuracy_available: true`

**Estimated effort:** 1 day

**Blocker:** Requires upstream data sources to provide accuracy

---

## Files Changed

| File | Change | Lines |
|------|--------|-------|
| `053_add_tag_fix_history.py` | NEW | +38 |
| `models.py` | MODIFY | +1 |
| `hive_service.py` | MODIFY | +52 |
| `test_hive_position_logging.py` | NEW | +296 |

**Total:** 387 insertions

---

## Summary for Testers

### ✅ What You Can Do NOW
- Access tag coordinates (lat/lon) in `positions_used`
- See current fix per tag in `tag_fix_history`
- Verify spatial relationships at evaluation time
- Check metadata flags for data availability

### ⚠️ What's Limited
- **Only 1 fix per tag** (not last 5 or 30 minutes)
- No trajectory analysis possible yet
- No source attribution
- No GPS accuracy data

### 🔜 What's Coming Next
1. Full position history (last 5 fixes / 30 min)
2. Source identifier per fix
3. GPS accuracy per fix

### 📋 Immediate Action Items
1. Verify enhanced logging in latest evaluations
2. Run `pytest tests/test_hive_position_logging.py`
3. Export sample evaluation records to validate JSON structure
4. Provide feedback on what additional trajectory data is needed

---

## Contact / Questions

For questions about:
- **What data is available:** Check metadata flags in `freshness_composition.meta`
- **How to access the data:** See "How to Access the New Logging" section above
- **When full history will be available:** Priority 1 task, ETA 2-3 days after decision to implement
- **Implementation details:** See commit d5ee0a8 and `HIVE_Position_Logging_Additions.md`

---

*Deployed: 2026-06-20, Commit d5ee0a8*
