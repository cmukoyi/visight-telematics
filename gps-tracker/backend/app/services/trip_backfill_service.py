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
from sqlalchemy import select

from app.models import DeviceState, DevicePosition, BLETag
from app.services.tracksolid_track_service import (
    call_track_list_api,
    _upsert_track_positions,
    _get_credentials,
    _get_access_token,
)
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
    
    # Get TrackSolid credentials
    creds = _get_credentials(db)
    if not creds:
        raise ValueError("TrackSolid credentials not configured")
    
    app_key, app_secret = creds
    
    # Get access token
    access_token = await _get_access_token(app_key, app_secret)
    if not access_token:
        raise ValueError("Failed to get TrackSolid access token")
    
    # Call track.list API
    logger.info("📡 Calling TrackSolid track.list API...")
    api_response = await call_track_list_api(
        access_token=access_token,
        app_key=app_key,
        app_secret=app_secret,
        imei=device_imei,
        begin_time=window_start,
        end_time=window_end,
        map_type="GOOGLE"
    )
    
    if not api_response:
        raise Exception("TrackSolid API call failed (no response)")
    
    code = api_response.get('code', -1)
    message = api_response.get('message', 'Unknown error')
    
    if code != 0:
        # Code 10004 (no data) is not an error for backfill
        if code == 10004:
            logger.info("ℹ️  No track data in window (code 10004)")
            track_points = []
        else:
            raise Exception(f"TrackSolid API error {code}: {message}")
    else:
        track_points = api_response.get('result', [])
    
    positions_fetched = len(track_points)
    logger.info("✅ Fetched %d positions from TrackSolid", positions_fetched)
    
    # Upsert positions (idempotent)
    positions_inserted = await _upsert_track_positions(
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
