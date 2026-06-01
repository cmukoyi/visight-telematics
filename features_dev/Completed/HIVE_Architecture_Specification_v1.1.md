# HIVE Function — Architecture Specification

**Version 1.1** · BLE Tag Group Proximity Tracking
*Updated with motion-aware refinements*

---

## Document History

| Version | Notes |
|---------|-------|
| 1.0 | Initial architecture specification |
| 1.1 | Added motion detection, Pre-Transit / In Transit / Settling states, full motion-lifecycle alert suppression. Recalibrated profile thresholds for 5–10 minute reporting cadence. Deprecated Fast profile (merged into Mobile). |

---

## 1. System Overview

**HIVE** is a proximity-tracking service that monitors groups of BLE tags and emits alerts when group members exceed a configurable distance threshold. It operates on crowdsourced position data from external sources, has variable per-tag reporting cadence, and supports per-hive mobility configuration with a 60-day lifecycle.

The system is **event-driven** at its core, with periodic sweeps for time-based state transitions (staleness, expiry, archive purge). It separates **live operational state** (low-latency reads/writes) from **historical record** (audit, replay, analytics) into two distinct stores.

As of v1.1, the system also includes **motion awareness**: detecting when a hive is moving as a group and suppressing proximity-alert evaluation during transit to prevent false-positive breach alerts caused by position-staleness.

### 1.1 Key Non-Functional Characteristics

- **Latency tolerant** — alert latency is bounded by reporting cadence, not system processing speed. Sub-second processing per event is sufficient.
- **Bursty load** — urban-area hives may see clusters of position updates; rural hives may go silent for hours. Capacity planning should target peak burst, not average.
- **Honest under uncertainty** — surfaces "data quality degraded" and "in transit" states rather than fabricating confident answers when proximity cannot be reliably evaluated.
- **Append-only history** — historical data is immutable once written; configuration changes never retroactively alter past records.
- **Hard membership invariants** — enforced at the database level, not application level.
- **Motion-aware** — distinguishes stationary, pre-transit, in-transit, and settling hive states; suppresses proximity alerts across the full motion lifecycle to prevent false positives.

---

## 2. Logical Components

The system decomposes into **nine** logical components (one new in v1.1: Motion Detection Service). Each has a clear responsibility and well-defined inputs/outputs.

### 2.1 Position Ingestion Service

**Responsibility:** Receives raw position updates for tags from the upstream location source (out of scope for this spec — assumed handled).

**Inputs:** Stream of position events `{tag_id, latitude, longitude, observed_at, source_metadata}`.

**Outputs:** Validated position events published to the internal event bus.

**Behaviour:**
- Validates payload structure and coordinate bounds
- Looks up which hive (if any) the tag currently belongs to via `hive_tag_membership`
- Drops positions for tags not in any active hive
- Publishes valid, hive-relevant positions to the event bus

### 2.2 Position Filter & Persistence Service

**Responsibility:** Applies meaningful-change and self-consistency filters before persisting positions and triggering evaluation.

**Inputs:** Position events from the bus.

**Outputs:** Persisted position records (historical store), updated tag state (live store), evaluation trigger events for affected hives.

**Behaviour:**
- Loads the hive's current config (mobility profile, meaningful-change threshold)
- Compares new position to tag's last known position; drops if change is below `meaningful_change_m`
- Computes implied speed against tag's last position; if it exceeds the profile's speed limit by a wide margin, quarantines the position
- For Stationary and Slow profiles: applies median smoothing over the last N accepted positions
- Persists accepted positions to the historical positions table
- Updates tag's current position and last-seen timestamp in the live state store
- **(v1.1)** Updates tag's velocity vector (derived from current and previous position) in live state — used by Motion Detection Service for group coherence check
- Publishes evaluation trigger event for the hive

### 2.3 Motion Detection Service *(new in v1.1)*

**Responsibility:** Determines whether a hive is stationary, in transit, or settling, and manages transitions between these states.

**Inputs:** Evaluation trigger events; hive position history from live state.

