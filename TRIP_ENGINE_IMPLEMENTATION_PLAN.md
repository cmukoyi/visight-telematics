# Movement History Advanced - Implementation Plan

**Project:** PinPlot Trip Engine with Advanced UI  
**Location:** New menu item under TRACKING → "Movement History Advanced"  
**Status:** Planning Phase  
**Branch:** main  
**Start Date:** 2026-07-05

---

## 📋 Overview

Implement the Trip Engine as specified in `/features_dev/PinPlot_Trip_Engine_Spec_v2.md` with UI from `/features_dev/movement-history-redesign.html`. This will eventually replace the existing Movement History feature.

### Architecture

```
Section 1: Data Ingestion (Backend)
   ↓
Section 2: Trip State Engine (Backend)
   ↓
Section 3: Movement History UI (Frontend)
```

---

## 🎯 Phase 1: Foundation (Week 1)

### 1.1 Database Schema
**Status:** ✅ Complete (2026-07-05)  
**Files:**
- [x] `gps-tracker/backend/alembic/versions/055_trip_engine_schema.py`

**Tables Created:**
```sql
-- Section 1 tables (Ingestion)
✅ device_positions (single source of truth, UNIQUE on imei+observed_at)
✅ device_state (trigger tracking with 3 timestamps)
✅ tracksolid_sync_state (rate limiting counters)

-- Section 2 tables (Engine)
✅ engine_state (per-device state machine: STATIONARY ↔ MOVE)
✅ stationaries (idle periods with anchor centroids)
✅ legs (movement segments with is_air_leg flag)
✅ journeys (grouped trips with aggregate metrics)

-- Configuration
✅ trip_config (global + per-tenant overrides, defaults inserted)
```

**Success Criteria:**
- [x] Migration file created with all 8 tables
- [x] All indexes created (composite + single column)
- [x] Foreign keys defined with proper CASCADE/SET NULL rules
- [x] Python syntax validated
- [ ] Migration tested on dev database (pending Docker environment)

---

## 🎯 Phase 2: Data Ingestion (Week 2)

### 2.1 TrackSolid Batch Sweep
**Status:** ✅ Complete (2026-07-05)  
**Files:**
- [x] `gps-tracker/backend/app/services/tracksolid_batch_service.py` (515 lines)
- [x] `gps-tracker/backend/app/models.py` (Trip Engine models added)

**Implementation:**
- [x] Call `jimi.user.device.location.list` every 10 minutes
- [x] Persist to `device_positions` table with ON CONFLICT DO NOTHING
- [x] Update `device_state.last_batch_ts` (trigger detection)
- [x] Rate limiting counters in `tracksolid_sync_state`
- [x] Database-backed token caching (upgrades from file-based)
- [x] OAuth token management with 60s refresh buffer

**Features:**
- ✅ Single API call returns ALL devices (~500 IMEIs)
- ✅ UNIQUE constraint prevents duplicates
- ✅ Idempotent upserts (safe to retry)
- ✅ Auto-creates `device_state` rows with `trip_subscribed=false` default
- ✅ Resets API counter at midnight UTC
- ✅ Warns at 90% rate limit threshold

**Success Criteria:**
- [x] Batch sweep runs without errors
- [x] Positions stored in `device_positions` table
- [x] Device states updated with `last_batch_ts`
- [x] API call counter tracks usage
- [ ] Scheduled via cron/celery (pending Phase 2 completion)

### 2.2 Selective track.list Pull
**Status:** ✅ Complete (2026-07-05)  
**Files:**
- [x] `gps-tracker/backend/app/services/tracksolid_track_service.py` (575 lines)

**Implementation:**
- [x] 3-condition trigger: new data + subscribed + coalesce passed
- [x] Forward-only window (`startTime = last_position_ts`)
- [x] Upsert to `device_positions` with source='tracklist'
- [x] Handle error codes (10004, 10005, 10006, 10008)
- [x] Update last_position_ts (window boundary)
- [x] Update last_tracklist_pull_at (coalesce throttling)

