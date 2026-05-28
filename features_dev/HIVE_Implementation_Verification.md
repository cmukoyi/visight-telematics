# HIVE — Implementation Verification Guide

**Purpose:** Verify that the v1.1 motion-aware implementation conforms to the architecture specification, with specific focus on two bugs surfaced by recent testing.

**Audience:** Engineering team implementing or maintaining HIVE.

**Reference spec:** `HIVE_Architecture_Specification_v1.1.md`, particularly Section 11 (Motion Awareness) and Section 2.4 (Hive Evaluation Engine).

---

## Bugs Under Investigation

Test scenario: a 3-tag hive (`PB708-283`, `PB708-087`, `PB708-342`) was created with all tags physically together. Tag `283` was then driven approximately 300 km away. Tags `087` and `342` remained stationary at the original location.

**Bug 1 — Motion state oscillation.** The system rapidly cycles between `STATIONARY` and `IN_TRANSIT` states, firing fresh breach alerts on each return to `STATIONARY`. Activity log shows the pattern `MOTION_STATE_CHANGED → RESOLVED_BY_TRANSIT → MOTION_STATE_CHANGED → Breach confirmed` repeating every 6–12 minutes.

**Bug 2 — Outlier mis-attribution.** The system identifies different tags as the outlier across successive breach events (`342`, `283`, `087` all appearing as outliers at different times), when `283` should consistently be identified as the outlier across all breach events.

---

## Section 1 — Centroid Computation (Spec Section 11.3)

### What the spec says

> The centroid is the geometric mean of all **Fresh-tier** tag positions. **Recent-tier tags are excluded** from centroid computation because their staleness undermines the centroid's accuracy.

### Check 1.1 — Verify centroid is computed from Fresh-tier tags only

**Look for** the centroid computation function in the Motion Detection Service. It should:

- Accept the list of all tags in the hive
- Filter to only those whose `freshness_tier == FRESH`
- Return early or return null if fewer than 2 Fresh tags remain
- Compute the geometric mean (average lat / average lng) of only the filtered set

**Anti-pattern to flag:** computing centroid from `all member tags` regardless of freshness, or filtering by `last_seen` time directly rather than using the `freshness_tier` classification.

**How to verify:**

Write a unit test with 3 tags where:
- Tag A: position (0, 0), freshness = FRESH
- Tag B: position (10, 10), freshness = FRESH
- Tag C: position (1000, 1000), freshness = STALE (anything older than the Recent window)

Expected centroid: (5, 5) — average of A and B only, C excluded.

If the test returns approximately (336, 336), the implementation is including Stale tags. **Fail.**

### Check 1.2 — Centroid velocity computation window

**What the spec says:**

> Centroid velocity is the rate of change of the centroid position over a rolling 5-minute window.

**Look for** the centroid velocity calculation. It should:

- Compare the current centroid position against the centroid position from ~5 minutes ago
- Compute speed in km/h and bearing in degrees
- Use great-circle distance (Haversine) for the speed calculation, not Euclidean

**Anti-pattern to flag:** using shorter windows (e.g. between the last two evaluations) that might be only seconds apart and produce wildly inflated speed values; using Euclidean distance on lat/lng pairs (this is wrong by orders of magnitude at typical latitudes).

**How to verify:**

Write a unit test where the centroid has moved from (51.000, 0.000) to (51.045, 0.000) over exactly 5 minutes. Expected speed: ~60 km/h (5 km north in 5 minutes). Expected bearing: 0° (due north). If you get values significantly off, the calculation is wrong.

---

## Section 2 — Group Motion Coherence Check (Spec Section 11.4)

This is the most likely site of Bug 1. The coherence check is what prevents the system from declaring "in transit" when only one tag is moving.

### What the spec says

> For each tag with at least 2 reports in the last 10 minutes, compute its individual velocity vector (speed and bearing) from its two most recent positions.
>
> A tag is **motion-coherent** with the centroid if both:
> - Its speed is within profile tolerance of the centroid speed
> - Its bearing is within profile tolerance of the centroid bearing
>
> A hive shows "coherent group motion" when **≥60% of tags with computable velocities are motion-coherent**.

