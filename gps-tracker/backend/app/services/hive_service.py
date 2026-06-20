"""HIVE Evaluation Service.

Implements:
- Haversine distance computation
- Freshness tier classification
- Pairwise max-distance (group diameter)
- Outlier identification
- Alert state machine (OK → BREACH_PENDING → BREACHING → RESOLVING → OK)
- Periodic sweeper (run as background thread)
"""
from __future__ import annotations

import json
import logging
import math
import threading
import time
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Tuple

from sqlalchemy.orm import Session

from app.database import SessionLocal
from app.models import (
    BLETag,
    Hive,
    HiveAlertState,
    HiveConfigVersion,
    HiveEvaluation,
    HiveEvent,
    HiveLiveState,
    HiveMotionState,
    HiveStatus,
    HiveTagMembership,
)
from app.services import hive_motion

log = logging.getLogger(__name__)

UTC = timezone.utc

# Re-notify the group every N hours while a hive remains in BREACHING state.
# Default 24h. Override with env HIVE_BREACH_RENOTIFY_HOURS.
import os as _os
HIVE_BREACH_RENOTIFY_HOURS = float(_os.getenv("HIVE_BREACH_RENOTIFY_HOURS", "24"))

# Duration-based breach persistence thresholds (v1.2 confirmation fix).
# A breach must persist for at least T_PERSIST_MINUTES AND T_PERSIST_EVALS
# to confirm, and must be backed by fresh evidence (not a stale snapshot).
T_PERSIST_MINUTES = float(_os.getenv("HIVE_PERSIST_MINUTES", "6"))
T_PERSIST_EVALS = int(_os.getenv("HIVE_PERSIST_EVALS", "3"))

# ──────────────────────────────────────────────────────────────────────────────
# Geometry helpers
# ──────────────────────────────────────────────────────────────────────────────

_EARTH_R = 6_371_000.0  # metres


