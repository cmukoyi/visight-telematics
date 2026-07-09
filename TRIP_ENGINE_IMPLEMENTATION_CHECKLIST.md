# Trip Engine Implementation Checklist

Based on `/Users/carl/Documents/MobileCode/Pinplot/features_dev/PinPlot_Trip_Engine_Spec_v2.md` and design in `movement-history-redesign.html`

## Section 1 — Ingestion

### 1.1-1.2 Data Pipeline
- [ ] **Batch sweep** every 10 min for fleet-wide positions
- [ ] **Track.list pull** with 3-condition trigger:
  - [ ] (a) `last_batch_ts > previous` (new data)
  - [ ] (b) `trip_subscribed = true` (premium opt-in)
  - [ ] (c) `now - last_tracklist_pull_at >= coalesce_floor_minutes`
- [ ] **Forward-only windowing**: `startTime = last_position_ts`, `endTime = now`
- [ ] **Error handling**: rate-limit retry logic (10005/10006/10008)

### 1.3 Positions Table (device_positions)
- [x] Core fields: `device_imei, observed_at, lat, lng`
- [x] Movement: `direction, gps_speed, pos_type, satellite, ignition, confidence`
- [x] Metadata: `source (batch|tracklist), created_at`
- [x] **Unique constraint**: `(device_imei, observed_at)`
- [x] **Trip linkage** (Section 3.4): `leg_id, stationary_id` (added)
- [x] **Address caching** (Section 3.6): `address TEXT` (added)
- [ ] **Upsert logic**: track.list supersedes batch, keep battery_percentage from batch
- [ ] **UTC normalization** before keying

### 1.4 Device State Table (device_state)
- [x] Core: `device_imei PK, trip_subscribed`
- [x] Trigger timestamps: `last_batch_ts, last_position_ts, last_tracklist_pull_at`
- [x] Per-device config: `coalesce_floor_minutes`
- [ ] **Separation validation**: last_batch_ts ≠ last_position_ts

### 1.5 Subscription Model
- [x] `trip_subscribed` boolean per device
- [x] Set via admin portal
- [ ] **Audit trail** for subscription changes
- [x] Unsubscribed devices: batch sweep only, no track.list pull

### 1.6-1.7 Admin Config
- [ ] Global defaults implemented:
  - [ ] `batch_sweep_interval_minutes = 10`
  - [ ] `tracklist_delay_minutes = 5`
  - [ ] `coalesce_floor_minutes = 120`
- [ ] Per-tenant override support
- [ ] Per-asset-class override support (future)

---

## Section 2 — Trip State Engine

### 2.1 Model & Hierarchy
- [x] **Stationary** model exists
- [x] **Leg** model exists  
- [x] **Journey** model exists
- [x] Hierarchy: Stationary → Leg → Journey
- [x] **Incremental processing** with state resumption
- [x] **Forward-only** processing (no historical backfill)

### 2.2 Core Rule — Geometry Not Time
- [x] Stationary confirmed by next reported point, not dwell time
- [x] Timestamps used for outlier gate and Journey grouping only
- [ ] **Verify**: No time-based stationary confirmation in code

### 2.3 State Machine (STATIONARY ↔ MOVE)
- [x] Two states: `STATIONARY`, `MOVE`
- [x] Anchor (rolling centroid) + count
- [x] First point → anchor, STATIONARY
- [x] **Within R** → roll centroid
- [x] **Beyond R** → enter MOVE, open Leg
- [x] **Last 3 points within R** → new Stationary formed, close Leg
- [ ] **Outlier / air gate**: speed > MAX_KMH classification
  - [ ] Hop >= AIR_MIN_KM + gap → air leg
  - [ ] Hop < AIR_MIN_KM → discard (teleport/glitch)
- [ ] **Gap policy**: time > GAP_TIMEOUT while MOVE → close as unknown-path
- [x] **Departure confirmation**: Leg emitted only if >= MOVE_CONFIRM (150m)

