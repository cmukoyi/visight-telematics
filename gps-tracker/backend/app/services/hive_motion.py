"""HIVE Motion Awareness — Phase 3 (spec v1.1).

Implements the four-state motion machine that suppresses proximity alerts
while a hive is moving:

    STATIONARY  ──▶  PRE_TRANSIT  ──▶  IN_TRANSIT  ──▶  SETTLING  ──▶  STATIONARY
                        │                              ▲
                        └──▶ (motion not sustained) ───┘

State semantics (spec §11.2):

  STATIONARY   Centroid at rest. Normal proximity evaluation.
  PRE_TRANSIT  Initial motion detected; awaiting confirmation
               (≥30 s above speed threshold, awaiting full 2 min).
               Proximity alerts SUPPRESSED.
  IN_TRANSIT   Sustained coherent group motion. Proximity alerts SUPPRESSED.
  SETTLING     Recently stopped; trailing stale reports still arriving.
               All alert evaluation SUPPRESSED.

User-facing labels (UI only): PRE_TRANSIT → "Starting", SETTLING → "Stopping".

Why two buffer states? At each motion edge the data is briefly unreliable:
position staleness across tags causes apparent breach distances even when
the group is together. PRE_TRANSIT absorbs the start; SETTLING absorbs the
stop. Together they guarantee no proximity alert can fire from "first hint
of motion" through "fully settled at destination".

This module is pure-Python / Postgres only — no Redis. Live state lives on
``hive_live_state`` and per-tag velocity on ``hive_tag_membership``. Called
from ``hive_service.evaluate_hive()`` before the proximity branch.
"""
from __future__ import annotations

import logging
import math
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Iterable, List, Optional, Sequence, Tuple

from sqlalchemy.orm import Session

from app.models import HiveConfigVersion, HiveLiveState, HiveMotionState, HiveTagMembership

log = logging.getLogger(__name__)

UTC = timezone.utc

# ─────────────────────────────────────────────────────────────────────────────
# Timing constants (spec §11.2). Kept here rather than per-profile because
# they describe machine behaviour (how long to wait for confirmation), not
# physical tuning (how fast counts as "moving"). Tuning lives in the profile.
# ─────────────────────────────────────────────────────────────────────────────
PRE_TRANSIT_CONFIRM_SECONDS  = 30          # speed > threshold for ≥30s → PRE_TRANSIT
IN_TRANSIT_CONFIRM_SECONDS   = 120         # 2 min total motion → IN_TRANSIT
COHERENCE_THRESHOLD          = 0.60        # ≥60% of tags moving with group
CENTROID_ANCHOR_WINDOW_SEC   = 300         # rolling 5-minute velocity window
COHERENCE_MIN_TAG_REPORTS    = 2           # tag needs ≥2 reports to compute v
COHERENCE_TAG_HISTORY_SEC    = 600         # within last 10 minutes


# ─────────────────────────────────────────────────────────────────────────────
# Geometry — duplicated locally to avoid an import cycle with hive_service.
# These are pure functions; tested independently.
# ─────────────────────────────────────────────────────────────────────────────

_EARTH_R_M = 6_371_000.0


