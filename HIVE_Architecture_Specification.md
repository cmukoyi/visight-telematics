# HIVE — Architecture Specification

*HIVE Function — Architecture Specification*
*BLE Tag Group Proximity Tracking*
*Version 1.0 — 29 April 2026*

---

## 1. System Overview

**HIVE** is a **proximity-tracking service** that monitors groups of BLE tags and emits alerts when group members exceed a configurable distance threshold. It operates on crowdsourced position data from external sources, has variable per-tag reporting cadence, and supports per-hive mobility configuration with a 60-day lifecycle.

The system is **event-driven** at its core, with periodic sweeps for time-based state transitions (staleness, expiry, archive purge). It separates **live operational state** (low-latency reads/writes) from **historical record** (audit, replay, analytics) into two distinct stores.

### 1.1 Key Non-Functional Characteristics

- **Latency tolerant:** alert latency is bounded by reporting cadence, not system processing speed. Sub-second processing per event is sufficient.
- **Bursty load:** urban-area hives may see clusters of position updates; rural hives may go silent for hours. Capacity planning should target peak burst, not average.
- **Honest under uncertainty:** surfaces "data quality degraded" states rather than fabricating confident answers when crowdsourced data is sparse.
- **Append-only history:** historical data is immutable once written; configuration changes never retroactively alter past records.
- **Hard membership invariants:** enforced at the database level, not application level.

---

## 2. Logical Components

The system decomposes into eight logical components. Each has a clear responsibility and well-defined inputs/outputs.

### 2.1 Position Ingestion Service

**Responsibility:** Receives raw position updates for tags from the upstream location source (out of scope for this spec — assumed handled).

**Inputs:** Stream of position events `{tag_id, latitude, longitude, observed_at, source_metadata}`.

**Outputs:** Validated position events published to the internal event bus.

**Behaviour:**
- Validates payload structure and coordinate bounds
- Looks up which hive (if any) the tag currently belongs to via `hive_tag_membership`
- Drops positions for tags not in any active hive (no-op for tracking purposes; may still be persisted for general telemetry by other systems)
- Publishes valid, hive-relevant positions to the event bus

This service is intentionally thin. Filtering and analysis happen downstream so this layer can scale horizontally with simple stateless processing.

---

### 2.2 Position Filter & Persistence Service

**Responsibility:** Applies meaningful-change and self-consistency filters before persisting positions and triggering evaluation.

**Inputs:** Position events from the bus.

**Outputs:** Persisted position records (historical store), updated tag state (live store), evaluation trigger events for affected hives.

**Behaviour:**
- Loads the hive's current config (mobility profile, meaningful-change threshold)
- Compares new position to tag's last known position; drops if change is below `meaningful_change_m`
- Computes implied speed against tag's last position; if it exceeds the profile's speed limit by a wide margin, quarantines the position (writes to a `position_quarantine` table for audit, does not update live state)
- For Stationary and Slow profiles: applies median smoothing over the last N accepted positions
- Persists accepted positions to the historical positions table
- Updates tag's current position and last-seen timestamp in the live state store
- Publishes evaluation trigger event for the hive

---

### 2.3 Hive Evaluation Engine

**Responsibility:** Computes hive geometric state and runs the alert state machine.

**Inputs:** Evaluation trigger events (from filter service or periodic sweeper).

**Outputs:** Evaluation records (historical), state transition events, alert events.

**Behaviour:**
- Loads hive's current config and all member tags' positions/freshness from live state
- Classifies each tag's freshness tier (Fresh/Recent/Stale/Lost) based on profile windows
- Computes pairwise distances using Haversine formula across tags in Fresh and Recent tiers
- Determines breach state with confidence margin (immediate fire vs. await confirmation based on excess over threshold)
- Identifies outlier tag (tag with most breaching pairs)
- Runs alert state machine: `OK → BREACH_PENDING → BREACHING → RESOLVING → OK`, with hysteresis on clearing
- Persists evaluation record to historical store with config version reference
- Emits alert events on state transitions
- Updates live state with new evaluation result

---

### 2.4 Periodic Sweeper

**Responsibility:** Triggers time-based state transitions that aren't event-driven.

**Inputs:** Scheduled tick (every 1–5 minutes; cadence varies by sweep type).

**Outputs:** Evaluation triggers for hives with freshness changes; expiry/purge transitions.