### Check 2.1 — Verify the coherence check is implemented and called

**Look for** a function with a name like `is_coherent_motion()`, `check_group_coherence()`, or similar in the Motion Detection Service.

**Critical**: verify this function is called as a gate condition before transitioning to `IN_TRANSIT`. The state transition from `PRE_TRANSIT → IN_TRANSIT` MUST require this function to return `true`.

**Anti-pattern to flag:**

- Function exists but is only used for logging / metrics, not as a gate
- Function is called but its return value is not used in the state transition decision
- State transitions to `IN_TRANSIT` based solely on centroid speed exceeding threshold, without checking coherence

**How to verify:**

Trace through the code path for `PRE_TRANSIT → IN_TRANSIT`. There must be a conditional that:

```
if (centroid_speed > profile.motion_threshold)
    AND (coherence_percentage >= 0.60)
    AND (sustained_for >= 2_minutes):
    transition to IN_TRANSIT
else:
    remain in PRE_TRANSIT or return to STATIONARY
```

If the `coherence_percentage` check is absent or commented out, **this is the root cause of Bug 1.**

### Check 2.2 — Verify per-tag velocity computation

**Look for** the per-tag velocity calculation. For each tag, it should:

- Find the two most recent positions for that tag within the last 10 minutes
- Compute speed (great-circle distance ÷ time delta)
- Compute bearing (great-circle bearing between the two points)
- Return `null` / unavailable if the tag has fewer than 2 reports in the window

**How to verify:**

Unit test with a tag that has reports at:
- (51.000, 0.000) at time T-8 minutes
- (51.045, 0.000) at time T (now)

Expected speed: ~60 km/h, bearing 0°. Same calculation as Check 1.2 but per-tag.

Then test with a tag that has only one report. Function should return `null` / unavailable, not throw and not return a default value.

### Check 2.3 — Verify the coherence comparison uses both speed AND bearing

**Critical for Bug 1.** The spec requires BOTH speed and bearing to be within tolerance for a tag to be coherent. A common implementation bug is to only check speed magnitude.

**Look for** the per-tag coherence comparison. It should:

```
tag_is_coherent =
    abs(tag.speed - centroid.speed) <= profile.coherence_speed_tolerance
    AND
    angular_difference(tag.bearing, centroid.bearing) <= profile.coherence_bearing_tolerance
```

**Anti-pattern to flag:**

- Only the speed check is implemented
- Bearing difference uses simple subtraction (incorrect at the 0°/360° boundary — must use angular difference)
- Speed comparison uses absolute speed rather than signed difference (a tag moving at 0 km/h and a centroid at 60 km/h must register as 60 km/h apart, not as 0 difference)

**How to verify:**

Set up the test scenario in code:
- Centroid velocity: 60 km/h, bearing 90° (heading east)
- Tag A velocity: 60 km/h, bearing 90° (matches centroid) → should be coherent
- Tag B velocity: 0 km/h, bearing 0° (stationary) → should NOT be coherent
- Tag C velocity: 60 km/h, bearing 270° (heading west, opposite direction) → should NOT be coherent

Expected coherence percentages:
- {A, B, C}: 1 of 3 coherent = 33% → coherent group motion = `false`
- {A, A, A}: 3 of 3 = 100% → coherent group motion = `true`
- {A, A, B}: 2 of 3 = 67% → coherent group motion = `true` (≥60%)

If Tag B or Tag C registers as coherent, the implementation is bug. If the function returns `true` for the {A, B, C} case (the test scenario), Bug 1 is confirmed.

### Check 2.4 — Verify the 60% threshold is correctly applied

**Look for** the final coherence decision. After computing per-tag coherence, the function should:

```
coherent_tags = count of tags where tag_is_coherent == true
total_evaluable_tags = count of tags with computable velocities
coherence_percentage = coherent_tags / total_evaluable_tags
return coherence_percentage >= 0.60
```

