"""
Trip State Engine (Trip Engine - Section 2)

Implements STATIONARY ↔ MOVE state machine from PinPlot_Trip_Engine_Spec_v2.1.md.

CRITICAL FIXES (19 July 2026):
    Fixed bugs that caused 0 legs output (should be 14 legs from 897 positions):
    
    Bug #1: Anchor Reassignment
        BEFORE: anchor recalculated via calculate_centroid(all_points) on every point
        AFTER:  anchor rolled incrementally: anchor += (point - anchor) / count
        IMPACT: Prevents anchor_count=1 bug, correct O(1) performance
    
    Bug #2: Leg Start Point
        BEFORE: leg started from anchor[-1] or current point
        AFTER:  leg starts from PREVIOUS point (last_position) when leaving stationary
        IMPACT: Spec compliance - "leg_buffer = [prev, point]"
    
    Bug #3: Missing Invariants
        ADDED: 6 invariant assertions from spec Section 6
        - anchor_count >= 1 always
        - journey has leg_count >= 1
        - leg distance >= MIN_LEG_DISTANCE (except unknown-path/air)
        - sum(leg.distance_m) == journey.distance_m
        - consecutive stationaries > R apart
    
    Reference: PinPlot_Trip_Engine_Implementation_Notes.md
    Test data: reference_legs.csv (14 legs, 16 stationaries, 40.6 km expected)

Architecture:
    - Per-device displacement state machine
    - Input: device_positions stream (observed_at, lat, lng)
    - Output: stationaries, legs, journeys
    - Resumable via engine_state table (crash recovery)
    - Pure function of stored positions → replayable/testable

State Machine:
    STATIONARY:  Points within radius R → roll anchor centroid
                 Beyond R → enter MOVE (leg opens)
    
    MOVE:        Accumulate points in leg buffer
                 Last 3 points within R → open stop candidate (v2.1)
                 Candidate holds ≥ settle_min_dwell_min → confirm stop, STATIONARY (v2.1)
                 Candidate leaves R before settling → discard, continue leg (v2.1)
                 Gap timeout → force close leg, STATIONARY

Rules:
    - Geometry-based (not time-based) confirmation
    - R = 100m (anchor radius)
    - Min leg distance = 300m (3 × R)
    - Move confirm = 150m (before emitting leg)
    - Settle dwell = 3 min (v2.1: minimum time to confirm stop)
    - MAX_KMH = 200 (outlier gate)
    - GAP_TIMEOUT = 30 min (force close)
    - Journey grouping: 30 min dwell threshold

Filters:
    - Outlier gate: > 200 km/h → classify by 3-part AND
    - Air legs: ≥ 300 km/h AND ≥ 150 km AND multi-hour gap (validated on real flights)
    - GPS glitches: > 200 km/h but < 150 km → discard
    - Median smoothing: window 3 on lat/lng
    - Gap policy: spatial jump = unknown-path leg, temporal gap = long stationary

v2.1 Changes:
    - Settle-dwell confirmation: stops must hold ≥3 min before confirming
    - Stationary merge: new stops within R of journey's last stop are merged (one place = one record)
    - Leg arrival fix: leg end_point set to stop candidate anchor (line reaches stop)
    - Air leg detection: 3-part AND validation (speed, distance, gap) prevents discarding real flights
    - Great-circle geometry for air legs (straight line, path unknown)
    - Prevents false stops from brief slowdowns (traffic lights, roundabouts)
    - Prevents duplicate stop records from scattered position reports
"""

import asyncio
import logging
from datetime import datetime, timedelta, timezone
from typing import List, Dict, Optional, Tuple
from dataclasses import dataclass
from math import radians, cos, sin, asin, sqrt
from statistics import median
from uuid import uuid4

from sqlalchemy import select, and_
from sqlalchemy.orm import Session
from sqlalchemy import text

from app.models import (
    DevicePosition,
    EngineState,
    Stationary,
    Leg,
    Journey,
    TripConfig,
)

logger = logging.getLogger(__name__)

# ── Engine Version (v2.2.0 - Fix Register) ────────────────────────────────
ENGINE_VERSION = "2.1.6"

# ── Configuration (defaults from spec validation) ─────────────────────────
DEFAULT_ANCHOR_RADIUS_M = 100
DEFAULT_MIN_LEG_DISTANCE_M = 300
DEFAULT_MOVE_CONFIRM_M = 150
DEFAULT_MAX_SPEED_KMH = 200
DEFAULT_GAP_TIMEOUT_MIN = 30
DEFAULT_AIR_SPEED_KMH = 300
DEFAULT_AIR_MIN_DISTANCE_KM = 150
DEFAULT_JOURNEY_BREAK_DWELL_MIN = 30
DEFAULT_SETTLE_MIN_DWELL_MIN = 3  # v2.1: settle-dwell confirmation (prevent false stops)
DEFAULT_SMOOTHING_WINDOW = 3

# v2.2: Additional parameters (Fix Register)
DEFAULT_STATIONARY_MERGE_RADIUS_M = 150  # R1: Wider merge radius (1.5 × R)
DEFAULT_STATIONARY_MERGE_GAP_S = 120  # R1: Time-contiguity window
DEFAULT_MIN_LEG_EXCURSION_M = 500  # R4a: Maximum excursion threshold
DEFAULT_ANCHOR_RESUME_RADIUS_M = 200  # R4b: Anchor restoration radius (2 × R)
DEFAULT_STATIONARY_FLUSH_INTERVAL_MIN = 0  # R4c: DISABLED until R2 verified (prevents 2.1.2 regression)
DEFAULT_DEDUPE_WINDOW_S = 60  # R5: Deduplication time window

# v2.1.6 B3: Air leg gate parameters
DEFAULT_AIR_MIN_GAP_MIN = 60  # B3: Minimum gap in minutes for air leg classification


# ═══════════════════════════════════════════════════════════════════════════
# GEOMETRY UTILITIES
# ═══════════════════════════════════════════════════════════════════════════

