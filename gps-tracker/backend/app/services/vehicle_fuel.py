"""Fuel used, estimated from distance and the vehicle's travelling consumption.

A vehicle's consumption (L/100 km) is set in its Fuel details and stored in
its attributes as {"fuel_consumption": {"value": "10.2"}}. Fuel used on a trip
= distance (km) × consumption / 100; vehicles without one have no estimate.
"""
from typing import Optional

from sqlalchemy.orm import Session

from app.models import BLETag

KEY = "fuel_consumption"
MAX_L_PER_100KM = 200


def rate(attributes: Optional[dict]) -> Optional[float]:
    """The vehicle's travelling consumption in L/100 km, or None when not set."""
    raw = ((attributes or {}).get(KEY) or {}).get("value")
    try:
        value = float(raw)
    except (TypeError, ValueError):
        return None
    return value if 0 < value <= MAX_L_PER_100KM else None


def litres(distance_m: Optional[int], l_per_100km: Optional[float]) -> Optional[float]:
    """Fuel used over a distance, or None without a consumption."""
    if l_per_100km is None:
        return None
    return round((distance_m or 0) / 1000 * l_per_100km / 100, 2)


def group_rates(db: Session, group_id) -> dict:
    """{imei: L/100 km} for the group's vehicles that have a consumption set."""
    tags = db.query(BLETag.imei, BLETag.attributes).filter(
        BLETag.attributes.op("->>")("_created_usergroup_id") == str(group_id)).all()
    return {imei: r for imei, a in tags if (r := rate(a)) is not None}