**Outputs:** Hive motion state (Stationary | Pre-Transit | In Transit | Settling).

**Behaviour:**

1. **Centroid velocity computation.** Computes the geometric centroid of all Fresh-tier tags. Tracks the centroid's movement over the last 5 minutes to derive a centroid velocity (speed and bearing).

2. **Group motion coherence check.** For each tag with sufficient position history (≥2 reports in last 10 minutes), computes its individual velocity vector. Counts how many tags' velocities agree with the centroid velocity (within profile-specific tolerance). A hive shows "coherent group motion" when ≥60% of tags with computable velocities are moving with the group. *This check is used solely to confirm transit detection — it does not trigger any alerts.*

3. **Motion state machine transitions:**
   - `Stationary → Pre-Transit`: centroid speed > profile-specific threshold for ≥30 seconds (initial motion detection)
   - `Pre-Transit → In Transit`: motion sustained for ≥2 minutes total, with coherent group motion confirmed
   - `Pre-Transit → Stationary`: motion not sustained (centroid speed dropped below threshold for ≥30 seconds before reaching In Transit threshold)
   - `In Transit → Settling`: centroid stable (speed < threshold) for ≥3 minutes
   - `Settling → Stationary`: continued stability for ≥5 minutes total post-stop
   - `Settling → In Transit`: motion re-detected (e.g. brief stop at lights resumed)

4. **Profile-aware thresholds:**

   | Profile | Motion speed threshold | Settling time |
   |---------|------------------------|---------------|
   | Stationary | Disabled (motion always treated as anomaly) | n/a |
   | Slow | 10 km/h | 10 min |
   | Mobile | 15 km/h | 10 min |

**State change events:** Publishes `hive.motion_state_changed` events on transitions, consumed by the Hive Evaluation Engine and Alert Dispatch.

### 2.4 Hive Evaluation Engine

**Responsibility:** Computes hive geometric state and runs the alert state machine.

**Inputs:** Evaluation trigger events; hive motion state from Motion Detection Service.

**Outputs:** Evaluation records (historical), state transition events, alert events.

**Behaviour:**

- Loads hive's current config and all member tags' positions/freshness from live state
- **(v1.1)** Loads hive's current motion state
- Classifies each tag's freshness tier (Fresh/Recent/Stale/Lost) based on profile windows
- **(v1.1) Branches on motion state:**
  - **If Stationary:** Computes pairwise distances using Haversine formula across tags in Fresh and Recent tiers; runs full breach evaluation
  - **If Pre-Transit:** Suppresses proximity-based breach evaluation; maintains evaluation record with `motion_state` annotated
  - **If In Transit:** Suppresses proximity-based breach evaluation; maintains evaluation record with `motion_state` annotated
  - **If Settling:** Suppresses all alert evaluation until transition to Stationary; updates display state only
- Determines breach state with confidence margin (immediate fire vs. await confirmation)
- Identifies outlier tag (tag with most breaching pairs)
- Runs alert state machine: `OK → BREACH_PENDING → BREACHING → RESOLVING → OK`, with hysteresis on clearing
- Persists evaluation record to historical store with config version and motion state references
- Emits alert events on state transitions (gated by motion state)
- Updates live state with new evaluation result

### 2.5 Periodic Sweeper

**Responsibility:** Triggers time-based state transitions that aren't event-driven.

**Inputs:** Scheduled tick (every 1–5 minutes; cadence varies by sweep type).

**Outputs:** Evaluation triggers for hives with freshness changes; expiry/purge transitions; **(v1.1)** motion state transitions.

**Behaviour:**

- **Freshness sweep** (every 1–2 minutes): scans active hives, recomputes freshness tiers, triggers re-evaluation for any hive whose composition changed
- **(v1.1) Motion sweep** (every 1 minute): for hives currently Pre-Transit, In Transit or Settling, checks elapsed time and recomputes motion state; transitions to next state if conditions met
- **Pre-expiry notification sweep** (every few hours): finds hives approaching 7-day or 2-day expiry markers; emits notifications
- **Hive expiry sweep** (every 5–15 minutes): transitions active hives past `expires_at` to archived state
- **Archive purge sweep** (daily, off-peak): purges archived hives past `archive_expires_at`

