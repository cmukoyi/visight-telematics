"""
TrackSolid Selective Track Service (Trip Engine - Section 1 Ingestion)

Implements the second tier of the two-tier API strategy from PinPlot_Trip_Engine_Spec_v2.md.

Architecture:
    Tier 1 (batch sweep): ALL devices, 1 API call every 10 min
    
    Tier 2 (this file): SELECTIVE devices with 3-condition trigger
        - Condition 1: New data detected (last_batch_ts > last_position_ts)
        - Condition 2: Subscribed (trip_subscribed = true)
        - Condition 3: Coalesce passed (now - last_pull ≥ coalesce_floor_minutes)
        
        Only ~10 devices qualify per cycle → ~10 API calls per 10 min
        Total: 1 batch + 10 selective = 11 calls per 10 min = 1,584/day

Key Concerns:
    - Forward-only window: startTime = last_position_ts (don't re-fetch old data)
    - UNIQUE constraint on (device_imei, observed_at) prevents duplicates
    - Updates last_position_ts (window boundary) and last_tracklist_pull_at (coalesce)
    - Error handling: 10004 (no data), 10005 (param error), 10006 (rate limit), 10008 (auth)
"""

import asyncio
import hashlib
import logging
from datetime import datetime, timedelta, timezone
from typing import List, Dict, Optional

import httpx
from sqlalchemy import select, and_, or_, func
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from app.models import (
    DevicePosition,
    DeviceState,
    TrackSolidSyncState,
    TripConfig,
)
from app.services.geocode_service import GeocodeService
from app.services.tracksolid_batch_service import (
    _get_credentials,
    _generate_signature,
    _get_access_token,
    _increment_api_call_counter,
    OPEN_API_BASE_URL,
    CONNECT_TIMEOUT_SECONDS,
    READ_TIMEOUT_SECONDS,
)

logger = logging.getLogger(__name__)

# ── Error Codes ────────────────────────────────────────────────────────────
ERROR_CODE_SUCCESS = 0
ERROR_CODE_NO_DATA = 10004         # No track data in time range (skip)
ERROR_CODE_PARAM_ERROR = 10005     # Parameter error (skip)
ERROR_CODE_RATE_LIMIT = 10006      # Rate limit exceeded (backoff)
ERROR_CODE_AUTH_FAILED = 10008     # Auth failed (refresh token)

# ── Configuration ──────────────────────────────────────────────────────────
DEFAULT_COALESCE_FLOOR_MINUTES = 120  # 2 hours between track.list calls


# ═══════════════════════════════════════════════════════════════════════════
# DEVICE SELECTION (3-Condition Trigger)
# ═══════════════════════════════════════════════════════════════════════════

async def _get_qualifying_devices(db: Session) -> List[DeviceState]:
    """
    Find devices that qualify for track.list pull.
    
    3 Conditions (ALL must be true):
    1. New data detected: last_batch_ts > last_position_ts
    2. Subscribed: trip_subscribed = true
    3. Coalesce passed: now - last_tracklist_pull_at ≥ coalesce_floor_minutes
    
    Returns:
        List of DeviceState objects that qualify
    """
    now = datetime.now(timezone.utc)
    
    # Get global coalesce_floor_minutes from config
    global_config = db.execute(
        select(TripConfig).where(TripConfig.tenant_id == None)
    ).scalar_one_or_none()
    
    global_coalesce = global_config.coalesce_floor_minutes if global_config else DEFAULT_COALESCE_FLOOR_MINUTES
    
    # Query qualifying devices
    query = select(DeviceState).where(
        and_(
            # Condition 2: Subscribed
            DeviceState.trip_subscribed == True,
            
            # Condition 1: New data detected (OR first pull)
            or_(
                DeviceState.last_position_ts == None,  # First pull
                DeviceState.last_batch_ts > DeviceState.last_position_ts  # New data
            ),
            
            # Condition 3: Coalesce passed (OR first pull)
            or_(
                DeviceState.last_tracklist_pull_at == None,  # First pull
                func.extract('epoch', now - DeviceState.last_tracklist_pull_at) 
                    >= func.coalesce(DeviceState.coalesce_floor_minutes, global_coalesce) * 60
            )
        )
    )
    
    devices = db.execute(query).scalars().all()
    
    logger.info("🎯 Qualifying devices for track.list: %d (3-condition trigger)", len(devices))
    
    for device in devices:
        coalesce_minutes = device.coalesce_floor_minutes or global_coalesce
        last_pull_ago = (now - device.last_tracklist_pull_at).total_seconds() / 60 if device.last_tracklist_pull_at else None
        
        logger.debug(
            "   • IMEI %s: subscribed=true, new_data=%s, coalesce=%d min (last_pull=%s min ago)",
            device.device_imei,
            device.last_position_ts is None or (device.last_batch_ts and device.last_batch_ts > device.last_position_ts),
            coalesce_minutes,
            f"{last_pull_ago:.0f}" if last_pull_ago else "never"
        )
    
    return devices


