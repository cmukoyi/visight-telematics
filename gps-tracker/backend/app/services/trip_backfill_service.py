"""
Trip Backfill Service (v2.2 A3)

Fetches historical positions from TrackSolid for a device and reprocesses trips.
Fills the gap BEHIND the forward pipeline without crossing the high-water mark.

Key guarantees:
- Never crosses forward pipeline boundary (last_position_ts)
- Idempotent position storage (upsert on device_imei, observed_at)
- Does NOT modify forward pipeline state (last_tracklist_pull_at unchanged)
- Works for subscribed AND unsubscribed devices (admin one-off)

Architecture:
    1. Calculate time window from preset
    2. Clamp endTime to last_position_ts (if exists)
    3. Call TrackSolid track.list API
    4. Upsert positions (idempotent)
    5. Reprocess affected device trips
"""

import logging
from datetime import datetime, timedelta, timezone
from enum import Enum
from typing import Optional, Dict, List
from sqlalchemy.orm import Session
from sqlalchemy.dialects.postgresql import insert

from app.models import DeviceState, DevicePosition, BLETag
from app.services.device_providers.tracksolid_provider import fetch_tracksolid_journey_points
from app.services.trip_reprocess_service import replay_device_trips

logger = logging.getLogger(__name__)


# ═══════════════════════════════════════════════════════════════════════════
# TIME WINDOW PRESETS
# ═══════════════════════════════════════════════════════════════════════════

class BackfillPreset(str, Enum):
    """Predefined time window presets for backfill operations."""
    TODAY = "today"
    YESTERDAY = "yesterday"
    LAST_7_DAYS = "last_7_days"
    LAST_30_DAYS = "last_30_days"


def get_preset_window(preset: BackfillPreset) -> tuple[datetime, datetime]:
    """
    Calculate start and end times for a backfill preset.
    
    Args:
        preset: Time window preset
    
    Returns:
        (start_time, end_time) tuple in UTC
    
    Examples:
        TODAY: 00:00:00 today → now
        YESTERDAY: 00:00:00 yesterday → 23:59:59 yesterday
        LAST_7_DAYS: 00:00:00 7 days ago → now
        LAST_30_DAYS: 00:00:00 30 days ago → now
    """
    now = datetime.now(timezone.utc)
    today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    
    if preset == BackfillPreset.TODAY:
        return (today_start, now)
    
    elif preset == BackfillPreset.YESTERDAY:
        yesterday_start = today_start - timedelta(days=1)
        yesterday_end = today_start - timedelta(microseconds=1)
        return (yesterday_start, yesterday_end)
    
    elif preset == BackfillPreset.LAST_7_DAYS:
        start = today_start - timedelta(days=7)
        return (start, now)
    
    elif preset == BackfillPreset.LAST_30_DAYS:
        start = today_start - timedelta(days=30)
        return (start, now)
    
    else:
        raise ValueError(f"Unknown preset: {preset}")


# ═══════════════════════════════════════════════════════════════════════════
# POSITION UPSERT
# ═══════════════════════════════════════════════════════════════════════════

async def _upsert_backfill_positions(db: Session, imei: str, track_points: List[dict]) -> int:
    """
    Upsert backfilled track points to device_positions table.
    
    Args:
        db: Database session
        imei: Device IMEI
        track_points: List of parsed GPS point dicts
    
    Returns:
        Number of new positions inserted (excludes duplicates)
    """
    if not track_points:
        return 0
    
    created_at = datetime.now(timezone.utc)
    inserted_count = 0
    
    for point in track_points:
        # Parse GPS time
        gps_time_str = point.get('gpsTime')
        if not gps_time_str:
            continue
        
        try:
            observed_at = datetime.strptime(str(gps_time_str), "%Y-%m-%d %H:%M:%S")
            observed_at = observed_at.replace(tzinfo=timezone.utc)
        except (ValueError, TypeError):
            logger.warning("⚠️  Invalid gpsTime for IMEI %s: %s", imei, gps_time_str)
            continue
        
        lat = point.get('lat')
        lng = point.get('lng')
        if lat is None or lng is None:
            continue
        
        # Prepare position data
        position_data = {
            'device_imei': imei,
            'lat': lat,
            'lng': lng,
            'observed_at': observed_at,
            'direction': point.get('direction'),
            'gps_speed': point.get('gpsSpeed'),
            'source': 'backfill',
            'created_at': created_at,
        }
        
        # Upsert using PostgreSQL INSERT ... ON CONFLICT DO NOTHING
        # This ensures idempotency (duplicate positions are silently ignored)
        stmt = insert(DevicePosition).values(position_data)
        stmt = stmt.on_conflict_do_nothing(
            index_elements=['device_imei', 'observed_at']
        )
        
        result = db.execute(stmt)
        if result.rowcount > 0:
            inserted_count += 1
    
    db.commit()
    return inserted_count


# ═══════════════════════════════════════════════════════════════════════════
# BACKFILL OPERATION
# ═══════════════════════════════════════════════════════════════════════════

