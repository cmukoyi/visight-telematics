"""Vehicle maintenance — when each schedule falls due, job statuses, summaries and notifications.

Meters (per vehicle, from its trips):
  odometer      the device's total odometer at the end of its latest trip (IO 16),
                or the sum of trip distances when the device doesn't send one
  engine hours  time on trips (ignition on, driving or idling)
  daily use     km and hours per day over the last 30 days, to turn km / hours
                thresholds into a planned date

An occurrence of a schedule on a vehicle (next_occurrence):
  - A schedule sets thresholds on odometer (km), months and engine hours. The
    first occurrence is At; a recurring schedule repeats Every after the last
    COMPLETED job of that schedule on the vehicle (its odometer, engine hours
    and end date), and stops past Until. Months count from the schedule's
    start date, or from the last completed job.
  - Without a completed job, a recurring schedule the vehicle is already past
    is due at its most recent missed threshold (e.g. At 5 000 every 1 000 km
    at 47 158 km → 47 000 km, overdue) — completing that job sets the baseline.
  - Whichever meter comes first decides: Overdue when any threshold is
    passed, Due when any is within the schedule's "remind before" window
    (km / days / hours), otherwise Recommended (upcoming).
  - A saved job that isn't completed (Booked / In Progress) stands for the
    occurrence, so it isn't projected as well.

Saved job status comes from its dates: Actual end → Completed, Actual start →
In Progress, otherwise Booked.
"""
import calendar
import logging
import re
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from typing import Optional

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.models import BLETag
from app.models_dataprofiler import DeviceEvent, Trip
from app.models_maintenance import (MaintenanceCost, MaintenanceLookup, MaintenanceNotice, MaintenanceSchedule,
                                    MaintenanceType, VehicleMaintenance, Workshop)

logger = logging.getLogger(__name__)

PROJECTED = ("Recommended", "Due", "Overdue")
SAVED = ("Booked", "In Progress", "Completed")
STATUSES = ["Overdue", "Due", "Recommended", "Booked", "In Progress", "Completed"]
VEHICLE_TYPE_KEY = "vehicle_type"


def _utc(dt: datetime) -> datetime:
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def add_months(d: date, months: int) -> date:
    m = d.month - 1 + months
    y, m = d.year + m // 12, m % 12 + 1
    return date(y, m, min(d.day, calendar.monthrange(y, m)[1]))


def months_between(a: date, b: date) -> int:
    """Whole months from a to b (b ≥ a)."""
    n = (b.year - a.year) * 12 + b.month - a.month
    return n - 1 if b.day < a.day else n


def job_status(job: VehicleMaintenance) -> str:
    if job.actual_end:
        return "Completed"
    if job.actual_start:
        return "In Progress"
    return "Booked"


# ---------------------------------------------------------------------------
# Vehicles and meters
# ---------------------------------------------------------------------------

def vehicle_type_id(attributes: Optional[dict]) -> Optional[str]:
    return ((attributes or {}).get(VEHICLE_TYPE_KEY) or {}).get("value") or None


def vehicles(db: Session, group_id, visible: Optional[set] = None) -> dict:
    """{imei: {name, tag_id, group, type_id}} of the group's vehicles (those the user may see)."""
    out = {}
    for tag in db.query(BLETag).filter(BLETag.attributes.op("->>")("_created_usergroup_id") == str(group_id),
                                       BLETag.imei.isnot(None)):
        if visible is not None and tag.imei not in visible:
            continue
        attrs = tag.attributes or {}
        out[tag.imei] = {"name": tag.description or tag.device_name or tag.imei, "tag_id": str(tag.id),
                         "group": (attrs.get("category") or {}).get("value"), "type_id": vehicle_type_id(attrs)}
    return out


@dataclass
class Meter:
    odometer_km: Optional[float] = None
    engine_hours: float = 0.0
    km_per_day: float = 0.0
    hours_per_day: float = 0.0