Each sweep is idempotent.

### 2.6 Lifecycle Manager

*Unchanged from v1.0.* Handles state transitions for hives (creation, deletion, expiry, archive, purge).

### 2.7 Setup & Config Service

*Unchanged from v1.0.* Backs the wizard and provides smart defaults.

### 2.8 Alert Dispatch Service

**Responsibility:** Receives alert events from the evaluation engine and routes them to delivery channels.

**Inputs:** Alert events with type:
- `CONFIRMED_BREACH`
- `SUSPECTED_BREACH`
- `BREACH_CLEARED`
- `LOST_CONTACT`
- `PARTIALLY_OBSERVABLE`
- `RESOLVED_BY_CONFIG_CHANGE`
- `RESOLVED_BY_HIVE_EXPIRY`
- `RESOLVED_BY_HIVE_DELETION`
- **(v1.1)** `RESOLVED_BY_TRANSIT` — fired when an active breach is auto-resolved because the hive entered In Transit

**Outputs:** Delivered notifications via downstream channels.

**Behaviour:** Out of scope. The HIVE evaluation engine treats this as a fire-and-forget event publication.

### 2.9 Query API

*Unchanged from v1.0,* with the following addition:

**(v1.1)** Live-state queries now return the hive's motion state alongside alert state, so the UI can display "In Transit" indicators on the hive list and detail views.

---

## 3. Data Stores

The system uses three logical stores. Schemas updated to support motion awareness.

### 3.1 Operational Database (PostgreSQL recommended)

**Purpose:** Source of truth for hive identity, configuration, and membership.

**Tables:**

```
hives
  hive_id              PK
  name
  created_at
  created_by
  expires_at
  member_tag_ids
  parent_hive_id
  status               (active | archived | purged)
  archived_at
  archived_reason      (expired | user_deleted)
  archive_expires_at
  purged_at
  purged_reason

hive_config_versions
  hive_id              FK
  version_number
  valid_from
  valid_to
  mobility_profile
  distance_threshold_m
  fresh_window_s
  recent_window_s
  stale_window_s
  lost_threshold_s
  meaningful_change_m
  hysteresis_pct
  confirmation_count
  motion_speed_threshold_kmh    -- (v1.1) profile-driven, persisted for audit
  motion_settling_time_s        -- (v1.1) profile-driven, persisted for audit
  changed_by
  PK (hive_id, version_number)

hive_tag_membership
  tag_id               PK
  hive_id              FK
  joined_at
  CONSTRAINT unique(tag_id)
```

### 3.2 Historical / Time-Series Store (TimescaleDB recommended)

**Purpose:** Append-only record of all observations and derived events.

**Tables:**

```
positions                                  (hot table, append-only)
  tag_id
  hive_id
  observed_at          PK component
  latitude
  longitude
  source_metadata      JSONB
  PARTITION BY observed_at (1-day chunks)

position_quarantine                        (rare writes)
  same shape as positions, plus:
  quarantine_reason
  expected_max_speed_m_per_s

hive_evaluations                           (one row per evaluation)
  hive_id
  evaluated_at         PK component
  config_version_number
  diameter_m
  threshold_m
  outlier_tag_id
  freshness_composition JSONB
  breach_state
  breach_confidence
  motion_state          ENUM (stationary | pre_transit | in_transit | settling)   -- (v1.1)
  centroid_speed_kmh    NUMERIC                                      -- (v1.1)
  PARTITION BY evaluated_at (1-week chunks)

hive_events                                (sparse, state transitions only)
  hive_id
  occurred_at          PK component
  event_type
  config_version_number
  from_state
  to_state
  triggering_tag_id
  details              JSONB
  PARTITION BY occurred_at (1-month chunks)
```