### 2.4 Filters & Rules — Core Parameters
- [x] **R (anchor radius) = 100 m**
- [x] **Min Leg distance = 300 m (3 × R)**
- [x] **MAX_KMH = 200** (ground outlier threshold)
- [x] **GAP_TIMEOUT = 30 min** (force-close MOVE leg)
- [x] **JOURNEY_BREAK_DWELL = 30 min** (split journeys)
- [ ] **MOVE_CONFIRM = 150 m** (1.5 × R minimum leg distance)
- [ ] **Never use confidence** for classification (spec 2.4)
- [ ] **Confidence** as optional light weighting only

### 2.4a Air Legs
- [ ] **Air leg detection** with 3-part AND:
  - [ ] Implied speed >= AIR_SPEED_KMH (300)
  - [ ] Displacement >= AIR_MIN_KM (150)
  - [ ] Multi-hour reporting gap
- [ ] **Air leg attributes**:
  - [ ] `mode = air`
  - [ ] `path = unknown` (great-circle geometry)
  - [ ] Endpoints = last pre-silence, first post-silence
  - [ ] Distance = great-circle length
  - [ ] `air_status`: `confirmed` (both in airport geofences) or `suspected`
- [ ] **Never contribute** to ground speed/segmentation

### 2.5 Geometry (PostGIS)
- [ ] **ST_Length(geography)** for distance calculation
- [ ] **ST_MakeLine** for Leg path
- [ ] **ST_Simplify** (Douglas-Peucker) for `path_simplified`
- [ ] GiST index on geometry columns
- [ ] Full-res path kept separate from simplified

### 2.6 Schema — Database Models

#### engine_state (per device, resumable)
- [x] `device_imei PK`
- [x] `state` (STATIONARY/MOVE)
- [x] `anchor_lat, anchor_lng, anchor_count`
- [x] `anchor_since`
- [x] `open_leg_buffer` (jsonb)
- [x] `last_processed_at` (was last_processed_ts)
- [x] `current_journey_id`
- [x] **4-tuple anchor_points**: `(lat, lng, timestamp, position_id)` ✅ FIXED

#### stationaries
- [x] `id` (UUID)
- [x] `device_imei, journey_id`
- [x] `anchor_lat, anchor_lng` (centroid)
- [x] `started_at, ended_at`
- [x] `duration_minutes` (dwell_min)
- [x] `point_count`
- [x] **Position references** (nullable for reconstructed state):
  - [x] `start_position_id` ✅ MADE NULLABLE
  - [x] `end_position_id` ✅ MADE NULLABLE

#### legs
- [x] `id` (UUID)
- [x] `device_imei, tenant_id, journey_id`
- [x] `started_at, ended_at` (start_ts, end_ts)
- [x] `distance_km, duration_minutes`
- [x] `point_count`
- [ ] `start_point, end_point` (Point geometry)
- [ ] `path` (LineString geometry)
- [ ] `path_simplified` (Douglas-Peucker simplified)
- [ ] `confidence_flag` (normal|low for partial path)
- [ ] `mode` (ground|air)
- [ ] `air_status` (confirmed|suspected|null)

#### journeys
- [x] `id` (UUID)
- [x] `device_imei, tenant_id`
- [x] `started_at, ended_at`
- [x] `distance_km, duration_minutes`
- [x] `leg_count`
- [ ] `stationary_count` (missing?)
- [ ] `position_count` (total across all legs)

### 2.7 Admin Config (global → per-tenant → per-asset-class)
- [ ] `engine_anchor_radius_m = 100`
- [ ] `engine_min_leg_distance_m = 300`
- [ ] `engine_move_confirm_m = 150`
- [ ] `engine_max_speed_kmh = 200`
- [ ] `engine_gap_timeout_min = 30`
- [ ] `engine_air_speed_kmh = 300`
- [ ] `engine_air_min_distance_km = 150`
- [ ] `engine_journey_break_dwell_min = 30`
- [ ] `engine_smoothing_window = 3`
- [ ] Per-tenant override capability
- [ ] Per-asset-class override capability (future)

---

## Section 3 — Movement History UI