def meters(db: Session, imeis: list) -> dict:
    """{imei: Meter} from the vehicles' trips."""
    if not imeis:
        return {}
    out = {imei: Meter() for imei in imeis}
    for imei, odo, dist, secs in (db.query(Trip.imei, func.max(Trip.end_odometer_m), func.sum(Trip.distance_m),
                                           func.sum(Trip.duration_s))
                                  .filter(Trip.imei.in_(imeis), Trip.real()).group_by(Trip.imei)):
        m = out[imei]
        m.odometer_km = round((odo if odo else (dist or 0)) / 1000, 1)
        m.engine_hours = round((secs or 0) / 3600, 1)
    since = datetime.now(timezone.utc) - timedelta(days=30)
    for imei, dist, secs in (db.query(Trip.imei, func.sum(Trip.distance_m), func.sum(Trip.duration_s))
                             .filter(Trip.imei.in_(imeis), Trip.real(), Trip.started_at >= since).group_by(Trip.imei)):
        out[imei].km_per_day = (dist or 0) / 1000 / 30
        out[imei].hours_per_day = (secs or 0) / 3600 / 30
    return out


# ---------------------------------------------------------------------------
# The due-date engine
# ---------------------------------------------------------------------------

@dataclass
class Occurrence:
    km: Optional[float]          # odometer threshold
    hours: Optional[float]       # engine-hours threshold
    on: Optional[date]           # calendar threshold
    status: str                  # Recommended | Due | Overdue
    planned: Optional[date]      # when it is (or was) expected, from whichever meter comes first
    km_left: Optional[float] = None
    hours_left: Optional[float] = None
    days_left: Optional[int] = None

    def key(self, schedule_id, imei) -> str:
        return f"{schedule_id}:{imei}:{self.km}:{self.hours}:{self.on}"


def _first(at, every, current, recurring):
    """The first threshold of a meter with no completed job: At, or the most recent one already passed."""
    if at is None:
        return None
    if recurring and every and current is not None and current >= at:
        return at + (current - at) // every * every
    return at


def _first_date(s: MaintenanceSchedule, today: date) -> Optional[date]:
    if s.at_months is None:
        return None
    first = add_months(s.starts_on, s.at_months)
    if s.recurring and s.every_months and today >= first:
        k = months_between(first, today) // s.every_months
        return add_months(first, k * s.every_months)
    return first


def next_occurrence(s: MaintenanceSchedule, meter: Meter, last: Optional[VehicleMaintenance],
                    today: date) -> Optional[Occurrence]:
    """The schedule's next occurrence on a vehicle, or None when it has finished (non-recurring done, or past Until)."""
    odo, eh = meter.odometer_km, meter.engine_hours
    if last is not None:
        if not s.recurring:
            return None
        done_on = _utc(last.actual_end or last.actual_start or last.planned_start).date()
        km = (last.odometer_km + s.every_km) if s.every_km and last.odometer_km is not None else (
            _first(s.at_km, s.every_km, odo, True) if s.every_km else None)
        hours = (last.engine_hours + s.every_hours) if s.every_hours and last.engine_hours is not None else (
            _first(s.at_hours, s.every_hours, eh, True) if s.every_hours else None)
        on = add_months(done_on, s.every_months) if s.every_months else None
    else:
        km = _first(s.at_km, s.every_km, odo, s.recurring)
        hours = _first(s.at_hours, s.every_hours, eh, s.recurring)
        on = _first_date(s, today)

    # Until: a meter past its end stops contributing; nothing left = finished
    if km is not None and s.until_km is not None and km > s.until_km:
        km = None
    if hours is not None and s.until_hours is not None and hours > s.until_hours:
        hours = None
    if on is not None and s.until_months is not None and on > add_months(s.starts_on, s.until_months):
        on = None
    if km is None and hours is None and on is None:
        return None

    km_left = None if km is None or odo is None else round(km - odo, 1)
    hours_left = None if hours is None else round(hours - eh, 1)
    days_left = None if on is None else (on - today).days
    overdue = (km_left is not None and km_left <= 0) or (hours_left is not None and hours_left <= 0) \
        or (days_left is not None and days_left < 0)
    due = (km_left is not None and km_left <= s.remind_km) or (hours_left is not None and hours_left <= s.remind_hours) \
        or (days_left is not None and days_left <= s.remind_days)

    # Planned date: the calendar threshold, or when daily use reaches the km / hours threshold (or did)
    when = []
    if on is not None:
        when.append(on)
    if km_left is not None and (meter.km_per_day > 0 or km_left <= 0):
        when.append(today + timedelta(days=int(km_left / meter.km_per_day)) if meter.km_per_day > 0 else today)
    if hours_left is not None and (meter.hours_per_day > 0 or hours_left <= 0):
        when.append(today + timedelta(days=int(hours_left / meter.hours_per_day)) if meter.hours_per_day > 0 else today)
    return Occurrence(km=km, hours=hours, on=on, status="Overdue" if overdue else "Due" if due else "Recommended",
                      planned=min(when) if when else None, km_left=km_left, hours_left=hours_left, days_left=days_left)