**(v1.1)** `event_type` enum extended to include:
- `MOTION_STATE_CHANGED` — hive transitioned between Stationary / Pre-Transit / In Transit / Settling

### 3.3 Live State Store (Redis recommended)

**Key structure (updated for v1.1):**

```
hive:{hive_id}                             HASH
  config_version
  current_diameter_m
  alert_state           (OK | BREACH_PENDING | BREACHING | RESOLVING)
  motion_state          (STATIONARY | PRE_TRANSIT | IN_TRANSIT | SETTLING)   -- (v1.1)
  motion_state_since    (timestamp)                            -- (v1.1)
  centroid_lat                                                  -- (v1.1)
  centroid_lng                                                  -- (v1.1)
  centroid_speed_kmh                                            -- (v1.1)
  centroid_bearing_deg                                          -- (v1.1)
  last_evaluated_at
  outlier_tag_id
  settling_until        (timestamp; alerts suppressed before this)

hive:{hive_id}:tags                        HASH
  {tag_id}              JSON: {
                          lat, lng, observed_at, freshness_tier,
                          smoothing_buffer,
                          velocity_speed_kmh,         -- (v1.1) for coherence check
                          velocity_bearing_deg,       -- (v1.1) for coherence check
                          velocity_computed_at        -- (v1.1)
                        }

hive:{hive_id}:state_machine               HASH
  pending_breach_since
  pending_clear_since
  consecutive_confirms
  pending_motion_change_since                                   -- (v1.1)

tag:{tag_id}:hive                          STRING
  {hive_id}             EXPIRE 1 hour
```

**Recovery (v1.1):** Live state is reconstructible from operational DB + recent positions. Velocity vectors and motion state can be re-derived from the position history on rehydration; no separate persistence needed.

---

## 4. Event Bus / Message Flow

**Topics (v1.1 additions in bold):**

- `positions.raw`
- `positions.accepted`
- `hive.evaluation_triggered`
- `hive.evaluation_completed`
- `hive.alert_events`
- `hive.lifecycle_events`
- **`hive.motion_state_changed`** — published on Stationary ↔ Pre-Transit ↔ In Transit ↔ Settling transitions

Partitioning key: `hive_id`. Ordered processing per hive remains a hard requirement.

---

## 5. End-to-End Data Flow

### 5.1 Position Update Flow (v1.1)

```
External upstream
    |
[1] Position Ingestion Service
    - Validates, looks up hive membership
    - Publishes to positions.raw
    |
[2] Position Filter & Persistence Service
    - Loads hive config (PostgreSQL)
    - Loads tag's last position (Redis)
    - Applies meaningful-change filter
    - Applies self-consistency / speed-limit check
    - Applies smoothing if applicable
    - Computes velocity vector for tag        -- (v1.1)
    - Writes accepted position (TimescaleDB)
    - Updates tag state including velocity (Redis)
    - Publishes to hive.evaluation_triggered
    |
[3] Motion Detection Service                  -- (v1.1)
    - Computes/updates centroid velocity
    - Assesses group motion coherence
    - Determines motion state transition
    - If transition: publishes hive.motion_state_changed
    - Updates motion state in Redis
    |
[4] Hive Evaluation Engine
    - Loads hive config + motion state (Redis)
    - Loads all member tag states (Redis)
    - Reclassifies freshness tiers
    - BRANCH on motion state:               -- (v1.1)
        STATIONARY:   full proximity evaluation
        PRE_TRANSIT:  suppress all proximity alerts
        IN_TRANSIT:   suppress all proximity alerts
        SETTLING:     suppress all evaluation, display only
    - For STATIONARY: computes pairwise distances, identifies outlier
    - Runs state machine with hysteresis and confirmation
    - Writes evaluation record (TimescaleDB)
    - On state transition: writes hive event (TimescaleDB)
    - On alert: publishes to hive.alert_events
    - Updates live state (Redis)
    |
[5] Alert Dispatch Service (out of scope)
```

### 5.2 Periodic Sweep Flow

