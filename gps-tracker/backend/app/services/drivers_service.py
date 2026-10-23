"""Drivers — who drove: the driver whose key was presented on the trip, else the vehicle's assigned driver.

Teltonika reports a one-wire driver key (iButton) in IO 78 as an integer; key
codes are captured as printed on the tag (hex, e.g. "01A2B3C4D5E6F701") or as a
decimal number, so both forms are compared (normalise_key).
"""
from typing import Optional

from sqlalchemy.orm import Session

from app.models import BLETag, Driver

IO_DRIVER_KEY = "78"


def normalise_key(value) -> Optional[str]:
    """A key code in one canonical form: upper-case hex without leading zeros ('' / 0 = no key)."""
    if value is None:
        return None
    if isinstance(value, int):
        return format(value, "X") if value else None
    text = str(value).strip().replace(" ", "").replace(":", "").replace("-", "").upper()
    if not text:
        return None
    if text.isdigit() and len(text) > 16:        # a long decimal: the device's integer form
        return format(int(text), "X")
    try:
        n = int(text, 16)
    except ValueError:
        return text
    return format(n, "X") if n else None


def key_index(db: Session, group_id) -> dict:
    """{normalised key: driver id} of the group's active drivers with a key."""
    out = {}
    for d in db.query(Driver).filter(Driver.usergroup_id == group_id, Driver.is_active == True,  # noqa: E712
                                     Driver.key_code.isnot(None)):
        k = normalise_key(d.key_code)
        if k:
            out[k] = d.id
            if d.key_code.strip().isdigit():          # also as typed, in case it was a decimal
                out.setdefault(format(int(d.key_code.strip()), "X"), d.id)
    return out


def names(db: Session, group_id) -> dict:
    """{driver id (str): full name}."""
    return {str(d.id): d.name for d in db.query(Driver).filter(Driver.usergroup_id == group_id)}


def vehicle_driver_id(attributes: Optional[dict]) -> Optional[str]:
    return ((attributes or {}).get("driver_id") or {}).get("value") or None


def sync_vehicle_names(db: Session, driver: Driver) -> None:
    """Keep attributes.driver (the name older code reads) in step on the driver's vehicles. Does not commit."""
    for tag in db.query(BLETag).filter(BLETag.attributes.op("->>")("_created_usergroup_id") == str(driver.usergroup_id)):
        attrs = dict(tag.attributes or {})
        if vehicle_driver_id(attrs) == str(driver.id):
            attrs["driver"] = {"value": driver.name}
            tag.attributes = attrs