### 3.1 Layout & Panel Collapse
- [ ] Four-column layout: nav (228px) | Assets (266px) | Map (flex) | Journeys/Positions (340px)
- [ ] Progressive collapse:
  - [ ] Assets interaction → nav collapses to icon rail
  - [ ] Asset selection → Journeys panel opens
  - [ ] Journeys interaction → Assets collapses to strip
- [ ] Reopening via: strip, header chevron, menu button
- [ ] Responsive stacking below 1100px

### 3.2 Assets Panel (Selection)
- [ ] **Search** typeahead: "Search assets or tags"
- [ ] **Date range pills**: Today · Yesterday · Last 7 days · Last 30 days · Custom
- [ ] **Stat chips**: Total / Active / Idle / Offline (color-coded)
- [ ] **Filter pills**: All · New Tags · Parcels · QR Code
- [ ] **Asset list** sorted by last reported (newest first):
  - [ ] Pin icon · Name · IMEI
  - [ ] **Relative-time badge** (2m/3h/2d) color-coded by freshness:
    - [ ] Green ≤15 min
    - [ ] Muted ≤3 h
    - [ ] Dim beyond 3h
    - [ ] Red offline
  - [ ] Battery % · Status dot
  - [ ] Selected row highlighted green

### 3.3 Map (Centre)
- [ ] Header: "Live map" + "Updated Ns ago"
- [ ] **Top-right controls**:
  - [ ] **Show/Hide geofences** toggle
  - [ ] **Clear markers** button
  - [ ] **Reset view** button (appears when zoomed)
- [ ] **Rendering** (color = hierarchy):
  - [ ] **Start**: green marker "S"
  - [ ] **Leg**: blue polyline through positions
  - [ ] **Position**: small blue dots along leg (zoom-dependent)
  - [ ] **Stationary**: amber marker with pulsing ring, numbered 1..n
  - [ ] **End**: red marker "E"
  - [ ] **Air leg**: dashed line between airports, labelled "✈ flight"
- [ ] **Default**: use `path_simplified`
- [ ] **Zoom-in**: reveal full Position dots
- [ ] **Bottom-left legend**: Start · Leg · Position · Stationary · End
- [ ] **Bottom-right journey badge**: "Journey N · km · legs · stationaries · positions"

### 3.4 Right Panel — Two Tabs

#### Journeys Tab
- [ ] **Summary line**:
  - [ ] "X journeys · Y km · Z legs · tag NAME · MONTH YEAR"
  - [ ] **Plot all** button (toggles to Clear)
- [ ] **Journey cards** grouped by date:
  - [ ] **Header**: "Journey N" · distance km
  - [ ] **Meta**: time – time · X legs · location → location (for air)
  - [ ] **Flight tag**: `✈ flight` badge for air-leg journeys
  - [ ] **Expand** to show ordered steps:
    - [ ] **Start**: green dot · time · address
    - [ ] **Leg N**: blue dot · km · X positions · duration · [partial path flag]
    - [ ] **Stationary N**: amber dot · dwell time · address
    - [ ] **Air leg**: dashed dot · km · duration · "great-circle · path unknown" · [confirmed/suspected]
    - [ ] **End**: red dot · time · address
- [ ] **Idle connectors** between cards:
  - [ ] Dashed amber rail
  - [ ] Pill: "Xh Ym idle · location"
  - [ ] These are significant Stationaries (dwell > journey_break_dwell)
- [ ] **Air-leg journey expansion**:
  - [ ] Start (departure airport)
  - [ ] Air leg with dashed marker
  - [ ] End (arrival airport)

#### Positions Tab
- [ ] **Summary line**:
  - [ ] Position count summary
  - [ ] **Plot all** button (toggles to Clear)
- [ ] **Rows** under sticky date headers:
  - [ ] **Time** · **Address** · **Leg/Stationary link** · **[Pin]**
  - [ ] **No coordinates shown** (per spec 3.4)
  - [ ] **No confidence shown** (per spec 3.4)
  - [ ] **Leg/Stationary link** color-coded (blue/amber/green/red):
    - [ ] Clickable to drive map (see 3.5)
    - [ ] Shows "Leg 3", "Stationary 6", "Start", "End"
  - [ ] **Pin button** per row (toggle to plot/unplot single position)