```
Scheduler tick
    |
Periodic Sweeper
    - Freshness sweep: identifies hives needing freshness reassessment
    - Motion sweep (v1.1): identifies hives needing motion state update
    - Publishes hive.evaluation_triggered for affected hives
    |
[3] Motion Detection Service (re-evaluates if needed)
[4] Hive Evaluation Engine
```

### 5.3 Hive Expiry Flow

*Unchanged from v1.0.*

---

## 6. Component Deployment Topology

*Unchanged from v1.0,* with the addition of the Motion Detection Service deployed alongside the Hive Evaluation Engine — same horizontal-scale stateless container pattern.

In small deployments, the Motion Detection Service can be implemented as a co-located module within the Hive Evaluation Engine container rather than a separate service. Logical separation matters more than physical separation at this scale.

---

## 7. Cross-Cutting Concerns

*Sections 7.1 to 7.7 unchanged from v1.0.*

### 7.8 Motion State Reasoning *(new in v1.1)*

Motion state is derived data, not user-configured. The system always knows the hive's current motion state and exposes it via the Query API for UI display, but users cannot directly set or override it.

The motion state is **profile-aware**:
- Stationary profile hives have motion detection disabled — they should not move; if they do, the user wants the alert
- Slow / Mobile profiles enable motion detection with profile-specific thresholds (see Section 2.3)

Motion state changes are persisted to `hive_events` so historical analysis can correlate alert behaviour with motion state. This is essential for debugging "why didn't I get an alert?" — the answer is often "your hive was In Transit at that moment."

---

## 8. Security & Privacy

*Unchanged from v1.0.*

---

## 9. Capacity Planning Notes

*Unchanged from v1.0,* with one addition:

**(v1.1)** Motion detection adds modest computational overhead per evaluation (centroid computation, per-tag velocity calculation, coherence check). At the scales in v1.0 capacity planning, this is well within headroom — sub-millisecond per evaluation. No additional infrastructure required.

---

## 10. Implementation Phasing

Updated for v1.1 to reflect motion-aware refinements:

### Phase 1 — Core Proximity Tracking (MVP)
*As per v1.0.* Position ingestion + filter + evaluation + basic alerting.

### Phase 2 — Configuration and Lifecycle
*As per v1.0.* Wizard, mobility profiles, smart defaults, 60-day lifecycle, archive, permanent deletion.

### Phase 3 — Motion Awareness *(v1.1)*

- Implement Motion Detection Service (centroid velocity, group coherence check, motion state machine)
- Add In Transit / Settling states to the hive lifecycle
- Suppress proximity alerts during In Transit and Settling
- Auto-resolve active breaches with `RESOLVED_BY_TRANSIT` when entering In Transit
- UI: show motion state on hive list and detail views
- Run a fresh proximity evaluation on `Settling → Stationary` transition

This phase delivers the false-positive fix for moving hives.

### Phase 4 — Polish and Operational Maturity
*As per v1.0.* Recreation chains, archive UI, full observability, capacity scaling, multi-region (if needed), historical analytics views, position uncertainty modelling.

---

## 11. Motion Awareness — Detailed Specification *(new in v1.1)*

This section is the authoritative specification for motion-related behaviour. It covers detection, the state machine, and evaluation modifications.

### 11.1 Why Motion Awareness Is Necessary

Crowdsourced position reporting at 2–5 minute cadence cannot reliably evaluate proximity for hives moving at vehicle speeds. At 30 km/h, a 2-minute-old position is up to 1 km behind where the tag actually is. Comparing this stale position against a fresher report from another tag in the same vehicle produces apparent distances exceeding 1 km — a textbook false-positive breach.

This is a fundamental constraint of position-staleness vs. motion-speed, not a bug that can be tuned away. Motion awareness addresses it by detecting when the constraint applies and suppressing evaluation that would produce misleading results.

### 11.2 Motion State Machine

Four states per hive, in addition to the existing alert state machine:

| State | Meaning | Alert evaluation |
|-------|---------|------------------|
| `STATIONARY` | Centroid stable, hive at rest | Normal proximity evaluation; all alert types active |
| `PRE_TRANSIT` | Initial motion detected, awaiting confirmation | Proximity alerts suppressed |
| `IN_TRANSIT` | Centroid moving with coherent group motion confirmed | Proximity alerts suppressed |
| `SETTLING` | Recently stopped, position data still stabilising | All alert evaluation suppressed; display only |

The four states form a clean cycle: Stationary → Pre-Transit → In Transit → Settling → Stationary. Pre-Transit and Settling are buffer states on either side of In Transit; their purpose is to absorb the transitional moments where position data is unreliable.

**Transitions:**

```
STATIONARY → PRE_TRANSIT
  Trigger: centroid speed > profile threshold for ≥30 seconds
  Side effect: suppress alert evaluation immediately
               (any active BREACHING alert is resolved with RESOLVED_BY_TRANSIT)

PRE_TRANSIT → IN_TRANSIT
  Trigger: motion sustained for ≥2 minutes total since entering Pre-Transit
           AND ≥60% of tags showing coherent group motion
  Side effect: none (alerts already suppressed)

PRE_TRANSIT → STATIONARY
  Trigger: centroid speed dropped below threshold for ≥30 seconds before
           reaching In Transit confirmation
  Side effect: run a fresh proximity evaluation; resume normal alerting
               (any genuine breach detected during the false-start is captured)

IN_TRANSIT → SETTLING
  Trigger: centroid speed < profile threshold for ≥3 minutes

SETTLING → STATIONARY
  Trigger: continued stability for ≥5 minutes total post-stop
  Side effect: run normal proximity evaluation; fire alert if breach detected

SETTLING → IN_TRANSIT
  Trigger: motion re-detected before settling completes
  (handles brief stops at lights, in traffic, etc.)
```

**Why two buffer states (Pre-Transit and Settling)?**

The motion lifecycle has two transition points where position data is unreliable:

- *Starting motion* — for the first ~2 minutes, the system needs to confirm motion is sustained and coherent before committing to In Transit. During this window, position staleness across tags can already cause false breaches if alerts continue to fire normally.
- *Stopping motion* — for the first 3–5 minutes after coming to rest, the trailing edge of in-motion reports keeps arriving with stale positions. Resuming evaluation immediately produces false breaches.

Pre-Transit and Settling are symmetric in purpose: both suppress evaluation during a transitional period where the data is too noisy to trust. Together they ensure no proximity alerts fire from the first hint of motion to fully settled at destination.

### 11.3 Centroid Velocity Computation

The centroid is the geometric mean of all Fresh-tier tag positions. Recent-tier tags are *excluded* from centroid computation because their staleness undermines the centroid's accuracy.

Centroid velocity is the rate of change of the centroid position over a rolling 5-minute window:

```
v = (centroid_now - centroid_5min_ago) / 5 minutes
```

Bearing is the great-circle bearing from the older centroid to the newer one.

If the hive has fewer than 2 Fresh tags, centroid velocity cannot be reliably computed; motion state remains in its current value until enough fresh data accumulates.

### 11.4 Group Motion Coherence Check

Used solely as a confirmation signal for entering `IN_TRANSIT` — never to fire alerts.

For each tag with at least 2 reports in the last 10 minutes, compute its individual velocity vector (speed and bearing) from its two most recent positions.

A tag is **motion-coherent** with the centroid if both:
- Its speed is within profile tolerance of the centroid speed
- Its bearing is within profile tolerance of the centroid bearing

A hive shows "coherent group motion" when ≥60% of tags with computable velocities are motion-coherent.

This check prevents one drifting tag's noisy positions from making the system think the whole hive is moving. If a single tag happens to produce reports that look like motion (e.g. the phone reporting the position is itself moving), but other tags are clearly stationary, the coherence check fails and the hive remains `STATIONARY`.

### 11.5 Profile-Specific Thresholds

The motion-detection parameters per profile:

| Profile | Motion speed threshold | Settling time | Coherence speed tolerance | Coherence bearing tolerance |
|---------|------------------------|---------------|---------------------------|------------------------------|
| Stationary | n/a (motion detection disabled) | n/a | n/a | n/a |
| Slow | 10 km/h | 10 min | ±5 km/h | ±60° |
| Mobile | 15 km/h | 10 min | ±10 km/h | ±45° |

For the complete set of profile parameters (freshness windows, default distance threshold, meaningful-change filter, hysteresis, confirmation requirement, lost threshold), see Appendix A.

These values are calibrated for typical 5–10 minute crowdsourced reporting cadence with bimodal variation (occasionally as frequent as 1–2 minutes; occasionally with gaps of 20+ minutes). They are starting values to be tuned with production telemetry.

### 11.6 Suppression Behaviour During Pre-Transit / In Transit / Settling

When a hive enters `PRE_TRANSIT`:
- Any active `BREACHING` alert is transitioned to `OK` with reason `RESOLVED_BY_TRANSIT`
- Any `BREACH_PENDING` state is cleared
- Future proximity-based evaluations record `motion_state = pre_transit` but do not transition the alert state machine
- The `Lost Contact` alert path remains active

When a hive enters `IN_TRANSIT` (from Pre-Transit):
- No alert state changes needed (already suppressed in Pre-Transit)
- Future proximity-based evaluations record `motion_state = in_transit`
- The `Lost Contact` alert path remains active

When a hive transitions `PRE_TRANSIT → STATIONARY` (motion not sustained):
- A normal proximity evaluation runs immediately
- If a breach is detected at this point (for example, a real breach happened to occur during the brief motion burst), normal alert flow applies
- This ensures false-start motion doesn't permanently suppress legitimate alerts

When a hive enters `SETTLING`:
- All evaluation is suppressed (no alert state changes)
- This avoids noise from the trailing edge of stale-but-now-Fresh-by-window-rules reports arriving after the stop

When a hive transitions `SETTLING → STATIONARY`:
- A normal proximity evaluation runs immediately
- If a breach is detected at this point, normal alert flow applies (with confirmation requirement)
- Alert copy on post-settling breach acknowledges the timing: *"Travel Kit arrived but Tag 4 is missing. T-04 was last seen 35 minutes ago, 12 km from current position."*

### 11.7 UI Implications

**Hive list:**
- Status pill includes motion state alongside alert state
- Suggested visual: `STATIONARY` shows alert state colour normally; `PRE_TRANSIT` shows transitional state "Starting..." (blue/amber); `IN_TRANSIT` shows calm blue badge "In Transit"; `SETTLING` shows transitional state "Stopping..." (blue/amber)
- Pre-Transit and Settling can share the same visual treatment (transitional badge) to keep the UI vocabulary simple — users don't need to distinguish them, only to understand that the hive is between rest and full motion

**Hive detail:**
- Prominent transit indicator when motion state is `PRE_TRANSIT`, `IN_TRANSIT`, or `SETTLING`
- Map continues to display tag positions (users want to see where things are)
- Diameter readout shows current diameter but with "(in transit)" annotation indicating it's not being evaluated for breaches
- Activity timeline includes motion state transitions as discrete events

**Alert messaging:**
- `RESOLVED_BY_TRANSIT` (fired on entry to Pre-Transit if a breach was active): "Travel Kit is on the move — proximity monitoring paused"
- Post-settling re-evaluation: "Travel Kit arrived at destination. All tags accounted for." (If clean) or "Travel Kit arrived but Tag 4 is missing." (If breach confirmed.)

### 11.8 Open Questions and Future Refinements

Items deferred for later consideration:

- **Mid-transit separation detection** — detecting when an individual tag's motion diverges from the group during transit (e.g. a tag falls out of a moving vehicle). Considered and descoped from v1.1; may be revisited based on real-world need.
- **User-controllable motion sensitivity** — exposing advanced settings for users to tune motion detection thresholds. Currently profile-driven only.
- **Multi-vehicle scenarios** — a hive split across two coordinated vehicles would currently appear as motion-incoherent. Detection of "two coherent sub-groups" is plausible but not yet specified.
- **Motion-aware historical analytics** — separating "alerts during stationary periods" from "alerts during transit" in analytics reports.