**Behaviour:**
- **Freshness sweep** (every 1–2 minutes): scans active hives, recomputes freshness tiers, triggers re-evaluation for any hive whose composition changed
- **Pre-expiry notification sweep** (every few hours): finds hives approaching 7-day or 2-day expiry markers; emits notifications
- **Hive expiry sweep** (every 5–15 minutes): transitions active hives past `expires_at` to archived state
- **Archive purge sweep** (daily, off-peak): purges archived hives past `archive_expires_at`

Each sweep is idempotent — safe to run multiple times in the same window. State transitions are gated on the current state, not on time alone.

---

### 2.5 Lifecycle Manager

**Responsibility:** Handles state transitions for hives (creation, deletion, expiry, archive, purge).

**Inputs:** User actions (create/delete/permanent-delete from API) and sweeper triggers (auto-expiry, auto-purge).

**Outputs:** Updated hive records, tag membership changes, lifecycle events.

**Behaviour:**
- **On creation:** validates tags are not in other active hives (DB constraint enforces); creates hive record; opens initial config version; populates `hive_tag_membership`; sets `expires_at = created_at + 60 days`; starts settling period (no alerts for 5–10 min)
- **On user delete or auto-expiry:** releases tags first (removes from `hive_tag_membership`), then sets status to archived with appropriate `archived_reason`, sets `archive_expires_at = now + 60 days`, auto-resolves any active alerts
- **On permanent delete or auto-purge:** releases tags (if still member), purges historical data, sets status to purged, retains tombstone row for chain integrity
- **On config change:** closes current config version (`valid_to = now`), opens new version; resets transient state machine states; for active breaches, re-evaluates under new config and emits `RESOLVED_BY_CONFIG_CHANGE` if appropriate

---

### 2.6 Setup & Config Service

**Responsibility:** Backs the wizard and provides smart defaults.

**Inputs:** User requests for hive setup defaults; tag selection.

**Outputs:** Suggested mobility profile, suggested distance threshold, confidence indicator.

**Behaviour:**
- Queries historical positions for selected tags over the last 7–30 days
- Computes movement statistics per tag (median position, max distance from median, daily movement)
- Maps statistics to suggested mobility profile
- Computes typical pairwise distances during periods with all tags fresh
- Suggests threshold as 2–3× typical observed distance, snapped to user-friendly values (50/100/250/500/1000m)
- Returns confidence level based on data sufficiency (high if >7 days history, low otherwise)
- For "Recreate similar hive" requests, returns the previous hive's resolved config as the default instead

---

### 2.7 Alert Dispatch Service

**Responsibility:** Receives alert events from the evaluation engine and routes them to delivery channels (out of scope per scoping, but the integration boundary is part of this spec).

**Inputs:** Alert events with type:
- `CONFIRMED_BREACH`
- `SUSPECTED_BREACH`
- `BREACH_CLEARED`
- `LOST_CONTACT`
- `PARTIALLY_OBSERVABLE`
- `RESOLVED_BY_CONFIG_CHANGE`
- `RESOLVED_BY_HIVE_EXPIRY`
- `RESOLVED_BY_HIVE_DELETION`

**Outputs:** Delivered notifications via downstream channels.

**Behaviour:** Out of scope. The HIVE evaluation engine treats this as a fire-and-forget event publication.

---

### 2.8 Query API

**Responsibility:** Serves user-facing read requests.

**Inputs:** HTTP/RPC requests for current hive state, historical alerts, evaluation history, archive contents.

**Outputs:** Serialised state and history data.

**Behaviour:**
- Live-state queries (current hive view, current diameter, current alert state) read from live state store
- Historical queries (past alerts, evaluation history, archived hives) read from historical store
- Configuration queries return current config version, with optional history
- Tag availability queries (for hive creation UI) read from `hive_tag_membership`

---

## 3. Data Stores

The system uses three logical stores, each chosen for its access pattern.

### 3.1 Operational Database (PostgreSQL recommended)

**Purpose:** Source of truth for hive identity, configuration, and membership. Strong consistency required.

**Tables:**

