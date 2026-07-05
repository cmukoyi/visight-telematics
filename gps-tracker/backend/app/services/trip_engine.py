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

import logging
from datetime import datetime, timedelta, timezone
from typing import List, Dict, Optional, Tuple
from dataclasses import dataclass
from math import radians, cos, sin, asin, sqrt
from statistics import median

from sqlalchemy import select, and_
from sqlalchemy.orm import Session

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
                # Air leg: Create leg from last to this with is_air_leg=True
                logger.info(
                    "✈️  IMEI %s: Air leg detected: %.0f km @ %.0f km/h",
                    self.device_imei, distance_m / 1000, implied_speed_kmh
                )
                # TODO: Implement air leg creation
                result['air_leg_detected'] = True
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
            # Close current leg, return to STATIONARY
            # TODO: Implement leg close
            self.context.current_state = "STATIONARY"
            self.context.anchor_lat = lat
            self.context.anchor_lng = lng
            self.context.anchor_points = [(lat, lng, observed_at)]
        
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
                    # TODO: Implement leg close and stationary creation
                    result['leg_created'] = True
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
