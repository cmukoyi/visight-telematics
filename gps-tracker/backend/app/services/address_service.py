"""Street addresses for positions (reverse geocoding), for trip start and end locations.

Lookups are cached in geocode_cache by position rounded to 4 decimals
(~11 m), so a depot or home address is fetched once. MapTiler is used when
MAPTILER_KEY is set; otherwise OpenStreetMap Nominatim, kept to its fair-use
limit of one request a second.

fill_trip_addresses() is run by the dashboard ingest every few seconds and
fills trips whose start or end address is still missing.

Each cached position also keeps its address parts (road, suburb, town, postal
code, province, country, POI); Describer shows a position in the user group's
Location Description Format, with the nearest Place as a land mark.
"""
import logging
import math
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


# ── Location Description Format (Configuration → User Groups) ──
# What each group shows for a position; the order here is the order in the text.
LOCATION_PARTS = ("landmark_distance", "landmark", "poi", "road", "suburb", "town", "postal_code", "province", "country")
DEFAULT_FORMAT = ("landmark", "road", "suburb", "town")
LANDMARK_RANGE_M = 5000     # a place further away than this isn't a useful landmark
_ADDRESS_PARTS = ("poi", "road", "suburb", "town", "postal_code", "province", "country")


def _town(name: Optional[str]) -> Optional[str]:
    """'City of Johannesburg Metropolitan Municipality' → 'Johannesburg'."""
    if not name:
        return name
    for prefix in ("City of ",):
        if name.startswith(prefix):
            name = name[len(prefix):]
    for suffix in (" Metropolitan Municipality", " Local Municipality", " District Municipality", " Municipality"):
        if name.endswith(suffix):
            name = name[: -len(suffix)]
    return name.strip() or None


def _maptiler(lat: float, lng: float, key: str) -> Optional[dict]:
    _throttle(0.1)
    r = requests.get(f"https://api.maptiler.com/geocoding/{lng},{lat}.json",
                     params={"key": key, "limit": 1, "language": "en"}, timeout=8)
    r.raise_for_status()
    features = r.json().get("features") or []
    if not features:
        return None
    f = features[0]
    kind = lambda x: (x.get("id") or "").split(".")[0]   # "municipality.46425" → "municipality"
    layers: dict = {}
    for x in [f, *(f.get("context") or [])]:
        layers.setdefault(kind(x), x)
    text_of = lambda *kinds: next((layers[k].get("text") for k in kinds if k in layers and layers[k].get("text")), None)
    road = None
    if kind(f) in ("address", "road", "street"):
        road = " ".join(x for x in (f.get("address"), f.get("text")) if x)
    road = road or text_of("road", "street")
    suburb = text_of("neighbourhood", "municipal_district", "locality")
    town = _town(text_of("municipality", "place", "joint_municipality", "locality", "county", "subregion"))
    parts = {"poi": f.get("text") if kind(f) == "poi" else None, "road": road,
             "suburb": suburb if suburb != town else None, "town": town,
             "postal_code": text_of("postal_code"), "province": text_of("region"), "country": text_of("country")}
    if not any(parts.values()):   # unknown layer names: keep the provider's own text
        names = [p.strip() for p in (f.get("place_name") or "").split(",")]
        parts["road"] = _short(names[:3])
    return parts


def _nominatim(lat: float, lng: float) -> Optional[dict]:
    _throttle(1.1)
    r = requests.get("https://nominatim.openstreetmap.org/reverse",
                     params={"lat": lat, "lon": lng, "format": "jsonv2", "zoom": 18, "addressdetails": 1},
                     headers={"User-Agent": USER_AGENT}, timeout=8)
    r.raise_for_status()
    data = r.json()
    a = data.get("address") or {}
    road = " ".join(x for x in (a.get("house_number"), a.get("road") or a.get("pedestrian")) if x) or None
    name = data.get("name") or None
    poi = name if name and name != (a.get("road") or "") and data.get("category") not in ("highway", "place", "boundary", "building") else None
    town = _town(a.get("city") or a.get("town") or a.get("village") or a.get("municipality"))
    suburb = a.get("suburb") or a.get("neighbourhood") or a.get("quarter")
    parts = {"poi": poi, "road": road, "suburb": suburb if suburb != town else None, "town": town,
             "postal_code": a.get("postcode"), "province": a.get("state"), "country": a.get("country")}
    if not any(parts.values()):
        parts["road"] = _short((data.get("display_name") or "").split(",")[:3])
    return parts