**Anti-pattern to flag:**

- The threshold is implemented as `> 0.60` instead of `>= 0.60` (edge case for exactly 60%)
- The denominator is `count of all member tags` rather than `count of tags with computable velocities` (this would lower the percentage incorrectly for hives with sparse data)
- The threshold value (0.60) is hardcoded in multiple places rather than centralised — making it fragile

---

## Section 3 — Outlier Identification (Spec Section 2.4)

This is the site of Bug 2.

### What the spec says

> Identifies outlier tag (tag with most breaching pairs)

### Check 3.1 — Verify the outlier algorithm

**Look for** the outlier identification function in the Hive Evaluation Engine.

The correct algorithm is:

```
For each pair of tags (A, B) where both are Fresh or Recent:
    if distance(A, B) > threshold:
        record pair (A, B) as breaching

For each tag T in the hive:
    breaching_pair_count[T] = number of breaching pairs T participates in

outlier = tag with the highest breaching_pair_count
```

**Anti-pattern to flag** (any of these will cause Bug 2):

- Outlier is selected as "the tag with the largest distance from the centroid" — this is a different metric and will pick whichever tag happens to be furthest from a possibly-moving centroid
- Outlier is selected as "the first tag whose pair distance exceeds threshold during iteration" — depends on iteration order
- Outlier is selected as "the tag whose most recent report triggered the breach detection" — depends on report timing
- Outlier is selected randomly or via implementation detail (set ordering, dictionary iteration) — depends on language/runtime

### Check 3.2 — Verify with test scenario

Write a unit test with 3 tags:
- Tag 283: position (50.6682, -4.7552) — Belgium-ish
- Tag 087: position (51.3759, -0.1951) — UK
- Tag 342: position (51.3758, -0.1952) — UK (very close to 087)
- Threshold: 1000 m

Expected pairwise distances (approximate):
- 283 ↔ 087: ~328,000 m → breach
- 283 ↔ 342: ~328,000 m → breach
- 087 ↔ 342: ~10 m → no breach

Expected breaching_pair_counts:
- 283: 2
- 087: 1
- 342: 1

Expected outlier: **283** (highest count)

If the function returns `087` or `342`, **Bug 2 is confirmed.**

### Check 3.3 — Tiebreaker behaviour

In the rare case of a tie in breaching_pair_count, the outlier should be deterministic. Pick a tiebreaker (e.g. alphabetical tag_id, or first by `tag_id` ordering) and document it. The choice doesn't matter much but should be consistent so the same data always produces the same outlier.

**Anti-pattern to flag:** non-deterministic tiebreakers (returning whichever the iteration found first, dependent on hash-set ordering, etc.) — these can cause apparent outlier-churn even when the underlying counts are stable.

---

## Section 4 — Motion State Machine Transitions (Spec Section 11.2)

### Check 4.1 — Verify all required state transitions

The state machine has the following transitions. Each should be implemented and reachable:

```
STATIONARY → PRE_TRANSIT:
    Triggered by: centroid_speed > profile.motion_threshold for ≥30 seconds

PRE_TRANSIT → IN_TRANSIT:
    Triggered by:
        time_in_pre_transit >= 2 minutes
        AND coherent_group_motion == true (Check 2.x)
    Side effect: any active BREACHING alert is resolved with RESOLVED_BY_TRANSIT

PRE_TRANSIT → STATIONARY:
    Triggered by: centroid_speed < profile.motion_threshold for ≥30 seconds
                  before reaching the IN_TRANSIT confirmation
    Side effect: run normal proximity evaluation, resume alerting

IN_TRANSIT → SETTLING:
    Triggered by: centroid_speed < profile.motion_threshold for ≥3 minutes

SETTLING → STATIONARY:
    Triggered by: continued stability for ≥10 minutes total post-stop (Slow/Mobile)
    Side effect: run normal proximity evaluation, fire alert if breach detected

SETTLING → IN_TRANSIT:
    Triggered by: motion re-detected before settling completes
```

