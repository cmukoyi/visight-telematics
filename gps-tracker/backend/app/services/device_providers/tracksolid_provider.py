"""
TrackSolid device provider.

Implements the Strategy interface for tags registered on the TrackSolid
(eu.tracksolidpro.com) platform.

Key concerns:
- TrackSolid rate-limits token requests. The token is valid for 1 hour.
  TrackSolidTokenManager (Singleton) caches it per worker process and only
  fetches a fresh one when the current token is within 60 seconds of expiry.
- Credentials are stored server-side only — never sent to the mobile client.
- Validation: log in → list all equipment → check if the IMEI appears.
- Location: uses the TrackSolid Open API (eu-open.tracksolidpro.com) which
  returns all device lat/lng in a single bulk call for efficiency.
"""

import asyncio
import hashlib
import logging
import os
import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone

import httpx

from .base_provider import DeviceTagProvider, TagValidationResult

logger = logging.getLogger(__name__)

# ── TrackSolid API constants ────────────────────────────────────────────────
_BASE_URL = "https://eu.tracksolidpro.com"
_LOGIN_URL = f"{_BASE_URL}/v3/new/homepage/login"
_EQUIPMENT_URL = f"{_BASE_URL}/v3/new/newEquipment/queryEquipmentList"
_TRACK_HISTORY_URL = f"{_BASE_URL}/v3/new/newTrackInfo/getPointList"
# V3 monitor endpoint — used for live location polling (Bearer JWT)
_MONITOR_INFO_URL = f"{_BASE_URL}/v3/new/newMonitor/getMonitorInfo"


@dataclass
class TrackSolidLocationInfo:
    """Location data returned by the TrackSolid Open API."""
    latitude: float
    longitude: float
    address: str | None = None
    battery_level: int | None = None  # 0-100 parsed from elecQuantity
    gps_time: "datetime | None" = None  # actual GPS fix time from device

# Credentials are read lazily from env vars when first needed.
# Reading them at module level would crash startup if they aren't set yet.
def _creds() -> tuple[str, str, int, str]:
    """Return (account, password, user_id, org_id) from environment."""
    return (
        os.environ["TRACKSOLID_ACCOUNT"],
        os.environ["TRACKSOLID_PASSWORD"],
        int(os.environ["TRACKSOLID_USER_ID"]),
        os.environ["TRACKSOLID_ORG_ID"],
    )

_TOKEN_TTL_SECONDS = 3600       # TrackSolid tokens last 1 hour
_TOKEN_REFRESH_BUFFER = 60      # Refresh 60 s before expiry to be safe

# ── Failure backoff ─────────────────────────────────────────────────────────
# When a token fetch fails (network block, WAF ban, upstream down) we cache
# the failure for an escalating cooldown so we don't hammer TrackSolid's
# login endpoint. Hammering is what gets the source IP banned in the first
# place, and once banned every poll would otherwise stall the backend for
# the full connect timeout, eating workers and triggering OOM.
_FAIL_BACKOFF_SCHEDULE = (30, 120, 600, 1800)  # seconds: 30s → 2m → 10m → 30m
_CONNECT_TIMEOUT_SECONDS = 5     # fail fast on TCP block
_READ_TIMEOUT_SECONDS = 15       # leave room for a real slow response