def schedule_vehicles(s: MaintenanceSchedule, fleet: dict) -> list:
    """The vehicles a schedule covers: those of its vehicle types, plus those picked one by one."""
    types, picked = set(map(str, s.vehicle_type_ids or [])), set(s.imeis or [])
    return [imei for imei, v in fleet.items() if imei in picked or (v["type_id"] and v["type_id"] in types)]


def projections(db: Session, group_id, fleet: dict, today: Optional[date] = None) -> list:
    """[(schedule, type, imei, Occurrence)] for every active schedule × vehicle with no open job."""
    today = today or datetime.now(timezone.utc).date()
    schedules = db.query(MaintenanceSchedule).filter(MaintenanceSchedule.usergroup_id == group_id,
                                                     MaintenanceSchedule.is_active == True).all()  # noqa: E712
    if not schedules or not fleet:
        return []
    types = {t.id: t for t in db.query(MaintenanceType).filter(MaintenanceType.usergroup_id == group_id)}
    jobs = (db.query(VehicleMaintenance)
            .filter(VehicleMaintenance.usergroup_id == group_id,
                    VehicleMaintenance.schedule_id.in_([s.id for s in schedules])).all())
    open_jobs, last_done = set(), {}
    for j in jobs:
        key = (j.schedule_id, j.imei)
        if j.actual_end is None:
            open_jobs.add(key)
        elif key not in last_done or _utc(j.actual_end) > _utc(last_done[key].actual_end):
            last_done[key] = j
    meter = meters(db, list(fleet))
    out = []
    for s in schedules:
        for imei in schedule_vehicles(s, fleet):
            if (s.id, imei) in open_jobs:
                continue
            occ = next_occurrence(s, meter.get(imei, Meter()), last_done.get((s.id, imei)), today)
            if occ:
                out.append((s, types.get(s.type_id), imei, occ))
    return out


# ---------------------------------------------------------------------------
# Rows for the screens
# ---------------------------------------------------------------------------

def _iso(d) -> Optional[str]:
    if d is None:
        return None
    return d.isoformat() if isinstance(d, (date, datetime)) else str(d)


def projected_row(s: MaintenanceSchedule, t: Optional[MaintenanceType], imei: str, occ: Occurrence, fleet: dict) -> dict:
    start = datetime.combine(occ.planned, datetime.min.time(), tzinfo=timezone.utc) if occ.planned else None
    end = start + timedelta(hours=t.duration_hours) if start and t else None
    return {
        "id": f"p:{s.id}:{imei}", "projected": True, "imei": imei, "vehicle": fleet[imei]["name"],
        "description": s.name, "reference": None, "type_id": str(s.type_id), "type": t.name if t else None,
        "schedule_id": str(s.id), "schedule": s.name, "status": occ.status,
        "planned_start": _iso(start), "planned_end": _iso(end), "actual_start": None, "actual_end": None,
        "odometer_km": occ.km, "engine_hours": occ.hours, "workshop_id": None, "workshop": None, "cost": None,
        "due": {"km": occ.km, "hours": occ.hours, "date": _iso(occ.on)},
        "left": {"km": occ.km_left, "hours": occ.hours_left, "days": occ.days_left},
    }