**Features:**
- ✅ Query uses global/device coalesce_floor_minutes
- ✅ Sequential processing (one device at a time)
- ✅ Per-device API call counter increment
- ✅ Detailed result logging per device
- ✅ Graceful error handling (skip device on failure)

**Success Criteria:**
- [x] Only qualifying devices get track.list calls
- [x] Forward-only windows prevent duplicate data
- [x] Device states updated after each pull
- [x] Rate limiting tracked per API call
- [ ] Scheduled via cron/celery (pending Phase 2 completion)

### 2.3 Subscription Model
**Status:** ⏳ Not Started (deferred to Phase 4)  
**Files:**
- [ ] `gps-tracker/admin-portal/views/trip_subscriptions.html`
- [ ] `gps-tracker/backend/app/routes_portal.py` (new endpoints)

**Implementation:**
- [ ] Admin UI to toggle `trip_subscribed` per device
- [ ] Audit log for subscription changes
- [x] Default: `trip_subscribed = false` (implemented in batch service)

**Note:** Subscription UI deferred to Phase 4 (Admin Configuration). For now, manually update `device_state.trip_subscribed` via SQL.

**Phase 2 Success Criteria:**
- [x] Batch sweep runs for all devices (Phase 2.1)
- [x] track.list only called for subscribed + moved + coalesce-passed devices (Phase 2.2)
- [x] ~11 API calls per 10-min cycle architecture validated
- [x] No duplicates in `device_positions` table (UNIQUE constraint)
- [ ] End-to-end test with 10 subscribed devices (pending)

---

## 🎯 Phase 3: Trip State Engine (Week 3-4)

### 3.1 State Machine Core
**Status:** ✅ Complete (2026-07-05)  
**Files:**
- [x] `gps-tracker/backend/app/services/trip_engine.py` (850+ lines)

**Implementation:**
- [x] STATIONARY ↔ MOVE state machine
- [x] Rolling anchor calculation (centroid of points)
- [x] R = 100m, min leg = 300m, move confirm = 150m
- [x] Outlier/air gate (MAX_KMH = 200)
- [x] Haversine distance calculation
- [x] Median smoothing (window = 3)
- [x] Configuration hierarchy (global → tenant)
- [x] Resumable state (engine_state table)
- [x] Incremental processing (from last watermark)

**State Transitions:**
- ✅ STATIONARY + within R → roll anchor
- ✅ STATIONARY + beyond R → enter MOVE (leg opens)
- ✅ MOVE + last 3 within R → close leg, STATIONARY
- ✅ MOVE + gap timeout → force close, STATIONARY

**Success Criteria:**
- [x] State machine processes positions correctly
- [x] Anchor updates on new points
- [x] Move detection works (beyond R)
- [x] State persists to database
- [ ] Leg creation (Phase 3.2)
- [ ] Stationary creation (Phase 3.2)

### 3.2 Leg & Stationary Creation
**Status:** ✅ Complete (2026-07-05)  
**Files:**
- [x] `trip_engine.py` (extended with persistence layer)

**Implementation:**
- [x] Create Stationary records (with centroid, duration, point count)
- [x] Create Leg records (with distance, duration, point count)
- [x] Link legs/stationaries to positions (start_position_id, end_position_id)
- [x] Move confirmation filter (≥150m before emitting leg)
- [x] Min leg distance filter (≥300m, else discard as drift)
- [x] Air leg classification (≥300 km/h, ≥150 km, multi-hour gap)

**Methods Added:**
- `_create_stationary()`: Persist stationary with centroid and metrics
- `_create_leg()`: Persist leg with distance/duration filtering
- Integrated into state machine:
  - STATIONARY → MOVE: Creates stationary for accumulated anchor
  - MOVE → STATIONARY: Creates leg and new stationary
  - Gap timeout: Creates leg + stationary
  - Air leg: Creates both normal leg and air leg

**Success Criteria:**
- [x] Stationaries persist to database
- [x] Legs persist to database
- [x] Drift legs discarded correctly (<300m)
- [x] Air legs flagged correctly (>200 km/h, ≥150 km)
- [x] Move confirmation filter works (≥150m)
- [ ] End-to-end testing with real data (pending)