### 3.5 Interaction Model (Two-way map ↔ list)

#### List → Map
- [ ] **Stationary/Start/End** tap → zoom to point, drop focus ring
- [ ] **Leg** tap → highlight segment (thicken + dim neighbors), fit map
- [ ] **Position leg/stationary link** tap:
  - [ ] Leg link → highlight segment
  - [ ] Stationary link → zoom to stop
- [ ] **Air leg** tap → switch to flight view:
  - [ ] Ground journey hides
  - [ ] Dashed great-circle arc between airports
  - [ ] Airport markers with dashed geofence rings (confirmed)
  - [ ] Reset view restores normal map

#### Map → List
- [ ] **Stationary/Start/End marker** click → zoom + highlight matching step
- [ ] **Position dot** click → focus ring on dot + highlight parent leg in list
- [ ] **Reset view** → clear highlights, return to default framing
- [ ] **Point focus and leg-segment highlight** mutually exclusive

### 3.6 Addresses
- [ ] **Reverse geocoding** at ingest (Section 1)
- [ ] **Cache on positions row** (`address` column)
- [ ] **Display addresses**, not lat/lon in UI
- [ ] **Bounded cost** (no repeated lookups)

---

## API Endpoints

### Portal API — Journeys
- [ ] `GET /api/portal/journeys` — list journeys with date range
  - [ ] Query params: `device_imei, start_date, end_date, page, page_size`
  - [ ] Response includes: legs, stationaries, position counts
  - [ ] Grouped by date
  - [ ] Includes air leg metadata (mode, air_status)

### Portal API — Positions
- [x] `GET /api/portal/positions` — list raw positions ✅ FIXED (field mapping)
  - [x] Query params: `device_imei, start_date, end_date, page, page_size`
  - [x] Response includes: `leg_id, stationary_id, address` ✅ ADDED
  - [ ] **No coordinates in response** (UI constraint, but API should provide)
  - [ ] Grouped by date with sticky headers

### Portal API — Trip Engine Admin
- [x] `POST /api/portal/admin/trip-engine/trigger` — manual trigger ✅ EXISTS
- [ ] `GET /api/portal/admin/trip-engine/config` — get engine config
- [ ] `PUT /api/portal/admin/trip-engine/config` — update engine config
- [ ] `GET /api/portal/devices/{imei}/subscription` — get subscription status ✅ EXISTS
- [ ] `PUT /api/portal/devices/{imei}/subscription` — update subscription ✅ EXISTS

---

## Trip Engine Core Logic

### Current State Issues
- [x] ~~Tuple index out of range~~ ✅ FIXED (4-tuple anchor_points)
- [x] ~~NOT NULL constraint violation~~ ✅ FIXED (nullable position IDs)
- [ ] **Verify**: Engine writes `leg_id`/`stationary_id` to device_positions
- [ ] **Verify**: Engine creates journeys with correct leg/stationary counts
- [ ] **Test**: Full 2950 position processing without errors

### Missing Features
- [ ] **Air leg detection** (Section 2.4a)
- [ ] **Airport geofence matching** for confirmed flights
- [ ] **Gap timeout** force-close MOVE leg logic
- [ ] **Confidence weighting** (optional, not for classification)
- [ ] **PostGIS geometry** storage and calculations
- [ ] **Douglas-Peucker simplification** for path_simplified
- [ ] **Position smoothing** (median filter, window 3)

### State Persistence
- [x] **_save_state()** persists engine state ✅ EXISTS
- [x] **_load_state()** reconstructs from database ✅ FIXED (4-tuple)
- [ ] **Verify**: State resumption works across restarts
- [ ] **Verify**: open_leg_buffer correctly serialized/deserialized

---

## Database Migrations Needed