# ── Singleton token manager ──────────────────────────────────────────────────
class TrackSolidTokenManager:
    """
    Singleton that holds one TrackSolid JWT per worker process.

    asyncio.Lock ensures only one coroutine fetches a new token at a time,
    preventing duplicate login calls when multiple requests arrive simultaneously
    while the token is being refreshed.
    """

    _instance: "TrackSolidTokenManager | None" = None
    # Declared here so type checkers know the shape; values set in __new__
    _token: "str | None"
    _expires_at: float
    _lock: asyncio.Lock
    _last_failure_at: float
    _failure_streak: int
    _last_failure_msg: str

    def __new__(cls) -> "TrackSolidTokenManager":
        if cls._instance is None:
            inst = object.__new__(cls)
            inst._token = None
            inst._expires_at = 0.0
            inst._lock = asyncio.Lock()
            inst._last_failure_at = 0.0
            inst._failure_streak = 0
            inst._last_failure_msg = ""
            cls._instance = inst
        return cls._instance

    def _current_backoff(self) -> int:
        idx = min(self._failure_streak - 1, len(_FAIL_BACKOFF_SCHEDULE) - 1)
        return _FAIL_BACKOFF_SCHEDULE[max(idx, 0)]

    async def get_token(self) -> str:
        """Return a valid token, fetching a new one only when necessary."""
        async with self._lock:
            now = time.time()
            if self._token and now < self._expires_at - _TOKEN_REFRESH_BUFFER:
                remaining = int(self._expires_at - now)
                logger.info(
                    "♻️  TrackSolid: reusing cached token (expires in %ds)", remaining
                )
                return self._token

            # If a previous fetch failed recently, fail fast instead of
            # re-hammering TrackSolid (which can get us IP-banned).
            if self._failure_streak > 0:
                wait = self._current_backoff() - (now - self._last_failure_at)
                if wait > 0:
                    logger.warning(
                        "⏸️  TrackSolid: in backoff (%d failures, retry in %ds): %s",
                        self._failure_streak, int(wait), self._last_failure_msg,
                    )
                    raise RuntimeError(
                        f"TrackSolid unavailable (backoff {int(wait)}s): "
                        f"{self._last_failure_msg}"
                    )

            logger.info("🔄 TrackSolid: fetching new token (old token expired or absent)")
            try:
                token = await self._fetch_token()
            except Exception as exc:
                self._failure_streak += 1
                self._last_failure_at = time.time()
                self._last_failure_msg = f"{type(exc).__name__}: {exc}" or repr(exc)
                logger.error(
                    "❌ TrackSolid token fetch failed (streak=%d, next retry in %ds): %s",
                    self._failure_streak, self._current_backoff(),
                    self._last_failure_msg,
                )
                raise
            self._token = token
            self._expires_at = time.time() + _TOKEN_TTL_SECONDS
            self._failure_streak = 0
            self._last_failure_msg = ""
            logger.info("✅ TrackSolid: new token obtained, valid for ~1 hour")
            return self._token

    async def _fetch_token(self) -> str:
        account, password, _, _ = _creds()
        password_md5 = hashlib.md5(password.encode()).hexdigest().lower()
        payload = {
            "account": account,
            "password": password_md5,
            "language": "en",
            "validCode": "",
            "nodeId": "",
        }
        timeout = httpx.Timeout(_READ_TIMEOUT_SECONDS, connect=_CONNECT_TIMEOUT_SECONDS)
        try:
            async with httpx.AsyncClient(timeout=timeout) as client:
                response = await client.post(_LOGIN_URL, json=payload)
                response.raise_for_status()
                data = response.json()
        except (httpx.ConnectTimeout, httpx.ConnectError) as exc:
            # TCP-level failure — almost always a WAF / IP block at TrackSolid.
            raise RuntimeError(
                f"🚫 TrackSolid WAF block suspected — cannot reach {_BASE_URL} "
                f"({type(exc).__name__}). Source IP may be banned."
            ) from exc
        except httpx.HTTPStatusError as exc:
            # WAF returning an explicit status (403/429/503) — also distinctive.
            raise RuntimeError(
                f"🚫 TrackSolid login HTTP {exc.response.status_code} "
                f"— likely WAF/rate-limit block"
            ) from exc

        # TrackSolid V3 API stores the JWT in one of several possible paths.
        # Try the most common ones in order.
        token = (
            (data.get("data") or {}).get("authorization")
            or (data.get("data") or {}).get("token")
            or data.get("authorization")
            or data.get("token")
            or data.get("accessToken")
        )
        if not token:
            raise RuntimeError(
                f"TrackSolid login succeeded (HTTP {response.status_code}) "
                f"but no token found in response: {list(data.keys())}"
            )
        return token


# Module-level singleton instance
_token_manager = TrackSolidTokenManager()


