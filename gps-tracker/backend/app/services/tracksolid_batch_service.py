"""
TrackSolid Batch Sweep Service (Trip Engine - Section 1 Ingestion)

Implements the first tier of the two-tier API strategy from PinPlot_Trip_Engine_Spec_v2.md.

Architecture:
    Tier 1 (this file): Batch sweep every 10 minutes
        - Call jimi.user.device.location.list → ALL devices, 1 API call
        - Upsert to device_positions table
        - Update device_state.last_batch_ts (for trigger detection)
    
    Tier 2 (tracksolid_track_service.py): Selective track.list
        - Only calls if 3 conditions met: new data + subscribed + coalesce passed
        - ~10 devices per cycle = ~11 total API calls per 10 min
        - Total: 1,584 calls/day (vs 86,400 limit ✅)

Key Concerns:
    - UNIQUE constraint on (device_imei, observed_at) prevents duplicates
    - ON CONFLICT DO NOTHING = idempotent upserts
    - Updates tracksolid_sync_state.api_calls_today (rate limiting)
    - Batch sweep does NOT trigger track.list calls (that's Phase 2.2)
"""

import asyncio
import hashlib
import logging
from datetime import datetime, timedelta, timezone

import httpx
from sqlalchemy import select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from app.models import (
    DevicePosition,
    DeviceState,
    TrackSolidSyncState,
    APIToken,
)

logger = logging.getLogger(__name__)

# ── API Constants ──────────────────────────────────────────────────────────
OPEN_API_BASE_URL = "https://eu-open.tracksolidpro.com/route/rest"
OPEN_API_TOKEN_TTL_SECONDS = 3600  # 1 hour
OPEN_API_TOKEN_REFRESH_BUFFER = 60  # Refresh 60s before expiry

# Rate limiting (TrackSolid limit: 86,400 calls/day)
MAX_API_CALLS_PER_DAY = 86400

# Timeouts
CONNECT_TIMEOUT_SECONDS = 10
READ_TIMEOUT_SECONDS = 30


# ═══════════════════════════════════════════════════════════════════════════
# CREDENTIAL MANAGEMENT
# ═══════════════════════════════════════════════════════════════════════════

def _get_credentials() -> tuple[str, str, str, str]:
    """Return (account, password, app_key, app_secret) from environment."""
    import os
    return (
        os.environ["TRACKSOLID_ACCOUNT"],
        os.environ["TRACKSOLID_PASSWORD"],
        os.environ["TRACKSOLID_APP_KEY"],
        os.environ["TRACKSOLID_APP_SECRET"],
    )


def _generate_signature(params: dict, app_secret: str) -> str:
    """
    Generate MD5 signature for Jimi Open API.
    
    Algorithm:
    1. Sort all params (except 'sign') alphabetically by key
    2. Concatenate as: key1value1key2value2...
    3. Wrap with: app_secret + concat + app_secret
    4. MD5 and uppercase
    """
    sorted_keys = sorted(params.keys())
    concat = ''.join(k + str(params[k]) for k in sorted_keys)
    sign_string = app_secret + concat + app_secret
    return hashlib.md5(sign_string.encode('utf-8')).hexdigest().upper()


# ═══════════════════════════════════════════════════════════════════════════
# TOKEN MANAGEMENT (Database-backed cache)
# ═══════════════════════════════════════════════════════════════════════════

async def _get_cached_token(db: Session) -> str | None:
    """Get cached access_token from database if still valid."""
    token_row = db.execute(
        select(APIToken).where(APIToken.provider == "tracksolid_open_api")
    ).scalar_one_or_none()
    
    if not token_row or not token_row.access_token:
        return None
    
    # Check if token is still valid (with buffer)
    if token_row.expires_at:
        now = datetime.now(timezone.utc)
        buffer = timedelta(seconds=OPEN_API_TOKEN_REFRESH_BUFFER)
        if token_row.expires_at > now + buffer:
            logger.info("♻️  TrackSolid: Using cached token (valid for %ds)", 
                       int((token_row.expires_at - now).total_seconds()))
            return token_row.access_token
    
    return None