def job_row(j: VehicleMaintenance, fleet: dict, types: dict, workshops: dict, schedules: dict, costs: dict) -> dict:
    t = types.get(j.type_id)
    return {
        "id": str(j.id), "projected": False, "imei": j.imei, "vehicle": fleet.get(j.imei, {}).get("name", j.imei),
        "description": j.description, "reference": j.reference, "type_id": str(j.type_id) if j.type_id else None,
        "type": t.name if t else None, "schedule_id": str(j.schedule_id) if j.schedule_id else None,
        "schedule": schedules.get(j.schedule_id), "status": job_status(j),
        "planned_start": _iso(j.planned_start), "planned_end": _iso(j.planned_end),
        "actual_start": _iso(j.actual_start), "actual_end": _iso(j.actual_end),
        "odometer_km": j.odometer_km, "engine_hours": j.engine_hours,
        "workshop_id": str(j.workshop_id) if j.workshop_id else None, "workshop": workshops.get(j.workshop_id),
        "cost": costs.get(j.id), "notes": j.notes, "due": None, "left": None,
    }


def lookups(db: Session, group_id) -> tuple:
    types = {t.id: t for t in db.query(MaintenanceType).filter(MaintenanceType.usergroup_id == group_id)}
    workshops = {w.id: w.name for w in db.query(Workshop).filter(Workshop.usergroup_id == group_id)}
    schedules = {s.id: s.name for s in db.query(MaintenanceSchedule).filter(MaintenanceSchedule.usergroup_id == group_id)}
    return types, workshops, schedules


def job_costs(db: Session, job_ids: list) -> dict:
    if not job_ids:
        return {}
    return {jid: float(total) for jid, total in db.query(MaintenanceCost.maintenance_id, func.sum(MaintenanceCost.amount))
            .filter(MaintenanceCost.maintenance_id.in_(job_ids)).group_by(MaintenanceCost.maintenance_id)}


def summary(db: Session, group_id, fleet: dict) -> list:
    """One row per vehicle: current meters, the next job (open or projected) and the last completed one."""
    today = datetime.now(timezone.utc).date()
    types, workshops, schedules = lookups(db, group_id)
    meter = meters(db, list(fleet))
    jobs = db.query(VehicleMaintenance).filter(VehicleMaintenance.usergroup_id == group_id,
                                               VehicleMaintenance.imei.in_(list(fleet))).all() if fleet else []
    costs = job_costs(db, [j.id for j in jobs])
    rank = {"Overdue": 0, "In Progress": 1, "Due": 2, "Booked": 3, "Recommended": 4}
    nxt, prev = {}, {}

    def better(a, b):   # the more urgent, then the sooner
        if b is None:
            return True
        return (rank[a["status"]], a["planned_start"] or "9999") < (rank[b["status"]], b["planned_start"] or "9999")

    for j in jobs:
        row = job_row(j, fleet, types, workshops, schedules, costs)
        if row["status"] == "Completed":
            if j.imei not in prev or row["actual_end"] > prev[j.imei]["actual_end"]:
                prev[j.imei] = row
        elif better(row, nxt.get(j.imei)):
            nxt[j.imei] = row
    for s, t, imei, occ in projections(db, group_id, fleet, today):
        row = projected_row(s, t, imei, occ, fleet)
        if better(row, nxt.get(imei)):
            nxt[imei] = row
    return [{"imei": imei, "vehicle": v["name"], "group": v["group"], "type_id": v["type_id"],
             "odometer_km": meter.get(imei, Meter()).odometer_km, "engine_hours": meter.get(imei, Meter()).engine_hours,
             "next": nxt.get(imei), "previous": prev.get(imei)} for imei, v in fleet.items()]


def cost_in_period(c: MaintenanceCost, start: date, end: date) -> float:
    """The part of a cost that falls in [start, end] (dates, inclusive).

    A cost with an amortisation period is spread evenly by day across it;
    otherwise it all falls on its date.
    """
    amount = float(c.amount or 0)
    if c.amortise_from and c.amortise_to:
        days = (c.amortise_to - c.amortise_from).days + 1
        overlap = (min(end, c.amortise_to) - max(start, c.amortise_from)).days + 1
        return round(amount * max(0, overlap) / days, 2) if days > 0 else 0.0
    return amount if start <= c.cost_date <= end else 0.0


# ---------------------------------------------------------------------------
# Notifications
# ---------------------------------------------------------------------------