```
hives
  hive_id              PK
  name
  created_at
  created_by           (user reference)
  expires_at
  member_tag_ids       (array, frozen at creation; informational copy)
  parent_hive_id       (nullable, for recreation chains)
  status               (active | archived | purged)
  archived_at
  archived_reason      (expired | user_deleted)
  archive_expires_at
  purged_at
  purged_reason        (auto_retention | user_purged)

hive_config_versions
  hive_id              FK
  version_number
  valid_from
  valid_to             (null = current)
  mobility_profile     (stationary | slow | mobile | fast | custom)
  distance_threshold_m
  fresh_window_s
  recent_window_s
  stale_window_s
  lost_threshold_s
  meaningful_change_m
  hysteresis_pct
  confirmation_count
  changed_by
  PK (hive_id, version_number)

hive_tag_membership
  tag_id               PK   <- enforces single-hive rule
  hive_id              FK
  joined_at

  CONSTRAINT: unique(tag_id) — physically impossible to violate
  FOREIGN KEY (hive_id) -> hives(hive_id)
```

**Why PostgreSQL:** ACID guarantees for the membership invariant, mature constraint enforcement, supports the temporal config pattern naturally with composite primary keys, and integrates cleanly with TimescaleDB on the same instance if desired.

---

### 3.2 Historical / Time-Series Store (TimescaleDB recommended)

**Purpose:** Append-only record of all observations and derived events. Optimised for time-range queries and high-volume writes.

**Tables (TimescaleDB hypertables):**

```
positions                                  (hot table, append-only)
  tag_id
  hive_id              (denormalised for query efficiency)
  observed_at          PK component
  latitude
  longitude
  source_metadata      JSONB
  PARTITION BY observed_at (1-day chunks)
  INDEX on (tag_id, observed_at DESC)
  INDEX on (hive_id, observed_at DESC)

position_quarantine                        (rare writes, audit)
  same shape as positions, plus:
  quarantine_reason    (impossible_speed | invalid_coords | other)
  expected_max_speed_m_per_s

hive_evaluations                           (one row per evaluation)
  hive_id
  evaluated_at         PK component
  config_version_number
  diameter_m
  threshold_m
  outlier_tag_id       (nullable)
  freshness_composition JSONB  (e.g. {fresh:3, recent:1, stale:1, lost:0})
  breach_state         (enum)
  breach_confidence    (high | low)
  PARTITION BY evaluated_at (1-week chunks)
  INDEX on (hive_id, evaluated_at DESC)

hive_events                                (sparse, state transitions only)
  hive_id
  occurred_at          PK component
  event_type
  config_version_number
  from_state
  to_state
  triggering_tag_id    (nullable)
  details              JSONB
  PARTITION BY occurred_at (1-month chunks)
  INDEX on (hive_id, occurred_at DESC)
  INDEX on (event_type, occurred_at DESC)
```

**Why TimescaleDB:** Time-series performance with full SQL, native PostgreSQL compatibility (so it can run alongside operational tables on one engine if desired), built-in continuous aggregates for downsampling at scale, mature retention policy support.

**Alternatives:** InfluxDB if you prefer a purpose-built TSDB and don't need SQL. ClickHouse if analytics workloads will dominate. Avoid generic relational stores without time-series extensions — they degrade poorly past ~10M rows in time-indexed tables.

**Retention policy:** Hot retention for the active 60-day lifetime + 60-day archive = ~120 days at full resolution. Beyond that, downsample to hourly aggregates if you want long-term analytics, or hard-purge per the user's permanent-delete action.

---

### 3.3 Live State Store (Redis recommended)

**Purpose:** Low-latency read/write of current hive and tag state. Working set is small enough to fit comfortably in memory.

**Key structure:**

```
hive:{hive_id}                             HASH
  config_version
  current_diameter_m
  alert_state           (OK | BREACH_PENDING | BREACHING | RESOLVING)
  last_evaluated_at
  outlier_tag_id
  settling_until        (timestamp; alerts suppressed before this)

hive:{hive_id}:tags                        HASH
  {tag_id}              JSON: {lat, lng, observed_at, freshness_tier, smoothing_buffer}

hive:{hive_id}:state_machine               HASH
  pending_breach_since
  pending_clear_since
  consecutive_confirms

tag:{tag_id}:hive                          STRING (cache of membership)
  {hive_id}             EXPIRE 1 hour, refresh on miss
```

**Why Redis:** Sub-millisecond read/write, atomic hash operations for in-place updates, persistence options (AOF/RDB) so it can recover from restarts, cluster mode for horizontal scaling if needed later.

**Recovery:** Live state is always reconstructible from the operational DB (hive config, membership) plus the last few hours of historical positions. On Redis failure, a rehydration job rebuilds state from authoritative sources. This means the live store can be treated as a cache, simplifying durability concerns.

---

## 4. Event Bus / Message Flow

An internal event bus connects the components, decoupling ingestion from evaluation and evaluation from alerting.