async def _save_token_to_db(db: Session, access_token: str, expires_in: int):
    """Save access_token to database with expiry time."""
    expires_at = datetime.now(timezone.utc) + timedelta(seconds=expires_in)
    
    # PostgreSQL UPSERT
    stmt = insert(APIToken).values(
        provider="tracksolid_open_api",
        access_token=access_token,
        expires_at=expires_at,
        updated_at=datetime.now(timezone.utc)
    ).on_conflict_do_update(
        index_elements=['provider'],
        set_={
            'access_token': access_token,
            'expires_at': expires_at,
            'updated_at': datetime.now(timezone.utc)
        }
    )
    db.execute(stmt)
    db.commit()
    logger.info("💾 TrackSolid: Token cached in database (expires in %ds)", expires_in)


async def _fetch_oauth_token(account: str, password: str, app_key: str, app_secret: str) -> tuple[str, int]:
    """
    Fetch OAuth access_token from TrackSolid Open API.
    
    Returns:
        (access_token, expires_in) tuple
    
    Raises:
        Exception if API call fails
    """
    timestamp = datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S')
    
    params = {
        'user_id': account,
        'user_pwd': password,
        'app_key': app_key,
        'timestamp': timestamp,
    }
    
    # Generate signature
    params['sign'] = _generate_signature(params, app_secret)
    
    timeout = httpx.Timeout(READ_TIMEOUT_SECONDS, connect=CONNECT_TIMEOUT_SECONDS)
    
    async with httpx.AsyncClient(timeout=timeout) as client:
        logger.info("🔑 TrackSolid: Fetching OAuth token...")
        response = await client.post(
            f"{OPEN_API_BASE_URL}",
            params={
                'method': 'jimi.oauth.token.get',
                **params
            }
        )
        response.raise_for_status()
        data = response.json()
        
        if data.get('code') != 0:
            error_msg = data.get('message', 'Unknown error')
            logger.error("❌ TrackSolid OAuth failed: %s", error_msg)
            raise Exception(f"TrackSolid OAuth error: {error_msg}")
        
        result = data.get('result', {})
        access_token = result.get('accessToken')
        expires_in = result.get('expiresIn', OPEN_API_TOKEN_TTL_SECONDS)
        
        if not access_token:
            raise Exception("No access_token in response")
        
        logger.info("✅ TrackSolid: OAuth token obtained (expires in %ds)", expires_in)
        return access_token, expires_in


async def _get_access_token(db: Session) -> str:
    """
    Get valid access_token with database caching.
    
    Returns:
        Valid access_token string
    
    Raises:
        Exception if token fetch fails
    """
    # Try cache first
    cached_token = await _get_cached_token(db)
    if cached_token:
        return cached_token
    
    # Fetch new token
    account, password, app_key, app_secret = _get_credentials()
    access_token, expires_in = await _fetch_oauth_token(account, password, app_key, app_secret)
    
    # Save to database
    await _save_token_to_db(db, access_token, expires_in)
    
    return access_token


# ═══════════════════════════════════════════════════════════════════════════
# BATCH SWEEP IMPLEMENTATION
# ═══════════════════════════════════════════════════════════════════════════

async def _fetch_batch_locations(access_token: str, app_key: str, app_secret: str, account: str) -> list[dict]:
    """
    Call jimi.user.device.location.list to get ALL device locations in one API call.
    
    Returns:
        List of location dictionaries with fields:
        - imei, lat, lng, gpsTime, speed, direction, satellite, ignition, 
          accStatus, posType, gpsMode, confidence
    """
    timestamp = datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S')
    
    params = {
        'access_token': access_token,
        'app_key': app_key,
        'user_id': account,
        'timestamp': timestamp,
    }
    
    # Generate signature
    params['sign'] = _generate_signature(params, app_secret)
    
    timeout = httpx.Timeout(READ_TIMEOUT_SECONDS, connect=CONNECT_TIMEOUT_SECONDS)
    
    async with httpx.AsyncClient(timeout=timeout) as client:
        logger.info("📡 TrackSolid: Fetching batch locations...")
        response = await client.post(
            f"{OPEN_API_BASE_URL}",
            params={
                'method': 'jimi.user.device.location.list',
                **params
            }
        )
        response.raise_for_status()
        data = response.json()
        
        if data.get('code') != 0:
            error_msg = data.get('message', 'Unknown error')
            logger.error("❌ TrackSolid batch locations failed: %s", error_msg)
            raise Exception(f"TrackSolid API error: {error_msg}")
        
        result = data.get('result', [])
        logger.info("✅ TrackSolid: Received %d device locations", len(result))
        return result