# ── TrackSolid tag provider (Strategy) ─────────────────────────────────────
class TrackSolidTagProvider(DeviceTagProvider):
    """
    Validates a BLE tag IMEI against the BeaconTelematics TrackSolid account.

    Flow:
      1. Obtain (or reuse) a valid JWT via TrackSolidTokenManager.
      2. POST to the equipment list endpoint.
      3. If the IMEI is present → valid; otherwise → "Tag not found on TrackSolid".
    """

    @property
    def provider_name(self) -> str:
        return "TrackSolid"

    @property
    def tag_type(self) -> str:
        return "tracksolid"

    async def validate_tag(self, imei: str) -> TagValidationResult:
        try:
            token = await _token_manager.get_token()
        except Exception as exc:
            logger.error("TrackSolid token fetch failed: %s", exc)
            return TagValidationResult(
                is_valid=False,
                message="Could not connect to TrackSolid. Please try again later.",
            )

        _, _, user_id, org_id = _creds()
        payload = {
            "imei": imei.strip(),  # filter to this IMEI avoids pagination issues
            "startRow": "0",
            "userType": 8,
            "userId": user_id,
            "orgId": org_id,
            "siftType": "",
            "sortType": "",
            "sortRule": "",
            "isNewMcType": "0",
            "videoEntry": "",
            "type": "NORMAL",
            "searchStatus": "ALL",
        }
        headers = {
            "Authorization": token,
            "Content-Type": "application/json",
        }

        try:
            async with httpx.AsyncClient(timeout=20) as client:
                response = await client.post(
                    _EQUIPMENT_URL, json=payload, headers=headers
                )
                response.raise_for_status()
                data = response.json()
        except httpx.HTTPStatusError as exc:
            logger.error("TrackSolid equipment list HTTP error: %s", exc)
            return TagValidationResult(
                is_valid=False,
                message="TrackSolid API error. Please try again later.",
            )
        except Exception as exc:
            logger.error("TrackSolid equipment list error: %s", exc)
            return TagValidationResult(
                is_valid=False,
                message="Could not reach TrackSolid. Check your connection.",
            )

        # Parse the device list — handle both wrapped and flat response shapes
        devices: list = []
        result_data = data.get("data") or data.get("result") or {}
        if isinstance(result_data, list):
            devices = result_data
        elif isinstance(result_data, dict):
            devices = (
                result_data.get("list")
                or result_data.get("data")
                or result_data.get("records")
                or []
            )

        imei_strip = imei.strip()
        logger.debug("TrackSolid returned %d device(s) for IMEI query '%s'", len(devices), imei_strip)
        found_device = None
        for device in devices:
            if str(device.get("imei", "")).strip() == imei_strip:
                found_device = device
                break

        if found_device is not None:
            # Parse elecQuantity "98.30%" → int 98
            battery_level: int | None = None
            elec = found_device.get("elecQuantity", "") or ""
            if elec:
                try:
                    battery_level = int(float(str(elec).rstrip("%")))
                except (ValueError, TypeError):
                    pass

            return TagValidationResult(
                is_valid=True,
                message="Series 2 tag verified.",
                battery_level=battery_level,
            )
        return TagValidationResult(
            is_valid=False,
            message="Tag not supported — IMEI not found on TrackSolid account.",
        )


# Note: The legacy TrackSolid Open API (eu-open.tracksolidpro.com) used
# app_key/app_secret signing. That code path was never invoked anywhere
# in the backend — location polling uses the V3 Bearer-JWT _MONITOR_INFO_URL
# below. The dead Open-API helpers were removed on 2026-05-19 along with
# the latent KeyError landmine for the unset TRACKSOLID_APP_KEY /
# TRACKSOLID_APP_SECRET env vars they referenced.


# ── Location helpers (used by location poller) ──────────────────────────────