def _provider(lat: float, lng: float) -> Optional[dict]:
    """Address parts at a position, or None when the provider has nothing there. Raises on failure."""
    key = os.getenv("MAPTILER_KEY")
    parts = _maptiler(lat, lng, key) if key else _nominatim(lat, lng)
    return {k: v for k, v in (parts or {}).items() if v} or None


def default_text(parts: Optional[dict]) -> str:
    """The stored address (trips, cache): road, suburb and town."""
    return _short([(parts or {}).get(k) for k in ("road", "suburb", "town")]) or ""


def cached(db: Session, lat: Optional[float], lng: Optional[float]) -> Optional[str]:
    """The street address at a position if it's already in the cache (no provider call)."""
    if lat is None or lng is None:
        return None
    row = db.get(GeocodeCache, (round(lat * 10000), round(lng * 10000)))
    return row.address if row else None


def lookup(db: Session, lat: Optional[float], lng: Optional[float]) -> Optional[str]:
    """The street address at a position, from the cache or the provider.

    "" when the provider has no address there; None when the lookup failed (try again later).
    """
    if lat is None or lng is None:
        return None
    lat_e4, lng_e4 = round(lat * 10000), round(lng * 10000)
    row = db.get(GeocodeCache, (lat_e4, lng_e4))
    if row:
        return row.address
    try:
        parts = _provider(lat, lng)
    except (requests.RequestException, ValueError) as exc:
        logger.warning("Reverse geocode %.5f,%.5f failed: %s", lat, lng, exc)
        return None
    address = default_text(parts)
    db.execute(pg_insert(GeocodeCache.__table__).values(lat_e4=lat_e4, lng_e4=lng_e4, address=address, parts=parts or {})
               .on_conflict_do_nothing())
    return address


def fill_missing_parts(db: Session, limit: int = 5) -> int:
    """Look up the parts of addresses cached before Location Description Formats (newest first). Commits."""
    rows = (db.query(GeocodeCache).filter(GeocodeCache.parts.is_(None))
            .order_by(GeocodeCache.created_at.desc().nullslast()).limit(limit).all())
    done = 0
    for row in rows:
        try:
            row.parts = _provider(row.lat_e4 / 10000, row.lng_e4 / 10000) or {}
        except (requests.RequestException, ValueError) as exc:
            logger.warning("Reverse geocode (parts) %s,%s failed: %s", row.lat_e4, row.lng_e4, exc)
            break
        db.commit()
        done += 1
    return done


def _compass(lat1, lng1, lat2, lng2) -> str:
    """Direction from point 1 to point 2: N, NE, E…"""
    y = math.sin(math.radians(lng2 - lng1)) * math.cos(math.radians(lat2))
    x = (math.cos(math.radians(lat1)) * math.sin(math.radians(lat2))
         - math.sin(math.radians(lat1)) * math.cos(math.radians(lat2)) * math.cos(math.radians(lng2 - lng1)))
    deg = (math.degrees(math.atan2(y, x)) + 360) % 360
    return ("N", "NE", "E", "SE", "S", "SW", "W", "NW")[round(deg / 45) % 8]


def _distance_text(m: float) -> str:
    return f"{round(m / 10) * 10:.0f} m" if m < 1000 else f"{m / 1000:.1f} km"


def group_format(group) -> tuple:
    fmt = getattr(group, "location_format", None)
    return tuple(k for k in LOCATION_PARTS if k in fmt) if isinstance(fmt, list) else DEFAULT_FORMAT


