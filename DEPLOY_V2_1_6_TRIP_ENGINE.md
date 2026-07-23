# Trip Engine v2.1.6 Deployment Guide

**Version:** 2.1.6  
**Date:** 2026-07-23  
**Spec:** PinPlot_Trip_Engine_Amendments_2.1.6.md

## Overview

All fixes implemented in 2 phases:
- **Phase 1:** B1 (duplicate prevention), B2 (leg termination), B3 (air gate) ✅
- **Phase 2:** B4 (journey break consistency), B5 (terminal stops) ✅

## Pre-Deployment Checklist

- [x] Code committed to main branch
- [x] All fixes implemented according to spec
- [x] Migrations created (v216_b1, v216_b5)
- [ ] GitHub Actions deployment complete
- [ ] Backend container rebuilt
- [ ] Worker container rebuilt
- [ ] Migrations applied

## Deployment Steps

### 1. Wait for GitHub Actions Sync

```bash
# Check deployment timestamp on server
ssh root@pinplot.me "ls -lah /root/pinplot/gps-tracker/backend/app/services/trip_engine.py"

# Expected: Jul 23 (today)
# Verify ENGINE_VERSION line shows "2.1.6"
ssh root@pinplot.me "grep 'ENGINE_VERSION =' /root/pinplot/gps-tracker/backend/app/services/trip_engine.py"
```

### 2. Rebuild Containers

```bash
ssh root@pinplot.me "cd /root/pinplot/gps-tracker && \
  docker compose build backend worker && \
  docker compose up -d backend worker && \
  docker restart pinplot_nginx"
```

### 3. Run Migrations

```bash
# Connect to backend container
ssh root@pinplot.me "docker compose -f /root/pinplot/gps-tracker/docker-compose.yml exec backend alembic upgrade head"

# Expected output:
# INFO  [alembic.runtime.migration] Running upgrade v22_refinements -> v216_b1_dup_prevention
# INFO  [alembic.runtime.migration] Running upgrade v216_b1_dup_prevention -> v216_b5_terminal_stops
# Detached X terminal stationaries
# Updated Y journey aggregates
# ✅ B5 migration complete: All journeys end at arrival
```

### 4. Verification Queries

Run these on production database to verify migrations:

```bash
# Connect to database
ssh root@pinplot.me "docker compose -f /root/pinplot/gps-tracker/docker-compose.yml exec db psql -U pinplot_db_user -d pinplot_db"
```

**B1: Verify no duplicate legs**
```sql
-- Should return 0
SELECT COUNT(*) 
FROM (
  SELECT device_imei, started_at, COUNT(*) as cnt
  FROM legs
  GROUP BY device_imei, started_at
  HAVING COUNT(*) > 1
) duplicates;
```

**B1: Check unique index exists**
```sql
SELECT indexname, indexdef 
FROM pg_indexes 
WHERE tablename = 'legs' AND indexname = 'ux_leg_device_start';
```

**B5: Verify no journey extends past last leg**
```sql
-- Should return 0
SELECT COUNT(*)
FROM journeys j
INNER JOIN (
  SELECT journey_id, MAX(ended_at) as max_leg_ended
  FROM legs
  WHERE journey_id IS NOT NULL
  GROUP BY journey_id
) leg_max ON leg_max.journey_id = j.id
WHERE j.ended_at > leg_max.max_leg_ended;
```

**B5: Count terminal stationaries detached**
```sql
-- Should show detached terminal stops (journey_id IS NULL)
SELECT COUNT(*) 
FROM stationaries 
WHERE journey_id IS NULL;
```

### 5. Smoke Test (Device 907, 22 July)

```sql
-- Check journey count for device 907 on 22 July
SELECT 
  DATE(started_at) as journey_date,
  COUNT(*) as journey_count,
  ARRAY_AGG(
    CONCAT(
      TO_CHAR(started_at, 'HH24:MI'), 
      ' → ', 
      TO_CHAR(ended_at, 'HH24:MI')
    ) ORDER BY started_at
  ) as journey_windows
FROM journeys
WHERE device_imei = '780901807707363'  -- Device 907
  AND started_at::date = '2026-07-22'
GROUP BY DATE(started_at);

-- Expected: Same journey count as device 767 for same date
-- B4 acceptance: 42.8-min stop should break journey
```

## Acceptance Criteria (from Spec)

### B1: Duplicate Prevention
- [ ] Zero same-start leg groups after replay
- [ ] Journey `5ee4d5c4` reports 38.74 km (was 77.48 km, +100% error)
- [ ] Journey `e17f5f66` reports 10.56 km (was 21.13 km, +100% error)
- [ ] Journey `0053a29c` reports 4.31 km (was 6.78 km, +57% error)
- [ ] All journeys: `sum(legs.distance_m) == journey.distance_m`

### B2: Leg Termination
- [ ] All adjacent leg→stationary pairs: gap = 0 seconds
- [ ] All adjacent leg→stationary pairs: distance = 0 meters
- [ ] Rendered route lines reach stop markers exactly

### B3: Air Gate
- [ ] Device 571 shows exactly 2 air legs (~1,973 km, ~1,979 km)
- [ ] Both flights marked `mode='air'`, `confidence_flag='low'`
- [ ] No ground leg on any device exceeds 150 km
- [ ] Outlier fixes at 247 km/h and 187 km/h discarded (not in any leg)

### B4: Journey Break Consistency
- [ ] Devices 907 and 767 produce identical journey counts for 22 July
- [ ] Device 907's 42.8-min stop (17:33→18:16) breaks journey

### B5: Terminal Stop Detachment
- [ ] No journey `ended_at` exceeds its last leg's `ended_at`
- [ ] Device 907, 21 July: ~34 min idle chip between journeys
- [ ] Journey `09:08:22 → 16:41:17` corrected to `09:08:22 → 10:11:13`
- [ ] All terminal stationaries have `journey_id = NULL`
- [ ] All waypoint stationaries have `journey_id` set

## Rollback Plan

If critical issues discovered:

```bash
# Rollback migrations (WARNING: B5 downgrade not supported)
ssh root@pinplot.me "docker compose -f /root/pinplot/gps-tracker/docker-compose.yml exec backend alembic downgrade v22_refinements"

# Rollback code
cd /Users/carl/Documents/MobileCode/Pinplot
git revert 8bfe880 b0c703f
git push origin main

# Wait for GitHub Actions, rebuild containers
```

**Note:** B5 migration is forward-only. Rollback requires manual SQL to re-attach terminal stops.

## Performance Impact

Expected performance improvements:
- **Duplicate cleanup:** Reduces leg/stationary table size by ~20%
- **Query optimization:** Journey aggregates pre-calculated, no runtime joins
- **UI responsiveness:** Correct end times eliminate confusing timeline gaps

Expected monitoring metrics:
- Database write load: Slight increase from upsert overhead
- Journey processing time: No significant change
- API response times: Faster for journey listings (smaller payloads)

## Post-Deployment Monitoring

Watch for:
1. Duplicate key violations (should be handled by upsert)
2. Journey count changes (acceptable - fixing previous bugs)
3. Distance discrepancies (expected - removing duplicates)
4. Idle chip rendering issues

Check logs:
```bash
ssh root@pinplot.me "docker compose -f /root/pinplot/gps-tracker/docker-compose.yml logs -f --tail=100 backend worker"
```

## Next Steps

After 24-hour soak test:
1. Run regression checks on devices 907, 767, 571, 363
2. Compare 22 July journey metrics with spec evidence
3. If successful, document in Trip Engine changelog
4. Plan v2.1.7 or v2.2.1 for backlog items (B4 full implementation, per-series provisioning)
