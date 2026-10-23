"""Working-hours time profiles — how much of a period falls inside or outside working hours.

A profile's windows are per weekday (0 = Monday) in the group's local time:
{"0": [["07:00", "17:00"]], "5": [["08:00", "12:00"]]}; a day with none is all
after hours. split() walks a trip day by day, so a trip from 16:30 to 18:00 on
a weekday with 07:00–17:00 has 30 min inside and 60 min after hours; distance is
shared out in the same proportion.
"""
from datetime import datetime, time, timedelta, timezone
from typing import Optional
from zoneinfo import ZoneInfo

from sqlalchemy.orm import Session

from app.models import TimeProfile

DEFAULT_WINDOWS = {str(d): [["07:00", "17:00"]] for d in range(5)}   # Mon–Fri 07:00–17:00
DAYS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]


def _t(hhmm: str) -> time:
    if hhmm in ("24:00", "23:59"):
        return time(23, 59, 59, 999999)
    h, m = hhmm.split(":")
    return time(int(h), int(m))


def valid_windows(windows: dict) -> dict:
    """Clean windows; raises ValueError with a readable message."""
    out = {}
    for day, spans in (windows or {}).items():
        if str(day) not in {str(d) for d in range(7)}:
            raise ValueError("Unknown weekday")
        clean = []
        for span in spans or []:
            start, end = span[0], span[1]
            try:
                a, b = _t(start), _t(end)
            except (ValueError, IndexError):
                raise ValueError(f"{DAYS[int(day)]}: use times like 07:30")
            if b <= a:
                raise ValueError(f"{DAYS[int(day)]}: the end time must be after the start")
            clean.append([start, end])
        if clean:
            out[str(day)] = clean
    return out


def describe(windows: dict) -> str:
    """"Mon–Fri 07:00–17:00, Sat 08:00–12:00"."""
    groups = []
    for d in range(7):
        spans = ", ".join(f"{a}–{b}" for a, b in (windows or {}).get(str(d), []))
        if not spans:
            continue
        if groups and groups[-1][2] == spans and groups[-1][1] == d - 1:
            groups[-1][1] = d
        else:
            groups.append([d, d, spans])
    return "; ".join(f"{DAYS[a]}{'–' + DAYS[b] if b != a else ''} {s}" for a, b, s in groups) or "No working hours"


def split(start: datetime, end: datetime, windows: dict, tz: ZoneInfo) -> tuple:
    """(seconds inside working hours, seconds outside) of [start, end)."""
    if not end or end <= start:
        return 0.0, 0.0
    a, b = start.astimezone(tz), end.astimezone(tz)
    total = (b - a).total_seconds()
    inside = 0.0
    day = a.date()
    while day <= b.date():
        for s, e in (windows or {}).get(str(day.weekday()), []):
            w0 = datetime.combine(day, _t(s), tzinfo=tz)
            w1 = datetime.combine(day, _t(e), tzinfo=tz)
            lo, hi = max(a, w0), min(b, w1)
            if hi > lo:
                inside += (hi - lo).total_seconds()
        day += timedelta(days=1)
    inside = min(inside, total)
    return inside, total - inside


def profiles(db: Session, group_id) -> tuple:
    """({profile id: windows}, default windows) for the group; the built-in Mon–Fri 07–17 when it has none."""
    rows = db.query(TimeProfile).filter(TimeProfile.usergroup_id == group_id).all()
    by_id = {str(p.id): p.windows or {} for p in rows}
    default = next((p.windows for p in rows if p.is_default), None)
    return by_id, (default if default is not None else DEFAULT_WINDOWS)


def for_vehicle(attributes: Optional[dict], by_id: dict, default: dict) -> dict:
    pid = ((attributes or {}).get("time_profile_id") or {}).get("value")
    return by_id.get(pid, default) if pid else default


def utc(dt: datetime) -> datetime:
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
