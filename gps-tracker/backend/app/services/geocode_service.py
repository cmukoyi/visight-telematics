"""
Reverse Geocoding Service with Smart Caching
=============================================
Designed for use with Jimi IoT device location data.
Only geocodes when a device has moved significantly, saving API calls.

Uses Nominatim (OpenStreetMap) - free, no API key needed.
Swap to LocationIQ or BigDataCloud if you need higher throughput.

Usage:
    from app.services.geocode_service import GeocodeService

    geo = GeocodeService()

    # Single device
    address = geo.reverse_geocode(device_imei="868120145233604", lat=51.3618, lng=-0.1945)

    # Batch from Jimi API response
    results = geo.batch_geocode(jimi_location_results)
"""

import time
import math
import json
import os
import hashlib
import requests
import threading
from datetime import datetime, timedelta


class GeocodeService:
    """
    Reverse geocoder with distance-based caching.

    Only makes an API call when a device has moved more than `threshold_metres`
    from its last geocoded position. For crowdsourced BLE trackers that update
    infrequently, this can reduce API calls by 90%+.
    """

    # --- Provider configs ---
    PROVIDERS = {
        "maptiler": {
            # MapTiler uses longitude,latitude order in the URL path
            "url": "https://api.maptiler.com/geocoding/",
            "build_url": lambda lat, lng: f"https://api.maptiler.com/geocoding/{lng},{lat}.json",
            "parse": lambda r: (
                r.json().get("features", [{}])[0].get("place_name", "Unknown")
                if r.json().get("features")
                else "Unknown"
            ),
            "rate_limit": 0.05,  # ~20 requests per second on paid tier
        },
        "nominatim": {
            "url": "https://nominatim.openstreetmap.org/reverse",
            "build_url": None,
            "params": lambda lat, lng: {
                "lat": lat,
                "lon": lng,
                "format": "json",
                "addressdetails": 1,
            },
            "parse": lambda r: r.json().get("display_name", "Unknown"),
            "rate_limit": 1.0,  # 1 request per second (Nominatim policy)
        },
        "locationiq": {
            "url": "https://us1.locationiq.com/v1/reverse",
            "build_url": None,
            "params": lambda lat, lng: {
                "lat": lat,
                "lon": lng,
                "format": "json",
                "key": os.environ["LOCATIONIQ_API_KEY"],  # Required if using this provider
            },
            "parse": lambda r: r.json().get("display_name", "Unknown"),
            "rate_limit": 0.5,  # 2 requests per second on free tier
        },
        "bigdatacloud": {
            "url": "https://api.bigdatacloud.net/data/reverse-geocode-client",
            "build_url": None,
            "params": lambda lat, lng: {
                "latitude": lat,
                "longitude": lng,
                "localityLanguage": "en",
            },
            "parse": lambda r: r.json().get("description", "Unknown"),
            "rate_limit": 0.1,
        },
    }

    def __init__(
        self,
        provider="maptiler",
        threshold_metres=500,
        cache_file="/tmp/visight_geocode_cache.json",
        user_agent="ViSight-Track/1.0 (support@visighttelematics.co.za)",
    ):
        """
        Args:
            provider:          Which geocoding provider to use (default: maptiler).
            threshold_metres:  Only re-geocode if device moved more than this distance.
            cache_file:        Path to persist the cache between restarts.
            user_agent:        Required by Nominatim. Set to your app/email.
        """
        self.provider = self.PROVIDERS[provider]
        self.threshold = threshold_metres
        self.cache_file = cache_file
        self.user_agent = user_agent
        # Read MapTiler API key from environment if using that provider
        self.api_key = os.environ.get("MAPTILER_KEY") if provider == "maptiler" else None
        self.cache = self._load_cache()
        self.last_request_time = 0
        self._lock = threading.Lock()

        # Stats
        self.stats = {"hits": 0, "misses": 0, "errors": 0}

    # -------------------------------------------------------------------------
    # Public API
    # -------------------------------------------------------------------------

    def reverse_geocode(self, device_imei: str, lat: float, lng: float) -> dict:
        """
        Get address for a device's position. Returns cached result if the
        device hasn't moved significantly.

        Returns:
            {
                "address": "123 High Street, Sutton, London, SM1 1AA, UK",
                "cached": True/False,
                "distance_moved": 45.2,  # metres since last geocode
                "last_geocoded": "2026-05-22T10:30:00"
            }
        """
        cached = self.cache.get(device_imei)

        if cached:
            distance = self._haversine(
                cached["lat"], cached["lng"], lat, lng
            )

            if distance < self.threshold:
                self.stats["hits"] += 1
                return {
                    "address": cached["address"],
                    "cached": True,
                    "distance_moved": round(distance, 1),
                    "last_geocoded": cached["timestamp"],
                }

        # Device moved beyond threshold or first time seeing it
        self.stats["misses"] += 1
        address = self._call_provider(lat, lng)

        if address:
            self.cache[device_imei] = {
                "lat": lat,
                "lng": lng,
                "address": address,
                "timestamp": datetime.utcnow().isoformat(),
            }
            self._save_cache()

            return {
                "address": address,
                "cached": False,
                "distance_moved": (
                    round(
                        self._haversine(cached["lat"], cached["lng"], lat, lng), 1
                    )
                    if cached
                    else 0
                ),
                "last_geocoded": self.cache[device_imei]["timestamp"],
            }

        # API call failed — return stale cache if available
        self.stats["errors"] += 1
        if cached:
            return {
                "address": cached["address"],
                "cached": True,
                "distance_moved": 0,
                "last_geocoded": cached["timestamp"],
                "error": "Geocode failed, returning stale cache",
            }

        return {
            "address": "Unknown",
            "cached": False,
            "distance_moved": 0,
            "last_geocoded": None,
            "error": "Geocode failed, no cache available",
        }

    def batch_geocode(self, jimi_results: list) -> list:
        """
        Process an entire jimi.user.device.location.list response.

        Args:
            jimi_results: The 'result' array from the Jimi API response.

        Returns:
            List of dicts with device info + geocoded address.
        """
        output = []

        for device in jimi_results:
            imei = device.get("imei", "")
            lat = device.get("lat")
            lng = device.get("lng")

            if lat is None or lng is None or (lat == 0 and lng == 0):
                output.append({
                    "imei": imei,
                    "deviceName": device.get("deviceName", ""),
                    "lat": lat,
                    "lng": lng,
                    "address": "No position available",
                    "cached": False,
                    "battery": device.get("electQuantity"),
                    "status": device.get("status"),
                    "gpsTime": device.get("gpsTime"),
                })
                continue

            geo = self.reverse_geocode(imei, lat, lng)

            output.append({
                "imei": imei,
                "deviceName": device.get("deviceName", ""),
                "lat": lat,
                "lng": lng,
                "address": geo["address"],
                "cached": geo["cached"],
                "battery": device.get("electQuantity"),
                "status": device.get("status"),
                "speed": device.get("speed"),
                "accStatus": device.get("accStatus"),
                "posType": device.get("posType"),
                "gpsTime": device.get("gpsTime"),
                "hbTime": device.get("hbTime"),
            })

        return output

    def get_stats(self) -> dict:
        """Return cache hit/miss/error statistics."""
        total = self.stats["hits"] + self.stats["misses"]
        hit_rate = (self.stats["hits"] / total * 100) if total > 0 else 0
        return {
            **self.stats,
            "total": total,
            "hit_rate": f"{hit_rate:.1f}%",
            "cache_size": len(self.cache),
        }

    def clear_cache(self, imei: str = None):
        """Clear cache for one device or all devices."""
        if imei:
            self.cache.pop(imei, None)
        else:
            self.cache = {}
        self._save_cache()

    # -------------------------------------------------------------------------
    # Internals
    # -------------------------------------------------------------------------

    def _call_provider(self, lat: float, lng: float) -> str | None:
        """Make a rate-limited API call to the geocoding provider."""
        with self._lock:
            # Respect rate limit
            elapsed = time.time() - self.last_request_time
            wait = self.provider["rate_limit"] - elapsed
            if wait > 0:
                time.sleep(wait)

            try:
                # MapTiler uses coordinates in the URL path, others use query params
                if self.provider.get("build_url"):
                    url = self.provider["build_url"](lat, lng)
                    params = {"key": self.api_key} if self.api_key else {}
                else:
                    url = self.provider["url"]
                    params = self.provider["params"](lat, lng)

                resp = requests.get(
                    url,
                    params=params,
                    headers={"User-Agent": self.user_agent},
                    timeout=10,
                )
                self.last_request_time = time.time()

                if resp.status_code == 200:
                    return self.provider["parse"](resp)
                else:
                    print(f"[Geocode] HTTP {resp.status_code}: {resp.text[:200]}")
                    return None

            except Exception as e:
                print(f"[Geocode] Error: {e}")
                self.last_request_time = time.time()
                return None

    @staticmethod
    def _haversine(lat1: float, lng1: float, lat2: float, lng2: float) -> float:
        """Calculate distance in metres between two lat/lng points."""
        R = 6_371_000  # Earth radius in metres
        phi1 = math.radians(lat1)
        phi2 = math.radians(lat2)
        dphi = math.radians(lat2 - lat1)
        dlam = math.radians(lng2 - lng1)

        a = (
            math.sin(dphi / 2) ** 2
            + math.cos(phi1) * math.cos(phi2) * math.sin(dlam / 2) ** 2
        )
        return R * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))

    def _load_cache(self) -> dict:
        """Load cache from disk."""
        if os.path.exists(self.cache_file):
            try:
                with open(self.cache_file, "r") as f:
                    return json.load(f)
            except (json.JSONDecodeError, IOError):
                return {}
        return {}

    def _save_cache(self):
        """Persist cache to disk."""
        try:
            with open(self.cache_file, "w") as f:
                json.dump(self.cache, f, indent=2)
        except IOError as e:
            print(f"[Geocode] Cache save error: {e}")
