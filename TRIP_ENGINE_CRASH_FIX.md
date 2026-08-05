# Trip Engine Crash Loop Fix - July 29, 2026

## Problem
Trip engine crash-looping every 15 minutes with:
```
UniqueViolation: duplicate key value violates unique constraint "ux_journey_device_start"
```

After the initial UniqueViolation, database session becomes poisoned:
```
This Session's transaction has been rolled back due to a previous exception during flush
```

## Root Causes

### 1. No Session Recovery After Error
When one device's processing hits a UniqueViolation, the database session becomes poisoned but wasn't rolled back. All remaining devices in that cycle failed with "session rolled back" error.

**Fixed in**: `trip_engine.py` line 2313
- Added `db.rollback()` after exception
- Allows remaining devices to process even if one fails

### 2. No Error Handling in Journey Upsert
The `_ensure_journey_open()` upsert had no try-except, so any conflict crashed the entire device processing.

**Fixed in**: `trip_engine.py` line 553
- Added try-except around upsert execution
- On failure, queries for existing journey as fallback
- Added explicit flush after successful upsert
- Rolls back and continues rather than crashing

### 3. Existing Duplicate Journeys in Database (Data Corruption)
If duplicate journeys already exist from previous bugs, the upsert will fail because you can't upsert when duplicates already exist.

**Fixed with**: `fix_duplicate_journeys.py` script
- Finds duplicate (device_imei, started_at) pairs
- Keeps oldest journey, deletes others
- Safe dry-run mode

## Files Changed

1. **gps-tracker/backend/app/services/trip_engine.py**
   - Line 2313: Added rollback in exception handler
   - Line 553-580: Added try-except around journey upsert with fallback

2. **fix_duplicate_journeys.py** (NEW)
   - Python script to clean up existing duplicates
   
3. **fix_duplicate_journeys.sql** (NEW)
   - SQL queries to manually inspect/fix duplicates

## Deployment Steps

### Step 1: Clean up existing duplicate journeys
```bash
cd ~/pinplot/gps-tracker
python3 fix_duplicate_journeys.py         # Dry run - shows what will be deleted
python3 fix_duplicate_journeys.py --fix   # Actually delete duplicates
```

### Step 2: Deploy code fix
```bash
# Build new backend image with fixes
cd ~/pinplot/gps-tracker
docker compose build backend

# Stop backend
docker compose down backend

# Start with new code
docker compose up -d backend
```

### Step 3: Monitor recovery
```bash
# Watch for successful trip engine cycles
docker logs -f pinplot_backend 2>&1 | grep "Trip engine:"

# Should see:
# INFO:app.services.trip_engine:✅ Trip engine: 36 devices processed, X new journeys created
```

### Step 4: Verify device 767 is processing
```bash
# Check engine state updates
docker exec pinplot_db psql -U beacon_user -d beacon_db -c "
SELECT 
    device_imei,
    last_received_at,
    last_processed_at,
    updated_at,
    (last_received_at - last_processed_at) as unprocessed_gap
FROM engine_state
WHERE device_imei = '780901807708767';
"

# Check if new journeys are being created
docker exec pinplot_db psql -U beacon_user -d beacon_db -c "
SELECT id, started_at, ended_at, leg_count, stationary_count
FROM journeys
WHERE device_imei = '780901807708767'
ORDER BY started_at DESC
LIMIT 5;
"
```

## Expected Behavior After Fix

✅ Trip engine completes successfully every 15 minutes  
✅ Devices with errors don't poison the session  
✅ Remaining devices process even if one fails  
✅ Journey upsert handles conflicts gracefully  
✅ No more crash loops  

## Monitoring Commands

```bash
# Count successful trip engine cycles (should increment every 15 min)
docker logs pinplot_backend 2>&1 | grep "devices processed" | tail -5

# Count errors (should be 0 or rare)
docker logs pinplot_backend 2>&1 | grep "Trip engine loop error" | wc -l

# Check device 767 watermark gap
docker exec pinplot_db psql -U beacon_user -d beacon_db -c "
SELECT 
    device_imei,
    last_received_at,
    last_processed_at,
    last_received_at - last_processed_at as gap
FROM engine_state
WHERE device_imei = '780901807708767';
"
```

## Rollback Plan

If the fix causes issues:

```bash
# Revert to previous backend image
cd ~/pinplot/gps-tracker
git log --oneline -5  # Find previous commit
git checkout <previous-commit-sha> gps-tracker/backend/app/services/trip_engine.py
docker compose build backend
docker compose down backend
docker compose up -d backend
```

## Prevention

These fixes prevent future crash loops by:
1. **Session isolation**: One device's error doesn't break others
2. **Graceful fallback**: Journey conflicts are handled, not crashed
3. **Data integrity**: Duplicate cleanup script can be run anytime
4. **Better logging**: More visibility into what's failing

## Related Files

- `diagnose_767_watermark.py` - Diagnostic tool for watermark issues
- `diagnose_767_watermark.sql` - SQL diagnostic queries
- `fix_watermark.py` - Tool to fix frozen watermarks (different issue)