class Describer:
    """Positions as text in a user group's Location Description Format.

    describe = Describer(db, group_id); describe(lat, lng, fallback=trip.start_address)
    Call prefetch() first with every position of a long list (one query instead of one per row).
    """

    def __init__(self, db: Session, group_id, fmt: Optional[tuple] = None):
        from app.models import UserGroup
        self.db = db
        self.fmt = fmt if fmt is not None else group_format(db.get(UserGroup, group_id) if group_id else None)
        self.group_id = group_id
        self._rows: dict = {}
        self._places: Optional[list] = None

    def prefetch(self, points) -> "Describer":
        keys = {(round(la * 10000), round(ln * 10000)) for la, ln in points if la is not None and ln is not None} - set(self._rows)
        if keys:
            lats = list({k[0] for k in keys})
            for i in range(0, len(lats), 1000):
                for row in self.db.query(GeocodeCache).filter(GeocodeCache.lat_e4.in_(lats[i:i + 1000])):
                    if (row.lat_e4, row.lng_e4) in keys:
                        self._rows[(row.lat_e4, row.lng_e4)] = row
            for k in keys:
                self._rows.setdefault(k, None)
        return self

    def _row(self, lat, lng):
        key = (round(lat * 10000), round(lng * 10000))
        if key not in self._rows:
            self._rows[key] = self.db.get(GeocodeCache, key)
        return self._rows[key]

    def _landmark(self, lat, lng) -> Optional[str]:
        from app.models import POI
        from app.services.geofence_engine import _distance_m, _outline, is_inside
        if self._places is None:
            self._places = (self.db.query(POI).filter(POI.usergroup_id == self.group_id, POI.is_active == True).all()  # noqa: E712
                            if self.group_id else [])
        best = None
        for p in self._places:
            if is_inside(p, lat, lng):
                return p.name
            outline = _outline(p)
            if outline:
                d = min(_distance_m(lat, lng, a, b) for a, b in outline)
            else:
                d = max(0.0, _distance_m(lat, lng, p.latitude, p.longitude) - float(p.radius or 150.0))
            if d <= LANDMARK_RANGE_M and (best is None or d < best[0]):
                best = (d, p)
        if not best:
            return None
        d, p = best
        if "landmark_distance" in self.fmt:
            return f"{_distance_text(d)} {_compass(p.latitude, p.longitude, lat, lng)} of {p.name}"
        return f"Near {p.name}"

    def __call__(self, lat, lng, fallback: Optional[str] = None) -> Optional[str]:
        if lat is None or lng is None:
            return fallback or None
        out = [self._landmark(lat, lng)] if "landmark" in self.fmt else []
        row = self._row(lat, lng)
        if row is not None and row.parts is not None:
            out += [row.parts.get(k) for k in _ADDRESS_PARTS if k in self.fmt]
        else:   # cached before address parts were kept (being filled in): the short street address
            out.append(fallback or (row.address if row is not None else None))
        return _short(out)


def fill_trip_addresses(db: Session, limit: int = 25) -> int:
    """Look up missing start addresses (any trip) and end addresses (closed trips), newest first. Commits."""
    trips = (db.query(Trip)
             .filter(Trip.real(), or_(Trip.start_address.is_(None) & Trip.start_latitude.isnot(None),
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


def fill_vehicle_addresses(db: Session, limit: int = 20) -> int:
    """Cache street addresses for vehicles' current positions (for the Workspace vehicle grid). Commits."""
    from app.models import BLETag
    tags = db.query(BLETag.latitude, BLETag.longitude).filter(BLETag.latitude.isnot(None), BLETag.is_active == True).all()  # noqa: E712
    done = 0
    for lat_s, lng_s in tags:
        try:
            lat, lng = float(lat_s), float(lng_s)
        except (TypeError, ValueError):
            continue
        if db.get(GeocodeCache, (round(lat * 10000), round(lng * 10000))):
            continue
        if lookup(db, lat, lng) is not None:
            db.commit()
            done += 1
        if done >= limit:
            break
    return done