def _haversine_m(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    φ1, φ2 = math.radians(lat1), math.radians(lat2)
    Δφ = math.radians(lat2 - lat1)
    Δλ = math.radians(lon2 - lon1)
    a = math.sin(Δφ / 2) ** 2 + math.cos(φ1) * math.cos(φ2) * math.sin(Δλ / 2) ** 2
    return 2 * _EARTH_R_M * math.asin(math.sqrt(a))


def _bearing_deg(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Initial great-circle bearing from (lat1,lon1) to (lat2,lon2), 0–360°."""
    φ1, φ2 = math.radians(lat1), math.radians(lat2)
    Δλ = math.radians(lon2 - lon1)
    y = math.sin(Δλ) * math.cos(φ2)
    x = math.cos(φ1) * math.sin(φ2) - math.sin(φ1) * math.cos(φ2) * math.cos(Δλ)
    return (math.degrees(math.atan2(y, x)) + 360.0) % 360.0


def _bearing_delta_deg(a: float, b: float) -> float:
    """Smallest absolute angular delta between two bearings, 0–180°."""
    d = abs(a - b) % 360.0
    return d if d <= 180.0 else 360.0 - d


# ─────────────────────────────────────────────────────────────────────────────
# Centroid + velocity
# ─────────────────────────────────────────────────────────────────────────────

@dataclass
class CentroidVelocity:
    centroid_lat: float
    centroid_lng: float
    speed_kmh: float            # 0.0 when no anchor available yet
    bearing_deg: Optional[float]  # None when speed is zero or no anchor


def compute_centroid(positions: Sequence[Tuple[str, float, float]]) -> Optional[Tuple[float, float]]:
    """Geometric mean of (tag_id, lat, lng) positions. None if fewer than 1."""
    if not positions:
        return None
    n = float(len(positions))
    return sum(p[1] for p in positions) / n, sum(p[2] for p in positions) / n


def compute_centroid_velocity(
    centroid_now: Tuple[float, float],
    now: datetime,
    anchor_lat: Optional[float],
    anchor_lng: Optional[float],
    anchor_at: Optional[datetime],
) -> CentroidVelocity:
    """Velocity of the centroid measured against an older anchor snapshot.

    If no anchor (first evaluation) or the anchor is too recent to be
    meaningful (<30s), return speed=0 — caller decides whether to refresh
    the anchor based on age.
    """
    if anchor_lat is None or anchor_lng is None or anchor_at is None:
        return CentroidVelocity(centroid_now[0], centroid_now[1], 0.0, None)
    if anchor_at.tzinfo is None:
        anchor_at = anchor_at.replace(tzinfo=UTC)
    dt_s = (now - anchor_at).total_seconds()
    if dt_s < 30.0:
        # Anchor too fresh — not enough baseline to derive meaningful speed.
        return CentroidVelocity(centroid_now[0], centroid_now[1], 0.0, None)
    dist_m = _haversine_m(anchor_lat, anchor_lng, centroid_now[0], centroid_now[1])
    speed_kmh = (dist_m / dt_s) * 3.6
    bearing = _bearing_deg(anchor_lat, anchor_lng, centroid_now[0], centroid_now[1]) \
        if dist_m > 0.0 else None
    return CentroidVelocity(centroid_now[0], centroid_now[1], speed_kmh, bearing)


# ─────────────────────────────────────────────────────────────────────────────
# Per-tag velocity & group coherence
# ─────────────────────────────────────────────────────────────────────────────

@dataclass
class TagVelocity:
    tag_id: str
    speed_kmh: float
    bearing_deg: Optional[float]
    computed_at: datetime


def update_tag_velocity(
    membership: HiveTagMembership,
    current_lat: Optional[float],
    current_lng: Optional[float],
    current_seen_at: Optional[datetime],
    now: datetime,
) -> Optional[TagVelocity]:
    """Roll the per-tag velocity vector forward.

    Compares the tag's current position to the previous_* anchor stored on
    its membership row, writes the new velocity, then advances the anchor.
    Returns the freshly computed velocity (or None if not enough data).

    Caller must commit. Idempotent: if current_seen_at == previous_seen_at
    no update is made.
    """
    if current_lat is None or current_lng is None or current_seen_at is None:
        return None
    if current_seen_at.tzinfo is None:
        current_seen_at = current_seen_at.replace(tzinfo=UTC)

    prev_lat = membership.previous_lat
    prev_lng = membership.previous_lng
    prev_at  = membership.previous_seen_at
    if prev_at is not None and prev_at.tzinfo is None:
        prev_at = prev_at.replace(tzinfo=UTC)

    velocity: Optional[TagVelocity] = None
    if prev_lat is not None and prev_lng is not None and prev_at is not None:
        dt_s = (current_seen_at - prev_at).total_seconds()
        if dt_s > 0.5:  # ignore duplicate or out-of-order reports
            dist_m = _haversine_m(prev_lat, prev_lng, current_lat, current_lng)
            speed_kmh = (dist_m / dt_s) * 3.6
            bearing = _bearing_deg(prev_lat, prev_lng, current_lat, current_lng) \
                if dist_m > 0.0 else None
            membership.velocity_speed_kmh = speed_kmh
            membership.velocity_bearing_deg = bearing
            membership.velocity_computed_at = now
            velocity = TagVelocity(str(membership.tag_id), speed_kmh, bearing, now)

    # Always roll the anchor forward so the next evaluation has a fresh
    # baseline — this is what makes the per-tag vector a rolling 1-step
    # velocity rather than ever-stale.
    if prev_at != current_seen_at:
        membership.previous_lat = current_lat
        membership.previous_lng = current_lng
        membership.previous_seen_at = current_seen_at

    return velocity


def coherence_score(
    tag_velocities: Iterable[TagVelocity],
    centroid_v: CentroidVelocity,
    cfg: HiveConfigVersion,
    now: datetime,
) -> float:
    """Fraction (0.0–1.0) of tags moving coherently with the centroid.

    A tag counts as motion-coherent when both its speed and bearing fall
    within profile tolerances of the centroid's. Tags without a recent
    velocity (>10 min stale) are excluded from both numerator and
    denominator (spec §11.4). Returns 0.0 when no tags qualify.
    """
    if centroid_v.speed_kmh <= 0.0 or centroid_v.bearing_deg is None:
        return 0.0
    speed_tol = cfg.coherence_speed_tol_kmh or 0.0
    bearing_tol = cfg.coherence_bearing_tol_deg or 360.0

    eligible = 0
    coherent = 0
    cutoff = now - timedelta(seconds=COHERENCE_TAG_HISTORY_SEC)
    for tv in tag_velocities:
        if tv.bearing_deg is None:
            continue
        if tv.computed_at < cutoff:
            continue
        eligible += 1
        if abs(tv.speed_kmh - centroid_v.speed_kmh) <= speed_tol and \
           _bearing_delta_deg(tv.bearing_deg, centroid_v.bearing_deg) <= bearing_tol:
            coherent += 1
    if eligible == 0:
        return 0.0
    return coherent / eligible


# ─────────────────────────────────────────────────────────────────────────────
# Motion state machine
# ─────────────────────────────────────────────────────────────────────────────

@dataclass
class MotionDecision:
    """Result of one motion-state evaluation cycle."""
    state: str                       # new HiveMotionState value
    previous_state: str              # state before this cycle
    changed: bool                    # True iff state != previous_state
    centroid: Optional[CentroidVelocity]
    coherence: float                 # 0.0–1.0
    suppress_proximity: bool         # True for any non-STATIONARY state
    fresh_eval_required: bool        # True on returns to STATIONARY


def _now_aware(dt: Optional[datetime]) -> Optional[datetime]:
    if dt is None:
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=UTC)


def evaluate_motion_state(
    live: HiveLiveState,
    cfg: HiveConfigVersion,
    centroid_v: Optional[CentroidVelocity],
    coherence: float,
    now: datetime,
) -> MotionDecision:
    """Run one tick of the motion state machine.

    Mutates ``live`` in place (motion_state, motion_state_since,
    pending_motion_change_since, centroid_*). Caller commits.

    When ``cfg.motion_speed_threshold_kmh`` is None (Stationary profile)
    the machine is disabled — state stays STATIONARY and any movement is
    handled by the existing proximity-breach path instead.
    """
    prev_state = live.motion_state or HiveMotionState.STATIONARY.value
    threshold = cfg.motion_speed_threshold_kmh

    # Default: no change
    new_state = prev_state
    fresh_eval_required = False

    if threshold is None:
        # Motion detection disabled for this profile. Keep state STATIONARY
        # and clear any pending transitional flag (defensive — should never
        # have been set, but a profile change could leave one stale).
        if prev_state != HiveMotionState.STATIONARY.value:
            new_state = HiveMotionState.STATIONARY.value
            fresh_eval_required = True
        live.pending_motion_change_since = None
    elif centroid_v is None:
        # Not enough Fresh tags to compute a centroid. Hold current state;
        # don't make unsubstantiated transitions.
        pass
    else:
        speed = centroid_v.speed_kmh
        moving = speed >= threshold
        settling_time_s = cfg.motion_settling_time_s or 300
        pending_since = _now_aware(live.pending_motion_change_since)
        state_since = _now_aware(live.motion_state_since) or now

        if prev_state == HiveMotionState.STATIONARY.value:
            if moving and coherence >= COHERENCE_THRESHOLD:
                # Start (or continue) tracking how long we've been moving.
                # Spec §11.1: PRE_TRANSIT requires BOTH centroid velocity > threshold
                # AND coherence ≥ 60% (tags moving together in same direction).
                if pending_since is None:
                    live.pending_motion_change_since = now
                elif (now - pending_since).total_seconds() >= PRE_TRANSIT_CONFIRM_SECONDS:
                    new_state = HiveMotionState.PRE_TRANSIT.value
                    live.pending_motion_change_since = pending_since  # carry over: counts toward 2-min IN_TRANSIT confirm
            else:
                live.pending_motion_change_since = None

        elif prev_state == HiveMotionState.PRE_TRANSIT.value:
            # PRE_TRANSIT counts from when motion was *first* detected,
            # which we preserved in pending_motion_change_since.
            motion_started = pending_since or state_since
            total_motion_s = (now - motion_started).total_seconds()
            if not moving:
                # Motion not sustained — check if we've been stopped
                # long enough to bail back to STATIONARY (spec §11.2).
                if (now - state_since).total_seconds() >= PRE_TRANSIT_CONFIRM_SECONDS:
                    new_state = HiveMotionState.STATIONARY.value
                    fresh_eval_required = True   # capture any genuine breach from the false start
                    live.pending_motion_change_since = None
            elif total_motion_s >= IN_TRANSIT_CONFIRM_SECONDS and coherence >= COHERENCE_THRESHOLD:
                new_state = HiveMotionState.IN_TRANSIT.value
                live.pending_motion_change_since = None

        elif prev_state == HiveMotionState.IN_TRANSIT.value:
            if not moving:
                if pending_since is None:
                    live.pending_motion_change_since = now
                elif (now - pending_since).total_seconds() >= 180:  # 3 min stable per spec
                    new_state = HiveMotionState.SETTLING.value
                    live.pending_motion_change_since = now  # restart timer for SETTLING→STATIONARY
            else:
                live.pending_motion_change_since = None

        elif prev_state == HiveMotionState.SETTLING.value:
            if moving:
                # Motion re-detected (lights/traffic). Back to IN_TRANSIT.
                new_state = HiveMotionState.IN_TRANSIT.value
                live.pending_motion_change_since = None
            else:
                if (now - state_since).total_seconds() >= settling_time_s:
                    new_state = HiveMotionState.STATIONARY.value
                    fresh_eval_required = True
                    live.pending_motion_change_since = None

    # Always update centroid telemetry if we have it (even if state didn't
    # change) so the UI sees a live readout.
    if centroid_v is not None:
        live.centroid_lat = centroid_v.centroid_lat
        live.centroid_lng = centroid_v.centroid_lng
        live.centroid_speed_kmh = centroid_v.speed_kmh
        live.centroid_bearing_deg = centroid_v.bearing_deg

    state_changed = new_state != prev_state
    if state_changed:
        live.motion_state = new_state
        live.motion_state_since = now

    suppress = new_state != HiveMotionState.STATIONARY.value

    return MotionDecision(
        state=new_state,
        previous_state=prev_state,
        changed=state_changed,
        centroid=centroid_v,
        coherence=coherence,
        suppress_proximity=suppress,
        fresh_eval_required=fresh_eval_required,
    )


def maybe_refresh_centroid_anchor(
    live: HiveLiveState,
    centroid_now: Optional[Tuple[float, float]],
    now: datetime,
) -> None:
    """Advance the rolling-5-min anchor used for centroid velocity.

    If no anchor exists, seed it. If the existing anchor is older than the
    window length, replace it with the current centroid so the next
    evaluation measures velocity over a fresh ~5-min interval.
    """
    if centroid_now is None:
        return
    anchor_at = _now_aware(live.centroid_anchor_at)
    if anchor_at is None or (now - anchor_at).total_seconds() >= CENTROID_ANCHOR_WINDOW_SEC:
        live.centroid_anchor_lat = centroid_now[0]
        live.centroid_anchor_lng = centroid_now[1]
        live.centroid_anchor_at = now
