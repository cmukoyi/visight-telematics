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
    usable_positions: List[Tuple[str, float, float]] = []   # fresh + recent + stale (anything not fully lost)
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
            if tier in ("fresh", "recent", "stale"):
                usable_positions.append((m.tag_id, lat, lon))
            if tier in ("fresh", "recent"):
                fresh_recent_positions.append((m.tag_id, lat, lon))
            if tier == "fresh":
                fresh_positions.append((m.tag_id, lat, lon))

    # ── Compute diameter ───────────────────────────────────────────────
    # Prefer fresh+recent; fall back to stale so a hive with infrequent
    # GPS reports still surfaces a diameter and can detect breach (with
    # 'low' confidence). Tags fully 'lost' are excluded.
    if len(fresh_recent_positions) >= 2:
        diameter_m, outlier_id = pairwise_max_distance(fresh_recent_positions)
    else:
        diameter_m, outlier_id = pairwise_max_distance(usable_positions)

    # No meaningful spread — clear outlier so UI doesn't flag a tag incorrectly
    if diameter_m is not None and diameter_m < cfg.meaningful_change_m:
        outlier_id = None

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
    # True iff this cycle should auto-resolve any active breach because the
    # hive just entered the motion lifecycle (spec §11.6).
    resolve_by_transit = (
        motion_decision.changed
        and motion_decision.state == HiveMotionState.PRE_TRANSIT.value
        and prev_state in ("BREACH_PENDING", "BREACHING", "RESOLVING")
    )

    if resolve_by_transit:
        # Force-resolve: hive is on the move, proximity is meaningless.
        new_state = "OK"
        confidence = None
        live.pending_breach_since = None
        live.pending_clear_since = None
        live.consecutive_confirms = 0
    elif motion_decision.suppress_proximity:
        # PRE_TRANSIT / IN_TRANSIT / SETTLING — hold current alert state,
        # don't run the proximity machine. Note any active BREACHING from
        # before motion-entry would have been resolved above.
        pass
    elif settling or diameter_m is None:
        # Not enough data / still in creation-time settling window —
        # hold current OK / RESOLVING.
        new_state = "OK" if prev_state in ("OK", "BREACH_PENDING") else prev_state
    else:
        is_breaching = diameter_m > threshold
        clear_threshold = threshold * (cfg.hysteresis_pct / 100.0)
        is_cleared = diameter_m <= clear_threshold

        # Confidence: high if we have ≥ confirmation_count fresh tags
        confidence = "high" if len(fresh_positions) >= cfg.confirmation_count else "low"

        if prev_state == "OK":
            if is_breaching:
                live.pending_breach_since = now
                live.consecutive_confirms = 1
                if confidence == "high" and 1 >= cfg.confirmation_count:
                    new_state = "BREACHING"
                else:
                    # Low-confidence (stale GPS) or pending confirmation
                    # \u2192 surface as a Suspected Breach so the user sees it.
                    new_state = "BREACH_PENDING"

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
        motion_state=motion_decision.state,
        centroid_speed_kmh=(motion_decision.centroid.speed_kmh
                            if motion_decision.centroid else None),
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
                "diameter_m": diameter_m,
                "motion_state": motion_decision.state,
            }),
        ))
    elif state_changed:
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
        delivered = _maybe_send_hive_alert(hive, new_state, prev_state, diameter_m,
                                           outlier_id, cfg, db,
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
                            force_renotify: bool = False) -> bool:
    """Fire a portal alert + email/SMS when a hive enters or clears a breach.

    Returns True if a notification was actually dispatched (so the caller can
    persist last_alert_at). force_renotify=True bypasses the state-edge guard
    and is used by the periodic 'still in breach' reminder.
    """
    from app.services import portal_alert_service as _pas

    gid = str(hive.usergroup_id)
    km = f"{diameter_m/1000:.1f} km" if diameter_m and diameter_m >= 1000 else (f"{diameter_m:.0f} m" if diameter_m else "unknown distance")

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
        if outlier_label:
            message = (
                f"Tag {outlier_label}"
                + (f" (IMEI {outlier_imei})" if outlier_imei and outlier_imei != outlier_label else "")
                + f" has left hive '{hive.name}'. "
                f"Spread is now {km} (threshold: {cfg.distance_threshold_m:.0f} m)."
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

    meta_data = {
        "hive_id": str(hive.id),
        "diameter_m": diameter_m,
        "outlier_tag_id": str(outlier_tag_id) if outlier_tag_id else None,
        "outlier_imei": outlier_imei,
        "outlier_label": outlier_label,
    }

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
        "previous_alert_state": prev_state,
        "reason": "RESOLVED_BY_TRANSIT",
    }
    try:
        _pas.create_alert(db, gid, None, "hive_resolved_by_transit",
                          title, message, meta_data=meta_data)
        db.commit()
        _pas._notify_group_by_email(db, gid, "hive_resolved_by_transit",
                                    title, message, meta_data=meta_data)
        return True
    except Exception as exc:
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