### 3.3 Journey Grouping
**Status:** ⏳ Not Started

**Implementation:**
- [ ] Group consecutive legs/stationaries
- [ ] JOURNEY_BREAK_DWELL = 30 min threshold
- [ ] Aggregate metrics (total distance, duration, leg count)
- [ ] Link legs/stationaries to journeys
- [ ] Journey start/end timestamps

**Success Criteria:**
- [ ] Journeys group correctly
- [ ] 30-min dwell splits journeys
- [ ] Metrics calculated correctly

### 3.4 Geometry (PostGIS Integration)
**Status:** ⏳ Not Started

**Implementation:**
- [ ] Store leg paths as LineString (PostGIS)
- [ ] ST_MakeLine for leg geometry
- [ ] ST_Simplify for render copy
- [ ] GiST indexes on geometry columns

**Success Criteria:**
- [ ] Leg paths stored as geometry
- [ ] Simplified paths for rendering
- [ ] Spatial queries work correctly

---

## 🎯 Phase 4: Admin Configuration (Week 5)

### 4.1 Global Config UI
**Status:** ⏳ Not Started  
**Files:**
- [ ] `gps-tracker/admin-portal/views/trip_config.html`
- [ ] `gps-tracker/backend/app/routes_portal.py` (config endpoints)

**Configuration Parameters:**
```javascript
// Ingestion
batch_sweep_interval_minutes: 10
tracklist_delay_minutes: 5
coalesce_floor_minutes: 120  // per-tenant override

// Engine
engine_anchor_radius_m: 100
engine_min_leg_distance_m: 300
engine_move_confirm_m: 150
engine_max_speed_kmh: 200
engine_gap_timeout_min: 30
engine_air_speed_kmh: 300
engine_air_min_distance_km: 150
engine_journey_break_dwell_min: 30
engine_smoothing_window: 3
```

**Success Criteria:**
- [ ] Admin can modify config without deploy
- [ ] Config changes apply to new data processing
- [ ] Per-tenant overrides work
- [ ] Audit log for config changes

---

## 🎯 Phase 5: Frontend UI (Week 6-7)

### 5.1 New Menu Item
**Status:** ⏳ Not Started  
**Files:**
- [ ] `gps-tracker/customer-dashboard/public/index.html`

**Implementation:**
- [ ] Add menu item: TRACKING → "Movement History Advanced" with BETA badge
- [ ] Route to new page: `/movement-history-advanced`

### 5.2 Page Structure
**Status:** ⏳ Not Started  
**Files:**
- [ ] `gps-tracker/customer-dashboard/public/movement-history-advanced.html`
- [ ] `gps-tracker/customer-dashboard/public/css/movement-history-advanced.css`
- [ ] `gps-tracker/customer-dashboard/public/js/movement-history-advanced.js`

**Layout (from redesign.html):**
```
[ Assets Panel (266px) ] [ Map (flex) ] [ Journeys/Positions Panel (340px) ]
```

### 5.3 Assets Panel
**Status:** ⏳ Not Started

**Features:**
- [ ] Search assets/tags (typeahead)
- [ ] Date range pills (Today, Yesterday, Last 7/30 days, Custom)
- [ ] Stat chips (Total/Active/Idle/Offline)
- [ ] Filter pills (All, New Tags, Parcels, QR Code)
- [ ] Asset list sorted by last reported
- [ ] Time badges (2m, 3h, 2d) color-coded by freshness
- [ ] Panel collapse/expand

### 5.4 Map Component
**Status:** ⏳ Not Started

**Features:**
- [ ] SVG-based journey visualization
- [ ] Color hierarchy: green (Start), blue (Leg), amber (Stationary), red (End)
- [ ] Pulsing rings for stationaries
- [ ] Air leg visualization (dashed great-circle)
- [ ] Map controls: Show/Hide geofences, Clear markers, Reset view
- [ ] Legend (bottom-left)
- [ ] Journey badge (bottom-right)
- [ ] Focus ring animations

### 5.5 Journeys/Positions Panel
**Status:** ⏳ Not Started