**Recommended:** Kafka or equivalent (Redpanda, AWS Kinesis, GCP Pub/Sub). For smaller scale, Redis Streams or RabbitMQ work. Avoid synchronous HTTP between these components — coupling ingestion to evaluation directly creates back-pressure problems under burst load.

**Topics:**

| Topic | Published by |
|---|---|
| `positions.raw` | Ingestion service |
| `positions.accepted` | Filter service (after meaningful-change/quarantine checks) |
| `hive.evaluation_triggered` | Filter service or sweeper |
| `hive.evaluation_completed` | Evaluation engine |
| `hive.alert_events` | Evaluation engine (on state transitions); consumed by alert dispatch |
| `hive.lifecycle_events` | Lifecycle manager (created/expired/archived/purged) |

**Partitioning key for hive-related topics:** `hive_id`. This guarantees ordered processing per hive, which the alert state machine depends on. Cross-hive operations are independent and can scale horizontally across partitions.

---

## 5. End-to-End Data Flow

### 5.1 Position Update Flow

The canonical path for a single position update:

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
    - Writes accepted position (TimescaleDB)
    - Updates tag state (Redis)
    - Publishes to hive.evaluation_triggered
    |
[3] Hive Evaluation Engine
    - Loads hive config (Redis cache, fallback PostgreSQL)
    - Loads all member tag states (Redis)
    - Reclassifies freshness tiers
    - Computes pairwise distances (Haversine)
    - Identifies outlier
    - Runs state machine with hysteresis and confirmation
    - Writes evaluation record (TimescaleDB)
    - On state transition: writes hive event (TimescaleDB)
    - On alert: publishes to hive.alert_events
    - Updates live state (Redis)
    |
[4] Alert Dispatch Service (out of scope)
```

### 5.2 Periodic Sweep Flow

```
Scheduler tick
    |
Periodic Sweeper
    - Queries Redis for hives needing freshness reassessment
    - Publishes hive.evaluation_triggered for affected hives
    |
[3] Hive Evaluation Engine (same as above)
```

### 5.3 Hive Expiry Flow

```
Hive expiry sweeper tick
    |
Lifecycle Manager
    - Finds hives with expires_at < now and status = active
    - For each: releases tags from hive_tag_membership (PostgreSQL)
                updates hive status to archived (PostgreSQL)
                clears hive's live state (Redis)
                writes lifecycle event (TimescaleDB)
                publishes RESOLVED_BY_HIVE_EXPIRY alert event
                publishes hive.lifecycle_events