def _parse_monitor_info_location(data: dict) -> "TrackSolidLocationInfo | None":
    """
    Parse a getMonitorInfo response dict into TrackSolidLocationInfo.

    Extracts:
      - lat/lng from data[latestPosition].latlng[source_latlng] ("lat,lng")
      - address from data[latestPosition].address
      - gps_time from data[latestPosition].positionTime (or gpsTime / time)
      - battery from data[todayActivity].battery[battery]
    """
    sections: list = data.get("data") or []
    lat, lng = 0.0, 0.0
    address: str | None = None
    battery_level: int | None = None
    gps_time: datetime | None = None

    # Candidate key names for the GPS fix timestamp in latestPosition
    _TIME_KEYS = {"positionTime", "gpsTime", "time", "dateTime", "posTime"}

    def _try_parse_ts(value: str) -> "datetime | None":
        """Try common timestamp formats: ISO, 'YYYY-MM-DD HH:MM:SS', epoch int."""
        if not value:
            return None
        # Unix epoch (int or float as string)
        try:
            epoch = float(value)
            if epoch > 1_000_000_000:  # sanity check
                return datetime.utcfromtimestamp(epoch)
        except (ValueError, TypeError):
            pass
        # String formats
        for fmt in ("%Y-%m-%dT%H:%M:%SZ", "%Y-%m-%dT%H:%M:%S",
                    "%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S.%fZ"):
            try:
                return datetime.strptime(str(value), fmt)
            except (ValueError, TypeError):
                pass
        return None

    for section in sections:
        model = section.get("modeleName", "")
        vos: list = section.get("monitorBaseVOS") or []

        if model == "latestPosition":
            for item in vos:
                key = item.get("key", "")
                if key == "latlng":
                    for sub in (item.get("value") or []):
                        if sub.get("key") == "source_latlng":
                            try:
                                parts = str(sub["value"]).split(",")
                                lat = float(parts[0].strip())
                                lng = float(parts[1].strip())
                            except (ValueError, IndexError, KeyError):
                                pass
                elif key == "address":
                    address = item.get("value") or None
                elif key in _TIME_KEYS and gps_time is None:
                    gps_time = _try_parse_ts(item.get("value"))
                    if gps_time is None:
                        # Also check sub-values
                        for sub in (item.get("value") or []) if isinstance(item.get("value"), list) else []:
                            if sub.get("key") in _TIME_KEYS:
                                gps_time = _try_parse_ts(sub.get("value"))
                                if gps_time:
                                    break

        elif model == "todayActivity":
            for item in vos:
                if item.get("key") == "battery":
                    for sub in (item.get("value") or []):
                        if sub.get("key") == "battery":
                            try:
                                battery_level = int(float(str(sub["value"])))
                            except (ValueError, TypeError, KeyError):
                                pass

    if lat == 0.0 and lng == 0.0:
        return None
    return TrackSolidLocationInfo(
        latitude=lat,
        longitude=lng,
        address=address,
        battery_level=battery_level,
        gps_time=gps_time,
    )


async def _fetch_monitor_info_single(imei: str) -> "TrackSolidLocationInfo | None":
    """Call getMonitorInfo for one IMEI using the V3 Bearer JWT."""
    try:
        token = await _token_manager.get_token()
    except Exception as exc:
        logger.error("TrackSolid: token fetch failed for getMonitorInfo: %s", exc)
        return None

    _, _, user_id, _ = _creds()
    payload = {"imei": imei.strip(), "userId": user_id, "isAllFlag": 1}
    headers = {"Authorization": token, "Content-Type": "application/json"}

    try:
        async with httpx.AsyncClient(timeout=15) as client:
            response = await client.post(_MONITOR_INFO_URL, json=payload, headers=headers)
            response.raise_for_status()
            data = response.json()
    except Exception as exc:
        logger.error("TrackSolid: getMonitorInfo HTTP error for IMEI %s: %s", imei, exc)
        return None

    if not data.get("ok"):
        logger.error(
            "TrackSolid: getMonitorInfo error IMEI %s: code=%s msg=%s",
            imei, data.get("code"), data.get("msg"),
        )
        return None

    return _parse_monitor_info_location(data)


