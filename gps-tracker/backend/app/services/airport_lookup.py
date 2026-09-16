"""
Commercial airport spatial lookup — used by the trip engine's flight detector.

Loads `app/data/airports_commercial.csv` (3,269 large/medium commercial airports
with scheduled service, derived from the OurAirports open dataset) into a
degree-based grid index, then answers "is this point within radius_km of a
commercial airport?" by scanning only the 3x3 neighbourhood of grid cells
around the query point.

See features_dev/trip-engine-flight-detection.md for the design this supports.
"""
import csv
import logging
import math
from pathlib import Path
from typing import Dict, List, Tuple

logger = logging.getLogger(__name__)

_AIRPORTS_CSV_PATH = Path(__file__).resolve().parent.parent / "data" / "airports_commercial.csv"

# 1 degree of latitude is ~111 km, comfortably larger than any AIRPORT_RADIUS_KM
# in use, so a 3x3 cell scan around the query point can never miss a match.
_GRID_CELL_DEG = 1.0

_grid: Dict[Tuple[int, int], List[Tuple[float, float]]] = {}
_loaded = False


def _cell(lat: float, lng: float) -> Tuple[int, int]:
    return (int(lat // _GRID_CELL_DEG), int(lng // _GRID_CELL_DEG))


def _load_grid() -> None:
    global _loaded
    if _loaded:
        return
    _loaded = True
    try:
        with open(_AIRPORTS_CSV_PATH, newline="", encoding="utf-8") as handle:
            for row in csv.DictReader(handle):
                try:
                    lat = float(row["latitude_deg"])
                    lng = float(row["longitude_deg"])
                except (KeyError, TypeError, ValueError):
                    continue
                _grid.setdefault(_cell(lat, lng), []).append((lat, lng))
    except OSError as exc:
        logger.error("Failed to load commercial airport reference data from %s: %s", _AIRPORTS_CSV_PATH, exc)
        return
    logger.info("✈️  Loaded %d commercial airports into spatial grid", sum(len(v) for v in _grid.values()))


def _haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    lat1, lon1, lat2, lon2 = map(math.radians, [lat1, lon1, lat2, lon2])
    dlat = lat2 - lat1
    dlon = lon2 - lon1
    a = math.sin(dlat / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin(dlon / 2) ** 2
    return 2 * math.asin(math.sqrt(a)) * 6371


def near_commercial_airport(lat: float, lng: float, radius_km: float) -> bool:
    """Return True if (lat, lng) is within radius_km of a commercial airport."""
    _load_grid()
    if not _grid:
        return False
    cell_lat, cell_lng = _cell(lat, lng)
    for d_lat in (-1, 0, 1):
        for d_lng in (-1, 0, 1):
            for airport_lat, airport_lng in _grid.get((cell_lat + d_lat, cell_lng + d_lng), []):
                if _haversine_km(lat, lng, airport_lat, airport_lng) <= radius_km:
                    return True
    return False