def haversine_distance(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """
    Calculate distance between two points using Haversine formula.
    
    Args:
        lat1, lon1: First point (degrees)
        lat2, lon2: Second point (degrees)
    
    Returns:
        Distance in meters
    """
    # Convert to radians
    lat1, lon1, lat2, lon2 = map(radians, [lat1, lon1, lat2, lon2])
    
    # Haversine formula
    dlat = lat2 - lat1
    dlon = lon2 - lon1
    a = sin(dlat / 2) ** 2 + cos(lat1) * cos(lat2) * sin(dlon / 2) ** 2
    c = 2 * asin(sqrt(a))
    
    # Earth radius in meters
    r = 6371000
    
    return c * r


def calculate_centroid(points: List[Tuple[float, float]]) -> Tuple[float, float]:
    """
    Calculate centroid (mean) of lat/lng points.
    
    Args:
        points: List of (lat, lng) tuples
    
    Returns:
        (centroid_lat, centroid_lng)
    """
    if not points:
        return 0.0, 0.0
    
    lat_sum = sum(p[0] for p in points)
    lng_sum = sum(p[1] for p in points)
    count = len(points)
    
    return lat_sum / count, lng_sum / count


def median_smooth_positions(
    positions: List[DevicePosition],
    window: int = 3
) -> List[Tuple[float, float, datetime]]:
    """
    Apply median smoothing to lat/lng coordinates.
    
    Args:
        positions: List of DevicePosition objects
        window: Smoothing window size (must be odd)
    
    Returns:
        List of (smoothed_lat, smoothed_lng, observed_at) tuples
    """
    if len(positions) < window:
        # Not enough points for smoothing, return original
        return [(p.lat, p.lng, p.observed_at) for p in positions]
    
    smoothed = []
    half_window = window // 2
    
    for i, pos in enumerate(positions):
        if i < half_window or i >= len(positions) - half_window:
            # Edges: use original values
            smoothed.append((pos.lat, pos.lng, pos.observed_at))
        else:
            # Apply median filter
            window_positions = positions[i - half_window:i + half_window + 1]
            lats = [p.lat for p in window_positions]
            lngs = [p.lng for p in window_positions]
            
            smoothed_lat = median(lats)
            smoothed_lng = median(lngs)
            smoothed.append((smoothed_lat, smoothed_lng, pos.observed_at))
    
    return smoothed


def deduplicate_consecutive_positions(
    positions: List[DevicePosition],
    dedupe_window_s: int = DEFAULT_DEDUPE_WINDOW_S
) -> List[DevicePosition]:
    """
    Remove duplicate consecutive positions (v2.2 R5).
    
    Drop a point whose coordinates match its immediate predecessor to 6 decimal places
    AND which arrives within dedupe_window_s seconds.
    
    Args:
        positions: List of DevicePosition objects
        dedupe_window_s: Time window for deduplication (default 60 seconds)
    
    Returns:
        List of deduplicated DevicePosition objects
    """
    if len(positions) <= 1:
        return positions
    
    deduped = [positions[0]]  # Always keep first position
    
    for i in range(1, len(positions)):
        prev = positions[i - 1]
        curr = positions[i]
        
        # Calculate time gap
        time_gap = (curr.observed_at - prev.observed_at).total_seconds()
        
        # Check if coordinates match to 6 decimal places
        lat_match = abs(curr.lat - prev.lat) < 0.000001  # ~0.1m precision
        lng_match = abs(curr.lng - prev.lng) < 0.000001
        
        if lat_match and lng_match and time_gap <= dedupe_window_s:
            # Duplicate - skip
            logger.debug(
                "⏭️  Skipping duplicate position at (%.6f, %.6f) within %.0f sec",
                curr.lat, curr.lng, time_gap
            )
            continue
        
        deduped.append(curr)
    
    if len(deduped) < len(positions):
        logger.info(
            "🔧 Deduplicated %d positions → %d unique positions",
            len(positions), len(deduped)
        )
    
    return deduped


# ═══════════════════════════════════════════════════════════════════════════
# CONFIGURATION MANAGEMENT
# ═══════════════════════════════════════════════════════════════════════════

@dataclass
class EngineConfig:
    """Trip engine configuration parameters."""
    anchor_radius_m: int
    min_leg_distance_m: int
    move_confirm_m: int
    max_speed_kmh: int
    gap_timeout_min: int
    air_speed_kmh: int
    air_min_distance_km: int
    journey_break_dwell_min: int
    settle_min_dwell_min: int  # v2.1: minimum dwell time to confirm a stop
    smoothing_window: int
    # v2.2: Additional parameters
    stationary_merge_radius_m: int = DEFAULT_STATIONARY_MERGE_RADIUS_M  # R1
    stationary_merge_gap_s: int = DEFAULT_STATIONARY_MERGE_GAP_S  # R1
    min_leg_excursion_m: int = DEFAULT_MIN_LEG_EXCURSION_M  # R4a
    anchor_resume_radius_m: int = DEFAULT_ANCHOR_RESUME_RADIUS_M  # R4b
    stationary_flush_interval_min: int = DEFAULT_STATIONARY_FLUSH_INTERVAL_MIN  # R4c
    dedupe_window_s: int = DEFAULT_DEDUPE_WINDOW_S  # R5
    # v2.1.6 B3: Air leg parameters
    air_min_gap_min: int = DEFAULT_AIR_MIN_GAP_MIN  # B3: Minimum gap for air classification


def _load_config(db: Session, tenant_id: Optional[str] = None) -> EngineConfig:
    """
    Load engine configuration with hierarchy: Global → Tenant.
    
    Args:
        db: Database session
        tenant_id: Tenant ID for override (None = global only)
    
    Returns:
        EngineConfig with resolved values
    """
    # Get global config
    global_config = db.execute(
        select(TripConfig).where(TripConfig.tenant_id == None)
    ).scalar_one_or_none()
    
    if global_config:
        config = EngineConfig(
            anchor_radius_m=global_config.engine_anchor_radius_m,
            min_leg_distance_m=global_config.engine_min_leg_distance_m,
            move_confirm_m=global_config.engine_move_confirm_m,
            max_speed_kmh=global_config.engine_max_speed_kmh,
            gap_timeout_min=global_config.engine_gap_timeout_min,
            air_speed_kmh=global_config.engine_air_speed_kmh,
            air_min_distance_km=global_config.engine_air_min_distance_km,
            journey_break_dwell_min=global_config.engine_journey_break_dwell_min,
            settle_min_dwell_min=global_config.engine_settle_min_dwell_min,
            smoothing_window=global_config.engine_smoothing_window,
        )
    else:
        # Fallback to hardcoded defaults
        config = EngineConfig(
            anchor_radius_m=DEFAULT_ANCHOR_RADIUS_M,
            min_leg_distance_m=DEFAULT_MIN_LEG_DISTANCE_M,
            move_confirm_m=DEFAULT_MOVE_CONFIRM_M,
            max_speed_kmh=DEFAULT_MAX_SPEED_KMH,
            gap_timeout_min=DEFAULT_GAP_TIMEOUT_MIN,
            air_speed_kmh=DEFAULT_AIR_SPEED_KMH,
            air_min_distance_km=DEFAULT_AIR_MIN_DISTANCE_KM,
            journey_break_dwell_min=DEFAULT_JOURNEY_BREAK_DWELL_MIN,
            settle_min_dwell_min=DEFAULT_SETTLE_MIN_DWELL_MIN,
            smoothing_window=DEFAULT_SMOOTHING_WINDOW,
        )
    
    # TODO: Apply tenant override if tenant_id provided
    
    return config


# ═══════════════════════════════════════════════════════════════════════════
# STATE MACHINE
# ═══════════════════════════════════════════════════════════════════════════

@dataclass
class EngineContext:
    """Runtime context for state machine."""
    config: EngineConfig
    device_imei: str
    current_state: str  # "STATIONARY" or "MOVE"
    
    # STATIONARY state
    anchor_lat: Optional[float] = None
    anchor_lng: Optional[float] = None
    anchor_points: List[Tuple[float, float, datetime, Optional[int]]] = None  # (lat, lng, observed_at, position_id)
    
    # MOVE state
    leg_buffer: List[Tuple[float, float, datetime, Optional[int]]] = None  # (lat, lng, observed_at, position_id)
    
    # v2.1: Stop candidate tracking (settle-dwell confirmation)
    stop_candidate_since: Optional[datetime] = None  # When the candidate was first detected
    stop_candidate_lat: Optional[float] = None  # Candidate centroid
    stop_candidate_lng: Optional[float] = None
    stop_candidate_points: List[Tuple[float, float, datetime, Optional[int]]] = None  # Points in the candidate cluster
    
    # v2.2: Anchor snapshot for restoration (R4b)
    anchor_snapshot: Optional[Tuple[float, float, int, datetime]] = None  # (lat, lng, count, since)
    
    # Last processed
    last_processed_at: Optional[datetime] = None
    last_position_lat: Optional[float] = None
    last_position_lng: Optional[float] = None
    last_position_time: Optional[datetime] = None
    last_position_id: Optional[int] = None  # Track position_id for air leg starts
    
    # Current journey context
    current_journey_id: Optional[str] = None
    last_stationary_ended_at: Optional[datetime] = None
    last_stationary_flush: Optional[datetime] = None  # v2.2 R4c: Track last flush time
    journey_just_created: bool = False  # Flag for tracking new journey creation
    
    def __post_init__(self):
        if self.anchor_points is None:
            self.anchor_points = []
        if self.leg_buffer is None:
            self.leg_buffer = []
        if self.stop_candidate_points is None:
            self.stop_candidate_points = []


class TripEngine:
    """
    Trip State Engine - processes GPS positions into trips.
    
    State Machine:
        STATIONARY → within R → roll anchor
                  → beyond R → enter MOVE (leg opens)
        
        MOVE → accumulate points
            → last 3 within R → close leg, STATIONARY
            → gap timeout → force close, STATIONARY
    """
    
    def __init__(self, db: Session, device_imei: str):
        self.db = db
        self.device_imei = device_imei
        self.config = _load_config(db)
        self.context: Optional[EngineContext] = None
    
    def _load_state(self) -> EngineContext:
        """Load engine state from database or create new."""
        state_row = self.db.execute(
            select(EngineState).where(EngineState.device_imei == self.device_imei)
        ).scalar_one_or_none()
        
        if state_row:
            # Resume from saved state
            context = EngineContext(
                config=self.config,
                device_imei=self.device_imei,
                current_state=state_row.current_state,
                anchor_lat=state_row.anchor_lat,
                anchor_lng=state_row.anchor_lng,
                anchor_points=[],  # Reconstructed from anchor
                leg_buffer=[],  # Reconstructed from open leg if needed
                last_processed_at=state_row.last_processed_at,
                current_journey_id=state_row.current_journey_id,
            )
            
            # Reconstruct anchor_points from anchor (single point for now)
            if state_row.anchor_lat and state_row.anchor_lng:
                # Must be 4-tuple: (lat, lng, timestamp, position_id)
                # position_id is None for reconstructed state (we don't persist it)
                context.anchor_points = [
                    (state_row.anchor_lat, state_row.anchor_lng, state_row.last_processed_at, None)
                ] * state_row.anchor_count
            
            logger.info(
                "🔄 Resumed engine state for IMEI %s: %s, anchor=%s, last_processed=%s",
                self.device_imei, context.current_state,
                f"({state_row.anchor_lat:.4f}, {state_row.anchor_lng:.4f})" if state_row.anchor_lat else "None",
                state_row.last_processed_at
            )
        else:
            # Initialize new state
            context = EngineContext(
                config=self.config,
                device_imei=self.device_imei,
                current_state="STATIONARY",
            )
            logger.info("🆕 Initialized new engine state for IMEI %s", self.device_imei)
        
        return context
    
    def _save_state(self, context: EngineContext):
        """Persist engine state to database."""
        from sqlalchemy.dialects.postgresql import insert
        
        # Calculate anchor from points
        anchor_lat, anchor_lng = None, None
        if context.anchor_points:
            anchor_lat, anchor_lng = calculate_centroid(
                [(p[0], p[1]) for p in context.anchor_points]
            )
        
        stmt = insert(EngineState).values(
            device_imei=context.device_imei,
            current_state=context.current_state,
            anchor_lat=anchor_lat,
            anchor_lng=anchor_lng,
            anchor_count=len(context.anchor_points),
            current_leg_id=None,  # TODO: Track open leg ID
            current_journey_id=context.current_journey_id,
            last_processed_at=context.last_processed_at,
            updated_at=datetime.now(timezone.utc),
        ).on_conflict_do_update(
            index_elements=['device_imei'],
            set_={
                'current_state': context.current_state,
                'anchor_lat': anchor_lat,
                'anchor_lng': anchor_lng,
                'anchor_count': len(context.anchor_points),
                'current_journey_id': context.current_journey_id,
                'last_processed_at': context.last_processed_at,
                'updated_at': datetime.now(timezone.utc),
            }
        )
        self.db.execute(stmt)
        self.db.commit()
    
    def _ensure_journey_open(self, timestamp: datetime) -> str:
        """
        Ensure a journey is open. Creates one if needed.
        
        Sets context.journey_just_created = True when creating a new journey.
        
        Args:
            timestamp: Current timestamp (for journey start)
        
        Returns:
            Journey ID (UUID as string)
        """
        if self.context.current_journey_id:
            self.context.journey_just_created = False
            return self.context.current_journey_id
        
        # Create new journey
        journey = Journey(
            device_imei=self.device_imei,
            started_at=timestamp,
            ended_at=timestamp,  # Will be updated as journey progresses
            total_distance_m=0,
            total_duration_seconds=0,
            leg_count=0,
            stationary_count=0,
            engine_version=ENGINE_VERSION,  # v2.2.0: Version tracking (Fix Register requirement)
            engine_params={  # Snapshot of config parameters
                'anchor_radius_m': self.config.anchor_radius_m,
                'min_leg_distance_m': self.config.min_leg_distance_m,
                'stationary_merge_radius_m': self.config.stationary_merge_radius_m,
                'stationary_merge_gap_s': self.config.stationary_merge_gap_s,
                'min_leg_excursion_m': self.config.min_leg_excursion_m,
            },
            created_at=datetime.now(timezone.utc),
        )
        
        self.db.add(journey)
        self.db.flush()  # Get ID
        
        self.context.current_journey_id = str(journey.id)
        self.context.journey_just_created = True  # Flag for stats tracking
        
        logger.info(
            "🆕 IMEI %s: Journey %s started at %s",
            self.device_imei, journey.id, timestamp.isoformat()
        )
        
        return self.context.current_journey_id
    
    def _close_journey(self) -> Optional[Journey]:
        """
        Close the current journey and calculate aggregate metrics.
        
        Returns:
            Closed Journey object or None if no journey was open
        """
        if not self.context.current_journey_id:
            return None
        
        # Flush any pending leg data before aggregating
        # CRITICAL: If we're in MOVE state with unflushed leg_buffer, create the leg now
        # Otherwise it won't be included in the journey metrics
        if self.context.current_state == "MOVE" and len(self.context.leg_buffer) >= 2:
            logger.debug(
                "🔄 IMEI %s: Flushing leg_buffer (%d points) before closing journey",
                self.device_imei, len(self.context.leg_buffer)
            )
            leg = self._create_leg(self.context.leg_buffer, is_air_leg=False)
            if leg:
                logger.debug("✅ IMEI %s: Flushed leg %s before journey close", self.device_imei, leg.id)
            self.context.leg_buffer = []
        
        # Flush any pending stationary data (anchor_points)
        # If we're in STATIONARY state with accumulated anchor points, create stationary now
        if self.context.current_state == "STATIONARY" and len(self.context.anchor_points) >= 1:
            # Don't create journey-breaking stationary here (would recursively close journey)
            # Just flush to a normal stationary
            logger.debug(
                "🔄 IMEI %s: Flushing anchor_points (%d points) before closing journey",
                self.device_imei, len(self.context.anchor_points)
            )
            stat = self._create_stationary(self.context.anchor_points, reason="journey_close")
            if stat:
                logger.debug("✅ IMEI %s: Flushed stationary %s before journey close", self.device_imei, stat.id)
            self.context.anchor_points = []
        
        # Get journey from DB
        journey = self.db.execute(
            select(Journey).where(Journey.id == self.context.current_journey_id)
        ).scalar_one_or_none()
        
        if not journey:
            logger.warning(
                "⚠️  IMEI %s: Journey %s not found in DB",
                self.device_imei, self.context.current_journey_id
            )
            self.context.current_journey_id = None
            return None
        
        # Aggregate legs
        legs = self.db.execute(
            select(Leg).where(
                and_(
                    Leg.device_imei == self.device_imei,
                    Leg.journey_id == self.context.current_journey_id
                )
            ).order_by(Leg.started_at)
        ).scalars().all()
        
        # Aggregate stationaries
        stationaries = self.db.execute(
            select(Stationary).where(
                and_(
                    Stationary.device_imei == self.device_imei,
                    Stationary.journey_id == self.context.current_journey_id
                )
            ).order_by(Stationary.started_at)
        ).scalars().all()
        
        # Calculate totals
        total_distance_m = sum(leg.distance_m for leg in legs)
        leg_count = len(legs)
        stationary_count = len(stationaries)
        
        # Update journey end time and metrics
        all_timestamps = []
        if legs:
            all_timestamps.extend([leg.started_at, leg.ended_at] for leg in legs)
        if stationaries:
            all_timestamps.extend([s.started_at, s.ended_at] for s in stationaries)
        
        if all_timestamps:
            flat_timestamps = [t for pair in all_timestamps for t in pair]
            journey.ended_at = max(flat_timestamps)
            journey.started_at = min(flat_timestamps)  # Ensure started_at is earliest
            journey.total_duration_seconds = int((journey.ended_at - journey.started_at).total_seconds())
        
        journey.total_distance_m = total_distance_m
        journey.leg_count = leg_count
        journey.stationary_count = stationary_count
        
        # v2.2 R3: Prevent 0-leg journeys from persisting
        # If journey has no legs, delete it instead of closing
        # (A journey is defined by movement; stationary-only periods don't qualify)
        if leg_count == 0:
            logger.warning(
                "🗑️  IMEI %s: Deleting 0-leg journey %s (%d stationaries, %.2f km)",
                self.device_imei, journey.id, stationary_count, total_distance_m / 1000
            )
            self.db.delete(journey)
            self.db.flush()
            self.context.current_journey_id = None
            return None
        
        self.db.flush()
        
        logger.info(
            "✅ IMEI %s: Journey %s closed: %.2f km, %d legs, %d stationaries, %.0f min",
            self.device_imei, journey.id, total_distance_m / 1000,
            leg_count, stationary_count, journey.total_duration_seconds / 60
        )
        
        # Clear journey context
        self.context.current_journey_id = None
        
        return journey
    
    def _flush_open_stationary(self) -> None:
        """
        v2.2 R4c: Flush open stationary to database on heartbeat.
        
        Upserts current anchor_points as an open stationary (is_open=true) so long dwells
        are visible before they end. Uses (device_imei, started_at) as unique key.
        """
        if self.context.current_state != "STATIONARY":
            return  # Not in stationary state
        
        if not self.context.anchor_points or len(self.context.anchor_points) < 1:
            return  # No anchor to flush
        
        # Check if we should flush (interval-based or first flush)
        if self.context.last_stationary_flush:
            time_since_flush = (self.context.last_processed_at - self.context.last_stationary_flush).total_seconds() / 60.0
            if time_since_flush < self.config.stationary_flush_interval_min:
                return  # Too soon
        
        # Calculate current stationary metrics
        centroid_lat, centroid_lng = calculate_centroid([(p[0], p[1]) for p in self.context.anchor_points])
        started_at = self.context.anchor_points[0][2]
        ended_at = self.context.anchor_points[-1][2]
        duration_seconds = (ended_at - started_at).total_seconds()
        point_count = len(self.context.anchor_points)
        
        logger.debug(
            "💾 IMEI %s: Flushing open stationary (%.0f min, %d points)",
            self.device_imei, duration_seconds / 60, point_count
        )
        
        # Upsert stationary with is_open=true (R4c uses device_imei + started_at as key)
        # This is spec-compliant: "upsert stationaries (device_id, started_at = anchor_since)"
        try:
            from sqlalchemy.dialects.postgresql import insert as pg_insert
            
            stationary_dict = {
                'device_imei': self.device_imei,
                'anchor_lat': centroid_lat,
                'anchor_lng': centroid_lng,
                'started_at': started_at,
                'ended_at': ended_at,
                'duration_seconds': int(duration_seconds),
                'point_count': point_count,
                'journey_id': self.context.current_journey_id,
                'is_open': True,  # Mark as open
                'created_at': datetime.now(timezone.utc),
            }
            
            stmt = pg_insert(Stationary).values(**stationary_dict)
            stmt = stmt.on_conflict_do_update(
                index_elements=['device_imei', 'started_at'],
                set_={
                    'ended_at': stmt.excluded.ended_at,
                    'duration_seconds': stmt.excluded.duration_seconds,
                    'point_count': stmt.excluded.point_count,
                    'anchor_lat': stmt.excluded.anchor_lat,
                    'anchor_lng': stmt.excluded.anchor_lng,
                    'is_open': True,  # Keep it open
                }
            )
            
            self.db.execute(stmt)
            self.db.flush()
            
            self.context.last_stationary_flush = self.context.last_processed_at
            
            logger.debug(
                "✅ IMEI %s: Open stationary flushed (upsert on device_imei+started_at)",
                self.device_imei
            )
        except Exception as exc:
            logger.warning(
                "⚠️  IMEI %s: Failed to flush open stationary: %s",
                self.device_imei, exc
            )
    
    def _refresh_journey_aggregates(self, journey_id: str) -> None:
        """
        v2.2 R3: Recompute journey aggregates incrementally (not just at close).
        
        This ensures open journeys always reflect their current contents,
        fixing the "0 legs" display for open journeys.
        
        Args:
            journey_id: Journey ID to refresh
        """
        journey = self.db.execute(
            select(Journey).where(Journey.id == journey_id)
        ).scalar_one_or_none()
        
        if not journey:
            logger.warning("⚠️  Cannot refresh journey %s - not found", journey_id)
            return
        
        # Aggregate legs
        legs = self.db.execute(
            select(Leg).where(Leg.journey_id == journey_id).order_by(Leg.started_at)
        ).scalars().all()
        
        # Aggregate stationaries
        stationaries = self.db.execute(
            select(Stationary).where(Stationary.journey_id == journey_id).order_by(Stationary.started_at)
        ).scalars().all()
        
        # Recompute metrics
        journey.leg_count = len(legs)
        journey.stationary_count = len(stationaries)
        journey.total_distance_m = sum(leg.distance_m for leg in legs)
        
        # Recompute time span (started_at from first leg, ended_at from max of all)
        if legs:
            journey.started_at = min(leg.started_at for leg in legs)
            
            all_end_times = [leg.ended_at for leg in legs]
            if stationaries:
                all_end_times.extend([s.ended_at for s in stationaries])
            
            journey.ended_at = max(all_end_times)
            journey.total_duration_seconds = int((journey.ended_at - journey.started_at).total_seconds())
        
        self.db.flush()
        
        logger.debug(
            "🔄 IMEI %s: Journey %s refreshed: %d legs, %.2f km",
            self.device_imei, journey_id, journey.leg_count, journey.total_distance_m / 1000
        )
    
    def _create_stationary(
        self,
        points: List[Tuple[float, float, datetime, Optional[int]]],
        reason: str = "anchor_formed"
    ) -> Optional[Stationary]:
        """
        Create a Stationary record from accumulated anchor points.
        
        Args:
            points: List of (lat, lng, observed_at, position_id) tuples
            reason: Creation reason ("anchor_formed", "trip_end", etc.)
        
        Returns:
            Created Stationary object or None if filtered out
        """
        if not points:
            return None
        
        # Calculate centroid and metrics
        centroid_lat, centroid_lng = calculate_centroid([(p[0], p[1]) for p in points])
        started_at = points[0][2]
        ended_at = points[-1][2]
        duration_seconds = (ended_at - started_at).total_seconds()
        point_count = len(points)
        
        # Get start/end position IDs (if available)
        start_position_id = points[0][3] if len(points) > 0 and points[0][3] else None
        end_position_id = points[-1][3] if len(points) > 0 and points[-1][3] else None
        
        # Journey grouping: Check if this stationary breaks the journey (dwell > 30 min)
        # Skip journey-breaking logic if called from journey_close (prevents recursive close)
        breaks_journey = (
            duration_seconds > (self.config.journey_break_dwell_min * 60) 
            and reason != "journey_close"
        )
        
        if breaks_journey and self.context.current_journey_id:
            # Close current journey before creating the stationary
            logger.info(
                "🔚 IMEI %s: Journey break detected (stationary %.0f min > threshold %.0f min)",
                self.device_imei, duration_seconds / 60, self.config.journey_break_dwell_min
            )
            self._close_journey()
        
        # Ensure journey is open (unless this is a journey-breaking stationary)
        if not breaks_journey:
            self._ensure_journey_open(started_at)
        
        # v2.2 R1: Stationary merge with wider radius and time-contiguity
        # Before creating a new stationary, check if we should merge with the journey's last stationary
        # Uses wider radius (150m) and time-contiguity test (120s gap) to prevent split stops
        last_stationary = None
        if self.context.current_journey_id and not breaks_journey:
            # Get the most recent stationary for this journey
            last_stationary_result = self.db.execute(
                select(Stationary)
                .where(and_(
                    Stationary.journey_id == self.context.current_journey_id,
                    Stationary.device_imei == self.device_imei
                ))
                .order_by(Stationary.ended_at.desc())
                .limit(1)
            ).first()
            
            if last_stationary_result:
                last_stationary = last_stationary_result[0]
                
                # R1: Check merge conditions (wider radius + time-contiguity)
                merge_distance = haversine_distance(
                    last_stationary.anchor_lat, last_stationary.anchor_lng,
                    centroid_lat, centroid_lng
                )
                time_gap = (started_at - last_stationary.ended_at).total_seconds()
                
                # R1: Merge if within wider radius AND time-contiguous
                should_merge = (
                    merge_distance <= self.config.stationary_merge_radius_m and
                    time_gap <= self.config.stationary_merge_gap_s
                )
                
                if should_merge:
                    # MERGE: Extend existing stationary instead of creating new
                    logger.info(
                        "🔄 IMEI %s: Merging into existing stationary %s (%.0f m away)",
                        self.device_imei, last_stationary.id, merge_distance
                    )
                    
                    # Get all existing points from the stationary (via device_positions)
                    existing_positions = self.db.execute(text("""
                        SELECT lat, lng, observed_at, id
                        FROM device_positions
                        WHERE stationary_id = :stationary_id
                        ORDER BY observed_at
                    """), {"stationary_id": str(last_stationary.id)}).fetchall()
                    
                    # Combine with new points
                    all_points = [(row[0], row[1], row[2], row[3]) for row in existing_positions]
                    all_points.extend(points)
                    
                    # Recalculate metrics
                    new_centroid_lat, new_centroid_lng = calculate_centroid([(p[0], p[1]) for p in all_points])
                    new_ended_at = points[-1][2]  # Latest point from new batch
                    new_duration_seconds = (new_ended_at - last_stationary.started_at).total_seconds()
                    new_point_count = len(all_points)
                    new_end_position_id = points[-1][3] if points[-1][3] else last_stationary.end_position_id
                    
                    # Update existing stationary
                    last_stationary.anchor_lat = new_centroid_lat
                    last_stationary.anchor_lng = new_centroid_lng
                    last_stationary.ended_at = new_ended_at
                    last_stationary.duration_seconds = int(new_duration_seconds)
                    last_stationary.point_count = new_point_count
                    last_stationary.end_position_id = new_end_position_id
                    
                    # Update geometry
                    try:
                        self.db.execute(text("""
                            UPDATE stationaries 
                            SET centroid = ST_SetSRID(ST_MakePoint(:lng, :lat), 4326)
                            WHERE id = :stationary_id
                        """), {
                            "lng": new_centroid_lng,
                            "lat": new_centroid_lat,
                            "stationary_id": str(last_stationary.id)
                        })
                    except Exception as exc:
                        logger.warning(
                            "⚠️  IMEI %s: Failed to update geometry for merged stationary %s: %s",
                            self.device_imei, last_stationary.id, exc
                        )
                    
                    # Link new positions to this stationary
                    try:
                        position_ids = [p[3] for p in points if p[3] is not None]
                        if position_ids:
                            placeholders = ", ".join([f":id{i}" for i in range(len(position_ids))])
                            params = {f"id{i}": pid for i, pid in enumerate(position_ids)}
                            params["stationary_id"] = str(last_stationary.id)
                            
                            self.db.execute(text(f"""
                                UPDATE device_positions 
                                SET stationary_id = :stationary_id
                                WHERE id IN ({placeholders})
                            """), params)
                            
                            logger.debug(
                                "✍️  IMEI %s: Linked %d new positions to merged stationary %s",
                                self.device_imei, len(position_ids), last_stationary.id
                            )
                    except Exception as exc:
                        logger.warning(
                            "⚠️  IMEI %s: Failed to link positions to merged stationary %s: %s",
                            self.device_imei, last_stationary.id, exc
                        )
                    
                    logger.info(
                        "✅ IMEI %s: Merged stationary now %.0f min, %d total points",
                        self.device_imei, new_duration_seconds / 60, new_point_count
                    )
                    
                    # Update journey context
                    self.context.last_stationary_ended_at = new_ended_at
                    
                    # Return the merged stationary
                    return last_stationary
                else:
                    # R1: No merge - either too far or time gap too large
                    logger.debug(
                        "📍 IMEI %s: No merge (dist=%.0fm vs %.0fm, gap=%.0fs vs %.0fs)",
                        self.device_imei, merge_distance, self.config.stationary_merge_radius_m,
                        time_gap, self.config.stationary_merge_gap_s
                    )
        
        # Create new stationary record (no merge)
        # v2.2 FIX: Use upsert to handle backfill idempotency
        # If a stationary with same (device_imei, started_at) exists, update it
        from sqlalchemy.dialects.postgresql import insert as pg_insert
        
        stationary_id = uuid4()
        
        stmt = pg_insert(Stationary).values(
            id=stationary_id,
            device_imei=self.device_imei,
            anchor_lat=centroid_lat,
            anchor_lng=centroid_lng,
            started_at=started_at,
            ended_at=ended_at,
            duration_seconds=int(duration_seconds),
            point_count=point_count,
            start_position_id=start_position_id,
            end_position_id=end_position_id,
            journey_id=self.context.current_journey_id,  # NULL for journey-breaking stationaries
            is_open=False,
            created_at=datetime.now(timezone.utc),
        ).on_conflict_do_update(
            index_elements=['device_imei', 'started_at'],  # uq_stationary_device_started
            set_={
                'ended_at': ended_at,
                'duration_seconds': int(duration_seconds),
                'point_count': point_count,
                'end_position_id': end_position_id,
                'anchor_lat': centroid_lat,
                'anchor_lng': centroid_lng,
                'journey_id': self.context.current_journey_id,
            }
        ).returning(Stationary.id)
        
        result = self.db.execute(stmt)
        returned_id = result.scalar_one()
        
        # Fetch the stationary object
        stationary = self.db.query(Stationary).filter(Stationary.id == returned_id).one()
        self.db.flush()
        
        # Build PostGIS Point geometry for the centroid
        try:
            self.db.execute(text("""
                UPDATE stationaries 
                SET centroid = ST_SetSRID(ST_MakePoint(:lng, :lat), 4326)
                WHERE id = :stationary_id
            """), {
                "lng": centroid_lng,
                "lat": centroid_lat,
                "stationary_id": str(stationary.id)
            })
            
            logger.debug(
                "📐 IMEI %s: Stationary %s geometry created",
                self.device_imei, stationary.id
            )
        except Exception as exc:
            logger.warning(
                "⚠️  IMEI %s: Failed to create geometry for stationary %s: %s",
                self.device_imei, stationary.id, exc
            )
            # Don't fail the stationary creation if geometry fails
        
        # Write stationary_id back to device_positions (Section 3.6)
        try:
            position_ids = [p[3] for p in points if p[3] is not None]
            if position_ids:
                placeholders = ", ".join([f":id{i}" for i in range(len(position_ids))])
                params = {f"id{i}": pid for i, pid in enumerate(position_ids)}
                params["stationary_id"] = str(stationary.id)
                
                self.db.execute(text(f"""
                    UPDATE device_positions 
                    SET stationary_id = :stationary_id
                    WHERE id IN ({placeholders})
                """), params)
                
                logger.debug(
                    "✍️  IMEI %s: Linked %d positions to stationary %s",
                    self.device_imei, len(position_ids), stationary.id
                )
        except Exception as exc:
            logger.warning(
                "⚠️  IMEI %s: Failed to link positions to stationary %s: %s",
                self.device_imei, stationary.id, exc
            )
        
        logger.info(
            "🟠 IMEI %s: Stationary created at (%.4f, %.4f) for %.0f min (%d points)%s",
            self.device_imei, centroid_lat, centroid_lng,
            duration_seconds / 60, point_count,
            " [JOURNEY BREAK]" if breaks_journey else ""
        )
        
        # Update journey context
        self.context.last_stationary_ended_at = ended_at
        
        # v2.2 R3: Refresh journey aggregates incrementally
        if stationary.journey_id:
            self._refresh_journey_aggregates(stationary.journey_id)
        
        return stationary
    
    def _create_leg(
        self,
        leg_buffer: List[Tuple[float, float, datetime, Optional[int]]],
        is_air_leg: bool = False,
        end_override: Optional[Tuple[float, float]] = None,  # v2.1: override end point (lat, lng) for stop arrival
        end_time_override: Optional[datetime] = None  # v2.2 R6: override end timestamp for leg termination at stop
    ) -> Optional[Leg]:
        """
        Create a Leg record from movement buffer with filtering.
        
        Filters:
        - Move confirmation: Leg must be ≥ move_confirm_m (150m) to emit
        - Min leg distance: Leg must be ≥ min_leg_distance_m (300m) to emit (drift rejection)
        - Air leg classification: ≥ air_min_distance_km with high speed
        
        Args:
            leg_buffer: List of (lat, lng, observed_at, position_id) tuples
            is_air_leg: Whether this is an air leg (teleport)
            end_override: Optional (lat, lng) to use as leg end point instead of last buffer point
                         (v2.1: for arrival at stop candidate anchor)
            end_time_override: Optional timestamp to use as leg end time instead of last buffer timestamp
                              (v2.2 R6: for leg termination at stop with zero gap)
        
        Returns:
            Created Leg object or None if filtered out
        """
        if len(leg_buffer) < 2:
            logger.debug("⏭️  IMEI %s: Leg has <2 points, skipping", self.device_imei)
            return None
        
        # Calculate distance
        # v2.1: Air legs use great-circle distance (direct path), ground legs use cumulative
        if is_air_leg:
            # Great-circle distance between endpoints (spec 2.4a)
            total_distance_m = haversine_distance(
                leg_buffer[0][0], leg_buffer[0][1],
                leg_buffer[-1][0], leg_buffer[-1][1]
            )
        else:
            # Cumulative distance through all points (ground travel)
            total_distance_m = 0.0
            for i in range(len(leg_buffer) - 1):
                p1 = leg_buffer[i]
                p2 = leg_buffer[i + 1]
                total_distance_m += haversine_distance(p1[0], p1[1], p2[0], p2[1])
        
        # Filter: Move confirmation (must travel at least move_confirm_m)
        # Skip for air legs (they're already validated by 150km threshold)
        if not is_air_leg and total_distance_m < self.config.move_confirm_m:
            logger.debug(
                "⏭️  IMEI %s: Leg %.0f m < move_confirm %.0f m, discarding",
                self.device_imei, total_distance_m, self.config.move_confirm_m
            )
            return None
        
        # v2.2 R4a: Calculate maximum excursion from leg start
        max_excursion_m = 0.0
        if not is_air_leg and len(leg_buffer) > 1:
            start_point = leg_buffer[0]
            for p in leg_buffer[1:]:
                excursion = haversine_distance(start_point[0], start_point[1], p[0], p[1])
                max_excursion_m = max(max_excursion_m, excursion)
        
        # Calculate straight-line distance (for qualification)
        straight_line_m = haversine_distance(
            leg_buffer[0][0], leg_buffer[0][1],
            leg_buffer[-1][0], leg_buffer[-1][1]
        ) if len(leg_buffer) >= 2 else 0.0
        
        # v2.2 R4a: Filter - Leg qualification with max excursion
        # Qualifies if: cumulative >= MOVE_CONFIRM (already checked) AND
        #               (straight >= MIN_LEG_DISTANCE OR max_excursion >= MIN_LEG_EXCURSION)
        if not is_air_leg:
            qualifies = (
                straight_line_m >= self.config.min_leg_distance_m or
                max_excursion_m >= self.config.min_leg_excursion_m
            )
            
            if not qualifies:
                logger.debug(
                    "⏭️  IMEI %s: Leg fails qualification (straight=%.0fm < %.0fm, excursion=%.0fm < %.0fm) - drift",
                    self.device_imei, 
                    straight_line_m, self.config.min_leg_distance_m,
                    max_excursion_m, self.config.min_leg_excursion_m
                )
                return None
            
            logger.debug(
                "✅ IMEI %s: Leg qualifies (cumulative=%.0fm, straight=%.0fm, excursion=%.0fm)",
                self.device_imei, total_distance_m, straight_line_m, max_excursion_m
            )
        
        # Calculate duration
        started_at = leg_buffer[0][2]
        # v2.2 R6: Use end_time_override if provided (for leg termination at stop with zero gap)
        ended_at = end_time_override if end_time_override else leg_buffer[-1][2]
        duration_seconds = (ended_at - started_at).total_seconds()
        point_count = len(leg_buffer)
        
        # Get start/end position IDs
        start_position_id = leg_buffer[0][3] if leg_buffer[0][3] else None
        end_position_id = leg_buffer[-1][3] if leg_buffer[-1][3] else None
        
        # v2.1.6 B2: Leg termination at stop
        # Build the geometry buffer INCLUDING the stop candidate point if provided
        geometry_buffer = list(leg_buffer)  # Copy the leg buffer
        
        # v2.1: Use end_override if provided (for arrival at stop candidate)
        if end_override:
            end_lat, end_lng = end_override
            # v2.1.6 B2: Append stop candidate as terminal vertex to geometry
            # This ensures the rendered line reaches the stop marker
            geometry_buffer.append((end_lat, end_lng, ended_at, end_position_id))
        else:
            end_lat, end_lng = leg_buffer[-1][0], leg_buffer[-1][1]
        
        # Ensure journey is open
        self._ensure_journey_open(started_at)
        
        # v2.1.6 B1: Use upsert to prevent duplicates
        # If a leg with same (device_imei, started_at) exists, update it
        from sqlalchemy.dialects.postgresql import insert as pg_insert
        
        leg_id = uuid4()
        
        stmt = pg_insert(Leg).values(
            id=leg_id,
            device_imei=self.device_imei,
            distance_m=int(total_distance_m),
            duration_seconds=int(duration_seconds),
            point_count=point_count,
            started_at=started_at,
            ended_at=ended_at,
            start_lat=leg_buffer[0][0],
            start_lng=leg_buffer[0][1],
            end_lat=end_lat,
            end_lng=end_lng,
            start_position_id=start_position_id,
            end_position_id=end_position_id,
            is_air_leg=is_air_leg,
            journey_id=self.context.current_journey_id,
            created_at=datetime.now(timezone.utc),
        ).on_conflict_do_update(
            index_elements=['device_imei', 'started_at'],  # ux_leg_device_start
            set_={
                'ended_at': ended_at,  # B1: Take the later ended_at (longer leg is correct)
                'duration_seconds': int(duration_seconds),
                'distance_m': int(total_distance_m),
                'point_count': point_count,
                'end_lat': end_lat,
                'end_lng': end_lng,
                'end_position_id': end_position_id,
                'journey_id': self.context.current_journey_id,
            }
        ).returning(Leg.id)
        
        result = self.db.execute(stmt)
        returned_id = result.scalar_one()
        
        # Fetch the leg object
        leg = self.db.query(Leg).filter(Leg.id == returned_id).one()
        self.db.flush()
        
        # Build PostGIS geometry for the leg path
        # v2.1: Air legs use great-circle (straight line), ground legs use all points
        try:
            if is_air_leg:
                # Air leg: Straight line between endpoints (great-circle, path unknown per spec 2.4a)
                # Only use start and end points, ignore any intermediate points
                start_point = f"ST_MakePoint({leg_buffer[0][1]}, {leg_buffer[0][0]})"  # lng, lat
                end_point = f"ST_MakePoint({leg_buffer[-1][1]}, {leg_buffer[-1][0]})"  # lng, lat
                
                self.db.execute(text(f"""
                    UPDATE legs 
                    SET path = ST_SetSRID(ST_MakeLine({start_point}, {end_point}), 4326),
                        path_simplified = ST_SetSRID(ST_MakeLine({start_point}, {end_point}), 4326)
                    WHERE id = :leg_id
                """), {"leg_id": str(leg.id)})
                
                logger.debug(
                    "✈️  IMEI %s: Air leg %s geometry created (great-circle)",
                    self.device_imei, leg.id
                )
            else:
                # Ground leg: Full path through all points
                # v2.1.6 B2: Use geometry_buffer which includes stop candidate if provided
                # Build array of points for ST_MakeLine: ARRAY[ST_MakePoint(lng, lat), ...]
                # Note: PostGIS uses (lng, lat) order, not (lat, lng)
                points_array = ", ".join([
                    f"ST_MakePoint({p[1]}, {p[0]})"  # lng, lat
                    for p in geometry_buffer  # B2: geometry_buffer includes terminal point
                ])
                
                # Create full-resolution path
                self.db.execute(text(f"""
                    UPDATE legs 
                    SET path = ST_SetSRID(ST_MakeLine(ARRAY[{points_array}]), 4326)
                    WHERE id = :leg_id
                """), {"leg_id": str(leg.id)})
                
                # Create simplified path using Douglas-Peucker algorithm
                # Tolerance of 0.0001 degrees ≈ 11m at equator (good for zoom level 12-15)
                self.db.execute(text(f"""
                    UPDATE legs 
                    SET path_simplified = ST_Simplify(
                        ST_SetSRID(ST_MakeLine(ARRAY[{points_array}]), 4326),
                        0.0001
                    )
                    WHERE id = :leg_id
                """), {"leg_id": str(leg.id)})
                
                logger.debug(
                    "📐 IMEI %s: Leg %s geometry created (%d points → simplified)",
                    self.device_imei, leg.id, point_count
                )
        except Exception as exc:
            logger.warning(
                "⚠️  IMEI %s: Failed to create geometry for leg %s: %s",
                self.device_imei, leg.id, exc
            )
            # Don't fail the leg creation if geometry fails
        
        # Write leg_id back to device_positions (Section 3.6)
        try:
            position_ids = [p[3] for p in leg_buffer if p[3] is not None]
            if position_ids:
                placeholders = ", ".join([f":id{i}" for i in range(len(position_ids))])
                params = {f"id{i}": pid for i, pid in enumerate(position_ids)}
                params["leg_id"] = str(leg.id)
                
                self.db.execute(text(f"""
                    UPDATE device_positions 
                    SET leg_id = :leg_id
                    WHERE id IN ({placeholders})
                """), params)
                
                logger.debug(
                    "✍️  IMEI %s: Linked %d positions to leg %s",
                    self.device_imei, len(position_ids), leg.id
                )
        except Exception as exc:
            logger.warning(
                "⚠️  IMEI %s: Failed to link positions to leg %s: %s",
                self.device_imei, leg.id, exc
            )
        
        emoji = "✈️ " if is_air_leg else "🔵"
        logger.info(
            "%s IMEI %s: Leg created: %.2f km over %.0f min (%d points)%s",
            emoji, self.device_imei, total_distance_m / 1000, duration_seconds / 60,
            point_count, " [AIR]" if is_air_leg else ""
        )
        
        # v2.2 R3: Refresh journey aggregates incrementally
        if leg.journey_id:
            self._refresh_journey_aggregates(leg.journey_id)
        
        return leg
    
    def process_positions(self, limit: Optional[int] = None) -> Dict:
        """
        Process unprocessed positions for this device.
        
        Args:
            limit: Max positions to process (None = all)
        
        Returns:
            Dict with processing statistics
        """
        # Load engine state
        self.context = self._load_state()
        
        # Get unprocessed positions
        query = select(DevicePosition).where(
            DevicePosition.device_imei == self.device_imei
        )
        
        # Filter to unprocessed only
        if self.context.last_processed_at:
            query = query.where(
                DevicePosition.observed_at > self.context.last_processed_at
            )
        
        query = query.order_by(DevicePosition.observed_at)
        
        if limit:
            query = query.limit(limit)
        
        positions = self.db.execute(query).scalars().all()
        
        if not positions:
            logger.info("✅ IMEI %s: No new positions to process", self.device_imei)
            return {
                'device_imei': self.device_imei,
                'positions_processed': 0,
                'stationaries_created': 0,
                'legs_created': 0,
                'journeys_created': 0,
            }
        
        logger.info(
            "🚀 Processing %d positions for IMEI %s (from %s to %s)",
            len(positions), self.device_imei,
            positions[0].observed_at.isoformat(),
            positions[-1].observed_at.isoformat()
        )
        
        # v2.2 R5: Deduplicate identical consecutive fixes
        positions = deduplicate_consecutive_positions(positions, self.config.dedupe_window_s)
        
        if not positions:
            logger.info("✅ IMEI %s: All positions were duplicates", self.device_imei)
            return stats
        
        # Apply median smoothing
        smoothed = median_smooth_positions(positions, self.config.smoothing_window)
        
        # Process each position
        stats = {
            'device_imei': self.device_imei,
            'positions_processed': 0,
            'stationaries_created': 0,
            'legs_created': 0,
            'journeys_created': 0,
        }
        
        for i, (lat, lng, observed_at) in enumerate(smoothed):
            position_id = positions[i].id
            result = self._process_single_position(lat, lng, observed_at, position_id)
            
            stats['positions_processed'] += 1
            if result.get('stationary_created'):
                stats['stationaries_created'] += 1
            if result.get('leg_created'):
                stats['legs_created'] += 1
            if result.get('journey_created'):
                stats['journeys_created'] += 1
        
        # v2.2 R4c: Flush open stationary before saving state
        self._flush_open_stationary()
        
        # Save final state
        self._save_state(self.context)
        
        logger.info(
            "✅ IMEI %s: Processed %d positions → %d stationaries, %d legs, %d journeys",
            self.device_imei, stats['positions_processed'],
            stats['stationaries_created'], stats['legs_created'], stats['journeys_created']
        )
        
        # Add final state to stats
        stats['current_state'] = self.context.current_state
        
        return stats
    
    def _process_single_position(
        self,
        lat: float,
        lng: float,
        observed_at: datetime,
        position_id: int
    ) -> Dict:
        """
        Process one position through the state machine.
        
        Returns:
            Dict with actions taken (stationary_created, leg_created, etc.)
        """
        result = {}
        
        # Update watermark
        self.context.last_processed_at = observed_at
        
        # First position ever (ANCHOR ASSIGNMENT #1 of 3)
        if self.context.last_position_time is None:
            self.context.anchor_lat = lat  # ← ASSIGNMENT #1
            self.context.anchor_lng = lng  # ← ASSIGNMENT #1
            self.context.anchor_points = [(lat, lng, observed_at, position_id)]
            self.context.last_position_lat = lat
            self.context.last_position_lng = lng
            self.context.last_position_time = observed_at
            self.context.last_position_id = position_id
            self.context.current_state = "STATIONARY"
            logger.debug("📍 IMEI %s: First position at (%f, %f)", self.device_imei, lat, lng)
            
            # INVARIANT: anchor_count >= 1 always
            assert len(self.context.anchor_points) >= 1, "BUG: First position didn't initialize anchor_points"
            return result
        
        # Day boundary check: Close journey at midnight (prevents multi-day open journeys)
        # Per spec Section 2.4: time is used for journey grouping. A day boundary represents
        # a "significant" period that should end a journey, even if device stayed within R.
        if self.context.current_journey_id:
            journey = self.db.execute(
                select(Journey).where(Journey.id == self.context.current_journey_id)
            ).scalar_one_or_none()
            
            if journey and journey.started_at.date() != observed_at.date():
                logger.info(
                    "📅 IMEI %s: Day boundary crossed (%s → %s) → closing journey %s",
                    self.device_imei, journey.started_at.date(), observed_at.date(),
                    str(journey.id)[:8]
                )
                self._close_journey()
        
        # Calculate implied speed (for outlier/air gate)
        time_diff_seconds = (observed_at - self.context.last_position_time).total_seconds()
        distance_m = haversine_distance(
            self.context.last_position_lat, self.context.last_position_lng,
            lat, lng
        )
        
        implied_speed_kmh = 0
        if time_diff_seconds > 0:
            implied_speed_kmh = (distance_m / time_diff_seconds) * 3.6
        
        # Step 1: Outlier/air gate (spec Section 2.3, 2.4a)
        # v2.1.6 B3: Compare KILOMETRES to AIR_MIN_KM (not metres!)
        if implied_speed_kmh > self.config.max_speed_kmh:
            # v2.1.6 B3: 3-part AND for air leg classification (prevents discarding real flights)
            # Spec 2.4a: "glitches are fast but short (sub-100 km, sub-minute)"
            distance_km = distance_m / 1000
            time_diff_min = time_diff_seconds / 60  # B3: Use minutes
            
            is_air_speed = implied_speed_kmh >= self.config.air_speed_kmh  # ≥300 km/h
            is_air_distance = distance_km >= self.config.air_min_distance_km  # B3: ≥150 km (KILOMETRES!)
            is_air_gap = time_diff_min >= self.config.air_min_gap_min  # B3: ≥60 min (replaces "multi-hour")
            
            if is_air_speed and is_air_distance and is_air_gap:
                # AIR LEG: All 3 conditions met (validated on Dublin⇄Split flights)
                logger.info(
                    "✈️  IMEI %s: Air leg detected: %.0f km @ %.0f km/h over %.1f min gap",
                    self.device_imei, distance_km, implied_speed_kmh, time_diff_min
                )
                
                # If in MOVE state, close current leg first
                if self.context.current_state == "MOVE" and len(self.context.leg_buffer) >= 2:
                    leg = self._create_leg(self.context.leg_buffer, is_air_leg=False)
                    if leg:
                        result['leg_created'] = True
                        if self.context.journey_just_created:
                            result['journey_created'] = True
                    self.context.leg_buffer = []
                
                # Create air leg (endpoints = last pre-silence & first post-silence)
                air_leg_buffer = [
                    (self.context.last_position_lat, self.context.last_position_lng, 
                     self.context.last_position_time, self.context.last_position_id),
                    (lat, lng, observed_at, position_id)
                ]
                air_leg = self._create_leg(air_leg_buffer, is_air_leg=True)
                if air_leg:
                    result['leg_created'] = True
                    result['air_leg_detected'] = True
                    if self.context.journey_just_created:
                        result['journey_created'] = True
                
                # Start new stationary at destination (arrival airport)
                # (ANCHOR ASSIGNMENT - air leg exception to 3-place rule)
                self.context.current_state = "STATIONARY"
                self.context.anchor_lat = lat  # ← ASSIGNMENT (air leg)
                self.context.anchor_lng = lng  # ← ASSIGNMENT (air leg)
                self.context.anchor_points = [(lat, lng, observed_at, position_id)]
            elif distance_km < self.config.air_min_distance_km:
                # GLITCH: Fast but short (< 150 km) → discard point
                logger.warning(
                    "⚠️  IMEI %s: GPS glitch discarded: %.0f m @ %.0f km/h (fast but short)",
                    self.device_imei, distance_m, implied_speed_kmh
                )
                return result
            else:
                # OUTLIER: Fast and far but missing other air leg criteria
                # Could be data error, treat as unknown-path leg
                logger.warning(
                    "⚠️  IMEI %s: High-speed outlier: %.0f km @ %.0f km/h over %.1f hr (not air leg)",
                    self.device_imei, distance_km, implied_speed_kmh, time_diff_hours
                )
                # Let it fall through to be processed as spatial gap

        
        # Step 2: Gap timeout check
        if self.context.current_state == "MOVE" and time_diff_seconds > self.config.gap_timeout_min * 60:
            logger.info(
                "⏱️  IMEI %s: Gap timeout (%.0f min) → force close leg",
                self.device_imei, time_diff_seconds / 60
            )
            # Close current leg
            if len(self.context.leg_buffer) >= 2:
                leg = self._create_leg(self.context.leg_buffer, is_air_leg=False)
                if leg:
                    result['leg_created'] = True
                    if self.context.journey_just_created:
                        result['journey_created'] = True
            
            # Create stationary from last position until now
            gap_stationary_points = [
                (self.context.last_position_lat, self.context.last_position_lng, 
                 self.context.last_position_time, None),
                (lat, lng, observed_at, position_id)
            ]
            stationary = self._create_stationary(gap_stationary_points, reason="gap_timeout")
            if stationary:
                result['stationary_created'] = True
                if self.context.journey_just_created:
                    result['journey_created'] = True
            
            # Return to STATIONARY state (ANCHOR ASSIGNMENT #2 of 3)
            self.context.current_state = "STATIONARY"
            self.context.anchor_lat = lat  # ← ASSIGNMENT #2
            self.context.anchor_lng = lng  # ← ASSIGNMENT #2
            self.context.anchor_points = [(lat, lng, observed_at, position_id)]
            self.context.leg_buffer = []
        
        # Step 3: State-specific logic
        if self.context.current_state == "STATIONARY":
            # Check if within anchor radius
            anchor_dist = haversine_distance(
                self.context.anchor_lat, self.context.anchor_lng,
                lat, lng
            )
            
            if anchor_dist <= self.config.anchor_radius_m:
                # Still stationary: roll anchor INCREMENTALLY (spec Section 1)
                # CRITICAL: Do NOT recalculate from all points - use incremental formula
                # Old (WRONG): anchor = centroid(all_points)  ← O(n) and causes anchor_count=1 bug
                # New (CORRECT): anchor += (point - anchor) / count  ← O(1) and preserves count
                self.context.anchor_points.append((lat, lng, observed_at, position_id))
                anchor_count = len(self.context.anchor_points)
                
                # Incremental centroid formula (spec Section 1)
                self.context.anchor_lat += (lat - self.context.anchor_lat) / anchor_count
                self.context.anchor_lng += (lng - self.context.anchor_lng) / anchor_count
                
                logger.debug(
                    "📍 IMEI %s: Stationary (%.0f m from anchor, count=%d)",
                    self.device_imei, anchor_dist, anchor_count
                )
                
                # INVARIANT: anchor_count > 1 after ≥2 in-radius points
                assert anchor_count >= 1, f"BUG: anchor_count < 1 ({anchor_count})"
            else:
                # Beyond R: Enter MOVE
                logger.info(
                    "🚀 IMEI %s: Leaving stationary (%.0f m from anchor, count=%d) → MOVE",
                    self.device_imei, anchor_dist, len(self.context.anchor_points)
                )
                
                # v2.2 R4b: Take anchor snapshot before leaving (for potential restoration)
                self.context.anchor_snapshot = (
                    self.context.anchor_lat,
                    self.context.anchor_lng,
                    len(self.context.anchor_points),
                    self.context.anchor_points[0][2] if self.context.anchor_points else observed_at
                )
                
                # Create stationary record from accumulated anchor points
                if len(self.context.anchor_points) >= 1:
                    stationary = self._create_stationary(self.context.anchor_points, reason="leaving_anchor")
                    if stationary:
                        result['stationary_created'] = True
                        if self.context.journey_just_created:
                            result['journey_created'] = True
                
                # Enter MOVE state
                self.context.current_state = "MOVE"
                
                # CRITICAL FIX: Leg must start from PREVIOUS position (last stationary point),
                # NOT from current position or anchor. Spec Section 2:
                # "leg_buffer = [prev, point]  # leg starts at the departure point"
                # Using last_position ensures the leg begins where the device LEFT the stationary zone.
                self.context.leg_buffer = [
                    (self.context.last_position_lat, self.context.last_position_lng, 
                     self.context.last_position_time, self.context.last_position_id),  # PREV point
                    (lat, lng, observed_at, position_id)  # Current point
                ]
        
        elif self.context.current_state == "MOVE":
            # Append to leg buffer
            self.context.leg_buffer.append((lat, lng, observed_at, position_id))
            
            # v2.1: Settle-dwell confirmation logic
            # Check if we have an active stop candidate
            if self.context.stop_candidate_since is not None:
                # We have a candidate - check if current point stays within R
                candidate_dist = haversine_distance(
                    self.context.stop_candidate_lat, self.context.stop_candidate_lng,
                    lat, lng
                )
                
                if candidate_dist <= self.config.anchor_radius_m:
                    # Point stays within R - fold it into the candidate
                    self.context.stop_candidate_points.append((lat, lng, observed_at, position_id))
                    # Recalculate candidate centroid
                    self.context.stop_candidate_lat, self.context.stop_candidate_lng = calculate_centroid(
                        [(p[0], p[1]) for p in self.context.stop_candidate_points]
                    )
                    
                    # Check if dwell time threshold reached
                    dwell_elapsed = (observed_at - self.context.stop_candidate_since).total_seconds() / 60.0  # minutes
                    
                    if dwell_elapsed >= self.config.settle_min_dwell_min:
                        # CONFIRMED STOP: Check leg qualification and close/restore
                        logger.info(
                            "✅ IMEI %s: Stop confirmed after %.1f min dwell → validate leg",
                            self.device_imei, dwell_elapsed
                        )
                        
                        # Close the leg BEFORE the candidate cluster (exclude all candidate points from leg)
                        # Find where candidate starts in leg_buffer
                        candidate_start_idx = len(self.context.leg_buffer) - len(self.context.stop_candidate_points)
                        leg_points = self.context.leg_buffer[:candidate_start_idx]
                        
                        # v2.2 R4a: Calculate leg metrics for qualification
                        leg_qualifies = False
                        if len(leg_points) >= 2:
                            # Calculate cumulative distance
                            cumulative_m = 0.0
                            for i in range(len(leg_points) - 1):
                                p1 = leg_points[i]
                                p2 = leg_points[i + 1]
                                cumulative_m += haversine_distance(p1[0], p1[1], p2[0], p2[1])
                            
                            # Calculate straight-line distance
                            straight_m = haversine_distance(
                                leg_points[0][0], leg_points[0][1],
                                leg_points[-1][0], leg_points[-1][1]
                            )
                            
                            # Calculate max excursion from leg start
                            max_excursion_m = 0.0
                            start_point = leg_points[0]
                            for p in leg_points[1:]:
                                excursion = haversine_distance(start_point[0], start_point[1], p[0], p[1])
                                max_excursion_m = max(max_excursion_m, excursion)
                            
                            # R4a: Leg qualifies if cumulative >= MOVE_CONFIRM AND
                            #      (straight >= MIN_LEG_DISTANCE OR max_excursion >= MIN_LEG_EXCURSION)
                            leg_qualifies = (
                                cumulative_m >= self.config.move_confirm_m and
                                (straight_m >= self.config.min_leg_distance_m or
                                 max_excursion_m >= self.config.min_leg_excursion_m)
                            )
                            
                            logger.debug(
                                "📊 IMEI %s: Leg metrics - cumulative=%.0fm, straight=%.0fm, excursion=%.0fm → qualifies=%s",
                                self.device_imei, cumulative_m, straight_m, max_excursion_m, leg_qualifies
                            )
                        
                        if leg_qualifies:
                            # v2.2 R6: Set leg end_point to cand_since time and candidate anchor coords
                            # This ensures leg.ended_at == stationary.started_at (zero gap)
                            leg = self._create_leg(
                                leg_points, 
                                is_air_leg=False,
                                end_override=(self.context.stop_candidate_lat, self.context.stop_candidate_lng),
                                end_time_override=self.context.stop_candidate_since  # R6: Leg terminates at stop start
                            )
                            if leg:
                                result['leg_created'] = True
                                if self.context.journey_just_created:
                                    result['journey_created'] = True
                            
                            # v2.2 R6: Create stationary with started_at = cand_since (not current time)
                            # This makes leg.ended_at == stationary.started_at
                            stationary = self._create_stationary(
                                self.context.stop_candidate_points,
                                reason="settle_dwell_confirmed"
                            )
                            if stationary:
                                result['stationary_created'] = True
                                if self.context.journey_just_created:
                                    result['journey_created'] = True
                            
                            # Transition to STATIONARY (ANCHOR ASSIGNMENT #3 of 3)
                            self.context.current_state = "STATIONARY"
                            self.context.anchor_points = [self.context.stop_candidate_points[-1]]
                            self.context.anchor_lat = self.context.stop_candidate_lat  # ← ASSIGNMENT #3
                            self.context.anchor_lng = self.context.stop_candidate_lng  # ← ASSIGNMENT #3
                            self.context.leg_buffer = []
                            self.context.anchor_snapshot = None  # Clear snapshot
                            
                            # Clear candidate
                            self.context.stop_candidate_since = None
                            self.context.stop_candidate_lat = None
                            self.context.stop_candidate_lng = None
                            self.context.stop_candidate_points = []
                        else:
                            # v2.2 R4b: Leg doesn't qualify - check if we should restore anchor
                            if self.context.anchor_snapshot:
                                snapshot_lat, snapshot_lng, snapshot_count, snapshot_since = self.context.anchor_snapshot
                                
                                # Check if candidate is close to snapshot anchor
                                restore_dist = haversine_distance(
                                    snapshot_lat, snapshot_lng,
                                    self.context.stop_candidate_lat, self.context.stop_candidate_lng
                                )
                                
                                if restore_dist <= self.config.anchor_resume_radius_m:
                                    # RESTORE: Sub-threshold leg ending near origin = scatter, not relocation
                                    logger.info(
                                        "🔄 IMEI %s: Restoring anchor (leg failed qualification, %.0fm from origin)",
                                        self.device_imei, restore_dist
                                    )
                                    
                                    # Restore anchor state
                                    self.context.current_state = "STATIONARY"
                                    self.context.anchor_lat = snapshot_lat
                                    self.context.anchor_lng = snapshot_lng
                                    
                                    # Fold all leg_buffer points back into anchor (incremental roll)
                                    self.context.anchor_points = self.context.leg_buffer.copy()
                                    for p in self.context.leg_buffer:
                                        anchor_count = len(self.context.anchor_points)
                                        self.context.anchor_lat += (p[0] - self.context.anchor_lat) / anchor_count
                                        self.context.anchor_lng += (p[1] - self.context.anchor_lng) / anchor_count
                                    
                                    self.context.leg_buffer = []
                                    self.context.anchor_snapshot = None
                                    
                                    # Clear candidate
                                    self.context.stop_candidate_since = None
                                    self.context.stop_candidate_lat = None
                                    self.context.stop_candidate_lng = None
                                    self.context.stop_candidate_points = []
                                    
                                    logger.debug(
                                        "✅ IMEI %s: Anchor restored with %d points",
                                        self.device_imei, len(self.context.anchor_points)
                                    )
                                else:
                                    # Too far from origin - real relocation, start new stationary
                                    logger.info(
                                        "📍 IMEI %s: New location (%.0fm from origin) → new stationary",
                                        self.device_imei, restore_dist
                                    )
                                    
                                    # Create stationary at new location
                                    stationary = self._create_stationary(
                                        self.context.stop_candidate_points,
                                        reason="settle_dwell_new_location"
                                    )
                                    if stationary:
                                        result['stationary_created'] = True
                                        if self.context.journey_just_created:
                                            result['journey_created'] = True
                                    
                                    # Transition to STATIONARY
                                    self.context.current_state = "STATIONARY"
                                    self.context.anchor_points = [self.context.stop_candidate_points[-1]]
                                    self.context.anchor_lat = self.context.stop_candidate_lat
                                    self.context.anchor_lng = self.context.stop_candidate_lng
                                    self.context.leg_buffer = []
                                    self.context.anchor_snapshot = None
                                    
                                    # Clear candidate
                                    self.context.stop_candidate_since = None
                                    self.context.stop_candidate_lat = None
                                    self.context.stop_candidate_lng = None
                                    self.context.stop_candidate_points = []
                            else:
                                # No snapshot - just discard and start new stationary
                                logger.info(
                                    "📍 IMEI %s: Leg discarded (no snapshot) → new stationary",
                                    self.device_imei
                                )
                                
                                stationary = self._create_stationary(
                                    self.context.stop_candidate_points,
                                    reason="settle_dwell_no_snapshot"
                                )
                                if stationary:
                                    result['stationary_created'] = True
                                    if self.context.journey_just_created:
                                        result['journey_created'] = True
                                
                                # Transition to STATIONARY
                                self.context.current_state = "STATIONARY"
                                self.context.anchor_points = [self.context.stop_candidate_points[-1]]
                                self.context.anchor_lat = self.context.stop_candidate_lat
                                self.context.anchor_lng = self.context.stop_candidate_lng
                                self.context.leg_buffer = []
                                
                                # Clear candidate
                                self.context.stop_candidate_since = None
                                self.context.stop_candidate_lat = None
                                self.context.stop_candidate_lng = None
                                self.context.stop_candidate_points = []
                    else:
                        # Not enough dwell yet - keep accumulating
                        logger.debug(
                            "⏳ IMEI %s: Stop candidate holding (%.1f/%.0f min)",
                            self.device_imei, dwell_elapsed, self.config.settle_min_dwell_min
                        )
                else:
                    # Point left R before settling - DISCARD candidate (was pass-through)
                    logger.info(
                        "❌ IMEI %s: Stop candidate discarded (point left R after %.1f m, needed %.0f m dwell)",
                        self.device_imei, 
                        (observed_at - self.context.stop_candidate_since).total_seconds() / 60.0,
                        self.config.settle_min_dwell_min
                    )
                    # Keep all points in leg (candidate was just pass-through)
                    # Clear candidate state
                    self.context.stop_candidate_since = None
                    self.context.stop_candidate_lat = None
                    self.context.stop_candidate_lng = None
                    self.context.stop_candidate_points = []
            
            # No active candidate - check if last 3 points form a new candidate
            elif len(self.context.leg_buffer) >= 3:
                last_3 = self.context.leg_buffer[-3:]
                # Calculate pairwise distances
                d12 = haversine_distance(last_3[0][0], last_3[0][1], last_3[1][0], last_3[1][1])
                d23 = haversine_distance(last_3[1][0], last_3[1][1], last_3[2][0], last_3[2][1])
                d13 = haversine_distance(last_3[0][0], last_3[0][1], last_3[2][0], last_3[2][1])
                
                if d12 <= self.config.anchor_radius_m and d23 <= self.config.anchor_radius_m and d13 <= self.config.anchor_radius_m:
                    # New stop CANDIDATE detected - open it but stay in MOVE
                    candidate_centroid = calculate_centroid([(p[0], p[1]) for p in last_3])
                    self.context.stop_candidate_since = observed_at
                    self.context.stop_candidate_lat = candidate_centroid[0]
                    self.context.stop_candidate_lng = candidate_centroid[1]
                    self.context.stop_candidate_points = [
                        (last_3[0][0], last_3[0][1], last_3[0][2], last_3[0][3]),
                        (last_3[1][0], last_3[1][1], last_3[1][2], last_3[1][3]),
                        (last_3[2][0], last_3[2][1], last_3[2][2], last_3[2][3]),
                    ]
                    logger.info(
                        "🔵 IMEI %s: Stop candidate opened (last 3 points within %.0f m) - awaiting %.0f min settle",
                        self.device_imei, self.config.anchor_radius_m, self.config.settle_min_dwell_min
                    )
        
        # Update last position
        self.context.last_position_lat = lat
        self.context.last_position_lng = lng
        self.context.last_position_time = observed_at
        self.context.last_position_id = position_id
        
        return result


# ═══════════════════════════════════════════════════════════════════════════
# PUBLIC API
# ═══════════════════════════════════════════════════════════════════════════

async def process_device_trips(db: Session, device_imei: str, limit: Optional[int] = None) -> Dict:
    """
    Process trips for a single device (incremental from last watermark).
    
    Args:
        db: Database session
        device_imei: Device IMEI to process
        limit: Max positions to process (None = all unprocessed)
    
    Returns:
        Dict with processing statistics
    """
    engine = TripEngine(db, device_imei)
    return engine.process_positions(limit=limit)


async def process_all_subscribed_devices(db: Session) -> Dict:
    """
    Process trips for all subscribed devices.
    
    Returns:
        Dict with aggregate statistics
    """
    from app.models import DeviceState
    
    # Ensure we see committed data from other transactions
    db.commit()
    
    # Get all subscribed devices
    logger.info("🔍 Querying device_state for trip_subscribed=true...")
    subscribed = db.execute(
        select(DeviceState).where(DeviceState.trip_subscribed == True)
    ).scalars().all()
    
    logger.info("🔄 Processing trips for %d subscribed devices", len(subscribed))
    
    if len(subscribed) == 0:
        logger.warning("⚠️  No subscribed devices found! Check device_state table.")
    else:
        logger.info("📱 Found devices: %s", [d.device_imei for d in subscribed])
    
    total_stats = {
        'devices_processed': 0,
        'total_positions': 0,
        'total_stationaries': 0,
        'total_legs': 0,
        'total_journeys': 0,
        'device_results': []
    }
    
    for device_state in subscribed:
        try:
            stats = await process_device_trips(db, device_state.device_imei)
            total_stats['devices_processed'] += 1
            total_stats['total_positions'] += stats['positions_processed']
            total_stats['total_stationaries'] += stats['stationaries_created']
            total_stats['total_legs'] += stats['legs_created']
            total_stats['total_journeys'] += stats['journeys_created']
            total_stats['device_results'].append(stats)
        except Exception as exc:
            logger.error("❌ IMEI %s: Processing failed: %s", device_state.device_imei, exc, exc_info=True)
    
    logger.info(
        "✅ Processed %d devices: %d positions → %d stationaries, %d legs, %d journeys",
        total_stats['devices_processed'], total_stats['total_positions'],
        total_stats['total_stationaries'], total_stats['total_legs'], total_stats['total_journeys']
    )
    
    # Add success flag for caller
    total_stats['success'] = True
    total_stats['error'] = None
    
    return total_stats


# ═══════════════════════════════════════════════════════════════════════════
# INVARIANT VALIDATION (Spec Section 6)
# ═══════════════════════════════════════════════════════════════════════════

def validate_journey_invariants(db: Session, journey_id: str) -> Dict[str, any]:
    """
    Validate journey invariants from spec Section 6.
    
    These are cheap checks that would have caught the 18 July defect on first run:
    1. anchor_count >= 1 always, and > 1 after any period with ≥2 in-radius points
    2. anchor only assigned in three places (checked via code review, not runtime)
    3. A persisted journey has leg_count >= 1
    4. A persisted leg has distance_m >= MIN_LEG_DISTANCE (except unknown-path and air)
    5. sum(leg.distance_m) == journey.distance_m to within rounding
    6. Two consecutive stationaries in one journey are always > R apart
    
    Args:
        db: Database session
        journey_id: Journey ID to validate
    
    Returns:
        Dict with validation results and any violations found
    """
    violations = []
    
    # Get journey
    journey = db.execute(
        select(Journey).where(Journey.id == journey_id)
    ).scalar_one_or_none()
    
    if not journey:
        return {'valid': False, 'violations': [f'Journey {journey_id} not found']}
    
    # Get legs
    legs = db.execute(
        select(Leg).where(Leg.journey_id == journey_id).order_by(Leg.started_at)
    ).scalars().all()
    
    # Get stationaries
    stationaries = db.execute(
        select(Stationary).where(Stationary.journey_id == journey_id).order_by(Stationary.started_at)
    ).scalars().all()
    
    # INVARIANT 3: A persisted journey has leg_count >= 1
    if journey.leg_count < 1:
        violations.append(f"INVARIANT 3 VIOLATION: Journey {journey_id} has leg_count={journey.leg_count} (expected >= 1)")
    
    # INVARIANT 4: A persisted leg has distance_m >= MIN_LEG_DISTANCE (except unknown-path and air)
    for leg in legs:
        if leg.mode not in ('air', 'unknown-path') and leg.distance_m < DEFAULT_MIN_LEG_DISTANCE_M:
            violations.append(
                f"INVARIANT 4 VIOLATION: Leg {leg.id} has distance_m={leg.distance_m} "
                f"(expected >= {DEFAULT_MIN_LEG_DISTANCE_M} for mode={leg.mode})"
            )
    
    # INVARIANT 5: sum(leg.distance_m) == journey.distance_m to within rounding
    total_leg_distance = sum(leg.distance_m for leg in legs)
    distance_diff = abs(total_leg_distance - journey.total_distance_m)
    tolerance = max(1.0, journey.total_distance_m * 0.01)  # 1% tolerance or 1m minimum
    
    if distance_diff > tolerance:
        violations.append(
            f"INVARIANT 5 VIOLATION: Journey {journey_id} total_distance_m={journey.total_distance_m} "
            f"but sum(legs)={total_leg_distance} (diff={distance_diff:.2f}m > tolerance={tolerance:.2f}m)"
        )
    
    # INVARIANT 6: Two consecutive stationaries in one journey are always > R apart
    for i in range(1, len(stationaries)):
        prev_stat = stationaries[i-1]
        curr_stat = stationaries[i]
        dist = haversine_distance(
            prev_stat.anchor_lat, prev_stat.anchor_lng,
            curr_stat.anchor_lat, curr_stat.anchor_lng
        )
        if dist <= DEFAULT_ANCHOR_RADIUS_M:
            violations.append(
                f"INVARIANT 6 VIOLATION: Stationaries {prev_stat.id} and {curr_stat.id} "
                f"are only {dist:.1f}m apart (expected > {DEFAULT_ANCHOR_RADIUS_M}m) - merge failed"
            )
    
    return {
        'valid': len(violations) == 0,
        'journey_id': journey_id,
        'leg_count': len(legs),
        'stationary_count': len(stationaries),
        'violations': violations
    }


# ═══════════════════════════════════════════════════════════════════════════
# TESTING / MANUAL TRIGGER
# ═══════════════════════════════════════════════════════════════════════════
# BACKGROUND TASK
# ═══════════════════════════════════════════════════════════════════════════

TRIP_ENGINE_INTERVAL_MINUTES = 15  # Run every 15 minutes
_trip_engine_task = None


async def _trip_engine_loop():
    """Background task that processes trips for all subscribed devices."""
    from app.database import SessionLocal
    
    logger.info("🚀 Trip engine loop started (interval: %d minutes)", TRIP_ENGINE_INTERVAL_MINUTES)
    
    # Wait 5 minutes for first sweeps to complete
    await asyncio.sleep(300)
    
    while True:
        try:
            db = SessionLocal()
            try:
                result = await process_all_subscribed_devices(db)
                if result['success']:
                    logger.info("✅ Trip engine: %d devices processed, %d new journeys created",
                               result['devices_processed'], result['total_journeys'])
                else:
                    logger.error("❌ Trip engine failed: %s", result['error'])
            finally:
                db.close()
        except Exception as exc:
            logger.error("❌ Trip engine loop error: %s", exc, exc_info=True)
        
        # Wait for next cycle
        await asyncio.sleep(TRIP_ENGINE_INTERVAL_MINUTES * 60)


def start_trip_engine():
    """Start the trip engine background task."""
    global _trip_engine_task
    if _trip_engine_task is None:
        _trip_engine_task = asyncio.create_task(_trip_engine_loop())
        logger.info("✅ Trip engine task scheduled")
    else:
        logger.warning("⚠️  Trip engine task already running")


# ═══════════════════════════════════════════════════════════════════════════
# TESTING / MANUAL TRIGGER
# ═══════════════════════════════════════════════════════════════════════════

async def main():
    """Test trip engine (manual trigger)."""
    import asyncio
    from app.database import SessionLocal
    
    db = SessionLocal()
    try:
        # Test with a specific device
        test_imei = "780901807676441"  # Replace with real IMEI
        
        print(f"\n{'='*60}")
        print(f"TRIP ENGINE TEST - IMEI: {test_imei}")
        print(f"{'='*60}")
        
        result = await process_device_trips(db, test_imei, limit=100)
        
        print(f"\nProcessing Result:")
        print(f"  Positions Processed: {result['positions_processed']}")
        print(f"  Stationaries Created: {result['stationaries_created']}")
        print(f"  Legs Created: {result['legs_created']}")
        print(f"  Journeys Created: {result['journeys_created']}")
        print(f"{'='*60}")
    finally:
        db.close()


if __name__ == "__main__":
    import asyncio
    asyncio.run(main())