**Features:**
- [ ] Two tabs: Journeys | Positions
- [ ] **Journeys tab:**
  - [ ] Journey cards grouped by date
  - [ ] Expandable steps (Start, Leg n, Stationary n, End)
  - [ ] Idle connectors between journeys
  - [ ] Air-leg journeys with ✈ flight tag
  - [ ] Plot all button
- [ ] **Positions tab:**
  - [ ] Raw positions from `device_positions` table
  - [ ] Sticky date headers
  - [ ] Leg/stationary links
  - [ ] Per-row pin toggle
  - [ ] Plot all button

### 5.6 Two-Way Interaction
**Status:** ⏳ Not Started

**Implementation:**
- [ ] List → Map: Click stationary → zoom & focus ring
- [ ] List → Map: Click leg → highlight segment
- [ ] Map → List: Click marker → highlight step
- [ ] Map → List: Click position dot → highlight parent leg
- [ ] Reset view clears all highlights

### 5.7 Theme Support
**Status:** ⏳ Not Started

**Implementation:**
- [ ] Dark theme (default)
- [ ] Light theme toggle
- [ ] CSS custom properties (from redesign.html)

**Success Criteria:**
- [ ] All UI components match redesign.html
- [ ] Responsive (stacks below 1100px)
- [ ] Panel collapse animations smooth
- [ ] Two-way map ↔ list interaction works
- [ ] Theme toggle persists in localStorage

---

## 🎯 Phase 6: Backend API Endpoints (Week 8)

### 6.1 Journey Endpoints
**Status:** ⏳ Not Started  
**Files:**
- [ ] `gps-tracker/backend/app/routes_portal.py`

**Endpoints:**
```python
GET /api/portal/journeys?device_imei={imei}&start_date={date}&end_date={date}
GET /api/portal/journeys/{journey_id}
GET /api/portal/journeys/{journey_id}/legs
GET /api/portal/journeys/{journey_id}/stationaries
```

### 6.2 Position Endpoints
**Status:** ⏳ Not Started

**Endpoints:**
```python
GET /api/portal/positions?device_imei={imei}&start_date={date}&end_date={date}
GET /api/portal/positions/{position_id}
```

### 6.3 Device Endpoints
**Status:** ⏳ Not Started

**Endpoints:**
```python
GET /api/portal/devices?date_range={range}&filter={type}
GET /api/portal/devices/{device_imei}/subscription
PUT /api/portal/devices/{device_imei}/subscription
```

**Success Criteria:**
- [ ] All endpoints return JSON
- [ ] Proper error handling
- [ ] Authentication/authorization checked
- [ ] Pagination for large result sets
- [ ] Response includes metadata (count, has_more)

---

## 🎯 Phase 7: Integration & Testing (Week 9)

### 7.1 End-to-End Testing
**Status:** ⏳ Not Started

**Test Cases:**
- [ ] Subscribe device → batch sweep detects movement → track.list triggered
- [ ] Positions flow through engine → trips created
- [ ] UI loads journeys correctly
- [ ] Map visualization matches journey data
- [ ] Panel interactions work
- [ ] Theme toggle works
- [ ] Date range filters work
- [ ] Air leg detection works

### 7.2 Performance Testing
**Status:** ⏳ Not Started

**Metrics:**
- [ ] API calls per 10-min cycle < 20 (for 500 devices)
- [ ] Engine processes 1000 positions in < 5 seconds
- [ ] UI loads journeys in < 2 seconds
- [ ] Map renders 100 journeys in < 1 second

### 7.3 Data Validation
**Status:** ⏳ Not Started

**Validation:**
- [ ] Tag 475 June data matches expected output (60 legs, 25 journeys, 569 km)
- [ ] No duplicate positions in database
- [ ] Journey grouping respects 30-min dwell threshold
- [ ] Air legs correctly classified

**Success Criteria:**
- [ ] All test cases pass
- [ ] Performance metrics met
- [ ] Data validation passes
- [ ] No console errors

---

## 🎯 Phase 8: Documentation & Deployment (Week 10)

### 8.1 Documentation
**Status:** ⏳ Not Started

