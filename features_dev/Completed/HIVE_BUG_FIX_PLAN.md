# HIVE Bug Fix Plan — May 28, 2026

## Summary

Two critical bugs identified in v1.1 implementation after testing with 3-tag hive (tags 283/087/342, where 283 was driven 300km away):

1. **Bug 1 — Motion State Oscillation**: System cycles STATIONARY → PRE_TRANSIT → STATIONARY every 6-12 minutes, firing fresh breach alerts each cycle
2. **Bug 2 — Outlier Mis-Attribution**: Different tags identified as outlier when 283 should consistently be the outlier

## Root Cause Analysis

### Bug 2 — Outlier Mis-Attribution (CONFIRMED)

**File**: `gps-tracker/backend/app/services/hive_service.py`  
**Lines**: 87-89

**Current Code**:
```python
# Outlier = tag with the highest max pairwise distance
outlier = max(pair_distances, key=lambda t: max(pair_distances[t]) if pair_distances[t] else 0.0)
```

**Problem**: Selects tag with **maximum distance** to any other tag, NOT the tag with the **most breaching pairs** as per spec.

**Spec Requirement** (Section 2.4):
> Identifies outlier tag (tag with most breaching pairs)

**Example from Test Scenario**:
- Tag 283 ↔ 087: ~328 km (BREACH)
- Tag 283 ↔ 342: ~328 km (BREACH)  
- Tag 087 ↔ 342: ~10 m (OK)

**Expected breaching_pair_counts**:
- 283: 2 breaching pairs
- 087: 1 breaching pair
- 342: 1 breaching pair

**Expected outlier**: 283

**Actual behavior**: Algorithm picks whichever tag happens to have the single highest distance to another tag — could be any of the three depending on measurement variance.

### Bug 1 — Motion State Oscillation (LIKELY ROOT CAUSE)

**File**: `gps-tracker/backend/app/services/hive_motion.py`  
**Lines**: 316-320

**Current Code**:
```python
elif total_motion_s >= IN_TRANSIT_CONFIRM_SECONDS and coherence >= COHERENCE_THRESHOLD:
    new_state = HiveMotionState.IN_TRANSIT.value
    live.pending_motion_change_since = None
```

**Problem**: Transition from PRE_TRANSIT → IN_TRANSIT requires BOTH:
- 2 minutes of sustained motion, AND
- Coherence ≥ 60%

**Scenario**: When tag 283 is 300km away:
1. System detects diameter > threshold → enters PRE_TRANSIT
2. Centroid jumps around as fresh_positions changes (283 drops to STALE, centroid recalculates from 087/342 only)
3. Individual tags (087 and 342) are stationary (speed ~0 km/h)
4. Centroid appears to move rapidly as composition changes
5. Coherence score = 0% (no tags moving coherently with jumping centroid)
6. After 30 seconds in PRE_TRANSIT without coherence, system returns to STATIONARY
7. Fresh proximity evaluation runs → immediate breach alert
8. Cycle repeats

**Additional Factor**: Centroid computed from FRESH tags only. When 283 becomes STALE (after 15 min for Mobile profile), centroid snaps to average of 087/342. When 283 receives a fresh GPS report, it re-enters FRESH tier and centroid jumps back. This compositional churn causes apparent centroid velocity even when all tags are physically stationary.

## Fixes Required

### Fix #1 — Correct Outlier Algorithm

**File**: `gps-tracker/backend/app/services/hive_service.py`  
**Function**: `pairwise_max_distance`  
**Lines**: 64-89

**Change**:
```python
def pairwise_max_distance(positions: List[Tuple[str, float, float]]) -> Tuple[Optional[float], Optional[str]]:
    """
    Given a list of (tag_id, lat, lng), compute the maximum pairwise distance
    (group diameter) and the tag_id that is the outlier (has the most breaching
    pairs).

    Returns (diameter_m, outlier_tag_id). If fewer than 2 positions, returns
    (None, None).
    """
    if len(positions) < 2:
        return None, None

    max_dist = 0.0
    pair_distances: Dict[str, List[float]] = {tid: [] for tid, _, _ in positions}

    for i, (tid_a, lat_a, lon_a) in enumerate(positions):
        for tid_b, lat_b, lon_b in positions[i + 1:]:
            d = haversine_m(lat_a, lon_a, lat_b, lon_b)
            pair_distances[tid_a].append(d)
            pair_distances[tid_b].append(d)
            if d > max_dist:
                max_dist = d

    # Outlier = tag with the most breaching pair relationships (spec §2.4).
    # Count how many distances for each tag exceed the threshold.
    # Note: threshold comes from the caller context (cfg.distance_threshold_m),
    # but we don't have it here. Use max_dist as a proxy: any tag involved in
    # the max-dist pair is definitely breaching. For proper counting, we need
    # to pass threshold or move this function.
    # 
    # INTERIM FIX: Use a heuristic — tag with highest SUM of distances is
    # likely the outlier (far from the group). This is better than max()
    # but still not spec-compliant. Proper fix requires threshold parameter.
    outlier = max(pair_distances, key=lambda t: sum(pair_distances[t]))
    return max_dist, outlier
```

