"""
Trip State Engine (Trip Engine - Section 2)

Implements STATIONARY ↔ MOVE state machine from PinPlot_Trip_Engine_Spec_v2.md.

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
                 Last 3 points within R of each other → close leg, STATIONARY
                 Gap timeout → force close leg, STATIONARY

Rules:
    - Geometry-based (not time-based) confirmation
    - R = 100m (anchor radius)
    - Min leg distance = 300m (3 × R)
    - Move confirm = 150m (before emitting leg)
    - MAX_KMH = 200 (outlier gate)
    - GAP_TIMEOUT = 30 min (force close)
    - Journey grouping: 30 min dwell threshold

Filters:
    - Outlier gate: > 200 km/h → air leg or discard
    - Air legs: ≥ 300 km/h, ≥ 150 km, multi-hour gap
    - Median smoothing: window 3 on lat/lng
    - Gap policy: spatial jump = unknown-path leg, temporal gap = long stationary
"""

import asyncio
import logging
from datetime import datetime, timedelta, timezone
from typing import List, Dict, Optional, Tuple
from dataclasses import dataclass
from math import radians, cos, sin, asin, sqrt
from statistics import median

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

# ── Configuration (defaults from spec validation) ─────────────────────────
DEFAULT_ANCHOR_RADIUS_M = 100
DEFAULT_MIN_LEG_DISTANCE_M = 300
DEFAULT_MOVE_CONFIRM_M = 150
DEFAULT_MAX_SPEED_KMH = 200
DEFAULT_GAP_TIMEOUT_MIN = 30
DEFAULT_AIR_SPEED_KMH = 300
DEFAULT_AIR_MIN_DISTANCE_KM = 150
DEFAULT_JOURNEY_BREAK_DWELL_MIN = 30
DEFAULT_SMOOTHING_WINDOW = 3


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
    smoothing_window: int


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
    anchor_points: List[Tuple[float, float, datetime]] = None  # (lat, lng, observed_at)
    
    # MOVE state
    leg_buffer: List[Tuple[float, float, datetime, int]] = None  # (lat, lng, observed_at, position_id)
    
    # Last processed
    last_processed_at: Optional[datetime] = None
    last_position_lat: Optional[float] = None
    last_position_lng: Optional[float] = None
    last_position_time: Optional[datetime] = None
    
    # Current journey context
    current_journey_id: Optional[str] = None
    last_stationary_ended_at: Optional[datetime] = None
    
    def __post_init__(self):
        if self.anchor_points is None:
            self.anchor_points = []
        if self.leg_buffer is None:
            self.leg_buffer = []


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
                context.anchor_points = [
                    (state_row.anchor_lat, state_row.anchor_lng, state_row.last_processed_at)
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
        
        Args:
            timestamp: Current timestamp (for journey start)
        
        Returns:
            Journey ID (UUID as string)
        """
        if self.context.current_journey_id:
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
            created_at=datetime.now(timezone.utc),
        )
        
        self.db.add(journey)
        self.db.flush()  # Get ID
        
        self.context.current_journey_id = str(journey.id)
        
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
        
        self.db.flush()
        
        logger.info(
            "✅ IMEI %s: Journey %s closed: %.2f km, %d legs, %d stationaries, %.0f min",
            self.device_imei, journey.id, total_distance_m / 1000,
            leg_count, stationary_count, journey.total_duration_seconds / 60
        )
        
        # Clear journey context
        self.context.current_journey_id = None
        
        return journey
    
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
        breaks_journey = duration_seconds > (self.config.journey_break_dwell_min * 60)
        
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
        
        # Create record
        stationary = Stationary(
            device_imei=self.device_imei,
            centroid_lat=centroid_lat,
            centroid_lng=centroid_lng,
            started_at=started_at,
            ended_at=ended_at,
            duration_seconds=int(duration_seconds),
            point_count=point_count,
            start_position_id=start_position_id,
            end_position_id=end_position_id,
            journey_id=self.context.current_journey_id,  # NULL for journey-breaking stationaries
            created_at=datetime.now(timezone.utc),
        )
        
        self.db.add(stationary)
        self.db.flush()  # Get ID without committing
        
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
        
        logger.info(
            "🟠 IMEI %s: Stationary created at (%.4f, %.4f) for %.0f min (%d points)%s",
            self.device_imei, centroid_lat, centroid_lng,
            duration_seconds / 60, point_count,
            " [JOURNEY BREAK]" if breaks_journey else ""
        )
        
        # Update journey context
        self.context.last_stationary_ended_at = ended_at
        
        return stationary
    
    def _create_leg(
        self,
        leg_buffer: List[Tuple[float, float, datetime, Optional[int]]],
        is_air_leg: bool = False
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
        
        Returns:
            Created Leg object or None if filtered out
        """
        if len(leg_buffer) < 2:
            logger.debug("⏭️  IMEI %s: Leg has <2 points, skipping", self.device_imei)
            return None
        
        # Calculate total distance
        total_distance_m = 0.0
        for i in range(len(leg_buffer) - 1):
            p1 = leg_buffer[i]
            p2 = leg_buffer[i + 1]
            total_distance_m += haversine_distance(p1[0], p1[1], p2[0], p2[1])
        
        # Filter: Move confirmation (must travel at least move_confirm_m)
        if total_distance_m < self.config.move_confirm_m:
            logger.debug(
                "⏭️  IMEI %s: Leg %.0f m < move_confirm %.0f m, discarding",
                self.device_imei, total_distance_m, self.config.move_confirm_m
            )
            return None
        
        # Filter: Min leg distance (drift rejection)
        if not is_air_leg and total_distance_m < self.config.min_leg_distance_m:
            logger.debug(
                "⏭️  IMEI %s: Leg %.0f m < min_leg_distance %.0f m (drift), discarding",
                self.device_imei, total_distance_m, self.config.min_leg_distance_m
            )
            return None
        
        # Calculate duration
        started_at = leg_buffer[0][2]
        ended_at = leg_buffer[-1][2]
        duration_seconds = (ended_at - started_at).total_seconds()
        point_count = len(leg_buffer)
        
        # Get start/end position IDs
        start_position_id = leg_buffer[0][3] if leg_buffer[0][3] else None
        end_position_id = leg_buffer[-1][3] if leg_buffer[-1][3] else None
        
        # Ensure journey is open
        self._ensure_journey_open(started_at)
        
        # Create record
        leg = Leg(
            device_imei=self.device_imei,
            distance_m=int(total_distance_m),
            duration_seconds=int(duration_seconds),
            point_count=point_count,
            started_at=started_at,
            ended_at=ended_at,
            start_lat=leg_buffer[0][0],
            start_lng=leg_buffer[0][1],
            end_lat=leg_buffer[-1][0],
            end_lng=leg_buffer[-1][1],
            start_position_id=start_position_id,
            end_position_id=end_position_id,
            is_air_leg=is_air_leg,
            journey_id=self.context.current_journey_id,
            created_at=datetime.now(timezone.utc),
        )
        
        self.db.add(leg)
        self.db.flush()  # Get ID without committing
        
        # Build PostGIS geometry for the leg path
        # Create LineString from all points in leg_buffer using ST_MakeLine
        try:
            # Build array of points for ST_MakeLine: ARRAY[ST_MakePoint(lng, lat), ...]
            # Note: PostGIS uses (lng, lat) order, not (lat, lng)
            points_array = ", ".join([
                f"ST_MakePoint({p[1]}, {p[0]})"  # lng, lat
                for p in leg_buffer
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
        
        emoji = "✈️ " if is_air_leg else "🔵"
        logger.info(
            "%s IMEI %s: Leg created: %.2f km over %.0f min (%d points)%s",
            emoji, self.device_imei, total_distance_m / 1000, duration_seconds / 60,
            point_count, " [AIR]" if is_air_leg else ""
        )
        
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
        
        # Save final state
        self._save_state(self.context)
        
        logger.info(
            "✅ IMEI %s: Processed %d positions → %d stationaries, %d legs, %d journeys",
            self.device_imei, stats['positions_processed'],
            stats['stationaries_created'], stats['legs_created'], stats['journeys_created']
        )
        
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
        
        # First position ever
        if self.context.last_position_time is None:
            self.context.anchor_lat = lat
            self.context.anchor_lng = lng
            self.context.anchor_points = [(lat, lng, observed_at)]
            self.context.last_position_lat = lat
            self.context.last_position_lng = lng
            self.context.last_position_time = observed_at
            self.context.current_state = "STATIONARY"
            logger.debug("📍 IMEI %s: First position at (%f, %f)", self.device_imei, lat, lng)
            return result
        
        # Calculate implied speed (for outlier/air gate)
        time_diff_seconds = (observed_at - self.context.last_position_time).total_seconds()
        distance_m = haversine_distance(
            self.context.last_position_lat, self.context.last_position_lng,
            lat, lng
        )
        
        implied_speed_kmh = 0
        if time_diff_seconds > 0:
            implied_speed_kmh = (distance_m / time_diff_seconds) * 3.6
        
        # Step 1: Outlier/air gate
        if implied_speed_kmh > self.config.max_speed_kmh:
            if distance_m >= self.config.air_min_distance_km * 1000:
                # Air leg: Create leg from last to current with is_air_leg=True
                logger.info(
                    "✈️  IMEI %s: Air leg detected: %.0f km @ %.0f km/h",
                    self.device_imei, distance_m / 1000, implied_speed_kmh
                )
                
                # If in MOVE state, close current leg first
                if self.context.current_state == "MOVE" and len(self.context.leg_buffer) >= 2:
                    leg = self._create_leg(self.context.leg_buffer, is_air_leg=False)
                    if leg:
                        result['leg_created'] = True
                    self.context.leg_buffer = []
                
                # Create air leg
                air_leg_buffer = [
                    (self.context.last_position_lat, self.context.last_position_lng, 
                     self.context.last_position_time, None),
                    (lat, lng, observed_at, position_id)
                ]
                air_leg = self._create_leg(air_leg_buffer, is_air_leg=True)
                if air_leg:
                    result['leg_created'] = True
                    result['air_leg_detected'] = True
                
                # Start new stationary at destination
                self.context.current_state = "STATIONARY"
                self.context.anchor_lat = lat
                self.context.anchor_lng = lng
                self.context.anchor_points = [(lat, lng, observed_at)]
            else:
                # Glitch: Discard point
                logger.warning(
                    "⚠️  IMEI %s: Outlier discarded: %.0f m @ %.0f km/h (glitch)",
                    self.device_imei, distance_m, implied_speed_kmh
                )
                return result
        
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
            
            # Create stationary from last position until now
            gap_stationary_points = [
                (self.context.last_position_lat, self.context.last_position_lng, 
                 self.context.last_position_time, None),
                (lat, lng, observed_at, position_id)
            ]
            stationary = self._create_stationary(gap_stationary_points, reason="gap_timeout")
            if stationary:
                result['stationary_created'] = True
            
            # Return to STATIONARY state
            self.context.current_state = "STATIONARY"
            self.context.anchor_lat = lat
            self.context.anchor_lng = lng
            self.context.anchor_points = [(lat, lng, observed_at)]
            self.context.leg_buffer = []
        
        # Step 3: State-specific logic
        if self.context.current_state == "STATIONARY":
            # Check if within anchor radius
            anchor_dist = haversine_distance(
                self.context.anchor_lat, self.context.anchor_lng,
                lat, lng
            )
            
            if anchor_dist <= self.config.anchor_radius_m:
                # Still stationary: roll anchor
                self.context.anchor_points.append((lat, lng, observed_at))
                self.context.anchor_lat, self.context.anchor_lng = calculate_centroid(
                    [(p[0], p[1]) for p in self.context.anchor_points]
                )
                logger.debug(
                    "📍 IMEI %s: Stationary (%.0f m from anchor)",
                    self.device_imei, anchor_dist
                )
            else:
                # Beyond R: Enter MOVE
                logger.info(
                    "🚀 IMEI %s: Leaving stationary (%.0f m from anchor) → MOVE",
                    self.device_imei, anchor_dist
                )
                
                # Create stationary record from accumulated anchor points
                if len(self.context.anchor_points) >= 1:
                    stationary = self._create_stationary(self.context.anchor_points, reason="leaving_anchor")
                    if stationary:
                        result['stationary_created'] = True
                
                # Enter MOVE state
                self.context.current_state = "MOVE"
                self.context.leg_buffer = [
                    (self.context.anchor_lat, self.context.anchor_lng, 
                     self.context.anchor_points[-1][2], None),  # Start from anchor
                    (lat, lng, observed_at, position_id)  # Current point
                ]
        
        elif self.context.current_state == "MOVE":
            # Append to leg buffer
            self.context.leg_buffer.append((lat, lng, observed_at, position_id))
            
            # Check if last 3 points form a new stationary (within R of each other)
            if len(self.context.leg_buffer) >= 3:
                last_3 = self.context.leg_buffer[-3:]
                # Calculate pairwise distances
                d12 = haversine_distance(last_3[0][0], last_3[0][1], last_3[1][0], last_3[1][1])
                d23 = haversine_distance(last_3[1][0], last_3[1][1], last_3[2][0], last_3[2][1])
                d13 = haversine_distance(last_3[0][0], last_3[0][1], last_3[2][0], last_3[2][1])
                
                if d12 <= self.config.anchor_radius_m and d23 <= self.config.anchor_radius_m and d13 <= self.config.anchor_radius_m:
                    # New stationary formed: close leg
                    logger.info(
                        "🛑 IMEI %s: New stationary detected (last 3 points within %.0f m) → close leg",
                        self.device_imei, self.config.anchor_radius_m
                    )
                    
                    # Close the leg (excluding the last 3 points which form the new stationary)
                    leg_points = self.context.leg_buffer[:-2]  # Keep all but last 2 (last point is current)
                    if len(leg_points) >= 2:
                        leg = self._create_leg(leg_points, is_air_leg=False)
                        if leg:
                            result['leg_created'] = True
                    
                    # Create new stationary from last 3 points
                    new_anchor_points = [
                        (last_3[0][0], last_3[0][1], last_3[0][2], last_3[0][3]),
                        (last_3[1][0], last_3[1][1], last_3[1][2], last_3[1][3]),
                        (last_3[2][0], last_3[2][1], last_3[2][2], last_3[2][3]),
                    ]
                    stationary = self._create_stationary(new_anchor_points, reason="anchor_formed")
                    if stationary:
                        result['stationary_created'] = True
                    
                    # Return to STATIONARY
                    self.context.current_state = "STATIONARY"
                    self.context.anchor_points = [last_3[-1][:3]]  # Start new anchor from last point
                    self.context.anchor_lat, self.context.anchor_lng = last_3[-1][0], last_3[-1][1]
                    self.context.leg_buffer = []
        
        # Update last position
        self.context.last_position_lat = lat
        self.context.last_position_lng = lng
        self.context.last_position_time = observed_at
        
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
    
    # Get all subscribed devices
    subscribed = db.execute(
        select(DeviceState).where(DeviceState.trip_subscribed == True)
    ).scalars().all()
    
    logger.info("🔄 Processing trips for %d subscribed devices", len(subscribed))
    
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
            logger.error("❌ IMEI %s: Processing failed: %s", device_state.device_imei, exc)
    
    logger.info(
        "✅ Processed %d devices: %d positions → %d stationaries, %d legs, %d journeys",
        total_stats['devices_processed'], total_stats['total_positions'],
        total_stats['total_stationaries'], total_stats['total_legs'], total_stats['total_journeys']
    )
    
    return total_stats


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
                               result['devices_processed'], result['total_journeys_created'])
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