async def fetch_all_tracksolid_locations(
    imeis: "list[str] | None" = None,
) -> "dict[str, TrackSolidLocationInfo]":
    """
    Fetch current locations for TrackSolid devices using getMonitorInfo
    (V3 Bearer JWT, per-IMEI calls run in parallel).

    Args:
        imeis: List of IMEI strings to query. When None/empty returns {}.

    Returns a dict keyed by IMEI string. Missing entries mean no GPS fix.
    """
    if not imeis:
        return {}

    # Pre-flight: try to get a token ONCE. If TrackSolid is unreachable
    # (WAF block, network outage, or we're in backoff), fail the whole batch
    # with a single clear log line instead of 110× per-IMEI spam.
    try:
        await _token_manager.get_token()
    except Exception as exc:
        logger.error(
            "🚫 TrackSolid batch skipped — %d IMEIs not polled this cycle: %s",
            len(imeis), exc,
        )
        return {}

    tasks = [_fetch_monitor_info_single(imei) for imei in imeis]
    results = await asyncio.gather(*tasks, return_exceptions=True)

    result_map: dict[str, TrackSolidLocationInfo] = {}
    for imei, loc in zip(imeis, results):
        if isinstance(loc, Exception):
            logger.error("TrackSolid: getMonitorInfo exception for IMEI %s: %s", imei, loc)
        elif loc is not None:
            result_map[imei.strip()] = loc

    logger.info(
        "📍 TrackSolid getMonitorInfo: %d/%d locations fetched",
        len(result_map), len(imeis),
    )
    return result_map


async def fetch_tracksolid_location(imei: str) -> "TrackSolidLocationInfo | None":
    """
    Fetch the current location for a single TrackSolid IMEI via getMonitorInfo.
    Returns None when there is no GPS fix.
    """
    loc = await _fetch_monitor_info_single(imei)
    if not loc:
        logger.warning("TrackSolid: no location for IMEI %s", imei)
    return loc


async def fetch_tracksolid_journey_points(
    imei: str,
    start_time: str,
    end_time: str,
) -> "dict | None":
    """
    Fetch GPS track points for a TrackSolid device over a date range.

    Uses the V3 Bearer token (JWT from login endpoint — same token used for
    equipment validation, NOT the Open API MD5 token).

    start_time / end_time format: "YYYY-MM-DD HH:MM:SS"

    Returns the raw API ``data`` dict on success, which contains:
      - ``gpsPointStrList``: pipe-delimited point strings
      - ``startAddress``, ``endAddress``
      - ``totalMileage``, ``showUnit``, ``avgSpeed``, ``speedUnit``
      - ``startDate``, ``endDate`` ("YYYY-MM-DD HH:MM:SS")
      - ``deviceName``, ``imei``
    Returns None on error.
    """
    try:
        token = await _token_manager.get_token()
    except Exception as exc:
        logger.error("TrackSolid: token fetch failed for journey points: %s", exc)
        return None

    payload = {
        "startTime": start_time,
        "endTime": end_time,
        "imei": imei,
        "confidenceLevel": "",
        "selectMap": "googleMap",
        "selectType": "all",
    }
    headers = {
        "Authorization": token,
        "Content-Type": "application/json",
    }

    try:
        async with httpx.AsyncClient(timeout=30) as client:
            response = await client.post(
                _TRACK_HISTORY_URL,
                json=payload,
                headers=headers,
            )
            response.raise_for_status()
            data = response.json()
    except Exception as exc:
        logger.error("TrackSolid: getPointList failed for IMEI %s: %s", imei, exc)
        return None

    if not data.get("ok"):
        logger.error(
            "TrackSolid: getPointList ok=false for IMEI %s: code=%s msg=%s",
            imei, data.get("code"), data.get("msg"),
        )
        return None

    track_data = data.get("data")
    logger.info(
        "📍 TrackSolid journey: IMEI %s — %d points, %s %s",
        imei,
        len((track_data or {}).get("gpsPointStrList") or []),
        (track_data or {}).get("totalMileage", "0"),
        (track_data or {}).get("showUnit", ""),
    )
    return track_data


# ── Open API Integration (jimi.user.device.location.list) ───────────────────
# Uses the official Jimi IoT Open API with app_key/app_secret authentication.
# One API call returns ALL devices under the account — replaces 110 parallel
# calls to getMonitorInfo. Solves WAF blocking by staying within official
# integration quotas (86,400 calls/day for location.list).

