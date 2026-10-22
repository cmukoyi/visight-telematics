"""Street addresses for positions (reverse geocoding), for trip start and end locations.

Lookups are cached in geocode_cache by position rounded to 4 decimals
(~11 m), so a depot or home address is fetched once. MapTiler is used when
MAPTILER_KEY is set; otherwise OpenStreetMap Nominatim, kept to its fair-use
limit of one request a second.

fill_trip_addresses() is run by the dashboard ingest every few seconds and
fills trips whose start or end address is still missing.
"""
import logging
import os
import threading
import time
from typing import Optional

import requests
from sqlalchemy import or_
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from app.models_dataprofiler import GeocodeCache, Trip

logger = logging.getLogger(__name__)

USER_AGENT = "ViSight-Track/1.0 (trip addresses)"
_lock = threading.Lock()
_last_call = 0.0


def _throttle(min_interval: float) -> None:
    global _last_call
    with _lock:
        wait = _last_call + min_interval - time.monotonic()
        if wait > 0:
            time.sleep(wait)
        _last_call = time.monotonic()


def _short(parts: list) -> Optional[str]:
    """Join non-empty parts, dropping repeats, e.g. ['35 Melville Ave', 'Rosebank', 'Johannesburg']."""
    out = []
    for p in parts:
        p = (p or "").strip()
        if p and p not in out:
            out.append(p)
    return ", ".join(out)[:255] or None


def _maptiler(lat: float, lng: float, key: str) -> Optional[str]:
    _throttle(0.1)
    r = requests.get(f"https://api.maptiler.com/geocoding/{lng},{lat}.json",
                     params={"key": key, "limit": 1, "language": "en"}, timeout=8)
    r.raise_for_status()
    features = r.json().get("features") or []
    if not features:
        return None
    # "35 Melville Avenue, Rosebank, Johannesburg, Gauteng, South Africa" → drop province and country
    parts = [p.strip() for p in (features[0].get("place_name") or "").split(",")]
    return _short(parts[:3] if len(parts) > 3 else parts)


def _nominatim(lat: float, lng: float) -> Optional[str]:
    _throttle(1.1)
    r = requests.get("https://nominatim.openstreetmap.org/reverse",
                     params={"lat": lat, "lon": lng, "format": "jsonv2", "zoom": 18, "addressdetails": 1},
                     headers={"User-Agent": USER_AGENT}, timeout=8)
    r.raise_for_status()
    data = r.json()
    a = data.get("address") or {}
    street = " ".join(x for x in (a.get("house_number"), a.get("road") or a.get("pedestrian")) if x)
    place = a.get("suburb") or a.get("neighbourhood") or a.get("village")
    city = a.get("city") or a.get("town") or a.get("municipality")
    return _short([street, place, city]) or _short((data.get("display_name") or "").split(",")[:3])


def lookup(db: Session, lat: Optional[float], lng: Optional[float]) -> Optional[str]:
    """The street address at a position, from the cache or the provider.

    "" when the provider has no address there; None when the lookup failed (try again later).
    """
    if lat is None or lng is None:
        return None
    lat_e4, lng_e4 = round(lat * 10000), round(lng * 10000)
    cached = db.get(GeocodeCache, (lat_e4, lng_e4))
    if cached:
        return cached.address
    key = os.getenv("MAPTILER_KEY")
    try:
        address = _maptiler(lat, lng, key) if key else _nominatim(lat, lng)
    except (requests.RequestException, ValueError) as exc:
        logger.warning("Reverse geocode %.5f,%.5f failed: %s", lat, lng, exc)
        return None
    address = address or ""
    db.execute(pg_insert(GeocodeCache.__table__).values(lat_e4=lat_e4, lng_e4=lng_e4, address=address)
               .on_conflict_do_nothing())
    return address


def fill_trip_addresses(db: Session, limit: int = 25) -> int:
    """Look up missing start addresses (any trip) and end addresses (closed trips), newest first. Commits."""
    trips = (db.query(Trip)
             .filter(or_(Trip.start_address.is_(None) & Trip.start_latitude.isnot(None),
                         (Trip.status == "closed") & Trip.end_address.is_(None) & Trip.end_latitude.isnot(None)))
             .order_by(Trip.started_at.desc()).limit(limit).all())
    filled = 0
    for trip in trips:
        if trip.start_address is None and trip.start_latitude is not None:
            trip.start_address = lookup(db, trip.start_latitude, trip.start_longitude)
        if trip.status == "closed" and trip.end_address is None and trip.end_latitude is not None:
            trip.end_address = lookup(db, trip.end_latitude, trip.end_longitude)
        db.commit()
        filled += trip.start_address is not None
    return filled
