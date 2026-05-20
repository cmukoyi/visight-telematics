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
from datetime import datetime

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
        async with httpx.AsyncClient(timeout=timeout) as client:
            response = await client.post(_LOGIN_URL, json=payload)
            response.raise_for_status()
            data = response.json()

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
