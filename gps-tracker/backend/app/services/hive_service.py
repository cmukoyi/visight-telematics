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
from typing import Dict, List, Optional, Tuple

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
    HiveStatus,
    HiveTagMembership,
)

log = logging.getLogger(__name__)

UTC = timezone.utc

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


def pairwise_max_distance(positions: List[Tuple[str, float, float]]) -> Tuple[Optional[float], Optional[str]]:
    """
    Given a list of (tag_id, lat, lng), compute the maximum pairwise distance
    (group diameter) and the tag_id that is the outlier (has the most breaching
    pairs or the furthest single distance).

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

    # Outlier = tag with the highest max pairwise distance
    outlier = max(pair_distances, key=lambda t: max(pair_distances[t]) if pair_distances[t] else 0.0)
    return max_dist, outlier


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
    composition = {"fresh": 0, "recent": 0, "stale": 0, "lost": 0}

    for m in memberships:
        tag = db.query(BLETag).filter(BLETag.id == m.tag_id).first()
        if not tag:
            continue
        tier = freshness_tier(tag.last_seen, cfg)
        composition[tier] += 1
        if tag.latitude and tag.longitude:
            try:
                lat, lon = float(tag.latitude), float(tag.longitude)
            except (TypeError, ValueError):
                continue
            if tier in ("fresh", "recent"):
                fresh_recent_positions.append((m.tag_id, lat, lon))
            if tier == "fresh":
                fresh_positions.append((m.tag_id, lat, lon))

    # ── Compute diameter ───────────────────────────────────────────────
    # Use fresh+recent for diameter; prefer fresh-only for high confidence
    diameter_m, outlier_id = pairwise_max_distance(fresh_recent_positions)

    # ── Determine breach ──────────────────────────────────────────────
    threshold = cfg.distance_threshold_m
    prev_state = live.alert_state or "OK"
    new_state = prev_state
    confidence = None

    if settling or diameter_m is None:
        # Not enough data / still settling — hold current OK / RESOLVING
        new_state = "OK" if prev_state in ("OK", "BREACH_PENDING") else prev_state
    else:
        is_breaching = diameter_m > threshold
        clear_threshold = threshold * (cfg.hysteresis_pct / 100.0)
        is_cleared = diameter_m <= clear_threshold

        # Confidence: high if we have ≥ confirmation_count fresh tags
        confidence = "high" if len(fresh_positions) >= cfg.confirmation_count else "low"

        if prev_state == "OK":
            if is_breaching:
                if confidence == "high":
                    new_state = "BREACH_PENDING"
                    live.pending_breach_since = now
                    live.consecutive_confirms = 1
                # low confidence → stay OK

        elif prev_state == "BREACH_PENDING":
            if not is_breaching:
                new_state = "OK"
                live.pending_breach_since = None
                live.consecutive_confirms = 0
            else:
                live.consecutive_confirms = (live.consecutive_confirms or 0) + 1
                if live.consecutive_confirms >= cfg.confirmation_count:
                    new_state = "BREACHING"

        elif prev_state == "BREACHING":
            if is_cleared:
                new_state = "RESOLVING"
                live.pending_clear_since = now
            # else stays BREACHING

        elif prev_state == "RESOLVING":
            if not is_cleared:
                new_state = "BREACHING"  # dipped back over
                live.pending_clear_since = None
            else:
                # Require 1 cycle to confirm clear
                new_state = "OK"
                live.pending_clear_since = None
                live.consecutive_confirms = 0

    state_changed = new_state != prev_state

    # ── Persist evaluation record ──────────────────────────────────────
    eval_id = str(uuid.uuid4())
    eval_rec = HiveEvaluation(
        id=eval_id,
        hive_id=hive_id,
        evaluated_at=now,
        config_version_number=cfg.version_number,
        diameter_m=diameter_m,
        threshold_m=threshold,
        outlier_tag_id=outlier_id,
        freshness_composition=json.dumps(composition),
        alert_state=new_state,
        breach_confidence=confidence,
    )
    db.add(eval_rec)

    # ── Emit event on state transition ────────────────────────────────
    if state_changed:
        event_type = _state_transition_event(prev_state, new_state)
        event = HiveEvent(
            id=str(uuid.uuid4()),
            hive_id=hive_id,
            occurred_at=now,
            event_type=event_type,
            config_version_number=cfg.version_number,
            from_state=prev_state,
            to_state=new_state,
            triggering_tag_id=outlier_id,
            details=json.dumps({"diameter_m": diameter_m, "confidence": confidence}),
        )
        db.add(event)

    # ── Update live state ─────────────────────────────────────────────
    live.alert_state = new_state
    live.breach_confidence = confidence
    live.last_evaluated_at = now
    live.current_diameter_m = diameter_m
    live.outlier_tag_id = outlier_id

    db.commit()

    if state_changed:
        log.info("HIVE %s state transition: %s → %s (diameter=%.0fm)",
                 hive_id, prev_state, new_state, diameter_m or 0)

    return new_state


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
        ("BREACH_PENDING", "BREACHING"): "CONFIRMED_BREACH",
        ("OK", "BREACH_PENDING"):        "SUSPECTED_BREACH",
        ("BREACH_PENDING", "OK"):        "BREACH_CLEARED",
        ("BREACHING", "RESOLVING"):      "BREACH_CLEARING",
        ("RESOLVING", "OK"):             "BREACH_CLEARED",
        ("RESOLVING", "BREACHING"):      "CONFIRMED_BREACH",
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