def _notify(db: Session, group_id, fleet: dict, s: MaintenanceSchedule, t, imei: str, occ: Occurrence) -> bool:
    key = f"{occ.key(s.id, imei)}:{occ.status}"[:200]
    if db.query(MaintenanceNotice.id).filter(MaintenanceNotice.occurrence == key).first():
        return False
    from app.services import portal_alert_service as alerts
    vehicle = fleet[imei]["name"]
    what = [f"{occ.km:,.0f} km" if occ.km is not None else None,
            f"{occ.hours:,.0f} engine hours" if occ.hours is not None else None,
            occ.on.strftime("%d %b %Y") if occ.on else None]
    what = [w for w in what if w]
    when = " / ".join(what) + (", whichever comes first" if len(what) > 1 else "")
    title = f"{vehicle}: {s.name} {'overdue' if occ.status == 'Overdue' else 'due'}"
    message = (f"{t.name if t else s.name} for {vehicle} is {occ.status.lower()} ({when})."
               + (f" Expected around {occ.planned:%d %b %Y}." if occ.planned and occ.status == "Due" else ""))
    meta = {"imei": imei, "schedule_id": str(s.id), "schedule": s.name, "type": t.name if t else None,
            "due_km": occ.km, "due_hours": occ.hours, "due_date": _iso(occ.on), "km_left": occ.km_left,
            "days_left": occ.days_left, "status": occ.status}
    atype = "maintenance_overdue" if occ.status == "Overdue" else "maintenance_due"
    alerts.create_alert(db, str(group_id), fleet[imei]["tag_id"], alert_type=atype, title=title, message=message, meta_data=meta)
    db.add(MaintenanceNotice(usergroup_id=group_id, occurrence=key))
    db.flush()
    try:
        alerts._notify_group_by_email(db, str(group_id), atype, title, message, meta, imei=imei)
    except Exception:
        logger.exception("Maintenance email for %s failed", imei)
    return True


def send_notices(db: Session) -> int:
    """Inbox alert (and email) once per occurrence when it becomes Due, and again when Overdue. Does not commit."""
    groups = [g for (g,) in db.query(MaintenanceSchedule.usergroup_id).filter(MaintenanceSchedule.is_active == True)  # noqa: E712
              .distinct()]
    sent = 0
    for group_id in groups:
        fleet = vehicles(db, group_id)
        for s, t, imei, occ in projections(db, group_id, fleet):
            if occ.status in ("Due", "Overdue"):
                sent += _notify(db, group_id, fleet, s, t, imei, occ)
    return sent


# ---------------------------------------------------------------------------
# DTC (diagnostic trouble codes) from the device's OBD data (Teltonika IO 281, "Fault codes")
# ---------------------------------------------------------------------------

IO_FAULT_CODES = "281"
_DTC_SYSTEM = {"P": "Powertrain", "C": "Chassis", "B": "Body", "U": "Network"}
_DTC_TEXT = {
    "P0100": "Mass air flow circuit malfunction", "P0101": "Mass air flow circuit range/performance",
    "P0110": "Intake air temperature circuit malfunction", "P0115": "Engine coolant temperature circuit malfunction",
    "P0120": "Throttle position sensor circuit malfunction", "P0130": "O2 sensor circuit malfunction (bank 1 sensor 1)",
    "P0171": "System too lean (bank 1)", "P0172": "System too rich (bank 1)", "P0174": "System too lean (bank 2)",
    "P0300": "Random/multiple cylinder misfire detected", "P0301": "Cylinder 1 misfire detected",
    "P0302": "Cylinder 2 misfire detected", "P0303": "Cylinder 3 misfire detected", "P0304": "Cylinder 4 misfire detected",
    "P0325": "Knock sensor 1 circuit malfunction", "P0335": "Crankshaft position sensor circuit malfunction",
    "P0340": "Camshaft position sensor circuit malfunction", "P0400": "Exhaust gas recirculation flow malfunction",
    "P0401": "Exhaust gas recirculation flow insufficient", "P0420": "Catalyst system efficiency below threshold (bank 1)",
    "P0440": "Evaporative emission control system malfunction", "P0442": "EVAP system leak detected (small leak)",
    "P0455": "EVAP system leak detected (large leak)", "P0500": "Vehicle speed sensor malfunction",
    "P0505": "Idle control system malfunction", "P0562": "System voltage low", "P0563": "System voltage high",
    "P0600": "Serial communication link malfunction", "P0700": "Transmission control system malfunction",
    "U0100": "Lost communication with ECM/PCM", "U0121": "Lost communication with ABS control module",
    "C0035": "Left front wheel speed sensor circuit", "B1000": "ECU malfunction",
}


