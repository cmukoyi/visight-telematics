# BLE Indoor Positioning - Tag Filtering Fix

## Problem

The PinPlot floor plan was tracking **38k+ unregistered BLE devices** instead of only tracking the registered DX-Smart CP27/CP28/CP29 indoor tags. This happened because the original `pareto_bridge.py` was processing all ambient BLE devices (phones, watches, laptops, etc.) detected by Pareto Anywhere.

## Root Cause

The filter in `pareto_bridge.py` only checked:
```python
BLETag.mac_address == tag_id AND BLETag.is_active == True
```

But it **did NOT** filter by `tag_type`, so it was allowing:
- GPS trackers (`series1`, `series2`, `series_3`, `scope`)  
- Any BLE device with a matching MAC address

This resulted in tens of thousands of ambient BLE devices being stored in `tag_indoor_positions`.

## Solution

### ✅ Fix 1: Enhanced Filter in pareto_bridge.py

**File**: `gps-tracker/backend/app/services/pareto_bridge.py`

Added `tag_type` filter to only process indoor BLE tags:

```python
registered_tag = db.query(BLETag).filter(
    BLETag.mac_address == tag_id,
    BLETag.tag_type == "ble",  # ← NEW: Only indoor BLE tags
    BLETag.is_active == True
).first()
```

This prevents future ingestion of unregistered devices.

### ✅ Fix 2: iBeacon UUID Validation (Optional)

Added optional secondary filter for deployments that want to restrict to specific DX-Smart tag batches:

**Environment Variable**: `ALLOWED_IBEACON_UUIDS`

```bash
# In .env or docker-compose.yml:
ALLOWED_IBEACON_UUIDS=E2C56DB5-DFFB-48D2-B060-D0F5A71096E0,other-uuid-here
```

When configured, only tags broadcasting one of the allowed iBeacon UUIDs will be tracked.

**Note**: Per the floor plan spec §3.6, the factory default UUID is `E2C56DB5-DFFB-48D2-B060-D0F5A71096E0`, but you should configure each deployment batch with its own unique UUID.

### ✅ Fix 3: Cleanup Script

**File**: `gps-tracker/backend/scripts/cleanup_unregistered_indoor_positions.py`

Removes existing unregistered indoor positions from the database.

## Usage

### Step 1: Deploy the Filter Fix

```bash
cd /Users/carl/Documents/MobileCode/Pinplot

# Commit the filter fix
git add gps-tracker/backend/app/services/pareto_bridge.py
git commit -m "fix(floor-plan): filter BLE indoor tags by tag_type='ble' to prevent 38k ambient device tracking"

# Push to main
git push origin main

# Deploy to production
cd gps-tracker/backend
# Follow your normal deployment process
```

### Step 2: Run Cleanup Script (Dry-Run First)

```bash
cd /Users/carl/Documents/MobileCode/Pinplot/gps-tracker/backend

# Preview what would be deleted (SAFE - no changes):
python scripts/cleanup_unregistered_indoor_positions.py --dry-run

# Output example:
# 📊 Current Statistics:
#    Total indoor positions: 38,247
#    Registered BLE tags (type='ble', active): 15
#    Unregistered positions to clean: 38,232
# 
# ⚠️  99.9% of positions are unregistered
```

### Step 3: Run Cleanup (With Backup)

```bash
# Create backup and delete unregistered positions:
python scripts/cleanup_unregistered_indoor_positions.py --backup

# You'll be prompted:
# ⚠️  WARNING: About to delete unregistered indoor positions!
#    Backup created: tag_indoor_positions_backup_20260624_153045
#    Records to delete: 38,232
# 
# Type 'DELETE' to confirm: DELETE
```

### Step 4: Verify Results

After cleanup, your floor plan should only show registered indoor BLE tags:

```bash
# In PostgreSQL:
psql -U postgres -d pinplot_db

SELECT 
    COUNT(*) as total_positions,
    COUNT(DISTINCT tag_id) as unique_tags
FROM tag_indoor_positions;

# Should match the number of registered BLETag records with tag_type='ble'
```

## Optional: Enable iBeacon UUID Filtering

If you want to restrict tracking to only DX-Smart tags configured with your deployment UUID:

```bash
# In docker-compose.yml or .env:
ALLOWED_IBEACON_UUIDS=your-deployment-uuid-here

# Restart backend:
docker-compose restart backend
```

**How to configure tags**: Follow the DX-Smart app instructions in `features_dev/pinplot-mvp-floorplan v2.md` §3.6 to set a custom UUID for your deployment.