async def backfill_device_positions(
    db: Session,
    device_imei: str,
    preset: BackfillPreset,
) -> Dict:
    """
    Backfill historical positions for a device and reprocess trips.
    
    Workflow:
        1. Calculate preset time window (today/yesterday/last_7/30_days)
        2. Get device's last_position_ts (forward pipeline high-water mark)
        3. Clamp endTime to min(preset_end, last_position_ts)
        4. Call TrackSolid track.list API
        5. Upsert positions (idempotent on device_imei, observed_at)
        6. Reprocess device trips over affected span
    
    Args:
        db: Database session
        device_imei: Target device IMEI
        preset: Time window preset
    
    Returns:
        Dict with:
        {
            'device_imei': str,
            'preset': str,
            'window_start': datetime,
            'window_end': datetime,
            'clamped': bool,  # True if endTime was clamped to last_position_ts
            'positions_fetched': int,
            'positions_inserted': int,
            'positions_processed': int,  # From reprocess
            'journeys_created': int,
            'legs_created': int,
            'stationaries_created': int,
            'engine_version': str,
        }
    
    Raises:
        ValueError: If device not found or TrackSolid credentials missing
        Exception: If API call fails
    """
    # Validate device exists
    tag = db.query(BLETag).filter(BLETag.imei == device_imei).first()
    if not tag:
        raise ValueError(f"Device not found: {device_imei}")
    
    # Calculate preset window
    preset_start, preset_end = get_preset_window(preset)
    
    # Get device state (may not exist yet for never-pulled devices)
    device_state = db.query(DeviceState).filter(
        DeviceState.device_imei == device_imei
    ).first()
    
    # Clamp endTime to last_position_ts (never cross forward pipeline boundary)
    clamped = False
    window_start = preset_start
    window_end = preset_end
    
    if device_state and device_state.last_position_ts:
        if preset_end > device_state.last_position_ts:
            window_end = device_state.last_position_ts
            clamped = True
            logger.info(
                "🔒 Clamped endTime to forward high-water mark: %s → %s",
                preset_end.isoformat(),
                window_end.isoformat()
            )
    
    logger.info(
        "📥 Backfill %s for device %s: %s to %s (clamped=%s)",
        preset.value,
        device_imei,
        window_start.isoformat(),
        window_end.isoformat(),
        clamped
    )
    
    # Format times for TrackSolid API (requires "YYYY-MM-DD HH:MM:SS")
    start_time_str = window_start.strftime("%Y-%m-%d %H:%M:%S")
    end_time_str = window_end.strftime("%Y-%m-%d %H:%M:%S")
    
    # Call TrackSolid journey points API
    logger.info("📡 Calling TrackSolid getPointList API...")
    track_data = await fetch_tracksolid_journey_points(
        imei=device_imei,
        start_time=start_time_str,
        end_time=end_time_str,
    )
    
    if not track_data:
        logger.warning("⚠️  No track data returned from TrackSolid")
        track_points = []
    else:
        # Parse pipe-delimited GPS points
        # Format: speed|direction|...|gpsTime|lat|lng|...
        gps_point_strs = track_data.get('gpsPointStrList') or []
        track_points = []
        
        for point_str in gps_point_strs:
            try:
                parts = point_str.split('|')
                if len(parts) < 10:
                    continue
                
                lat = float(parts[8])
                lng = float(parts[9])
                if lat == 0.0 and lng == 0.0:
                    continue
                
                gps_time_str = parts[7]  # "YYYY-MM-DD HH:MM:SS"
                
                track_points.append({
                    'lat': lat,
                    'lng': lng,
                    'gpsTime': gps_time_str,
                    'direction': int(float(parts[1])) if parts[1] else None,
                    'gpsSpeed': float(parts[0]) if parts[0] else None,
                })
            except (ValueError, IndexError) as e:
                logger.warning("⚠️  Failed to parse GPS point: %s", e)
                continue
    
    positions_fetched = len(track_points)
    logger.info("✅ Fetched %d positions from TrackSolid", positions_fetched)
    
    # Upsert positions (idempotent)
    positions_inserted = await _upsert_backfill_positions(
        db=db,
        imei=device_imei,
        track_points=track_points
    )
    
    logger.info(
        "💾 Upserted %d new positions (%d duplicates skipped)",
        positions_inserted,
        positions_fetched - positions_inserted
    )
    
    # Reprocess device trips over full history
    # (v2.2 A4 only supports full-history reprocess; windowed reprocess deferred)
    logger.info("🔄 Reprocessing device trips...")
    reprocess_result = replay_device_trips(
        db=db,
        device_imei=device_imei,
        start_date=None,  # Full history
        end_date=None,
        tenant_id=None  # TODO: resolve from device's usergroup when available
    )
    
    # Build response
    result = {
        'device_imei': device_imei,
        'preset': preset.value,
        'window_start': window_start,
        'window_end': window_end,
        'clamped': clamped,
        'positions_fetched': positions_fetched,
        'positions_inserted': positions_inserted,
        'positions_processed': reprocess_result['positions_processed'],
        'journeys_created': reprocess_result['journeys_created'],
        'legs_created': reprocess_result['legs_created'],
        'stationaries_created': reprocess_result['stationaries_created'],
        'engine_version': reprocess_result['engine_version'],
    }
    
    logger.info(
        "✅ Backfill complete: %d fetched, %d inserted, %d journeys",
        positions_fetched,
        positions_inserted,
        reprocess_result['journeys_created']
    )
    
    return result