**Critical check:** the `PRE_TRANSIT → IN_TRANSIT` transition MUST be gated on the coherence check. This is the most likely source of Bug 1.

### Check 4.2 — Verify suppression behaviour per state

For each motion state, verify the Hive Evaluation Engine's evaluation branch:

```
if motion_state == STATIONARY:
    Run full proximity evaluation, allow all alert transitions

if motion_state == PRE_TRANSIT:
    Suppress all proximity alerts
    Record evaluation with motion_state annotated
    Do not transition alert state machine

if motion_state == IN_TRANSIT:
    Suppress all proximity alerts
    Record evaluation with motion_state annotated
    Do not transition alert state machine

if motion_state == SETTLING:
    Suppress all evaluation (display only)
    Do not transition alert state machine
```

**Anti-pattern to flag:**

- Alert state transitions still happening during PRE_TRANSIT or IN_TRANSIT states
- The "active breach resolved" side-effect of entering PRE_TRANSIT not being applied — would cause alerts to persist across motion-state changes when they should clear
- Settling allowing fresh breach alerts to fire — would cause spurious alerts during the settling buffer

### Check 4.3 — Verify motion state persistence

Motion state changes should be:
- Persisted to live state (Redis) as `motion_state` field on the hive
- Emitted as `MOTION_STATE_CHANGED` events to `hive_events` historical store
- Published to the `hive.motion_state_changed` event topic for downstream consumers

---

## Section 5 — Diagnostic Logging for Investigation

If the checks above don't immediately reveal the bug, add structured logging at key decision points to capture a trace of one evaluation cycle.

### Recommended trace points

For each evaluation, log at INFO or DEBUG level (single structured log line per evaluation):

```
{
  "event": "hive_evaluation",
  "hive_id": "...",
  "evaluated_at": "...",
  "motion_state_before": "STATIONARY",

  "tags": [
    {
      "tag_id": "PB708-283",
      "freshness_tier": "FRESH",
      "last_seen_seconds_ago": 240,
      "position": { "lat": 50.6682, "lng": -4.7552 },
      "velocity": { "speed_kmh": 0.2, "bearing_deg": null },
      "velocity_computable": true,
      "is_motion_coherent_with_centroid": false
    },
    ...
  ],

  "centroid": {
    "lat": 51.05,
    "lng": -2.5,
    "computed_from_tag_count": 3,
    "fresh_tags_included": ["PB708-283", "PB708-087", "PB708-342"]
  },

  "centroid_velocity": {
    "speed_kmh": 145.2,
    "bearing_deg": 270,
    "computed_over_seconds": 300
  },

  "coherence": {
    "tags_with_computable_velocity": 3,
    "tags_coherent": 0,
    "percentage": 0.0,
    "threshold": 0.6,
    "result": false
  },

  "proximity": {
    "diameter_m": 328448,
    "threshold_m": 1000,
    "breaching_pairs": [
      ["PB708-283", "PB708-087"],
      ["PB708-283", "PB708-342"]
    ],
    "breaching_pair_counts": {
      "PB708-283": 2,
      "PB708-087": 1,
      "PB708-342": 1
    },
    "selected_outlier": "PB708-283"
  },

  "motion_state_after": "STATIONARY",
  "alert_state_before": "BREACHING",
  "alert_state_after": "BREACHING",
  "alert_event_emitted": null
}
```

With this format, one trace per evaluation tells the full story. Capture 5–10 consecutive evaluations covering one full motion-state oscillation cycle in production. The bugs should be visible immediately.

### What to look for in the trace

**For Bug 1 (motion state oscillation):**
- Is `centroid.fresh_tags_included` changing between evaluations? (Indicates freshness-composition jumping, expected behaviour)
- Is `centroid_velocity.speed_kmh` high (>50 km/h) while individual tags are at low speeds? (Centroid jumping problem)
- Is `coherence.result` returning `false`? (If yes, motion detection should NOT fire — but it is, so the gate is broken)
- Is `coherence.result` returning `true` despite individual tag speeds being inconsistent? (Coherence calculation broken)