_OPEN_API_URL = "https://eu-open.tracksolidpro.com/route/rest"
_OPEN_API_TOKEN_TTL = 7200  # 2 hours per Jimi docs
_TOKEN_REFRESH_BUFFER = 300  # Refresh 5 min before expiry


def _open_api_creds() -> tuple[str, str, str, str]:
    """Return (account, password, app_key, app_secret) for Open API."""
    return (
        os.environ["TRACKSOLID_ACCOUNT"],
        os.environ["TRACKSOLID_PASSWORD"],
        os.environ["TRACKSOLID_APP_KEY"],
        os.environ["TRACKSOLID_APP_SECRET"],
    )


def _generate_open_api_signature(params: dict, app_secret: str) -> str:
    """
    Generate MD5 signature for Jimi Open API per official algorithm.
    
    Algorithm:
    1. Sort all params (except 'sign') alphabetically by key
    2. Concatenate as: key1value1key2value2...
    3. Wrap with: app_secret + concat + app_secret
    4. MD5 and uppercase
    """
    sorted_keys = sorted(params.keys())
    concat = ''.join(k + params[k] for k in sorted_keys)
    sign_string = app_secret + concat + app_secret
    return hashlib.md5(sign_string.encode('utf-8')).hexdigest().upper()


async def _get_cached_access_token(db_session) -> str | None:
    """Get cached access_token from DB if still valid."""
    from app.models import APIToken
    from sqlalchemy import select
    
    token_row = db_session.execute(
        select(APIToken).where(APIToken.provider == "tracksolid_open_api")
    ).scalar_one_or_none()
    
    if not token_row:
        return None
    
    # Check if token is still valid (with buffer)
    if token_row.expires_at and token_row.expires_at > datetime.now(timezone.utc) + timedelta(seconds=_TOKEN_REFRESH_BUFFER):
        return token_row.access_token
    
    return None


async def _save_access_token(db_session, access_token: str, expires_in: int):
    """Save access_token to DB with expiry time."""
    from app.models import APIToken
    from sqlalchemy import select
    from sqlalchemy.dialects.postgresql import insert
    
    expires_at = datetime.now(timezone.utc) + timedelta(seconds=expires_in)
    
    # Use PostgreSQL UPSERT
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
    db_session.execute(stmt)
    db_session.commit()


async def _fetch_open_api_access_token() -> str:
    """Fetch fresh OAuth access_token via jimi.oauth.token.get."""
    account, password, app_key, app_secret = _open_api_creds()
    password_md5 = hashlib.md5(password.encode()).hexdigest().lower()
    timestamp = datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S')
    
    token_params = {
        'app_key': app_key,
        'expires_in': str(_OPEN_API_TOKEN_TTL),
        'format': 'json',
        'method': 'jimi.oauth.token.get',
        'sign_method': 'md5',
        'timestamp': timestamp,
        'user_id': account,
        'user_pwd_md5': password_md5,
        'v': '0.9',
    }
    token_params['sign'] = _generate_open_api_signature(token_params, app_secret)
    
    timeout = httpx.Timeout(_READ_TIMEOUT_SECONDS, connect=_CONNECT_TIMEOUT_SECONDS)
    
    async with httpx.AsyncClient(timeout=timeout) as client:
        resp = await client.post(_OPEN_API_URL, data=token_params)
        resp.raise_for_status()
        data = resp.json()
        
        if data.get('code') != 0:
            raise Exception(f"OAuth error code={data.get('code')}: {data.get('message')}")
        
        access_token = data['result']['accessToken']
        logger.info("✅ TrackSolid Open API: fetched new access_token")
        return access_token