async def _upsert_positions(db: Session, locations: list[dict]) -> int:
    """
    Upsert locations to device_positions table.
    
    Returns:
        Number of new positions inserted (excludes duplicates)
    """
    if not locations:
        return 0
    
    batch_ts = datetime.now(timezone.utc)
    inserted_count = 0
    
    for loc in locations:
        imei = str(loc.get('imei', '')).strip()
        if not imei:
            continue
        
        # Parse GPS time
        gps_time_str = loc.get('gpsTime')
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
            lat = float(loc.get('lat', 0))
            lng = float(loc.get('lng', 0))
        except (ValueError, TypeError):
            continue
        
        if lat == 0 and lng == 0:
            continue
        
        # Prepare position data
        position_data = {
            'device_imei': imei,
            'lat': lat,
            'lng': lng,
            'observed_at': observed_at,
            'direction': loc.get('direction'),
            'gps_speed': loc.get('speed'),
            'pos_type': loc.get('posType'),
            'satellite': loc.get('satellite'),
            'ignition': loc.get('ignition'),
            'acc_status': loc.get('accStatus'),
            'gps_mode': loc.get('gpsMode'),
            'confidence': loc.get('confidence'),
            'source': 'batch',
            'created_at': batch_ts,
        }
        
        # UPSERT with ON CONFLICT DO NOTHING (idempotent)
        stmt = insert(DevicePosition).values(**position_data).on_conflict_do_nothing(
            index_elements=['device_imei', 'observed_at']
        )
        result = db.execute(stmt)
        
        # Check if row was inserted (rowcount > 0) or skipped (rowcount = 0)
        if result.rowcount > 0:
            inserted_count += 1
    
    db.commit()
    logger.info("💾 Upserted %d/%d positions to device_positions", inserted_count, len(locations))
    return inserted_count


async def _update_device_states(db: Session, locations: list[dict]):
    """
    Update device_state.last_batch_ts for all devices in the batch.
    
    Creates device_state rows if they don't exist (with trip_subscribed=false default).
    """
    if not locations:
        return
    
    batch_ts = datetime.now(timezone.utc)
    imeis = {str(loc.get('imei', '')).strip() for loc in locations if loc.get('imei')}
    imeis = {imei for imei in imeis if imei}  # Remove empty strings
    
    if not imeis:
        return
    
    for imei in imeis:
        # UPSERT device_state row
        stmt = insert(DeviceState).values(
            device_imei=imei,
            last_batch_ts=batch_ts,
            trip_subscribed=False,
            created_at=batch_ts,
            updated_at=batch_ts,
        ).on_conflict_do_update(
            index_elements=['device_imei'],
            set_={
                'last_batch_ts': batch_ts,
                'updated_at': batch_ts,
            }
        )
        db.execute(stmt)
    
    db.commit()
    logger.info("📊 Updated device_state.last_batch_ts for %d devices", len(imeis))


async def _increment_api_call_counter(db: Session):
    """
    Increment tracksolid_sync_state.api_calls_today counter.
    
    Resets counter at midnight UTC.
    """
    now = datetime.now(timezone.utc)
    
    # Get or create sync state row (singleton)
    sync_state = db.execute(
        select(TrackSolidSyncState).where(TrackSolidSyncState.id == 1)
    ).scalar_one_or_none()
    
    if not sync_state:
        # Create initial row
        sync_state = TrackSolidSyncState(
            id=1,
            last_batch_sweep_at=now,
            api_calls_today=1,
            api_calls_reset_at=now.replace(hour=0, minute=0, second=0, microsecond=0) + timedelta(days=1),
            updated_at=now,
        )
        db.add(sync_state)
    else:
        # Check if we need to reset counter (new day)
        if sync_state.api_calls_reset_at and now >= sync_state.api_calls_reset_at:
            sync_state.api_calls_today = 1
            sync_state.api_calls_reset_at = now.replace(hour=0, minute=0, second=0, microsecond=0) + timedelta(days=1)
            logger.info("🔄 Reset API call counter (new day)")
        else:
            sync_state.api_calls_today += 1
        
        sync_state.last_batch_sweep_at = now
        sync_state.updated_at = now
        
        # Warn if approaching rate limit
        if sync_state.api_calls_today > MAX_API_CALLS_PER_DAY * 0.9:
            logger.warning("⚠️  TrackSolid API calls today: %d/%d (90%% limit!)", 
                          sync_state.api_calls_today, MAX_API_CALLS_PER_DAY)
    
    db.commit()
    logger.info("📈 API calls today: %d/%d", sync_state.api_calls_today, MAX_API_CALLS_PER_DAY)