**For Bug 2 (outlier mis-attribution):**
- Does `proximity.breaching_pair_counts` show the expected counts (2 for the truly separated tag, 1 for each of the together tags)?
- Does `proximity.selected_outlier` match the tag with the highest count?
- If the counts are right but the selected outlier is wrong, the selection logic is broken
- If the counts themselves are wrong, the pair-counting logic is broken

---

## Section 6 — Suggested Verification Sequence

To efficiently isolate the bugs, run checks in this order:

**Step 1 — Quick spec compliance review (1–2 hours):**
- Check 2.1 (coherence check called as a gate)
- Check 3.1 (outlier algorithm)

These two alone, if confirmed compliant, should resolve both bugs. If non-compliant, the fix path is clear and probably small.

**Step 2 — Detailed unit tests (half a day):**
- Run Checks 1.1, 2.3, 3.2 as automated unit tests

This catches subtle calculation errors in centroid, coherence, and outlier identification with specific expected values.

**Step 3 — Production logging trace (one test run):**
- Add structured logging from Section 5
- Re-run the original test scenario (3 tags, one taken on a long trip)
- Capture 10+ consecutive evaluation traces
- Review against expected values

If steps 1 and 2 pass but the bugs persist in production, step 3 will reveal what's actually happening in the wild — including issues that unit tests might miss (timing, persistence, eventual consistency).

---

## Section 7 — Common Implementation Pitfalls

A few patterns that commonly cause the bugs we've seen, included as a reference:

**Centroid drift from stale data inclusion.** If freshness filtering isn't strict, stale positions remain in the centroid calculation indefinitely, anchoring the centroid in old locations even as new positions arrive. Symptom: centroid that "lags" behind the actual moving tags.

**Coherence check used for logging only.** A common code-review oversight is implementing a function but not wiring it into the decision logic. The function gets called, the result gets logged, but the state transition uses different logic. Look specifically for: `if (centroid_moving) { transition() }` rather than `if (centroid_moving && coherent) { transition() }`.

**Outlier selection by "max distance" rather than "most breaching pairs."** These produce identical results in many cases, which can mask the bug for a long time. They differ exactly when one tag is far from a group of together tags — the case we care most about. The distinction is: max-distance picks the tag furthest from some reference (centroid? closest neighbour?), while most-breaching-pairs counts breached relationships.

**Iteration-order-dependent outlier selection.** Code like `for tag in tags: if tag.has_breaching_pair: return tag` will return whichever tag happens to be first in iteration. In modern languages with stable iteration order, this might consistently return the same tag (which can mask the bug). In languages with unstable iteration (some hash-set implementations), it produces apparent churn — exactly matching Bug 2's symptoms.

**Bearing arithmetic without angular wrap.** Computing `abs(bearing_a - bearing_b)` directly returns `350` for the difference between `5°` and `355°`, when the actual angular difference is `10°`. Coherence checks comparing bearings must use proper angular subtraction.

**Centroid velocity computed from too-short windows.** If centroid velocity uses "since last evaluation" (could be seconds) rather than a 5-minute rolling window, tiny centroid jitter from freshness changes produces enormous apparent speeds. The spec requires a 5-minute window for stability.

---

## Section 8 — What To Report Back

After running the checks, please report:

**For each check (1.1, 1.2, 2.1, 2.2, 2.3, 2.4, 3.1, 3.2, 3.3, 4.1, 4.2, 4.3):**
- Pass / Fail / Not applicable
- If Fail: what's actually being done vs. what the spec says

**Summary diagnosis:**
- Which bug(s) the failures explain
- Whether the bugs are pure implementation issues (spec is correct, code is wrong) or whether the spec itself has a gap

**Trace data from Section 5** if Steps 1 and 2 don't fully resolve the questions.

This will allow us to decide between:
- (a) Implementation-only fix — no spec changes needed
- (b) Spec clarification — spec wording is ambiguous, needs to be tightened
- (c) Genuine design refinement — spec is missing a needed behaviour

---

*End of verification guide*