async def fetch_all_tracksolid_locations_open_api(
    imeis: "list[str] | None" = None,
    db_session=None,
) -> "dict[str, TrackSolidLocationInfo]":
    """
    Fetch and store ALL TrackSolid devices using official Open API.
    
    Calls TWO API endpoints:
    1. jimi.user.device.list → metadata (stored in tracksolid_devices)
    2. jimi.user.device.location.list → telemetry (stored in tracksolid_locations)
    
    Also updates ble_tags table for backwards compatibility with existing app logic.
    
    Args:
        imeis: Optional list of IMEIs to filter in the returned dict
        db_session: SQLAlchemy session for DB operations
    
    Returns:
        Dict keyed by IMEI string (filtered by imeis if provided)
    """
    if imeis is not None and len(imeis) == 0:
        return {}
    
    account, password, app_key, app_secret = _open_api_creds()
    timeout = httpx.Timeout(_READ_TIMEOUT_SECONDS, connect=_CONNECT_TIMEOUT_SECONDS)
    
    # Step 1: Get or refresh OAuth access_token with caching
    access_token = None
    if db_session:
        access_token = await _get_cached_access_token(db_session)
    
    if not access_token:
        try:
            access_token = await _fetch_open_api_access_token()
            if db_session:
                await _save_access_token(db_session, access_token, _OPEN_API_TOKEN_TTL)
        except Exception as exc:
            logger.error("🚫 TrackSolid Open API token fetch failed: %s", exc)
            return {}
    else:
        logger.info("♻️  TrackSolid Open API: using cached access_token")
    
    # Step 2: Fetch device metadata via jimi.user.device.list
    try:
        device_metadata = await _fetch_device_list(access_token, app_key, app_secret, account, timeout)
        if db_session:
            await _save_device_metadata(db_session, device_metadata)
    except Exception as exc:
        logger.error("🚫 TrackSolid device.list failed: %s", exc)
        device_metadata = {}
    
    # Step 3: Fetch device locations via jimi.user.device.location.list
    try:
        locations = await _fetch_device_locations(access_token, app_key, app_secret, account, timeout)
        if db_session:
            await _save_device_locations(db_session, locations)
    except Exception as exc:
        logger.error("🚫 TrackSolid location.list failed: %s", exc)
        return {}
    
    # Step 4: Parse into TrackSolidLocationInfo objects (filtered by imeis)
    result_map: dict[str, TrackSolidLocationInfo] = {}
    
    for device in locations:
        imei = str(device.get("imei", "")).strip()
        if not imei:
            continue
        
        # Filter to requested IMEIs if provided
        if imeis is not None and imei not in imeis:
            continue
        
        lat = float(device.get("lat", 0))
        lng = float(device.get("lng", 0))
        
        if lat == 0 and lng == 0:
            continue
        
        # Parse battery
        battery_level: int | None = None
        battery_val = device.get("batteryPowerVal")
        if battery_val:
            try:
                voltage = float(battery_val)
                if voltage > 2.5:
                    battery_level = min(100, max(0, int((voltage - 3.0) / 1.2 * 100)))
            except (ValueError, TypeError):
                pass
        
        # Parse GPS time
        gps_time: datetime | None = None
        gps_time_str = device.get("gpsTime")
        if gps_time_str:
            try:
                gps_time = datetime.strptime(str(gps_time_str), "%Y-%m-%d %H:%M:%S")
            except (ValueError, TypeError):
                pass
        
        address = device.get("locDesc") or None
        
        result_map[imei] = TrackSolidLocationInfo(
            latitude=lat,
            longitude=lng,
            address=address,
            battery_level=battery_level,
            gps_time=gps_time,
        )
    
    logger.info(
        "📍 TrackSolid Open API: %d/%d devices had valid GPS fixes",
        len(result_map), len(locations)
    )
    
    return result_map


async def _fetch_device_list(access_token: str, app_key: str, app_secret: str, account: str, timeout) -> list:
    """Call jimi.user.device.list to get device metadata."""
    timestamp = datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S')
    
    params = {
        'access_token': access_token,
        'app_key': app_key,
        'format': 'json',
        'method': 'jimi.user.device.list',
        'sign_method': 'md5',
        'target': account,
        'timestamp': timestamp,
        'v': '0.9',
    }
    params['sign'] = _generate_open_api_signature(params, app_secret)
    
    async with httpx.AsyncClient(timeout=timeout) as client:
        resp = await client.post(_OPEN_API_URL, data=params)
        resp.raise_for_status()
        data = resp.json()
        
        if data.get('code') != 0:
            raise Exception(f"device.list error code={data.get('code')}: {data.get('message')}")
        
        devices = data.get('result', [])
        logger.info("📋 TrackSolid device.list: received %d devices", len(devices))
        return devices