**BETTER FIX** (requires threshold parameter):
```python
def pairwise_max_distance_and_outlier(
    positions: List[Tuple[str, float, float]],
    threshold_m: float
) -> Tuple[Optional[float], Optional[str]]:
    """
    Compute max pairwise distance (diameter) and identify the outlier tag
    (tag participating in the most breaching pairs per spec §2.4).
    """
    if len(positions) < 2:
        return None, None

    max_dist = 0.0
    breaching_pair_counts: Dict[str, int] = {tid: 0 for tid, _, _ in positions}

    for i, (tid_a, lat_a, lon_a) in enumerate(positions):
        for tid_b, lat_b, lon_b in positions[i + 1:]:
            d = haversine_m(lat_a, lon_a, lat_b, lon_b)
            if d > max_dist:
                max_dist = d
            if d > threshold_m:
                breaching_pair_counts[tid_a] += 1
                breaching_pair_counts[tid_b] += 1

    # Outlier = tag with most breaching pairs
    outlier = max(breaching_pair_counts, key=breaching_pair_counts.get) \
        if any(breaching_pair_counts.values()) else None

    return max_dist, outlier
```

**Action**: Implement BETTER FIX — refactor function to accept threshold, update all call sites.

### Fix #2 — Add Diagnostic Logging

**File**: `gps-tracker/backend/app/services/hive_service.py`  
**Function**: `evaluate_hive`

**Add structured logging** at end of evaluation cycle (before return) to capture:
- Motion state before/after
- Centroid position, speed, bearing
- Tag velocities + coherence score
- Breaching pair counts per tag
- Selected outlier

**Format** (per verification guide Section 5):
```python
log.info(
    "hive_evaluation",
    extra={
        "hive_id": hive_id,
        "evaluated_at": now.isoformat(),
        "motion_state_before": motion_decision.previous_state,
        "motion_state_after": motion_decision.state,
        "centroid": {
            "lat": centroid_v.centroid_lat if centroid_v else None,
            "lng": centroid_v.centroid_lng if centroid_v else None,
            "speed_kmh": centroid_v.speed_kmh if centroid_v else 0.0,
            "bearing_deg": centroid_v.bearing_deg if centroid_v else None,
            "fresh_tag_count": len(fresh_positions),
        },
        "coherence": {
            "score": coherence,
            "threshold": hive_motion.COHERENCE_THRESHOLD,
            "tags_with_velocity": len(tag_velocities),
        },
        "proximity": {
            "diameter_m": diameter_m,
            "threshold_m": cfg.distance_threshold_m,
            "outlier": outlier_id,
            "fresh_count": len(fresh_positions),
            "recent_count": len(fresh_recent_positions) - len(fresh_positions),
        },
        "alert_state_before": prev_state,
        "alert_state_after": new_state,
    }
)
```

### Fix #3 — Strengthen Centroid Stability (Optional Enhancement)

**Not required for MVP**, but recommended to reduce centroid jitter:

**Option A**: Use FRESH + RECENT tags for centroid computation (not just FRESH). This prevents compositional snapping when a tag transitions FRESH → RECENT.

**Option B**: Add hysteresis to freshness tier transitions (e.g., tag must be stale for 2+ consecutive evaluations before dropping from centroid). This dampens noise from GPS report timing variance.

**Decision**: Defer to post-MVP unless Bug 1 persists after Fix #1.

## Implementation Steps

1. **Fix outlier algorithm** — refactor `pairwise_max_distance` to accept threshold and count breaching pairs
2. **Update all call sites** — pass `cfg.distance_threshold_m` to the refactored function
3. **Add diagnostic logging** — structured log at end of `evaluate_hive`
4. **Write unit tests**:
   - Test outlier algorithm with 3-tag scenario (283/087/342)
   - Test coherence scoring with stationary tags + moving centroid
5. **Deploy to pinplot.me** — capture logs from next test run
6. **Validate** — confirm outlier is stable and motion state doesn't oscillate

## Success Criteria

- **Bug 2 Fixed**: Outlier consistently identified as tag 283 across all breach events when 283 is 300km away and 087/342 are together
- **Bug 1 Fixed**: No motion state oscillation when tags are stationary. System remains in STATIONARY state and fires one breach alert, not repeated alerts every 6-12 minutes.
- **Diagnostic Data**: Structured logs capture full evaluation state for future debugging

## Rollback Plan

If bugs persist or new issues surface:
1. Revert commits
2. Review diagnostic logs to identify next failure mode
3. Iterate on fix

No schema changes required — safe to deploy/rollback at will.