# ═══════════════════════════════════════════════════════════════════════════
# TRACK.LIST API CALL
# ═══════════════════════════════════════════════════════════════════════════

async def _fetch_device_track(
    access_token: str,
    app_key: str,
    app_secret: str,
    imei: str,
    begin_time: datetime,
    end_time: datetime,
    map_type: str = "GOOGLE"
) -> Optional[Dict]:
    """
    Call jimi.device.track.list to get historical GPS track data for one device.
    
    Args:
        access_token: OAuth token
        imei: Device IMEI
        begin_time: Start of time window (forward-only: last_position_ts)
        end_time: End of time window (now)
        map_type: "GOOGLE" for calibrated coordinates
    
    Returns:
        Dict with:
        {
            'code': int,
            'message': str,
            'result': List[dict],  # GPS points
            'data': {'mileage': float}
        }
        or None if request fails
    """
    timestamp = datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S')
    begin_time_str = begin_time.strftime('%Y-%m-%d %H:%M:%S')
    end_time_str = end_time.strftime('%Y-%m-%d %H:%M:%S')
    
    params = {
        'access_token': access_token,
        'app_key': app_key,
        'begin_time': begin_time_str,
        'end_time': end_time_str,
        'format': 'json',
        'imei': imei,
        'map_type': map_type,
        'method': 'jimi.device.track.list',
        'sign_method': 'md5',
        'timestamp': timestamp,
        'v': '0.9',
    }
    
    # Generate signature
    params['sign'] = _generate_signature(params, app_secret)
    
    timeout = httpx.Timeout(READ_TIMEOUT_SECONDS, connect=CONNECT_TIMEOUT_SECONDS)
    
    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            logger.debug(
                "📡 Calling jimi.device.track.list: IMEI=%s, window=%s to %s",
                imei, begin_time_str, end_time_str
            )
            
            response = await client.post(OPEN_API_BASE_URL, data=params)
            response.raise_for_status()
            data = response.json()
            
            code = data.get('code', -1)
            message = data.get('message', 'Unknown error')
            
            if code == ERROR_CODE_SUCCESS:
                result = data.get('result', [])
                logger.info("✅ IMEI %s: Received %d GPS points", imei, len(result))
                return data
            
            elif code == ERROR_CODE_NO_DATA:
                logger.debug("ℹ️  IMEI %s: No track data in time range (code 10004)", imei)
                return data  # Return with empty result
            
            elif code == ERROR_CODE_PARAM_ERROR:
                logger.warning("⚠️  IMEI %s: Parameter error (code 10005): %s", imei, message)
                return data
            
            elif code == ERROR_CODE_RATE_LIMIT:
                logger.error("🚫 IMEI %s: Rate limit exceeded (code 10006): %s", imei, message)
                raise Exception(f"Rate limit exceeded: {message}")
            
            elif code == ERROR_CODE_AUTH_FAILED:
                logger.error("🔐 IMEI %s: Auth failed (code 10008): %s", imei, message)
                raise Exception(f"Auth failed: {message}")
            
            else:
                logger.error("❌ IMEI %s: API error code %d: %s", imei, code, message)
                return data
    
    except httpx.TimeoutException:
        logger.error("⏱️  IMEI %s: Request timeout", imei)
        return None
    
    except Exception as exc:
        logger.error("❌ IMEI %s: Request failed: %s", imei, exc)
        raise


# ═══════════════════════════════════════════════════════════════════════════
# POSITION STORAGE
# ═══════════════════════════════════════════════════════════════════════════

