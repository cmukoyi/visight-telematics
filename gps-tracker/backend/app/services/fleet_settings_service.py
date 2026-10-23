"""A group's fleet cost and scoring settings, with defaults.

Used to put a price on usage (fuel, speeding, excess idling, after-hours
driving), to spread fixed costs (tracking, licences) over the days in a
period, and by the trip builder (speed limit, excess-idle threshold).
"""
from typing import Optional

from sqlalchemy.orm import Session

from app.models import FleetSettings

# key: (default, label, unit, help)
FIELDS: dict = {
    "fuel_price":               (23.0, "Fuel price", "R/L", "What a litre of fuel costs"),
    "default_l_per_100km":      (10.0, "Default travelling consumption", "L/100 km",
                                 "For vehicles without their own (vehicle editor → Fuel)"),
    "idle_l_per_hour":          (1.0, "Fuel burnt idling", "L/h", "Fuel an idling engine uses per hour"),
    "excess_idle_minutes":      (5, "Excess idle after", "min", "Idling longer than this, per stop, is excess idle"),
    "speed_limit_kmh":          (120, "Speed limit", "km/h", "Time driven above this counts as speeding duration"),
    "speeding_cost_per_hour":   (100.0, "Speeding cost", "R/h", "Cost of an hour of speeding (fuel, wear, risk)"),
    "after_hours_cost_per_km":  (3.0, "After-hours cost", "R/km", "Cost of a km driven outside working hours"),
    "tracking_fee_per_month":   (0.0, "Tracking fee", "R/vehicle/month", "Spread over each day the vehicle is in the period"),
    "licence_fee_per_year":     (0.0, "Licence fee", "R/vehicle/year", "Spread over each day; or capture licence costs as cost items"),
}
DEFAULTS = {k: v[0] for k, v in FIELDS.items()}


def get(db: Session, group_id) -> dict:
    """The group's settings, defaults filled in."""
    row = db.get(FleetSettings, group_id) if group_id else None
    values = dict(DEFAULTS)
    for k, v in ((row.values if row else None) or {}).items():
        if k in DEFAULTS and isinstance(v, (int, float)):
            values[k] = v
    return values


def seeded(db: Session, group_id) -> set:
    """Starting content already given to the group (so a deleted page or expression doesn't come back)."""
    row = db.get(FleetSettings, group_id)
    return set(((row.values if row else None) or {}).get("_seeded", []))


def mark_seeded(db: Session, group_id, *keys: str) -> None:
    row = db.get(FleetSettings, group_id)
    if row is None:
        row = FleetSettings(usergroup_id=group_id, values={})
        db.add(row)
    values = dict(row.values or {})
    values["_seeded"] = sorted(set(values.get("_seeded", [])) | set(keys))
    row.values = values


def save(db: Session, group_id, data: dict) -> dict:
    """Store the given settings (validated by the route). Does not commit."""
    row = db.get(FleetSettings, group_id)
    if row is None:
        row = FleetSettings(usergroup_id=group_id, values={})
        db.add(row)
    values = dict(row.values or {})
    for k, v in data.items():
        if k in DEFAULTS and v is not None:
            values[k] = float(v)
    row.values = values
    return get(db, group_id)


def fuel_cost_per_km(settings: dict, l_per_100km: Optional[float]) -> float:
    return (l_per_100km or settings["default_l_per_100km"]) / 100 * settings["fuel_price"]