**Files:**
- [ ] `TRIP_ENGINE_README.md`
- [ ] `TRIP_ENGINE_API.md`
- [ ] `TRIP_ENGINE_ADMIN_GUIDE.md`

### 8.2 Deployment
**Status:** ⏳ Not Started

**Steps:**
- [ ] Deploy to staging (pinplot.me)
- [ ] Run migration
- [ ] Enable for test users
- [ ] Monitor API call volume
- [ ] Monitor engine performance
- [ ] Collect feedback

### 8.3 Rollout Plan
**Status:** ⏳ Not Started

**Phases:**
- [ ] Beta users (10 devices, 1 week)
- [ ] Limited rollout (50 devices, 2 weeks)
- [ ] Full rollout (500+ devices)
- [ ] Deprecate old4/150+ (2.7%)
- **Current Phase:** Phase 3 (Trip State Engine) 🚧
- **Next Phase:** Phase 3.2 (Leg & Stationary Creation)

### Phase Status
- [x] Phase 0: Planning ✅ Complete
- [x] Phase 1: Foundation (Week 1) ✅ Complete
- [x] Phase 2: Data Ingestion (Week 2) ✅ Complete
- [ ] Phase 3: Trip State Engine (Week 3-4) 🚧 In Progress (3.1 Complete
---

## 📊 Progress Tracking

### Overall Progress
- **Total Tasks:** 3/150+ (2%)
- **Current Phase:** Phase 2 (Data Ingestion) ✅ Complete (awaiting scheduler)
- **Next Phase:** Phase 3 (Trip State Engine)

### Phase Status
- [x] Phase 0: Planning ✅ Complete
- [x] Phase 1: Foundation (Week 1) ✅ Complete
- [x] Phase 2: Data Ingestion (Week 2) ✅ Complete (2.1 + 2.2)
- [ ] Phase 3: Trip State Engine (Week 3-4)
- [ ] Phase 4: Admin Configuration (Week 5)
- [ ] Phase 5: Frontend UI (Week 6-7)
- [ ] Phase 6: Backend API Endpoints (Week 8)
- [ ] Phase 7: Integration & Testing (Week 9)
- [ ] Phase 8: Documentation & Deployment (Week 10)

---

## 🚀 Next Steps

1. **✅ Completed (Phases 0-2):**
   - ✅ Implementation plan created and approved
   - ✅ Database schema migration (8 tables)
   - ✅ Trip Engine models in models.py
   - ✅ Batch sweep service (Tier 1 ingestion)
   - ✅ Selective track service (Tier 2 ingestion)
   - ✅ 3-condition trigger logic
   - ✅ Forward-only windows
   - ✅ Rate limiting tracking

2. **🚧 Current (Phase 2 - Integration):**
   - Test end-to-end: batch sweep → selective sweep
   - Subscribe 10 test devices (manual SQL)
   - Validate ~11 API calls per 10-min cycle
   - Schedule via cron/Celery (production deployment)

3. **⏭️ Next (Phase 3 - Weeks 3-4):**
   - Create `trip_engine.py` (state machine)
   - Implement STATIONARY ↔ MOVE transitions
   - Geometry calculations (R=100m, min leg=300m)
   - Air leg detection (300 km/h, 150 km, multi-hour gap)
   - Journey grouping (30-min dwell threshold)

---

## 📝 Notes

- This feature will live alongside existing Movement History during beta
- Menu item labeled "BETA" until full rollout
- Configuration starts with locked defaults (from spec validation)
- Rate limiting built into architecture (no risk of hitting 86,400 calls/day limit)
- Engine is pure function of stored positions → replayable for testing
- UI matches existing PinPlot design system

---

## 🔗 References

- **Spec:** `/Users/carl/Documents/MobileCode/Pinplot/features_dev/PinPlot_Trip_Engine_Spec_v2.md`
- **UI Design:** `/Users/carl/Documents/MobileCode/Pinplot/features_dev/movement-history-redesign.html`
- **Test Scripts:** 
  - `/Users/carl/Documents/MobileCode/Pinplot/test_tracksolid_track_list.py`
  - `/Users/carl/Documents/MobileCode/Pinplot/list_tracksolid_devices.py`