## Rollback (If Needed)

If something goes wrong, restore from backup:

```sql
-- In PostgreSQL:
DROP TABLE tag_indoor_positions;
ALTER TABLE tag_indoor_positions_backup_20260624_153045 RENAME TO tag_indoor_positions;
```

## Architecture Summary

### Multi-Tenant Separation (Question 1)

**Yes**, BLE networks must be registered in a usergroup for assets to appear on floor plans:

1. **Building** → has `usergroup_id` (tenant)  
2. **Floor** → belongs to Building  
3. **Gateway** → registered in `IndoorGateway`, assigned to Floor  
4. **BLE Tag** → must exist in `BLETag` with `tag_type='ble'` and `is_active=True`  
5. **TagIndoorPosition** → has `usergroup_id` copied from Building via Floor→Building chain

Different users see different floor plans because the API (`routes_floorplan.py`) filters by `usergroup_id`.

### Tag Types

| tag_type | Description | Indoor Tracking? |
|----------|-------------|------------------|
| `ble` | Indoor BLE tags (DX-Smart CP27/CP28/CP29) | ✅ Yes |
| `series1` | GPS tracker (Series 1) | ❌ No |
| `series2` | GPS tracker (Series 2) | ❌ No |
| `series_3` | GPS tracker (Series 3 with QR) | ❌ No |
| `scope` | GPS tracker (Scope) | ❌ No |

### Supported Tags (Question 3)

Per spec §3.6, only these tags should be tracked indoors:
- **DX-Smart CP27** (card, 40×24×5 mm, IP67)  
- **DX-Smart CP28** (disc, 61×61×18 mm, wall-mount)  
- **DX-Smart CP29** (card, 53×85×6 mm, rechargeable)

All three are BLE 5.1 tags with iBeacon + Eddystone support.

## Implementation Status (Question 2)

| Feature | Status | Location |
|---------|--------|----------|
| Pareto Anywhere integration | ✅ Implemented | `services/pareto_bridge.py` |
| Floor Plan API | ✅ Implemented | `routes_floorplan.py` |
| Indoor positioning table | ✅ Implemented | `models.py` (TagIndoorPosition) |
| Gateway registration | ✅ Implemented | Admin portal + DB |
| Tenant scoping | ✅ Implemented | Via usergroup_id chain |
| Tag type filtering | ✅ Fixed (this PR) | `pareto_bridge.py` line 132 |
| iBeacon UUID filtering | ✅ Added (optional) | `pareto_bridge.py` line 142 |
| Battery telemetry | ✅ Implemented | Via Eddystone-TLM |
| TX power tuning | ⚠️ Manual | Admin configures tags per spec §3.6 |

## Testing

1. **Verify filter is working**:
   ```bash
   # Tail backend logs to see rejected devices:
   docker-compose logs -f backend | grep "pareto_bridge"
   
   # You should see rejections for unregistered devices (silently ignored)
   # But no logs for ambient BLE devices anymore
   ```

2. **Check tag count**:
   ```sql
   -- Should only show registered indoor tags:
   SELECT COUNT(DISTINCT tag_id) FROM tag_indoor_positions;
   
   -- Compare to registered BLE tags:
   SELECT COUNT(*) FROM ble_tags 
   WHERE tag_type = 'ble' AND is_active = TRUE;
   ```

3. **Verify floor plan UI**:
   - Log in to customer dashboard
   - Navigate to floor plan
   - Should only see registered indoor BLE tags (typically 10-50, not 38k!)

## Next Steps

After deploying this fix:

1. ✅ No more ambient BLE device ingestion  
2. ✅ Clean database with only registered indoor tags  
3. ✅ Optional iBeacon UUID filtering available  
4. ⏭️ Configure DX-Smart tags with deployment UUID (optional, see spec §3.6)  
5. ⏭️ Tune TX power for multi-floor isolation (see spec §3.3 and §3.6)

## Related Files

- **Spec**: `features_dev/pinplot-mvp-floorplan v2.md`  
- **Filter**: `gps-tracker/backend/app/services/pareto_bridge.py`  
- **Cleanup**: `gps-tracker/backend/scripts/cleanup_unregistered_indoor_positions.py`  
- **Models**: `gps-tracker/backend/app/models.py`  
- **API**: `gps-tracker/backend/app/routes_floorplan.py`

## Questions?

See the floor plan spec for comprehensive implementation details:
```bash
open /Users/carl/Documents/MobileCode/Pinplot/features_dev/pinplot-mvp-floorplan\ v2.md
```