### Immediate
- [x] `ALTER TABLE stationaries ALTER COLUMN start_position_id DROP NOT NULL;` ✅ DONE
- [x] `ALTER TABLE stationaries ALTER COLUMN end_position_id DROP NOT NULL;` ✅ DONE
- [x] `ALTER TABLE device_positions ADD COLUMN leg_id UUID;` ✅ DONE
- [x] `ALTER TABLE device_positions ADD COLUMN stationary_id UUID;` ✅ DONE
- [x] `ALTER TABLE device_positions ADD COLUMN address TEXT;` ✅ DONE

### Phase 2 (PostGIS)
- [ ] `ALTER TABLE legs ADD COLUMN start_point GEOGRAPHY(POINT);`
- [ ] `ALTER TABLE legs ADD COLUMN end_point GEOGRAPHY(POINT);`
- [ ] `ALTER TABLE legs ADD COLUMN path GEOGRAPHY(LINESTRING);`
- [ ] `ALTER TABLE legs ADD COLUMN path_simplified GEOGRAPHY(LINESTRING);`
- [ ] `ALTER TABLE legs ADD COLUMN confidence_flag VARCHAR(10) DEFAULT 'normal';`
- [ ] `ALTER TABLE legs ADD COLUMN mode VARCHAR(10) DEFAULT 'ground';`
- [ ] `ALTER TABLE legs ADD COLUMN air_status VARCHAR(20);`
- [ ] `CREATE INDEX idx_legs_path ON legs USING GIST(path);`

### Phase 3 (Journey counts)
- [ ] `ALTER TABLE journeys ADD COLUMN stationary_count INTEGER;`
- [ ] `ALTER TABLE journeys ADD COLUMN position_count INTEGER;`

---

## Testing Checklist

### Unit Tests
- [ ] State machine transitions (STATIONARY ↔ MOVE)
- [ ] Anchor rolling centroid calculation
- [ ] Departure confirmation (150m minimum)
- [ ] Journey grouping by dwell time (30 min threshold)
- [ ] Air leg detection (3-part AND)
- [ ] Gap timeout logic (30 min)
- [ ] Min leg distance filtering (300m)

### Integration Tests
- [ ] Full pipeline: positions → engine → journeys/legs/stationaries
- [ ] State persistence and resumption
- [ ] Error recovery (rate limits, transient errors)
- [ ] Batch sweep + track.list integration
- [ ] 3-condition trigger logic

### End-to-End Tests
- [x] Manual trigger with IMEI 781950640095475 ✅ WORKING (no new positions)
- [ ] Process full 2950 positions successfully
- [ ] Verify journeys match expected structure
- [ ] Verify legs have correct distances/durations
- [ ] Verify stationaries have correct centroids/dwell times
- [ ] Positions tab shows correct leg/stationary links
- [ ] UI displays journeys with correct metadata

### Performance Tests
- [ ] Large dataset processing (10k+ positions)
- [ ] Concurrent device processing
- [ ] PostGIS geometry calculations performance
- [ ] Simplified path generation time

---

## Summary of Current Status

### ✅ Completed (Recent Fixes)
1. Fixed anchor_points 4-tuple structure in _load_state()
2. Made start_position_id and end_position_id nullable in Stationary model
3. Added leg_id, stationary_id, address columns to device_positions
4. Fixed positions API endpoint field mapping (lat→latitude, lng→longitude, etc.)
5. Positions API returns leg/stationary linkage data

### 🚧 In Progress
1. Trip engine processes first journey but needs verification on all 2950 positions
2. Database migrations applied but need production restart to take effect

### ❌ Critical Missing
1. **Air leg detection and classification** (spec 2.4a)
2. **PostGIS geometry storage** for legs (LineString paths)
3. **Douglas-Peucker path simplification** for rendering
4. **Engine writes leg_id/stationary_id** back to device_positions
5. **Journeys UI** (entire frontend for Section 3)
6. **Reverse geocoding service** for address caching

### 🎯 Next Immediate Steps
1. Test full 2950 position processing on production
2. Verify journeys created match spec expectations
3. Implement leg_id/stationary_id writes during engine processing
4. Build Journeys UI panel following movement-history-redesign.html spec