```

---

## 6. Component Deployment Topology

Recommended deployment shape, scaling-agnostic:

- **Stateless services** (Position Ingestion, Position Filter, Hive Evaluation, Lifecycle Manager, Setup Service, Query API): deploy as containers behind a load balancer. Horizontal scale-out by increasing replicas. No sticky sessions needed.
- **Periodic Sweeper:** deploy as a single-leader scheduled job (e.g., Kubernetes CronJob, or leader-elected service). Idempotent design means brief overlaps during failover are safe.
- **Operational DB (PostgreSQL/TimescaleDB):** managed instance with read replicas for the Query API. Primary handles writes from filter service, evaluation engine, lifecycle manager.
- **Live state (Redis):** managed instance with persistence enabled. Single primary at small scale; cluster mode if state size grows past memory of a single node.
- **Event bus:** managed Kafka or equivalent. Multi-AZ replication.

A single-region deployment is sufficient for v1. Multi-region only matters if the upstream location source is geographically distributed and latency to a central region becomes problematic — unlikely at the alert latency you're working with.

---

## 7. Cross-Cutting Concerns

### 7.1 Configuration Management

Mobility profile presets are stored as application configuration (code or config files), not in the database. The resolved parameters from a preset choice are persisted into `hive_config_versions` at the moment of selection. This means changing a preset's defaults later affects new hives only — existing hives keep their resolved values.

### 7.2 Time and Clocks

All timestamps are stored as UTC. The 60-day expiry and archive timers are computed in UTC. User-facing displays convert to the user's local timezone at the presentation layer. Don't trust client clocks for any backend logic — `expires_at` is set server-side at creation time.

### 7.3 Idempotency

All write operations should be idempotent at their natural boundary:

- **Position ingestion:** deduplicate on `(tag_id, observed_at)` to handle upstream redelivery
- **Evaluation engine:** keyed on `(hive_id, evaluated_at)`; same trigger reprocessed produces same result
- **Sweepers:** gated on current state, not just time
- **Lifecycle transitions:** state machine transitions check current state before applying

This makes the system tolerant of message redelivery, sweeper overlap during deployments, and partial-failure retries.

### 7.4 Observability

Required telemetry:

- **Metrics:** position throughput, evaluation latency, alert event rate, state distribution across hives, sweep duration, queue depth on event bus topics
- **Per-hive metrics** (sampled): alert state transitions over time, freshness composition trends, evaluation frequency
- **Structured logs:** every evaluation logs `hive_id`, `config_version`, tags, freshness tiers, computed diameter, decision. Critical for debugging "why did this alert fire?" questions
- **Traces:** end-to-end traces from position ingestion through alert publication, to identify latency bottlenecks

Alert lifecycle events themselves are part of the historical store and serve as their own audit log — no separate logging needed for "what alerts did the system send?".

### 7.5 Data Validation

The system has multiple validation boundaries; each should reject bad data with clear error semantics:

- **Ingestion:** reject malformed payloads, invalid coordinates (out of [-90,90]/[-180,180])
- **Filter service:** quarantine impossible-speed positions to a separate table rather than dropping silently
- **Lifecycle:** reject hive creation with tags already in active hives (DB constraint)
- **Config service:** reject configs with logically inconsistent parameter values (e.g., fresh window > recent window)

Validation failures should produce events in the historical store where appropriate so they're auditable.

### 7.6 Testing Strategy

Three levels of testing the architecture supports:

- **Unit tests** on the geometric primitives (Haversine, max-pairwise, outlier attribution) and the alert state machine. These have no infrastructure dependencies and should achieve very high coverage.
- **Component tests** with real PostgreSQL/TimescaleDB/Redis but mocked event bus, exercising each service in isolation.
- **Integration tests** with the full stack, using a synthetic position event generator that can replay realistic scenarios (urban hyperactivity, rural silence, breach-and-recover, etc.)

The clean component separation in this architecture is partly motivated by making each of these levels feasible.

### 7.7 Failure Modes and Degradation

| Failure | Impact | Recovery |
|---|---|---|
| **Redis unavailable** | Live state queries fail; evaluation engine cannot run | Rehydrate from PostgreSQL + recent TimescaleDB positions. Position ingestion can continue (writes to TimescaleDB only) and evaluation catches up after recovery. |
| **TimescaleDB unavailable** | Position writes fail; evaluation engine fails. Worst case — no degraded mode | Local write buffering at the ingestion service with a bounded backlog |
| **Event bus unavailable** | Services may buffer locally depending on bus implementation | For simpler buses, consider a degraded path where ingestion writes directly to TimescaleDB and a recovery process replays missed events |
| **PostgreSQL unavailable** | Hive creation/deletion blocked; existing hive evaluation continues from cached config in Redis | Brief outages are tolerable given read-mostly nature of operational data |

The asymmetric criticality (TimescaleDB > PostgreSQL > Redis > Event bus) should drive your reliability investment priorities.

---

## 8. Security & Privacy

A few specific considerations beyond standard practice:

- **Tag data is potentially location-sensitive personal data.** Treat positions and hive membership as PII; encrypt at rest, restrict access logs, comply with whatever framework applies in your jurisdiction (GDPR, etc.)
- **Cross-user data isolation:** every query must scope by user/tenant. The Query API and Setup Service are the primary enforcement points; defence in depth via row-level security or tenant-scoped database connections is recommended
- **Permanent deletion must actually delete.** Auditing the purge process is worth doing — verify that purged data is unrecoverable from backups within a reasonable retention window. Regulatory frameworks often require this guarantee
- **Source phone identifiers** (if available from upstream) should be hashed/anonymised before storage — they're contributor data, not user data, and shouldn't be exposed via any user-facing path

---

## 9. Capacity Planning Notes

Rough sizing for context:

- **Position throughput:** 5 tags/hive × 6–20 reports/hour/tag (urban) = 30–100 events/hour/hive at peak. For 100K active hives at peak: ~3–10M events/hour, easily handled by a small Kafka cluster and a horizontally-scaled filter service.
- **TimescaleDB volume:** at 10M positions/hour during peak periods, ~1KB/row, that's ~10GB/hour of raw data. Hot retention of 120 days = ~30TB at sustained peak. Likely much lower in practice given the meaningful-change filter dropping stationary-tag noise. Plan for tiered storage and aggressive downsampling beyond the 120-day operational window.
- **Redis state:** ~5KB/hive in live state. 100K hives = 500MB. Fits in a small Redis instance.
- **PostgreSQL operational data:** tiny by comparison. A modest instance handles millions of hives.

Scale planning should focus on TimescaleDB and event bus throughput; everything else is comfortable headroom.

---

## 10. Implementation Phasing Suggestion

This is a substantial architecture. A phased build-out might look like:

### Phase 1 — Core Proximity Tracking (MVP)

Position ingestion + filter + evaluation + basic alerting. PostgreSQL + Redis + TimescaleDB. Single mobility profile, fixed thresholds. No wizard, no archive. Validates the core algorithm and data model end-to-end.

### Phase 2 — Configuration and Lifecycle

Add wizard, mobility profiles, smart defaults, 60-day lifecycle, archive, permanent deletion. The full lifecycle manager. This is where the user-facing feature becomes complete.

### Phase 3 — Polish and Operational Maturity

Recreation chains, archive UI, full observability, capacity scaling, multi-region (if needed), historical analytics views, position uncertainty modelling.

Splitting like this lets the algorithmic core be validated against real data before the full lifecycle complexity is built around it — and the architecture supports each phase being a meaningful, deployable increment rather than a big-bang launch.

---

## Appendix A — Mobility Profile Parameters

Reference table for the parameter values bundled by each mobility profile preset. These are starting points to tune with real data.

| Parameter | Stationary | Slow | Mobile | Fast |
|---|---|---|---|---|
| Fresh tier window | <30 min | <15 min | <5 min | <2 min |
| Recent tier window | 30 min – 4 hr | 15 min – 1 hr | 5–20 min | 2–10 min |
| Stale tier window | 4 – 24 hr | 1 – 6 hr | 20 min – 2 hr | 10 – 30 min |
| Lost contact threshold | >24 hr | >6 hr | >2 hr | >30 min |
| Meaningful-change filter | 2–3 m | 5–10 m | 15–25 m | 30–50 m |
| Default distance threshold | 50 m | 100 m | 200 m | 500 m+ |
| Hysteresis (clear at) | 90% | 85% | 80% | 75% |
| Confirmation requirement | 1 fresh | 1 fresh | 2 fresh | 2 fresh |

---

## Appendix B — Hive Lifecycle States

Summary of the three hive lifecycle phases:

| Phase | Status | Duration | Behaviour |
|---|---|---|---|
| Active | `active` | Up to 60 days from creation | Evaluating, alerting, visible in main hive list. Tags in-use. |
| Archived | `archived` | 60 days from expiry/deletion | No evaluation/alerts. Tags released. Visible in archive view with full history. |
| Purged | `purged` | Permanent | Data permanently removed. Tombstone retained for chain integrity. |

### Action Outcomes

| Action | From State | Result |
|---|---|---|
| Delete hive | Active | Hive moves to archive (60-day retention starts) |
| Auto-expiry | Active | Hive moves to archive (60-day retention starts) |
| Permanently delete | Active or Archived | Hive purged immediately, no recovery |
| Auto-purge | Archived (after 60d) | Hive purged automatically |

---

## Appendix C — Component Responsibility Matrix

Quick-reference summary of which component reads/writes which store.

| Component | PostgreSQL | TimescaleDB | Redis | Event Bus |
|---|---|---|---|---|
| Position Ingestion | Read | — | Read (cache) | Publish |
| Position Filter | Read | Write | Read/Write | Subscribe/Publish |
| Evaluation Engine | Read | Write | Read/Write | Subscribe/Publish |
| Periodic Sweeper | Read | — | Read | Publish |
| Lifecycle Manager | Read/Write | Write | Write (clear) | Subscribe/Publish |
| Setup Service | Read | Read | — | — |
| Alert Dispatch | — | — | — | Subscribe |
| Query API | Read | Read | Read | — |

---

## Summary

The architecture is eight logical components sharing three data stores through an event bus, with periodic sweepers handling time-based transitions. PostgreSQL holds operational truth, TimescaleDB holds historical record, Redis holds live state for low-latency reads and writes. Event-driven processing with periodic sweeps for staleness and lifecycle transitions. Strong invariants (single-hive membership, immutable history) enforced at the database layer. Clear degradation modes and observability story.

This spec should be enough for a technical team to start making implementation decisions — picking specific managed services in your cloud, choosing language/framework for each component, designing the API contracts between them.