---

## 12. Summary of Changes from v1.0

For reviewers familiar with v1.0:

- **New component:** Motion Detection Service (Section 2.3)
- **New hive states:** Stationary / Pre-Transit / In Transit / Settling (Section 11.2)
- **New alert behaviour:** Suppression of proximity alerts across the full motion lifecycle (Pre-Transit, In Transit, and Settling)
- **New alert type:** `RESOLVED_BY_TRANSIT` (auto-resolves active breaches when entering transit)
- **Schema additions:** velocity vectors per tag (for group coherence check only), motion state per hive, centroid tracking, motion state in evaluation records
- **New event topic:** `hive.motion_state_changed`
- **New event type:** `MOTION_STATE_CHANGED` in `hive_events`
- **Profile structure update:** three profiles (Stationary / Slow / Mobile) instead of four. Fast profile deprecated and merged into Mobile.
- **Profile thresholds recalibrated** for 5–10 minute crowdsourced reporting cadence — see Appendix A for full reference values.
- **Phasing update:** Phase 3 added — Motion Awareness

All v1.0 behaviour is preserved. Motion awareness is additive — hives configured with the Stationary profile behave exactly as in v1.0.

---

## Appendix A — Complete Profile Parameter Reference

Authoritative reference for the resolved parameter values bundled by each mobility profile preset. These are the defaults applied at hive creation time and persisted into `hive_config_versions`. Users may override the distance threshold via the wizard; other parameters are profile-driven.

| Parameter | Stationary | Slow | Mobile |
|-----------|------------|------|--------|
| **Default distance threshold** | 150 m | 450 m | 1000 m |
| Fresh window | <30 min | <20 min | <15 min |
| Recent window | 30 min – 4 hr | 20 min – 2 hr | 15 min – 1 hr |
| Stale window | 4–24 hr | 2–8 hr | 1–4 hr |
| Lost threshold | >24 hr | >8 hr | >2 hr |
| Motion detection | Disabled | Enabled at 10 km/h | Enabled at 15 km/h |
| Pre-Transit confirmation period | n/a | 10 min | 10 min |
| Settling window | n/a | 10 min | 10 min |
| Meaningful-change filter | 2–3 m | 15 m | 30 m |
| Hysteresis (clear at) | 90% | 85% | 75% |
| Confirmation requirement | 1 fresh report | 1 fresh report | 1 fresh report |
| Coherence speed tolerance | n/a | ±5 km/h | ±10 km/h |
| Coherence bearing tolerance | n/a | ±60° | ±45° |

**Calibration notes:**

- These values are calibrated against typical bimodal reporting cadence (5–10 minute average, with occasional bursts of 1–2 minutes when phones are nearby and gaps of 20+ minutes in low-traffic areas).
- Distance thresholds reflect the lower bound at which proximity evaluation is reliable given the position uncertainty implied by the data cadence. At reporting intervals of 5–10 minutes, position drift for moving assets can be hundreds of metres even when the tags are physically together.
- Motion detection thresholds (10 km/h for Slow, 15 km/h for Mobile) sit above walking pace (~5 km/h) to avoid triggering transit suppression during pedestrian movement. Slow uses a lower threshold to be more sensitive to motion in keeping with the profile's stricter expected-stationarity.
- Lost thresholds are conservative — they're the point at which the system actively alerts that something is wrong rather than just stale. For Mobile, 2 hours is appreciably longer than the bimodal worst-case reporting gap and represents genuine concern.
- Confirmation requirement is reduced to 1 fresh report (down from 2 in earlier drafts) to keep alert latency tolerable at slow reporting cadence. The meaningful-change filter and confidence margin provide the noise floor instead.

---

*End of specification v1.1*