# ═══════════════════════════════════════════════════════════════════════════
# PUBLIC API
# ═══════════════════════════════════════════════════════════════════════════

async def run_batch_sweep(db: Session) -> dict:
    """
    Run batch sweep: fetch ALL device locations and store in device_positions.
    
    This is Tier 1 of the two-tier ingestion strategy.
    
    Steps:
    1. Get OAuth access_token (with database caching)
    2. Call jimi.user.device.location.list → ALL devices, 1 API call
    3. Upsert to device_positions table (ON CONFLICT DO NOTHING)
    4. Update device_state.last_batch_ts (for trigger detection)
    5. Increment tracksolid_sync_state.api_calls_today
    
    Returns:
        Dict with sweep statistics:
        {
            'success': bool,
            'devices_received': int,
            'positions_inserted': int,
            'api_calls_today': int,
            'error': str | None
        }
    """
    try:
        # Step 1: Get access token
        account, password, app_key, app_secret = _get_credentials()
        access_token = await _get_access_token(db)
        
        # Step 2: Fetch batch locations
        locations = await _fetch_batch_locations(access_token, app_key, app_secret, account)
        
        # Step 3: Upsert positions
        inserted_count = await _upsert_positions(db, locations)
        
        # Step 4: Update device states
        await _update_device_states(db, locations)
        
        # Step 5: Increment API call counter
        await _increment_api_call_counter(db)
        
        # Get final API call count
        sync_state = db.execute(
            select(TrackSolidSyncState).where(TrackSolidSyncState.id == 1)
        ).scalar_one_or_none()
        
        result = {
            'success': True,
            'devices_received': len(locations),
            'positions_inserted': inserted_count,
            'api_calls_today': sync_state.api_calls_today if sync_state else 1,
            'error': None
        }
        
        logger.info("✅ Batch sweep complete: %d devices, %d new positions", 
                   len(locations), inserted_count)
        return result
        
    except Exception as exc:
        logger.error("❌ Batch sweep failed: %s", exc, exc_info=True)
        return {
            'success': False,
            'devices_received': 0,
            'positions_inserted': 0,
            'api_calls_today': 0,
            'error': str(exc)
        }


# ═══════════════════════════════════════════════════════════════════════════
# TESTING / MANUAL TRIGGER
# ═══════════════════════════════════════════════════════════════════════════

# ═══════════════════════════════════════════════════════════════════════════
# BACKGROUND TASK
# ═══════════════════════════════════════════════════════════════════════════

BATCH_SWEEP_INTERVAL_MINUTES = 10
_batch_sweep_task = None


async def _batch_sweep_loop():
    """Background task that runs batch sweep every 10 minutes."""
    from app.database import SessionLocal
    
    logger.info("🚀 Batch sweep loop started (interval: %d minutes)", BATCH_SWEEP_INTERVAL_MINUTES)
    
    while True:
        try:
            db = SessionLocal()
            try:
                result = await run_batch_sweep(db)
                if result['success']:
                    logger.info("✅ Batch sweep: %d devices, %d new positions, %d API calls today",
                               result['devices_received'], result['positions_inserted'], result['api_calls_today'])
                else:
                    logger.error("❌ Batch sweep failed: %s", result['error'])
            finally:
                db.close()
        except Exception as exc:
            logger.error("❌ Batch sweep loop error: %s", exc, exc_info=True)
        
        # Wait for next cycle
        await asyncio.sleep(BATCH_SWEEP_INTERVAL_MINUTES * 60)


def start_batch_sweep():
    """Start the batch sweep background task."""
    global _batch_sweep_task
    if _batch_sweep_task is None:
        _batch_sweep_task = asyncio.create_task(_batch_sweep_loop())
        logger.info("✅ Batch sweep task scheduled")
    else:
        logger.warning("⚠️  Batch sweep task already running")


async def main():
    """Test batch sweep service (manual trigger)."""
    from app.database import SessionLocal
    
    db = SessionLocal()
    try:
        result = await run_batch_sweep(db)
        print("\n" + "="*60)
        print("BATCH SWEEP RESULT:")
        print("="*60)
        for key, value in result.items():
            print(f"{key:>20}: {value}")
        print("="*60)
    finally:
        db.close()


if __name__ == "__main__":
    asyncio.run(main())
