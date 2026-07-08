# Trip Engine Deployment & Activation Guide

**Date:** July 8, 2026  
**Status:** CRITICAL - Trip engine code deployed but never activated

---

## 🚨 PROBLEM IDENTIFIED

The Movement History Advanced feature UI is 100% complete and working, but **NO DATA** appears because:
- ✅ Trip engine database schema fully deployed (8 tables with PostGIS)
- ✅ All ingestion/processing code exists and tested
- ❌ **Background tasks NEVER STARTED** in production
- ❌ **No data migration** from old `tracksolid_locations` table
- ❌ **No devices subscribed** to trip tracking

**Result:** 
- 5,595 positions exist in OLD table (`tracksolid_locations`)
- 0 positions in NEW table (`device_positions`)
- 0 journeys generated
- UI shows empty state

---

## 🛠️ DEPLOYMENT STEPS

### Step 1: Pull Latest Code

```bash
cd ~/pinplot/gps-tracker
git pull origin main
```

**Expected commit:** `a678853` - "fix: Add Trip Engine background tasks and data migration"

**Changes:**
- `backend/app/main.py` - Added trip engine startup tasks
- `backend/app/services/tracksolid_batch_service.py` - Added background loop
- `backend/app/services/tracksolid_track_service.py` - Added background loop
- `backend/app/services/trip_engine.py` - Added background loop
- `backend/migrate_trip_engine_data.py` - NEW migration script

---

### Step 2: Run Data Migration (ONE-TIME)

This migrates existing position data and sets up device subscriptions.

```bash
# Navigate to backend directory
cd ~/pinplot/gps-tracker/backend

# Option A: Migrate ONLY test device (recommended for testing)
docker exec -it pinplot_backend python migrate_trip_engine_data.py \
  --imei 781950640095475 \
  --subscribe-all

# Option B: Migrate ALL devices (production deployment)
docker exec -it pinplot_backend python migrate_trip_engine_data.py \
  --all \
  --subscribe-all

# Option C: Dry run first (see what would happen)
docker exec -it pinplot_backend python migrate_trip_engine_data.py \
  --imei 781950640095475 \
  --subscribe-all \
  --dry-run
```

**What this does:**
1. Copies positions from `tracksolid_locations` → `device_positions`
2. Creates `device_state` rows with `trip_subscribed=true`
3. Initializes `tracksolid_sync_state` singleton

**Expected output:**
```
================================================================================
MIGRATING POSITIONS FROM tracksolid_locations → device_positions
================================================================================
🎯 Target: IMEI 781950640095475
📊 Found 5595 positions to migrate

✅ Migration complete:
   Inserted: 5595
   Skipped (duplicates): 0

================================================================================
CREATING device_state ROWS
================================================================================
✅ Created/updated 1 device_state rows
   trip_subscribed: True

================================================================================
INITIALIZING tracksolid_sync_state
================================================================================
✅ Created tracksolid_sync_state row

================================================================================
✅ MIGRATION COMPLETE!
================================================================================
🚀 Trip engine is now ready to process trips!
   Restart the backend to start background tasks
```

---

### Step 3: Restart Backend

```bash
cd ~/pinplot/gps-tracker
docker compose restart backend
```

**Watch logs to confirm background tasks started:**
```bash
docker logs -f pinplot_backend
```

**Expected startup logs:**
```
Database initialized!
...
🚀 Location Poller Service started (60-second interval)
🛡️  HIVE sweeper started (2-minute freshness sweep)
📜 GDPR cleanup task started (runs every 24 h)
🚨 Critical service alert monitor started (60-second cycle)
🚗 Trip Engine: Batch sweep started (10-minute interval)
📍 Trip Engine: Selective sweep started (12-minute interval)
🛣️  Trip Engine: Journey processor started (15-minute interval)
```

**If you see these 3 new lines ✅, trip engine is active!**

---

### Step 4: Verify Background Tasks Are Running

Wait 10-15 minutes for first cycle, then check logs:

```bash
docker logs pinplot_backend | grep -E "Batch sweep|Selective sweep|Trip engine"
```

**Expected logs:**
```
✅ Batch sweep task scheduled
✅ Selective sweep task scheduled
✅ Trip engine task scheduled
...
✅ Batch sweep: 1361 devices, 847 new positions, 1 API calls today
✅ Selective sweep: 1 qualified, 1 processed, 234 positions inserted
✅ Trip engine: 1 devices processed, 12 new journeys created
```

---

### Step 5: Verify Data in Database

```bash
docker exec -it pinplot_db psql -U pinplot_db_user -d pinplot_db
```

```sql
-- Check device subscription
SELECT device_imei, trip_subscribed, last_batch_ts, last_position_ts
FROM device_state 
WHERE device_imei = '781950640095475';

-- Should show:
-- trip_subscribed = true
-- last_batch_ts = recent timestamp
-- last_position_ts = recent timestamp

-- Check positions were migrated
SELECT COUNT(*) FROM device_positions WHERE device_imei = '781950640095475';
-- Should show: 5595+ positions

-- Check journeys were created
SELECT COUNT(*) FROM journeys WHERE device_imei = '781950640095475';
-- Should show: 10+ journeys

-- List recent journeys
SELECT 
    id,
    started_at,
    ended_at,
    total_distance_m/1000 as km,
    leg_count,
    stationary_count
FROM journeys 
WHERE device_imei = '781950640095475'
ORDER BY started_at DESC
LIMIT 10;
```