async def _upsert_track_positions(db: Session, imei: str, track_points: List[dict]) -> int:
    """
    Upsert track points to device_positions table.
    
    Args:
        imei: Device IMEI
        track_points: List of GPS point dicts from API
    
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
        
        # Parse coordinates
        try:
            lat = float(point.get('lat', 0))
            lng = float(point.get('lng', 0))
        except (ValueError, TypeError):
            continue
        
        if lat == 0 and lng == 0:
            continue
        
        # Defensive type conversion for integer fields
        def safe_int(value):
            """Convert to int or None. TrackSolid sometimes returns strings."""
            if value is None:
                return None
            try:
                return int(value)
            except (ValueError, TypeError):
                return None
        
        # Reverse geocode position (with smart caching)
        address = None
        try:
            # Import here to avoid circular dependency
            from app.services.tracksolid_batch_service import get_geocode_service
            geocode_service = get_geocode_service()
            result = geocode_service.reverse_geocode(
                device_imei=imei,
                lat=lat,
                lng=lng
            )
            address = result.get("address")
        except Exception as e:
            # Don't fail position insert if geocoding fails
            logger.warning("⚠️  Geocoding failed for IMEI %s: %s", imei, str(e))
        
        # Prepare position data
        position_data = {
            'device_imei': imei,
            'lat': lat,
            'lng': lng,
            'observed_at': observed_at,
            'direction': safe_int(point.get('direction')),
            'gps_speed': point.get('gpsSpeed'),
            'pos_type': safe_int(point.get('posType')),
            'satellite': safe_int(point.get('satellite')),
            'ignition': point.get('ignition'),
            'acc_status': point.get('accStatus'),
            'gps_mode': safe_int(point.get('gpsMode')),
            'confidence': safe_int(point.get('confidence')),
            'address': address,  # Add reverse geocoded address
            'source': 'tracklist',  # Tag as from selective pull
            'created_at': created_at,
        }
        
        # UPSERT with ON CONFLICT DO NOTHING (idempotent)
        stmt = insert(DevicePosition).values(**position_data).on_conflict_do_nothing(
            index_elements=['device_imei', 'observed_at']
        )
        result = db.execute(stmt)
        
        if result.rowcount > 0:
            inserted_count += 1
    
    db.commit()
    
    if inserted_count > 0:
        logger.info("💾 IMEI %s: Upserted %d/%d positions", imei, inserted_count, len(track_points))
    
    return inserted_count


async def _update_device_state_after_pull(
    db: Session,
    imei: str,
    latest_position_ts: Optional[datetime]
):
    """
    Update device_state after successful track.list pull.
    
    Updates:
    - last_position_ts: Latest GPS timestamp from this pull (forward-only window boundary)
    - last_tracklist_pull_at: Now (for coalesce throttling)
    """
    now = datetime.now(timezone.utc)
    
    # Get device state
    device_state = db.execute(
        select(DeviceState).where(DeviceState.device_imei == imei)
    ).scalar_one_or_none()
    
    if not device_state:
        logger.warning("⚠️  IMEI %s: device_state row not found (should exist from batch sweep)", imei)
        return
    
    # Update timestamps
    device_state.last_tracklist_pull_at = now
    
    if latest_position_ts:
        # Only update if newer than current (or NULL)
        if device_state.last_position_ts is None or latest_position_ts > device_state.last_position_ts:
            device_state.last_position_ts = latest_position_ts
            logger.debug(
                "📊 IMEI %s: Updated last_position_ts=%s, last_pull=%s",
                imei, latest_position_ts.isoformat(), now.isoformat()
            )
    
    device_state.updated_at = now
    db.commit()


# ═══════════════════════════════════════════════════════════════════════════
# SELECTIVE SWEEP ORCHESTRATION
# ═══════════════════════════════════════════════════════════════════════════

async def _process_single_device(
    db: Session,
    device_state: DeviceState,
    access_token: str,
    app_key: str,
    app_secret: str
) -> Dict:
    """
    Process one device: fetch track data, store positions, update state.
    
    Returns:
        Dict with processing statistics
    """
    imei = device_state.device_imei
    now = datetime.now(timezone.utc)
    
    # Determine time window (forward-only)
    if device_state.last_position_ts:
        begin_time = device_state.last_position_ts
    else:
        # First pull: start from 24 hours ago (or last_batch_ts if available)
        if device_state.last_batch_ts:
            begin_time = device_state.last_batch_ts - timedelta(hours=1)  # Small buffer
        else:
            begin_time = now - timedelta(hours=24)
    
    end_time = now
    
    # Skip if window is too small (< 1 minute)
    if (end_time - begin_time).total_seconds() < 60:
        logger.debug("⏭️  IMEI %s: Skipping (time window < 1 min)", imei)
        return {'imei': imei, 'status': 'skipped', 'reason': 'window_too_small'}
    
    try:
        # Fetch track data
        response = await _fetch_device_track(
            access_token, app_key, app_secret, imei, begin_time, end_time
        )
        
        if not response:
            return {'imei': imei, 'status': 'error', 'reason': 'request_failed'}
        
        code = response.get('code', -1)
        
        if code == ERROR_CODE_SUCCESS:
            track_points = response.get('result', [])
            
            # Upsert positions
            inserted_count = await _upsert_track_positions(db, imei, track_points)
            
            # Find latest GPS timestamp
            latest_position_ts = None
            if track_points:
                for point in track_points:
                    gps_time_str = point.get('gpsTime')
                    if gps_time_str:
                        try:
                            ts = datetime.strptime(str(gps_time_str), "%Y-%m-%d %H:%M:%S")
                            ts = ts.replace(tzinfo=timezone.utc)
                            if latest_position_ts is None or ts > latest_position_ts:
                                latest_position_ts = ts
                        except (ValueError, TypeError):
                            pass
            
            # Update device state
            await _update_device_state_after_pull(db, imei, latest_position_ts)
            
            return {
                'imei': imei,
                'status': 'success',
                'points_received': len(track_points),
                'points_inserted': inserted_count,
                'latest_position_ts': latest_position_ts.isoformat() if latest_position_ts else None
            }
        
        elif code == ERROR_CODE_NO_DATA:
            # No data in window - still update pull timestamp
            await _update_device_state_after_pull(db, imei, None)
            
            return {
                'imei': imei,
                'status': 'no_data',
                'points_received': 0,
                'points_inserted': 0
            }
        
        else:
            return {
                'imei': imei,
                'status': 'api_error',
                'code': code,
                'message': response.get('message', 'Unknown error')
            }
    
    except Exception as exc:
        logger.error("❌ IMEI %s: Processing failed: %s", imei, exc)
        return {
            'imei': imei,
            'status': 'exception',
            'error': str(exc)
        }


# ═══════════════════════════════════════════════════════════════════════════
# PUBLIC API
# ═══════════════════════════════════════════════════════════════════════════

async def run_selective_sweep(db: Session) -> Dict:
    """
    Run selective sweep: fetch track data for devices that meet 3-condition trigger.
    
    This is Tier 2 of the two-tier ingestion strategy.
    
    Steps:
    1. Find qualifying devices (3-condition trigger)
    2. For each device:
       a. Call jimi.device.track.list with forward-only window
       b. Upsert positions to device_positions
       c. Update last_position_ts and last_tracklist_pull_at
    3. Increment API call counter
    
    Returns:
        Dict with sweep statistics:
        {
            'success': bool,
            'devices_qualified': int,
            'devices_processed': int,
            'total_positions_inserted': int,
            'device_results': List[dict],
            'api_calls_today': int,
            'error': str | None
        }
    """
    try:
        # Step 1: Get access token
        account, password, app_key, app_secret = _get_credentials()
        access_token = await _get_access_token(db)
        
        # Step 2: Find qualifying devices
        qualifying_devices = await _get_qualifying_devices(db)
        
        if not qualifying_devices:
            logger.info("✅ Selective sweep complete: 0 qualifying devices")
            return {
                'success': True,
                'devices_qualified': 0,
                'devices_processed': 0,
                'total_positions_inserted': 0,
                'device_results': [],
                'api_calls_today': 0,
                'error': None
            }
        
        # Step 3: Process each device sequentially
        device_results = []
        total_positions_inserted = 0
        
        for device_state in qualifying_devices:
            result = await _process_single_device(
                db, device_state, access_token, app_key, app_secret
            )
            device_results.append(result)
            
            if result['status'] == 'success':
                total_positions_inserted += result['points_inserted']
            
            # Increment API call counter after each device
            await _increment_api_call_counter(db)
        
        # Get final API call count
        sync_state = db.execute(
            select(TrackSolidSyncState).where(TrackSolidSyncState.id == 1)
        ).scalar_one_or_none()
        
        # Update last_selective_sweep_at
        if sync_state:
            sync_state.last_selective_sweep_at = datetime.now(timezone.utc)
            db.commit()
        
        result = {
            'success': True,
            'devices_qualified': len(qualifying_devices),
            'devices_processed': len(device_results),
            'total_positions_inserted': total_positions_inserted,
            'device_results': device_results,
            'api_calls_today': sync_state.api_calls_today if sync_state else 0,
            'error': None
        }
        
        logger.info(
            "✅ Selective sweep complete: %d devices, %d positions inserted, %d API calls today",
            len(device_results), total_positions_inserted, result['api_calls_today']
        )
        
        return result
    
    except Exception as exc:
        logger.error("❌ Selective sweep failed: %s", exc, exc_info=True)
        return {
            'success': False,
            'devices_qualified': 0,
            'devices_processed': 0,
            'total_positions_inserted': 0,
            'device_results': [],
            'api_calls_today': 0,
            'error': str(exc)
        }


# ═══════════════════════════════════════════════════════════════════════════
# BACKGROUND TASK
# ═══════════════════════════════════════════════════════════════════════════

SELECTIVE_SWEEP_INTERVAL_MINUTES = 12  # Run after batch sweep (10min + 2min buffer)
_selective_sweep_task = None


async def _selective_sweep_loop():
    """Background task that runs selective sweep every 12 minutes."""
    from app.database import SessionLocal
    
    logger.info("🚀 Selective sweep loop started (interval: %d minutes)", SELECTIVE_SWEEP_INTERVAL_MINUTES)
    
    # Wait 2 minutes for first batch sweep to complete
    await asyncio.sleep(120)
    
    while True:
        try:
            db = SessionLocal()
            try:
                result = await run_selective_sweep(db)
                if result['success']:
                    logger.info("✅ Selective sweep: %d qualified, %d processed, %d positions inserted",
                               result['devices_qualified'], result['devices_processed'], result['total_positions_inserted'])
                else:
                    logger.error("❌ Selective sweep failed: %s", result['error'])
            finally:
                db.close()
        except Exception as exc:
            logger.error("❌ Selective sweep loop error: %s", exc, exc_info=True)
        
        # Wait for next cycle
        await asyncio.sleep(SELECTIVE_SWEEP_INTERVAL_MINUTES * 60)


def start_selective_sweep():
    """Start the selective sweep background task."""
    global _selective_sweep_task
    if _selective_sweep_task is None:
        _selective_sweep_task = asyncio.create_task(_selective_sweep_loop())
        logger.info("✅ Selective sweep task scheduled")
    else:
        logger.warning("⚠️  Selective sweep task already running")


# ═══════════════════════════════════════════════════════════════════════════
# TESTING / MANUAL TRIGGER
# ═══════════════════════════════════════════════════════════════════════════

async def main():
    """Test selective sweep service (manual trigger)."""
    from app.database import SessionLocal
    
    db = SessionLocal()
    try:
        result = await run_selective_sweep(db)
        print("\n" + "="*60)
        print("SELECTIVE SWEEP RESULT:")
        print("="*60)
        print(f"         Success: {result['success']}")
        print(f" Devices Qualified: {result['devices_qualified']}")
        print(f"Devices Processed: {result['devices_processed']}")
        print(f"Positions Inserted: {result['total_positions_inserted']}")
        print(f"API Calls Today: {result['api_calls_today']}")
        
        if result['device_results']:
            print(f"\nDevice Results:")
            for dev_result in result['device_results']:
                print(f"\n  IMEI: {dev_result['imei']}")
                print(f"  Status: {dev_result['status']}")
                if dev_result['status'] == 'success':
                    print(f"  Points Received: {dev_result['points_received']}")
                    print(f"  Points Inserted: {dev_result['points_inserted']}")
                    if dev_result.get('latest_position_ts'):
                        print(f"  Latest Position: {dev_result['latest_position_ts']}")
        
        print("="*60)
    finally:
        db.close()


if __name__ == "__main__":
    asyncio.run(main())