# SAE J2012: the second character says generic (0, 2, 3x) or manufacturer (1, 3); for powertrain codes the
# third says which subsystem — enough to describe any code we have no exact text for
_P_SUBSYSTEM = {"0": "Fuel and air metering, auxiliary emission controls", "1": "Fuel and air metering",
                "2": "Fuel and air metering (injector circuit)", "3": "Ignition system or misfire",
                "4": "Auxiliary emission controls", "5": "Vehicle speed, idle control and auxiliary inputs",
                "6": "Computer and output circuits", "7": "Transmission", "8": "Transmission", "9": "Transmission",
                "A": "Hybrid propulsion", "B": "Hybrid propulsion", "C": "Hybrid propulsion"}


def describe_dtc(code: str) -> str:
    if code in _DTC_TEXT:
        return _DTC_TEXT[code]
    system = _DTC_SYSTEM.get(code[0], "Other")
    maker = code[1] in ("1", "3") and not (code[0] == "P" and code[1] == "3" and code[2] >= "4")
    detail = _P_SUBSYSTEM.get(code[2], "") if code[0] == "P" else ""
    text = f"{system}{': ' + detail if detail else ''}"
    return f"{text} ({'manufacturer-specific' if maker else 'generic'} code — see the manufacturer's list for the exact fault)"


def _fault_codes(raw) -> list:
    """Codes from an IO 281 value (ASCII text, or hex of it), e.g. "P0300,P0171"."""
    text = raw if isinstance(raw, str) else ""
    if text and re.fullmatch(r"[0-9a-fA-F]+", text) and len(text) % 2 == 0:
        try:
            text = bytes.fromhex(text).decode("ascii", "ignore")
        except ValueError:
            pass
    return re.findall(r"\b[PCBU][0-9A-F]{4}\b", text.upper())


def dtc_events(db: Session, imei: str, start: datetime, end: datetime) -> list:
    rows = (db.query(DeviceEvent.recorded_at, DeviceEvent.io)
            .filter(DeviceEvent.imei == imei, DeviceEvent.recorded_at >= start, DeviceEvent.recorded_at < end,
                    DeviceEvent.io.op("->>")(IO_FAULT_CODES).isnot(None))
            .order_by(DeviceEvent.recorded_at.desc()).limit(2000).all())
    out = []
    for at, io in rows:
        for code in _fault_codes((io or {}).get(IO_FAULT_CODES)):
            out.append({"code": code, "description": describe_dtc(code),
                        "category": _DTC_SYSTEM.get(code[0], "Other"), "recorded_at": _iso(at)})
    return out


# ---------------------------------------------------------------------------
# Starting content for a user group
# ---------------------------------------------------------------------------

# Starter items are "system" items (Is System): they can't be renamed or deleted; groups add their own
DEFAULT_ITEMS = ["Change engine oil", "Replace oil filter", "Replace air filter", "Replace fuel filter",
                 "Check brakes", "Rotate tyres", "Wheel alignment", "Check lights", "Licence renewal"]
DEFAULT_LOOKUPS = {"vehicle_type": ["Light vehicle", "Truck"], "cost_centre": ["Operations"]}


def ensure_defaults(db: Session, group_id) -> None:
    """A few editable starter items, vehicle types and a cost centre the first time a group opens maintenance."""
    from app.models_maintenance import MaintenanceItem
    if db.query(MaintenanceItem.id).filter(MaintenanceItem.usergroup_id == group_id).first() \
            or db.query(MaintenanceLookup.id).filter(MaintenanceLookup.usergroup_id == group_id).first():
        return
    for name in DEFAULT_ITEMS:
        db.add(MaintenanceItem(usergroup_id=group_id, name=name, is_system=True))
    for kind, names in DEFAULT_LOOKUPS.items():
        for name in names:
            db.add(MaintenanceLookup(usergroup_id=group_id, kind=kind, name=name))
    db.commit()