---

### Step 6: Test UI

1. Open https://pinplot.me/
2. Login to Customer Portal
3. Click "Movement History Advanced" tab
4. Select asset with IMEI `781950640095475`
5. Choose date range (Last 7 days)
6. Verify journeys appear with:
   - Journey cards showing distance/duration/stats
   - Map visualization with routes
   - Expandable journey details
   - Idle connectors between journeys
   - Positions tab with date grouping

---

## 📊 BACKGROUND TASK SCHEDULE

| Task | Interval | Purpose | First Run |
|------|----------|---------|-----------|
| **Batch Sweep** | 10 min | Fetch latest position for ALL devices from TrackSolid | Immediate |
| **Selective Sweep** | 12 min | Fetch detailed track.list for subscribed devices | After 2 min |
| **Trip Engine** | 15 min | Process positions → journeys for subscribed devices | After 5 min |

**Timeline:**
- T+0: Backend starts, tasks scheduled
- T+10: First batch sweep (all devices)
- T+12: First selective sweep (subscribed devices)
- T+15: First trip engine run (processes journeys)
- T+20: Second batch sweep
- T+24: Second selective sweep
- T+30: Second trip engine run

**Expected API usage:** ~1,584 calls/day (vs 86,400 limit = 1.8% ✅)

---

## 🔍 TROUBLESHOOTING

### No journeys appearing after 20 minutes

**Check 1: Are background tasks running?**
```bash
docker logs pinplot_backend | grep "Trip Engine"
```
If no logs → tasks didn't start → restart backend

**Check 2: Is device subscribed?**
```sql
SELECT device_imei, trip_subscribed FROM device_state WHERE device_imei = '781950640095475';
```
If `trip_subscribed = false` → re-run migration with `--subscribe-all`

**Check 3: Are positions being ingested?**
```sql
SELECT COUNT(*), MAX(observed_at) FROM device_positions WHERE device_imei = '781950640095475';
```
If count = 0 → batch sweep not running or failing

**Check 4: Check for errors in logs**
```bash
docker logs pinplot_backend | grep -E "ERROR|Exception" | tail -20
```

### API rate limit errors

```bash
docker exec -it pinplot_db psql -U pinplot_db_user -d pinplot_db
```

```sql
SELECT api_calls_today, api_calls_reset_at FROM tracksolid_sync_state WHERE id = 1;
```

If `api_calls_today > 80000` → approaching limit, wait for reset

### Trip engine not processing

```bash
docker logs pinplot_backend | grep "Trip engine"
```

Look for:
- "Trip engine: 0 devices processed" → no subscribed devices
- "Trip engine: N devices processed, 0 new journeys" → positions exist but no valid trips (all stationary/drift)

---

## 🎯 SUBSCRIPTION MANAGEMENT

### Subscribe individual device
```sql
UPDATE device_state SET trip_subscribed = true WHERE device_imei = '781950640095475';
```

### Subscribe all devices (production)
```sql
UPDATE device_state SET trip_subscribed = true;
```

### Unsubscribe device (stop trip tracking, save API calls)
```sql
UPDATE device_state SET trip_subscribed = false WHERE device_imei = '781950640095475';
```

### List subscribed devices
```sql
SELECT device_imei, trip_subscribed, last_position_ts 
FROM device_state 
WHERE trip_subscribed = true
ORDER BY last_position_ts DESC;
```

---

## 📅 POST-DEPLOYMENT CHECKLIST

- [ ] Code pulled (`git log` shows commit `a678853`)
- [ ] Migration script executed successfully
- [ ] Backend restarted
- [ ] Startup logs show 3 trip engine tasks
- [ ] Wait 20 minutes
- [ ] Batch sweep logs appear
- [ ] Selective sweep logs appear
- [ ] Trip engine logs appear
- [ ] `device_positions` has data (SQL query)
- [ ] `journeys` has data (SQL query)
- [ ] UI shows journeys for test device
- [ ] Map visualization working
- [ ] Journey expansion working
- [ ] Positions tab working

---

## 🚀 LAUNCH READINESS

After completing all steps above:

✅ **Backend:** 100% deployed and running  
✅ **Frontend:** 100% complete (already deployed)  
✅ **Data Pipeline:** Active and ingesting  
✅ **Trip Processing:** Running and creating journeys  
✅ **Feature:** Ready for testing and launch July 10, 2026

---

## 📞 SUPPORT

If issues persist after following this guide:
1. Share logs: `docker logs pinplot_backend > backend.log`
2. Share SQL query results from Step 5
3. Share screenshot from UI
4. Contact: Check conversation history for debugging