async def _fetch_device_locations(access_token: str, app_key: str, app_secret: str, account: str, timeout) -> list:
    """Call jimi.user.device.location.list to get location data."""
    timestamp = datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S')
    
    params = {
        'access_token': access_token,
        'app_key': app_key,
        'format': 'json',
        'map_type': 'GOOGLE',
        'method': 'jimi.user.device.location.list',
        'sign_method': 'md5',
        'target': account,
        'timestamp': timestamp,
        'v': '0.9',
    }
    params['sign'] = _generate_open_api_signature(params, app_secret)
    
    async with httpx.AsyncClient(timeout=timeout) as client:
        resp = await client.post(_OPEN_API_URL, data=params)
        resp.raise_for_status()
        data = resp.json()
        
        if data.get('code') != 0:
            raise Exception(f"location.list error code={data.get('code')}: {data.get('message')}")
        
        devices = data.get('result', [])
        logger.info("📍 TrackSolid location.list: received %d devices", len(devices))
        return devices


async def _save_device_metadata(db_session, devices: list):
    """Save device metadata to tracksolid_devices table (UPSERT)."""
    from app.models import TrackSolidDevice
    from sqlalchemy.dialects.postgresql import insert
    
    for device in devices:
        imei = device.get("imei")
        if not imei:
            continue
        
        stmt = insert(TrackSolidDevice).values(
            imei=imei,
            device_name=device.get("deviceName"),
            mc_type=device.get("mcType"),
            sim=device.get("sim"),
            vehicle_number=device.get("vehicleNumber"),
            driver_name=device.get("driverName"),
            driver_phone=device.get("driverPhone"),
            activation_time=_parse_datetime(device.get("activationTime")),
            expiration=_parse_datetime(device.get("expiration")),
            enabled_flag=device.get("enabledFlag", 1),
            updated_at=datetime.now(timezone.utc)
        ).on_conflict_do_update(
            index_elements=['imei'],
            set_={
                'device_name': device.get("deviceName"),
                'mc_type': device.get("mcType"),
                'sim': device.get("sim"),
                'vehicle_number': device.get("vehicleNumber"),
                'driver_name': device.get("driverName"),
                'driver_phone': device.get("driverPhone"),
                'activation_time': _parse_datetime(device.get("activationTime")),
                'expiration': _parse_datetime(device.get("expiration")),
                'enabled_flag': device.get("enabledFlag", 1),
                'updated_at': datetime.now(timezone.utc)
            }
        )
        db_session.execute(stmt)
    
    db_session.commit()
    logger.info("💾 Saved %d device metadata rows", len(devices))


async def _save_device_locations(db_session, devices: list):
    """Save location telemetry to tracksolid_locations table (always INSERT)."""
    from app.models import TrackSolidLocation
    
    for device in devices:
        imei = device.get("imei")
        if not imei:
            continue
        
        location = TrackSolidLocation(
            imei=imei,
            lat=device.get("lat"),
            lng=device.get("lng"),
            speed=device.get("speed"),
            acc_status=device.get("accStatus"),
            gps_time=_parse_datetime(device.get("gpsTime")),
            hb_time=_parse_datetime(device.get("hbTime")),
            pos_type=device.get("posType"),
            battery=device.get("batteryPowerVal"),
            gps_signal=device.get("gpsSignal"),
            status=device.get("status"),
            recorded_at=datetime.now(timezone.utc)
        )
        db_session.add(location)
    
    db_session.commit()
    logger.info("💾 Saved %d location history rows", len(devices))


def _parse_datetime(value) -> datetime | None:
    """Parse datetime string in format YYYY-MM-DD HH:MM:SS."""
    if not value:
        return None
    try:
        return datetime.strptime(str(value), "%Y-%m-%d %H:%M:%S")
    except (ValueError, TypeError):
        return None
