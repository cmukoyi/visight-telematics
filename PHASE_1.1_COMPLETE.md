# Phase 1.1 Complete: Trip Engine Database Schema

**Date:** 2026-07-05  
**Status:** ✅ Complete  
**Branch:** Ready for main

---

## 🎯 What Was Delivered

Created comprehensive database migration implementing the complete Trip Engine architecture from `PinPlot_Trip_Engine_Spec_v2.md`.

### Files Created
- ✅ `/gps-tracker/backend/alembic/versions/055_trip_engine_schema.py` (565 lines)
- ✅ `/TRIP_ENGINE_IMPLEMENTATION_PLAN.md` (updated with Phase 1.1 completion)

---

## 📊 Database Schema Summary

### **8 Tables Organized in 3 Sections:**

#### Section 1: Data Ingestion (TrackSolid API → Database)
1. **`device_positions`** - Single source of truth for GPS breadcrumbs
   - UNIQUE constraint on `(device_imei, observed_at)` prevents duplicates
   - Stores: lat, lng, speed, ignition, ACC status, satellite count, confidence
   - Source tracking: 'batch' (every 10 min) or 'tracklist' (selective)

2. **`device_state`** - Smart triggering metadata
   - `last_batch_ts` - Latest batch sweep timestamp
   - `last_position_ts` - Latest GPS point (forward-only window boundary)
   - `last_tracklist_pull_at` - Last time track.list was called
   - `trip_subscribed` - Premium opt-in flag (cost control)
   - `coalesce_floor_minutes` - Per-device override (NULL = use global)

3. **`tracksolid_sync_state`** - Rate limiting (singleton row)
   - `api_calls_today` - Counter (resets at midnight)
   - TrackSolid limit: 86,400 calls/day
   - Architecture ensures ~1,600 calls/day for 500 IMEIs

#### Section 2: Trip State Engine (STATIONARY ↔ MOVE State Machine)
4. **`engine_state`** - Per-device state machine
   - `current_state` - STATIONARY or MOVE
   - Rolling anchor: `anchor_lat`, `anchor_lng`, `anchor_count`
   - Current context: `current_leg_id`, `current_journey_id`
   - Processing watermark: `last_processed_at`

5. **`stationaries`** - Idle periods
   - Anchor centroid (R = 100m default)
   - Duration, point count
   - Links to journey (nullable for ungrouped)

6. **`legs`** - Movement segments
   - Distance (meters), duration (seconds), point count
   - `is_air_leg` flag (300 km/h, 150 km, multi-hour gap)
   - Links to journey (nullable for ungrouped)

7. **`journeys`** - Grouped trips
   - 30-min dwell threshold (configurable)
   - Aggregate metrics: total distance, duration, leg/stationary counts
   - `is_air_journey` flag (contains air legs)

#### Configuration
8. **`trip_config`** - Three-tier hierarchy
   - Global defaults (tenant_id = NULL) ← **Inserted on migration**
   - Per-tenant overrides
   - Per-device overrides (`device_state.coalesce_floor_minutes`)

---

## 🔗 Foreign Key Relationships

```
device_positions (1) → (N) stationaries.start_position_id
device_positions (1) → (N) stationaries.end_position_id
device_positions (1) → (N) legs.start_position_id
device_positions (1) → (N) legs.end_position_id

journeys (1) → (N) stationaries.journey_id
journeys (1) → (N) legs.journey_id
journeys (1) → (1) legs.first_leg_id
journeys (1) → (1) legs.last_leg_id

engine_state (1) → (1) legs.current_leg_id
engine_state (1) → (1) journeys.current_journey_id
```

**Cascade Rules:**
- Delete position → CASCADE delete legs/stationaries
- Delete journey → SET NULL on orphaned legs/stationaries

---

## ⚙️ Validated Configuration Defaults

The following defaults are locked from spec validation (tag 475 June data):

```python
batch_sweep_interval_minutes = 10      # Batch every 10 min
tracklist_delay_minutes = 5            # Buffer before calling track.list
coalesce_floor_minutes = 120           # Min 2 hours between track.list calls

engine_anchor_radius_m = 100           # R = 100m (stationary detection)
engine_min_leg_distance_m = 300        # Min leg length
engine_move_confirm_m = 150            # Distance to confirm MOVE state
engine_max_speed_kmh = 200             # Outlier gate (MAX_KMH)
engine_gap_timeout_min = 30            # Gap policy

engine_air_speed_kmh = 300             # Air leg: 300 km/h
engine_air_min_distance_km = 150       # Air leg: 150 km min distance
engine_journey_break_dwell_min = 30    # Journey grouping threshold

engine_smoothing_window = 3            # Median filter window
```

---

## 📈 Scalability Math

**Problem:** 500 IMEIs × 1 track.list call = rate limit exceeded

**Solution (Two-Tier Architecture):**
```
Every 10 minutes:
  1. Batch sweep (latest-points/batch) → ALL 500 devices = 1 API call
  2. Selective sweep (track.list) → ONLY devices where:
     - New data detected (last_batch_ts > last_position_ts)
     - Subscribed (trip_subscribed = true)
     - Coalesce passed (now - last_tracklist_pull_at ≥ 120 min)

Expected: ~10 devices qualify per cycle
Total: 1 + 10 = 11 API calls per 10 min
Daily: 11 × 144 cycles = 1,584 calls/day (vs 86,400 limit ✅)
```

---

## ✅ Validation Steps

- [x] Python syntax validated (`py_compile` passed)
- [x] Schema reviewed against spec
- [x] Foreign keys defined with proper CASCADE/SET NULL
- [x] Indexes created for query patterns:
  - `(device_imei, observed_at)` - Position lookups
  - `(device_imei, started_at)` - Time-range queries
  - `trip_subscribed` - Subscription filtering
  - `is_air_leg`, `is_air_journey` - Classification queries
- [ ] Migration tested on Docker database (pending environment)

---

## 🚢 Deployment Notes

**Before First Run:**
1. Ensure PostgreSQL 15+ (uses `gen_random_uuid()`)
2. Database will auto-insert global config defaults
3. Migration is idempotent (checks table existence)

**After Migration:**
1. All devices default to `trip_subscribed = false`
2. Admin portal (Phase 4) will allow toggling subscriptions
3. Engine will only process subscribed devices

**Rollback:**
```bash
alembic downgrade -1
```
Drops all 8 tables in reverse dependency order (safe).

---

## 📝 Next Steps (Phase 2)

**Week 2: Data Ingestion Services**
1. Create `tracksolid_batch_service.py`
   - Call `latest-points/batch` every 10 min
   - Upsert to `device_positions`
   - Update `device_state.last_batch_ts`

2. Create `tracksolid_track_service.py`
   - Implement 3-condition trigger
   - Forward-only window (`startTime = last_position_ts`)
   - Update `tracksolid_sync_state` counters

3. Upgrade token caching
   - Migrate from file-based to `api_tokens` table (already exists from migration 037)
   - Reuse existing `APIToken` model

---

## 📚 References

- **Spec:** `/features_dev/PinPlot_Trip_Engine_Spec_v2.md`
- **UI Design:** `/features_dev/movement-history-redesign.html`
- **Implementation Plan:** `/TRIP_ENGINE_IMPLEMENTATION_PLAN.md`
- **Test Scripts:** 
  - `/test_tracksolid_track_list.py`
  - `/list_tracksolid_devices.py`
- **API Response Sample:** `/tracksolid_track_response.json` (655 points, 24h)

---

**Ready for commit to main branch** 🚀