def haversine_m(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Return distance in metres between two WGS-84 coordinates."""
    φ1, φ2 = math.radians(lat1), math.radians(lat2)
    Δφ = math.radians(lat2 - lat1)
    Δλ = math.radians(lon2 - lon1)
    a = math.sin(Δφ / 2) ** 2 + math.cos(φ1) * math.cos(φ2) * math.sin(Δλ / 2) ** 2
    return 2 * _EARTH_R * math.asin(math.sqrt(a))


def pairwise_max_distance_and_outlier(
    positions: List[Tuple[str, float, float]],
    threshold_m: float
) -> Tuple[Optional[float], Optional[str]]:
    """
    Given a list of (tag_id, lat, lng), compute the maximum pairwise distance
    (group diameter) and the tag_id that is the outlier (per spec §2.4: the
    tag participating in the most breaching pairs).

    A breaching pair is one where distance > threshold_m.

    Returns (diameter_m, outlier_tag_id). If fewer than 2 positions, returns
    (None, None). If no pairs breach threshold, outlier is None.
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
            # Count breaching pairs: both tags in the pair get +1 if d > threshold
            if d > threshold_m:
                breaching_pair_counts[tid_a] += 1
                breaching_pair_counts[tid_b] += 1

    # Outlier = tag with the highest breaching_pair_count.
    # If no pairs breach, all counts are 0 → outlier is None.
    # Tiebreaker: first by tag_id alphabetically (deterministic).
    max_count = max(breaching_pair_counts.values())
    if max_count == 0:
        outlier = None
    else:
        candidates = [tid for tid, cnt in breaching_pair_counts.items() if cnt == max_count]
        outlier = sorted(candidates)[0]  # alphabetical tiebreaker

    return max_dist, outlier


def _profile_coherence_window_s(profile: Optional[str]) -> int:
    """Per-profile temporal coherence window used by v1.2 evaluation."""
    p = (profile or "").strip().lower()
    if p == "stationary":
        return 30 * 60
    if p == "slow":
        return 10 * 60
    # default/mobile
    return 5 * 60


def pairwise_temporal_eval(
    positions: List[Tuple[str, float, float, datetime]],
    threshold_m: float,
    coherence_window_s: int,
) -> Tuple[
    Optional[float],  # display diameter (all candidate pairs)
    Optional[float],  # coherent diameter (only temporally coherent pairs)
    Optional[str],    # coherent outlier
    int,              # coherent_pair_count
    int,              # incoherent_pair_count
    Optional[float],  # max_pair_dt_s
    Dict[str, int],   # breaching_pair_counts
    str,              # outlier_selection_reason
    int,              # separated_tag_count (cluster-based)
    List[Dict[str, Any]],  # pairwise_detail
]:
    """Evaluate pairwise distances with a temporal coherence gate.

    v1.2 semantics:
    - display diameter is computed from all candidate pairs
    - coherent diameter/outlier are computed only from pairs where
      |observed_at(A) - observed_at(B)| <= coherence_window_s
    """
    if len(positions) < 2:
        return None, None, None, 0, 0, None, {}, "none", 0, []

    display_max = 0.0
    coherent_max: Optional[float] = None
    coherent_pair_count = 0
    incoherent_pair_count = 0
    max_pair_dt_s = 0.0
    breaching_pair_counts: Dict[str, int] = {tid: 0 for tid, _, _, _ in positions}
    pairwise_detail: List[Dict[str, Any]] = []
    coherent_tag_ids: set[str] = set()
    coherent_positions_by_tag: Dict[str, Tuple[float, float]] = {}
    coherent_close_neighbors: Dict[str, set[str]] = {str(tid): set() for tid, _, _, _ in positions}

    for i, (tid_a, lat_a, lon_a, ts_a) in enumerate(positions):
        for tid_b, lat_b, lon_b, ts_b in positions[i + 1:]:
            d = haversine_m(lat_a, lon_a, lat_b, lon_b)
            if d > display_max:
                display_max = d

            dt_s = abs((ts_a - ts_b).total_seconds())
            if dt_s > max_pair_dt_s:
                max_pair_dt_s = dt_s

            temporally_coherent = dt_s <= coherence_window_s
            breaching = temporally_coherent and d > threshold_m
            pairwise_detail.append({
                "tag_a": str(tid_a),
                "tag_b": str(tid_b),
                "distance_m": round(d, 3),
                "dt_seconds": round(dt_s, 3),
                "temporally_coherent": temporally_coherent,
                "breaching": breaching,
            })

            if temporally_coherent:
                coherent_pair_count += 1
                coherent_tag_ids.add(str(tid_a))
                coherent_tag_ids.add(str(tid_b))
                coherent_positions_by_tag[str(tid_a)] = (lat_a, lon_a)
                coherent_positions_by_tag[str(tid_b)] = (lat_b, lon_b)
                if d <= threshold_m:
                    coherent_close_neighbors[str(tid_a)].add(str(tid_b))
                    coherent_close_neighbors[str(tid_b)].add(str(tid_a))
                if coherent_max is None or d > coherent_max:
                    coherent_max = d
                if breaching:
                    breaching_pair_counts[tid_a] += 1
                    breaching_pair_counts[tid_b] += 1
            else:
                incoherent_pair_count += 1

    outlier = None
    outlier_selection_reason = "none"
    if coherent_pair_count > 0:
        max_count = max(breaching_pair_counts.values())
        if max_count > 0:
            candidates = [tid for tid, cnt in breaching_pair_counts.items() if cnt == max_count]
            if len(candidates) == 1:
                outlier = str(candidates[0])
                outlier_selection_reason = "most_breaching_pairs"
            else:
                centroid_source = [
                    coords for tid, coords in coherent_positions_by_tag.items()
                    if tid in coherent_tag_ids
                ]
                if centroid_source:
                    centroid_lat = sum(lat for lat, _ in centroid_source) / len(centroid_source)
                    centroid_lng = sum(lng for _, lng in centroid_source) / len(centroid_source)
                    dist_by_candidate: Dict[str, float] = {}
                    for tid in candidates:
                        coords = coherent_positions_by_tag.get(str(tid))
                        if not coords:
                            continue
                        lat, lng = coords
                        dist_by_candidate[str(tid)] = haversine_m(lat, lng, centroid_lat, centroid_lng)
                    if dist_by_candidate:
                        max_dist = max(dist_by_candidate.values())
                        distance_winners = [
                            tid for tid, dist in dist_by_candidate.items()
                            if dist == max_dist
                        ]
                        if len(distance_winners) == 1:
                            outlier = distance_winners[0]
                            outlier_selection_reason = "tiebreak_distance"
                        else:
                            outlier = sorted(distance_winners)[0]
                            outlier_selection_reason = "tiebreak_alphabetical"
                    else:
                        outlier = sorted(str(tid) for tid in candidates)[0]
                        outlier_selection_reason = "tiebreak_alphabetical"
                else:
                    outlier = sorted(str(tid) for tid in candidates)[0]
                    outlier_selection_reason = "tiebreak_alphabetical"

    # Fix 3 correction: separated-tag count is cluster-based, not the number of
    # non-zero breaching-pair entries (which double-counts both sides of a split).
    separated_tag_count = 0
    if coherent_tag_ids and coherent_positions_by_tag:
        unvisited = set(coherent_tag_ids)
        components: List[List[str]] = []
        while unvisited:
            seed = next(iter(unvisited))
            stack = [seed]
            component: List[str] = []
            while stack:
                cur = stack.pop()
                if cur not in unvisited:
                    continue
                unvisited.remove(cur)
                component.append(cur)
                for nbr in coherent_close_neighbors.get(cur, set()):
                    if nbr in unvisited:
                        stack.append(nbr)
            components.append(component)

        if components:
            # Deterministic main-cluster choice: largest component, then lexical.
            main_cluster = sorted(
                (sorted(comp) for comp in components),
                key=lambda comp: (-len(comp), comp),
            )[0]

            cluster_coords = [
                coherent_positions_by_tag[tid]
                for tid in main_cluster
                if tid in coherent_positions_by_tag
            ]
            if cluster_coords:
                cluster_centroid_lat = sum(lat for lat, _ in cluster_coords) / len(cluster_coords)
                cluster_centroid_lng = sum(lng for _, lng in cluster_coords) / len(cluster_coords)
                separated_tag_count = sum(
                    1
                    for tid in coherent_tag_ids
                    if tid in coherent_positions_by_tag
                    and haversine_m(
                        coherent_positions_by_tag[tid][0],
                        coherent_positions_by_tag[tid][1],
                        cluster_centroid_lat,
                        cluster_centroid_lng,
                    ) > threshold_m
                )

    return (
        display_max,
        coherent_max,
        outlier,
        coherent_pair_count,
        incoherent_pair_count,
        max_pair_dt_s,
        breaching_pair_counts,
        outlier_selection_reason,
        separated_tag_count,
        pairwise_detail,
    )


def _snapshot_fingerprint(positions: List[Tuple[str, float, float, datetime]]) -> Optional[str]:
    """Stable fingerprint of the position set feeding this evaluation."""
    payload = _positions_used_payload(positions)
    if not payload:
        return None
    return "|".join(f"{item['tag_id']}@{item['observed_at']}" for item in payload)


def _positions_used_payload(positions: List[Tuple[str, float, float, datetime]]) -> List[Dict[str, str]]:
    """Canonical JSON-safe representation of the position set used for evaluation."""
    payload: List[Dict[str, str]] = []
    for tid, _lat, _lng, ts in positions:
        ts_utc = ts if ts.tzinfo else ts.replace(tzinfo=UTC)
        payload.append({
            "tag_id": str(tid),
            "observed_at": ts_utc.astimezone(UTC).isoformat(),
        })
    payload.sort(key=lambda item: (item["tag_id"], item["observed_at"]))
    return payload


def _previous_snapshot_fingerprint(hive_id: str, db: Session) -> Optional[str]:
    """Read prior evaluation fingerprint from explicit positions_used or legacy metadata."""
    prev = (
        db.query(HiveEvaluation)
        .filter(HiveEvaluation.hive_id == hive_id)
        .order_by(HiveEvaluation.evaluated_at.desc())
        .first()
    )
    if not prev:
        return None
    if prev.positions_used:
        try:
            payload = json.loads(prev.positions_used)
        except Exception:
            payload = None
        if isinstance(payload, list) and payload:
            return "|".join(
                f"{item.get('tag_id')}@{item.get('observed_at')}"
                for item in payload
                if isinstance(item, dict) and item.get("tag_id") and item.get("observed_at")
            ) or None
    if not prev.freshness_composition:
        return None
    try:
        payload = json.loads(prev.freshness_composition)
    except Exception:
        return None
    meta = payload.get("meta") if isinstance(payload, dict) else None
    if isinstance(meta, dict):
        fp = meta.get("snapshot_fingerprint")
        return fp if isinstance(fp, str) and fp else None
    return None


# ──────────────────────────────────────────────────────────────────────────────
# Freshness tier
# ──────────────────────────────────────────────────────────────────────────────

def freshness_tier(last_seen: Optional[datetime], cfg: HiveConfigVersion) -> str:
    """Return 'fresh', 'recent', 'stale', or 'lost' for a tag."""
    if last_seen is None:
        return "lost"
    now = datetime.now(UTC)
    # Ensure tz-aware comparison
    if last_seen.tzinfo is None:
        last_seen = last_seen.replace(tzinfo=UTC)
    age_s = (now - last_seen).total_seconds()
    if age_s <= cfg.fresh_window_s:
        return "fresh"
    if age_s <= cfg.recent_window_s:
        return "recent"
    if age_s <= cfg.stale_window_s:
        return "stale"
    return "lost"


# ──────────────────────────────────────────────────────────────────────────────
# Evaluation engine
# ──────────────────────────────────────────────────────────────────────────────

def evaluate_hive(hive_id: str, db: Session) -> Optional[str]:
    """
    Run a full evaluation cycle for the given hive.

    Returns the new alert_state string, or None if the hive is not found /
    not active.
    """
    hive = db.query(Hive).filter(Hive.id == hive_id, Hive.status == "active").first()
    if not hive:
        return None

    cfg = _current_config(hive_id, db)
    if not cfg:
        return None

    live = _get_or_create_live_state(hive_id, db)
    now = datetime.now(UTC)

    # Settling period — suppress alerts
    settling = False
    if hive.settling_until:
        su = hive.settling_until
        if su.tzinfo is None:
            su = su.replace(tzinfo=UTC)
        settling = now < su

    # ── Load member tag positions ──────────────────────────────────────
    memberships = db.query(HiveTagMembership).filter(
        HiveTagMembership.hive_id == hive_id
    ).all()

    fresh_positions: List[Tuple[str, float, float]] = []
    fresh_recent_positions: List[Tuple[str, float, float]] = []
    candidate_positions: List[Tuple[str, float, float, datetime]] = []
    composition = {"fresh": 0, "recent": 0, "stale": 0, "lost": 0}

    for m in memberships:
        tag = db.query(BLETag).filter(BLETag.id == m.tag_id).first()
        if not tag:
            continue
        tier = freshness_tier(tag.last_seen, cfg)
        composition[tier] += 1
        if tag.latitude and tag.longitude and tag.last_seen:
            try:
                lat, lon = float(tag.latitude), float(tag.longitude)
            except (TypeError, ValueError):
                continue
            ts = tag.last_seen if tag.last_seen.tzinfo else tag.last_seen.replace(tzinfo=UTC)
            if tier in ("fresh", "recent", "stale"):
                candidate_positions.append((m.tag_id, lat, lon, ts))
            if tier in ("fresh", "recent"):
                fresh_recent_positions.append((m.tag_id, lat, lon))
            if tier == "fresh":
                fresh_positions.append((m.tag_id, lat, lon))

    # ── Compute diameter with v1.2 temporal coherence rules ───────────
    threshold_m = cfg.distance_threshold_m
    coherence_window_s = _profile_coherence_window_s(getattr(cfg, "mobility_profile", None))
    if len(candidate_positions) >= 2:
        (
            display_diameter_m,
            coherent_diameter_m,
            outlier_id,
            coherent_pair_count,
            incoherent_pair_count,
            max_pair_dt_s,
            breaching_pair_counts,
            outlier_selection_reason,
            separated_tag_count,
            pairwise_detail,
        ) = (
            pairwise_temporal_eval(candidate_positions, threshold_m, coherence_window_s)
        )
    else:
        display_diameter_m = None
        coherent_diameter_m = None
        outlier_id = None
        coherent_pair_count = 0
        incoherent_pair_count = 0
        max_pair_dt_s = None
        breaching_pair_counts = {}
        outlier_selection_reason = "none"
        separated_tag_count = 0
        pairwise_detail = []

    # Keep UI-facing diameter, but gate state transitions on coherent evidence.
    diameter_m = display_diameter_m

    snapshot_fp = _snapshot_fingerprint(candidate_positions)
    prev_snapshot_fp = _previous_snapshot_fingerprint(hive_id, db)
    stale_snapshot = bool(snapshot_fp and prev_snapshot_fp and snapshot_fp == prev_snapshot_fp)

    positions_used_payload = _positions_used_payload(candidate_positions)

    # No meaningful spread — clear outlier so UI doesn't flag a tag incorrectly
    if diameter_m is not None and diameter_m < cfg.meaningful_change_m:
        outlier_id = None
        outlier_selection_reason = "none"

    # JSON serialization guard: membership/tag ids can be UUID objects in this
    # process, so normalize map keys before persisting or emitting payloads.
    breaching_pair_counts_payload = {
        str(tag_id): int(count)
        for tag_id, count in (breaching_pair_counts or {}).items()
    }

    # ── Motion awareness (Phase 3, spec v1.1) ─────────────────────────
    # Roll each tag's velocity vector forward, derive centroid velocity over
    # the rolling anchor window, score group coherence, run the motion
    # state machine. Result gates the proximity branch below.
    tag_velocities: List[hive_motion.TagVelocity] = []
    for m in memberships:
        tag = db.query(BLETag).filter(BLETag.id == m.tag_id).first()
        if not tag:
            continue
        cur_lat = float(tag.latitude) if tag.latitude else None
        cur_lng = float(tag.longitude) if tag.longitude else None
        tv = hive_motion.update_tag_velocity(m, cur_lat, cur_lng, tag.last_seen, now)
        if tv is not None:
            tag_velocities.append(tv)

    centroid_now = hive_motion.compute_centroid(fresh_positions)
    centroid_v = None
    if centroid_now is not None:
        centroid_v = hive_motion.compute_centroid_velocity(
            centroid_now, now,
            live.centroid_anchor_lat, live.centroid_anchor_lng, live.centroid_anchor_at,
        )
    coherence = hive_motion.coherence_score(tag_velocities, centroid_v, cfg, now) \
        if centroid_v is not None else 0.0

    motion_decision = hive_motion.evaluate_motion_state(live, cfg, centroid_v, coherence, now)
    hive_motion.maybe_refresh_centroid_anchor(live, centroid_now, now)

    # ── Determine breach ──────────────────────────────────────────────
    threshold = cfg.distance_threshold_m
    prev_state = live.alert_state or "OK"
    new_state = prev_state
    confidence = None
    # v1.2: motion state is retained for diagnostics only and does not gate alerts.
    resolve_by_transit = False

    if settling or diameter_m is None:
        # Not enough data / still in creation-time settling window —
        # hold current OK / RESOLVING.
        new_state = "OK" if prev_state in ("OK", "BREACH_PENDING") else prev_state
    else:
        is_breaching = coherent_diameter_m is not None and coherent_diameter_m > threshold
        clear_threshold = threshold * (cfg.hysteresis_pct / 100.0)
        is_cleared = coherent_diameter_m is not None and coherent_diameter_m <= clear_threshold
        required_confirms = max(int(cfg.confirmation_count or 1), 2)

        # Confidence: high if we have ≥ confirmation_count fresh tags
        confidence = "high" if len(fresh_positions) >= required_confirms else "low"

        # Rule 2: stale snapshot cannot advance the breach state machine.
        can_advance_breach = not stale_snapshot
        can_advance_clear = not stale_snapshot

        if prev_state == "OK":
            if is_breaching and can_advance_breach:
                live.pending_breach_since = now
                # v1.2 duration-based persistence
                live.persistence_eval_count = 1
                live.persistence_snapshot_fp_at_start = snapshot_fp
                live.persistence_has_new_evidence = False
                live.consecutive_confirms = 1  # legacy field
                if confidence == "high" and 1 >= required_confirms:
                    new_state = "BREACHING"
                else:
                    # Low-confidence (stale GPS) or pending confirmation
                    # → surface as a Suspected Breach so the user sees it.
                    new_state = "BREACH_PENDING"

        elif prev_state == "BREACH_PENDING":
            # ─── v1.2 Duration-based persistence confirmation ────────────────
            # Replaces "two consecutive fixes from separated tag" with:
            #   1. Persistence duration: ≥T_PERSIST_MINUTES AND ≥T_PERSIST_EVALS
            #   2. Fresh evidence: at least one eval with new fingerprint
            #   3. No contradiction: breach still active
            
            if not is_breaching:
                # Fresh coherent data shows breach cleared → reset
                new_state = "OK"
                live.pending_breach_since = None
                live.persistence_eval_count = 0
                live.persistence_snapshot_fp_at_start = None
                live.persistence_has_new_evidence = False
                live.consecutive_confirms = 0  # legacy field
            
            elif can_advance_breach:
                # Breach still active and we have fresh (non-stale) evidence
                live.persistence_eval_count = (live.persistence_eval_count or 0) + 1
                
                # Track if new position data has arrived (not same frozen snapshot)
                if live.persistence_eval_count == 1:
                    # First evaluation in BREACH_PENDING → record starting fingerprint
                    live.persistence_snapshot_fp_at_start = snapshot_fp
                    live.persistence_has_new_evidence = False
                else:
                    # Subsequent evaluation → check if fingerprint differs
                    if snapshot_fp and snapshot_fp != live.persistence_snapshot_fp_at_start:
                        live.persistence_has_new_evidence = True
                
                # Calculate elapsed time since breach started
                elapsed_minutes = 0.0
                if live.pending_breach_since:
                    pending_since = live.pending_breach_since if live.pending_breach_since.tzinfo else live.pending_breach_since.replace(tzinfo=UTC)
                    elapsed_td = now - pending_since
                    elapsed_minutes = elapsed_td.total_seconds() / 60.0
                
                # Check both persistence conditions
                duration_met = (elapsed_minutes >= T_PERSIST_MINUTES and 
                               live.persistence_eval_count >= T_PERSIST_EVALS)
                
                fresh_evidence_guard = live.persistence_has_new_evidence
                
                # Confirm if both conditions satisfied
                if duration_met and fresh_evidence_guard:
                    new_state = "BREACHING"
                    log.info(
                        f"HIVE {hive_id}: BREACH_PENDING → BREACHING (duration-based persistence)",
                        extra={
                            "hive_id": hive_id,
                            "elapsed_minutes": round(elapsed_minutes, 2),
                            "eval_count": live.persistence_eval_count,
                            "has_new_evidence": live.persistence_has_new_evidence,
                            "persistence_rule": "v1.2_duration_based"
                        }
                    )
                
                # Legacy field for compatibility (not used in confirmation decision)
                live.consecutive_confirms = live.persistence_eval_count
            
            # else: stale snapshot → hold BREACH_PENDING without advancing
            # (can_advance_breach is False, so this block doesn't run)

        elif prev_state == "BREACHING":
            if is_cleared and can_advance_clear:
                new_state = "RESOLVING"
                live.pending_clear_since = now
            # else stays BREACHING

        elif prev_state == "RESOLVING":
            if not is_cleared:
                new_state = "BREACHING"  # dipped back over
                live.pending_clear_since = None
            elif can_advance_clear:
                # Require 1 cycle to confirm clear
                new_state = "OK"
                live.pending_clear_since = None
                live.consecutive_confirms = 0

    state_changed = new_state != prev_state
    alert_diameter_m = coherent_diameter_m if coherent_diameter_m is not None else diameter_m

    # ── Diagnostic logging (HIVE bug fix — May 2026) ──────────────────
    # Structured log capturing full evaluation state for debugging motion
    # oscillation (Bug 1) and outlier mis-attribution (Bug 2).
    log.info(
        f"HIVE evaluation: {hive_id}",
        extra={
            "hive_id": hive_id,
            "evaluated_at": now.isoformat(),
            "motion_state_before": motion_decision.previous_state,
            "motion_state_after": motion_decision.state,
            "motion_changed": motion_decision.changed,
            "suppress_proximity": motion_decision.suppress_proximity,
            "centroid": {
                "lat": centroid_v.centroid_lat if centroid_v else None,
                "lng": centroid_v.centroid_lng if centroid_v else None,
                "speed_kmh": round(centroid_v.speed_kmh, 2) if centroid_v else 0.0,
                "bearing_deg": centroid_v.bearing_deg if centroid_v else None,
                "fresh_tag_count": len(fresh_positions),
                "fresh_tags": [tid for tid, _, _ in fresh_positions],
            },
            "coherence": {
                "score": round(coherence, 3),
                "threshold": hive_motion.COHERENCE_THRESHOLD,
                "tags_with_velocity": len(tag_velocities),
                "result": "PASS" if coherence >= hive_motion.COHERENCE_THRESHOLD else "FAIL",
            },
            "proximity": {
                "diameter_m": round(diameter_m, 1) if diameter_m else None,
                "coherent_diameter_m": round(coherent_diameter_m, 1) if coherent_diameter_m else None,
                "threshold_m": threshold,
                "is_breaching": coherent_diameter_m > threshold if coherent_diameter_m else False,
                "outlier_tag_id": outlier_id,
                "outlier_selection_reason": outlier_selection_reason,
                "breaching_pair_counts": breaching_pair_counts_payload,
                "coherence_window_s": coherence_window_s,
                "coherent_pair_count": coherent_pair_count,
                "incoherent_pair_count": incoherent_pair_count,
                "max_pair_dt_s": max_pair_dt_s,
                "separated_tag_count": separated_tag_count,
                "stale_snapshot": stale_snapshot,
                "fresh_count": len(fresh_positions),
                "recent_count": len(fresh_recent_positions) - len(fresh_positions),
                "stale_count": composition.get("stale", 0),
                "lost_count": composition.get("lost", 0),
                "persistence": {
                    "eval_count": live.persistence_eval_count if prev_state == "BREACH_PENDING" else 0,
                    "has_new_evidence": live.persistence_has_new_evidence if prev_state == "BREACH_PENDING" else False,
                    "snapshot_fp_at_start": live.persistence_snapshot_fp_at_start if prev_state == "BREACH_PENDING" else None,
                    "elapsed_minutes": round((now - live.pending_breach_since).total_seconds() / 60.0, 2) 
                                      if live.pending_breach_since else 0.0,
                },
            },
            "alert_state_before": prev_state,
            "alert_state_after": new_state,
            "alert_changed": state_changed,
            "confidence": confidence,
            "resolve_by_transit": resolve_by_transit,
        },
    )

    # ── Persist evaluation record ──────────────────────────────────────
    eval_id = str(uuid.uuid4())
    if stale_snapshot:
        breach_evidence = "stale_snapshot"
    elif coherent_diameter_m is not None and coherent_diameter_m > threshold:
        breach_evidence = "coherent"
    elif coherent_pair_count == 0 and incoherent_pair_count > 0 and diameter_m and diameter_m > threshold:
        breach_evidence = "incoherent_only"
    else:
        breach_evidence = "none"

    freshness_payload = {
        **composition,
        "meta": {
            "snapshot_fingerprint": snapshot_fp,
            "coherence_window_s": coherence_window_s,
            "coherent_pair_count": coherent_pair_count,
            "incoherent_pair_count": incoherent_pair_count,
            "max_pair_dt_s": max_pair_dt_s,
            "separated_tag_count": separated_tag_count,
            "stale_snapshot": stale_snapshot,
            "breach_evidence": breach_evidence,
        },
    }

    eval_rec = HiveEvaluation(
        id=eval_id,
        hive_id=hive_id,
        evaluated_at=now,
        config_version_number=cfg.version_number,
        diameter_m=diameter_m,
        threshold_m=threshold,
        outlier_tag_id=outlier_id,
        outlier_selection_reason=outlier_selection_reason,
        breaching_pair_counts=json.dumps(breaching_pair_counts_payload) if breaching_pair_counts_payload else None,
        pairwise_detail=json.dumps(pairwise_detail) if state_changed and pairwise_detail else None,
        freshness_composition=json.dumps(freshness_payload),
        alert_state=new_state,
        breach_confidence=confidence,
        motion_state=motion_decision.state,
        centroid_speed_kmh=(motion_decision.centroid.speed_kmh
                            if motion_decision.centroid else None),
        positions_used=json.dumps(positions_used_payload),
        max_pair_dt_s=max_pair_dt_s,
        coherent_pair_count=coherent_pair_count,
        incoherent_pair_count=incoherent_pair_count,
        breach_evidence=breach_evidence,
    )
    db.add(eval_rec)

    # ── Emit events on state transitions ──────────────────────────────
    if resolve_by_transit:
        # The proximity state machine just collapsed to OK because motion
        # was detected. Surface this explicitly so users know why their
        # active breach went quiet.
        db.add(HiveEvent(
            id=str(uuid.uuid4()),
            hive_id=hive_id,
            occurred_at=now,
            event_type="RESOLVED_BY_TRANSIT",
            config_version_number=cfg.version_number,
            from_state=prev_state,
            to_state=new_state,
            triggering_tag_id=outlier_id,
            details=json.dumps({
                "diameter_m": alert_diameter_m,
                "motion_state": motion_decision.state,
            }),
        ))
    elif state_changed:
        event_type = _state_transition_event(prev_state, new_state)
        event_details = {
            "diameter_m": alert_diameter_m,
            "display_diameter_m": diameter_m,
            "confidence": confidence,
            "breach_evidence": breach_evidence,
            "outlier_tag_id": str(outlier_id) if outlier_id else None,
            "outlier_selection_reason": outlier_selection_reason,
            "breaching_pair_counts": breaching_pair_counts_payload,
            "separated_tag_count": separated_tag_count,
        }
        if pairwise_detail:
            event_details["pairwise_detail"] = pairwise_detail

        event = HiveEvent(
            id=str(uuid.uuid4()),
            hive_id=hive_id,
            occurred_at=now,
            event_type=event_type,
            config_version_number=cfg.version_number,
            from_state=prev_state,
            to_state=new_state,
            triggering_tag_id=outlier_id,
            details=json.dumps(event_details),
        )
        db.add(event)

    if motion_decision.changed:
        db.add(HiveEvent(
            id=str(uuid.uuid4()),
            hive_id=hive_id,
            occurred_at=now,
            event_type="MOTION_STATE_CHANGED",
            config_version_number=cfg.version_number,
            from_state=motion_decision.previous_state,
            to_state=motion_decision.state,
            details=json.dumps({
                "centroid_speed_kmh": (motion_decision.centroid.speed_kmh
                                       if motion_decision.centroid else None),
                "coherence": motion_decision.coherence,
            }),
        ))

    # ── Update live state ─────────────────────────────────────────────
    live.alert_state = new_state
    live.breach_confidence = confidence
    live.last_evaluated_at = now
    live.current_diameter_m = diameter_m
    live.outlier_tag_id = outlier_id

    db.commit()

    # Fire alerts on state edge AND re-notify if hive remains BREACHING for
    # more than HIVE_BREACH_RENOTIFY_HOURS without a delivered notification.
    # The latter guards against the original alert failing silently.
    should_alert = state_changed
    if not state_changed and new_state == "BREACHING":
        last_alert = getattr(live, "last_alert_at", None)
        if last_alert is None:
            should_alert = True  # never delivered an alert for this breach
        else:
            try:
                hours = (now - last_alert).total_seconds() / 3600.0
            except Exception:
                hours = 0
            if hours >= HIVE_BREACH_RENOTIFY_HOURS:
                should_alert = True

    if state_changed:
        log.info("HIVE %s state transition: %s → %s (diameter=%.0fm)",
                 hive_id, prev_state, new_state, diameter_m or 0)

    if motion_decision.changed:
        log.info("HIVE %s motion transition: %s → %s (centroid_speed=%.1f km/h, coherence=%.2f)",
                 hive_id, motion_decision.previous_state, motion_decision.state,
                 motion_decision.centroid.speed_kmh if motion_decision.centroid else 0.0,
                 motion_decision.coherence)

    if resolve_by_transit:
        delivered = _send_resolved_by_transit_alert(hive, prev_state, db)
        if delivered:
            live.last_alert_at = now
            db.commit()
    elif should_alert:
        delivered = _maybe_send_hive_alert(hive, new_state, prev_state, alert_diameter_m,
                                           outlier_id, cfg, db,
                                           breaching_pair_counts=breaching_pair_counts_payload,
                                           separated_tag_count=separated_tag_count,
                                           force_renotify=not state_changed)
        if delivered:
            live.last_alert_at = now
            db.commit()

    return new_state


def _describe_tag(tag_id, db: Session):
    """Return (label, imei) for a tag id, where label is human-friendly."""
    if not tag_id:
        return None, None
    from app.models import BLETag
    t = db.query(BLETag).filter(BLETag.id == tag_id).first()
    if not t:
        return None, None
    label = (t.description or t.device_name or t.imei or str(t.id))
    return label.strip() if isinstance(label, str) else str(label), t.imei


def _maybe_send_hive_alert(hive: Hive, new_state: str, prev_state: str,
                            diameter_m: Optional[float],
                            outlier_tag_id,
                            cfg, db: Session,
                            breaching_pair_counts: Optional[Dict[str, int]] = None,
                            separated_tag_count: Optional[int] = None,
                            force_renotify: bool = False) -> bool:
    """Fire a portal alert + email/SMS when a hive enters or clears a breach.

    Returns True if a notification was actually dispatched (so the caller can
    persist last_alert_at). force_renotify=True bypasses the state-edge guard
    and is used by the periodic 'still in breach' reminder.
    """
    from app.services import portal_alert_service as _pas

    gid = str(hive.usergroup_id)
    km = f"{diameter_m/1000:.1f} km" if diameter_m and diameter_m >= 1000 else (f"{diameter_m:.0f} m" if diameter_m else "unknown distance")
    miles = (diameter_m / 1609.344) if diameter_m else None

    outlier_label, outlier_imei = _describe_tag(outlier_tag_id, db)
    # Build a compact "Label / IMEI 1234..." suffix used in the title
    if outlier_label and outlier_imei and outlier_imei != outlier_label:
        outlier_suffix = f" – {outlier_label} (IMEI {outlier_imei})"
    elif outlier_label:
        outlier_suffix = f" – {outlier_label}"
    else:
        outlier_suffix = ""

    if new_state == "BREACHING":
        alert_type = "hive_breach"
        prefix = "🔴 HIVE Breach" if not force_renotify else "🔴 HIVE Still in Breach"
        title      = f"{prefix}: {hive.name}{outlier_suffix}"
        fallback_pair_count = sum(
            1 for _tid, count in (breaching_pair_counts or {}).items() if int(count or 0) > 0
        )
        separated_count = int(separated_tag_count or 0)
        if separated_count <= 0:
            separated_count = fallback_pair_count

        if separated_count >= 2 and outlier_label:
            others = separated_count - 1
            other_word = "other" if others == 1 else "others"
            message = (
                f"{hive.name} has split - {separated_count} tags have separated from the group "
                f"({outlier_label} and {others} {other_word})."
            )
        elif outlier_label:
            message = (
                f"{outlier_label}"
                + (f" (IMEI {outlier_imei})" if outlier_imei and outlier_imei != outlier_label else "")
                + f" has separated from {hive.name} - now "
                + (f"{miles:.1f} mi" if miles is not None else km)
                + " from the group."
            )
        else:
            message = (
                f"The hive '{hive.name}' is in breach. "
                f"Tags are {km} apart (threshold: {cfg.distance_threshold_m:.0f} m)."
            )
    elif new_state == "OK" and prev_state in ("BREACHING", "RESOLVING"):
        alert_type = "hive_breach_cleared"
        title      = f"✅ HIVE Cleared: {hive.name}"
        message    = (
            f"The hive '{hive.name}' is back within range. "
            f"Current spread: {km}."
        )
    else:
        return False  # BREACH_PENDING / RESOLVING don't warrant alerts

    # Get GPS coordinates from outlier tag or first tag in hive for map plotting
    lat, lng = None, None
    if outlier_tag_id:
        outlier = db.query(BLETag).filter(BLETag.id == outlier_tag_id).first()
        if outlier:
            lat, lng = outlier.latitude, outlier.longitude
    if lat is None and hive.memberships:
        # Fallback to first tag in hive
        first_tag = next((m.tag for m in hive.memberships if m.tag and m.tag.latitude), None)
        if first_tag:
            lat, lng = first_tag.latitude, first_tag.longitude
    
    meta_data = {
        "hive_id": str(hive.id),
        "hive_name": hive.name,
        "diameter_m": diameter_m,
        "outlier_tag_id": str(outlier_tag_id) if outlier_tag_id else None,
        "outlier_imei": outlier_imei,
        "outlier_label": outlier_label,
        "separated_tag_count": separated_tag_count,
        "latitude": float(lat) if lat else None,
        "longitude": float(lng) if lng else None,
    }

    # Check if an alert already exists today to avoid unique constraint violation
    if _pas._recent_alert_exists(db, gid,
                                 str(outlier_tag_id) if outlier_tag_id else None,
                                 alert_type, within_hours=24):
        log.debug("Skipping duplicate %s alert for hive %s (already sent today)",
                  alert_type, hive.id)
        return False

    try:
        _pas.create_alert(db, gid,
                          str(outlier_tag_id) if outlier_tag_id else None,
                          alert_type, title, message, meta_data=meta_data)
        db.commit()
        _pas._notify_group_by_email(db, gid, alert_type, title, message,
                                    meta_data=meta_data)
        _pas._notify_group_by_sms(db, gid, alert_type, title, message)
        return True
    except Exception as exc:
        db.rollback()  # Critical: rollback to prevent PendingRollbackError
        import traceback as _tb
        log.error("Failed to send hive alert for %s: %s\n%s",
                  hive.id, exc, _tb.format_exc())
        return False


def _send_resolved_by_transit_alert(hive: Hive, prev_state: str, db: Session) -> bool:
    """Notify users that an active breach was auto-resolved because the hive
    entered the motion lifecycle (spec §11.7). Proximity is meaningless while
    a group is travelling, so users get one consolidated "on the move" message
    instead of a noisy "cleared" toast.
    """
    if prev_state not in ("BREACH_PENDING", "BREACHING", "RESOLVING"):
        return False
    from app.services import portal_alert_service as _pas
    gid = str(hive.usergroup_id)
    title = f"🚗 HIVE On the Move: {hive.name}"
    message = (
        f"The hive '{hive.name}' has started moving together. "
        f"Proximity monitoring is paused until the group settles."
    )
    meta_data = {
        "hive_id": str(hive.id),
        "hive_name": hive.name,
        "previous_alert_state": prev_state,
        "reason": "RESOLVED_BY_TRANSIT",
    }
    
    # Check if an alert already exists today
    if _pas._recent_alert_exists(db, gid, None, "hive_resolved_by_transit", within_hours=24):
        log.debug("Skipping duplicate resolved_by_transit alert for hive %s (already sent today)", hive.id)
        return False
    
    try:
        _pas.create_alert(db, gid, None, "hive_resolved_by_transit",
                          title, message, meta_data=meta_data)
        db.commit()
        _pas._notify_group_by_email(db, gid, "hive_resolved_by_transit",
                                    title, message, meta_data=meta_data)
        return True
    except Exception as exc:
        db.rollback()  # Critical: rollback to prevent PendingRollbackError
        import traceback as _tb
        log.error("Failed to send resolved-by-transit alert for %s: %s\n%s",
                  hive.id, exc, _tb.format_exc())
        return False


def _current_config(hive_id: str, db: Session) -> Optional[HiveConfigVersion]:
    return (
        db.query(HiveConfigVersion)
        .filter(HiveConfigVersion.hive_id == hive_id, HiveConfigVersion.valid_to.is_(None))
        .first()
    )


def _get_or_create_live_state(hive_id: str, db: Session) -> HiveLiveState:
    ls = db.query(HiveLiveState).filter(HiveLiveState.hive_id == hive_id).first()
    if ls is None:
        ls = HiveLiveState(hive_id=hive_id, alert_state="OK", consecutive_confirms=0)
        db.add(ls)
        db.flush()
    return ls


def _state_transition_event(from_s: str, to_s: str) -> str:
    transitions = {
        ("OK",             "BREACH_PENDING"): "SUSPECTED_BREACH",
        ("OK",             "BREACHING"):      "CONFIRMED_BREACH",
        ("BREACH_PENDING", "BREACHING"):      "CONFIRMED_BREACH",
        ("BREACH_PENDING", "OK"):             "BREACH_CLEARED",
        ("BREACHING",      "RESOLVING"):      "BREACH_CLEARING",
        ("RESOLVING",      "OK"):             "BREACH_CLEARED",
        ("RESOLVING",      "BREACHING"):      "CONFIRMED_BREACH",
    }
    return transitions.get((from_s, to_s), f"{from_s}_TO_{to_s}")


# ──────────────────────────────────────────────────────────────────────────────
# Lifecycle helpers (called from routes)
# ──────────────────────────────────────────────────────────────────────────────

def archive_hive(hive: Hive, reason: str, db: Session) -> None:
    """Release tags and move hive to archived state."""
    now = datetime.now(UTC)
    # Release tag memberships
    db.query(HiveTagMembership).filter(HiveTagMembership.hive_id == str(hive.id)).delete()
    # Update hive
    hive.status = "archived"
    hive.archived_at = now
    hive.archived_reason = reason
    hive.archive_expires_at = now + timedelta(days=60)
    # Resolve any active alert
    ls = db.query(HiveLiveState).filter(HiveLiveState.hive_id == str(hive.id)).first()
    if ls and ls.alert_state not in ("OK",):
        ls.alert_state = "OK"
        event = HiveEvent(
            id=str(uuid.uuid4()),
            hive_id=str(hive.id),
            occurred_at=now,
            event_type="RESOLVED_BY_HIVE_DELETION" if reason == "user_deleted" else "RESOLVED_BY_HIVE_EXPIRY",
        )
        db.add(event)
    db.commit()


def purge_hive(hive: Hive, reason: str, db: Session) -> None:
    """Permanently purge hive data (release memberships if still present, delete history)."""
    now = datetime.now(UTC)
    # Release any remaining memberships (archived hives have none, but be safe)
    db.query(HiveTagMembership).filter(HiveTagMembership.hive_id == str(hive.id)).delete()
    # Purge history
    db.query(HiveEvaluation).filter(HiveEvaluation.hive_id == str(hive.id)).delete()
    db.query(HiveEvent).filter(HiveEvent.hive_id == str(hive.id)).delete()
    db.query(HiveLiveState).filter(HiveLiveState.hive_id == str(hive.id)).delete()
    db.query(HiveConfigVersion).filter(HiveConfigVersion.hive_id == str(hive.id)).delete()
    # Set tombstone
    hive.status = "purged"
    hive.purged_at = now
    hive.purged_reason = reason
    db.commit()


# ──────────────────────────────────────────────────────────────────────────────
# Periodic sweeper
# ──────────────────────────────────────────────────────────────────────────────

_sweeper_thread: Optional[threading.Thread] = None
_sweeper_stop = threading.Event()

SWEEP_INTERVAL_S = 120   # freshness re-evaluation every 2 minutes
EXPIRY_INTERVAL_S = 600  # expiry check every 10 minutes


def start_sweeper() -> None:
    global _sweeper_thread
    if _sweeper_thread and _sweeper_thread.is_alive():
        return
    _sweeper_stop.clear()
    _sweeper_thread = threading.Thread(target=_sweeper_loop, daemon=True, name="hive-sweeper")
    _sweeper_thread.start()
    log.info("HIVE sweeper started")


def stop_sweeper() -> None:
    _sweeper_stop.set()
    if _sweeper_thread:
        _sweeper_thread.join(timeout=5)
    log.info("HIVE sweeper stopped")


def _sweeper_loop() -> None:
    last_expiry_check = 0.0
    while not _sweeper_stop.is_set():
        try:
            _freshness_sweep()
        except Exception:
            log.exception("HIVE freshness sweep error")

        now = time.monotonic()
        if now - last_expiry_check >= EXPIRY_INTERVAL_S:
            try:
                _expiry_sweep()
                _archive_purge_sweep()
            except Exception:
                log.exception("HIVE expiry/purge sweep error")
            last_expiry_check = now

        _sweeper_stop.wait(SWEEP_INTERVAL_S)


def _freshness_sweep() -> None:
    """Re-evaluate all active hives (staleness may have changed since last event)."""
    db: Session = SessionLocal()
    try:
        hive_ids = [
            row[0] for row in
            db.query(Hive.id).filter(Hive.status == "active").all()
        ]
        for hive_id in hive_ids:
            try:
                evaluate_hive(str(hive_id), db)
            except Exception:
                log.exception("Error evaluating hive %s", hive_id)
    finally:
        db.close()


def _expiry_sweep() -> None:
    """Auto-archive hives past their expires_at."""
    db: Session = SessionLocal()
    try:
        now = datetime.now(UTC)
        expired = db.query(Hive).filter(
            Hive.status == "active",
            Hive.expires_at <= now,
        ).all()
        for hive in expired:
            log.info("Auto-archiving expired hive %s", hive.id)
            archive_hive(hive, "expired", db)
    finally:
        db.close()


def _archive_purge_sweep() -> None:
    """Auto-purge archived hives past their archive_expires_at."""
    db: Session = SessionLocal()
    try:
        now = datetime.now(UTC)
        expired_archives = db.query(Hive).filter(
            Hive.status == "archived",
            Hive.archive_expires_at <= now,
        ).all()
        for hive in expired_archives:
            log.info("Auto-purging archived hive %s", hive.id)
            purge_hive(hive, "auto_retention", db)
    finally:
        db.close()
