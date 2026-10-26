"""Breakdowns logged by drivers in the mobile app, and the tracker's evidence for each.

Starting a breakdown opens a "Breakdown" maintenance job (actual start = now),
so the vehicle counts as in the workshop on the Maintenance Overview and the
job is in the Maintenance List; resolving it completes the job. The driver can
log phases on the way (waiting for dispatch, mechanic en route …), each with
the time and the phone's position.

evidence() checks the claim against the vehicle's own tracker data for the
breakdown window: how far it moved (odometer, else the GPS path), how long the
ignition was on, trips that started, and how far the phone was from the
vehicle when the breakdown was logged. Any of those raises a flag for the
manager to check; a breakdown with no tracker data can't be confirmed.
"""
import logging
import math
from datetime import datetime, timedelta, timezone
from typing import Optional

from fastapi import HTTPException
from sqlalchemy.orm import Session

from app.models import BLETag, PortalUser
from app.models_dataprofiler import DeviceEvent, Trip
from app.models_maintenance import MaintenanceType, VehicleBreakdown, VehicleMaintenance

logger = logging.getLogger(__name__)

CAUSES = ("Engine", "Flat tyre", "Electrical", "Overheating", "Battery", "Accident", "Fuel", "Other")
PHASES = ("Waiting for dispatch", "Mechanic en route", "Under repair", "Being towed", "Waiting for parts")
TYPE_NAME = "Breakdown"

# Evidence thresholds
MOVED_KM = 1.0              # driving this far during a breakdown needs explaining
IGNITION_MIN = 15           # minutes of ignition on
PHONE_GAP_M = 500           # phone this far from the vehicle when the breakdown was logged
JITTER_M = 30               # GPS steps shorter than this are noise when summing a path
LONG_HOURS = 12


def _utc(dt: Optional[datetime]) -> Optional[datetime]:
    if dt is None:
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def _m(lat1, lng1, lat2, lng2) -> float:
    p1, p2 = math.radians(lat1), math.radians(lat2)
    a = math.sin((p2 - p1) / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(math.radians(lng2 - lng1) / 2) ** 2
    return 2 * 6371000 * math.asin(math.sqrt(a))


def _dur(seconds: float) -> str:
    m = int(seconds // 60)
    return f"{m // 60}h {m % 60:02d}m" if m >= 60 else f"{m} min"


def breakdown_type(db: Session, group_id) -> MaintenanceType:
    """The group's "Breakdown" maintenance type (created the first time it's needed)."""
    t = (db.query(MaintenanceType).filter(MaintenanceType.usergroup_id == group_id, MaintenanceType.name == TYPE_NAME).first())
    if not t:
        t = MaintenanceType(usergroup_id=group_id, name=TYPE_NAME, duration_hours=4, item_ids=[])
        db.add(t)
        db.flush()
    return t


def active(db: Session, group_id, imei: str) -> Optional[VehicleBreakdown]:
    return (db.query(VehicleBreakdown).filter(VehicleBreakdown.usergroup_id == group_id, VehicleBreakdown.imei == imei,
                                              VehicleBreakdown.ended_at.is_(None))
            .order_by(VehicleBreakdown.started_at.desc()).first())


def _tag(db: Session, group_id, imei: str) -> Optional[BLETag]:
    return (db.query(BLETag).filter(BLETag.imei == imei,
                                    BLETag.attributes.op("->>")("_created_usergroup_id") == str(group_id)).first())


def start(db: Session, me: PortalUser, imei: str, lat: Optional[float], lng: Optional[float],
          accuracy: Optional[float], cause: Optional[str]) -> VehicleBreakdown:
    """Log a breakdown and open its maintenance job. Commits."""
    from app.services import portal_alert_service
    if active(db, me.usergroup_id, imei):
        raise HTTPException(status_code=409, detail="This vehicle already has a breakdown in progress")
    tag = _tag(db, me.usergroup_id, imei)
    if not tag:
        raise HTTPException(status_code=404, detail="Vehicle not found")
    now = datetime.now(timezone.utc)
    who = " ".join(x for x in (me.first_name, me.last_name) if x) or me.email
    name = tag.description or tag.device_name or imei
    driver = ((tag.attributes or {}).get("driver") or {}).get("value") or None
    t = breakdown_type(db, me.usergroup_id)
    job = VehicleMaintenance(usergroup_id=me.usergroup_id, imei=imei, description=f"Breakdown{f': {cause}' if cause else ''}",
                             type_id=t.id, planned_start=now, planned_end=now + timedelta(hours=t.duration_hours),
                             actual_start=now, created_by=me.email, reference="Mobile app",
                             notes=f"Logged by {who} in the mobile app.")
    db.add(job)
    db.flush()
    b = VehicleBreakdown(usergroup_id=me.usergroup_id, imei=imei, job_id=job.id, reported_by_id=me.id, reported_by=who,
                         driver=driver, cause=cause, started_at=now, start_lat=lat, start_lng=lng, start_accuracy=accuracy,
                         phases=[])
    db.add(b)
    db.commit()
    try:
        portal_alert_service.create_alert(
            db, str(me.usergroup_id), str(tag.id), "breakdown", f"{name} broke down",
            f"{who} logged a breakdown{f' ({cause.lower()})' if cause else ''} for {name}.",
            {"latitude": lat, "longitude": lng, "breakdown_id": str(b.id)} if lat is not None else {"breakdown_id": str(b.id)})
        db.commit()
    except Exception:
        db.rollback()
        logger.exception("Breakdown %s: inbox alert failed", b.id)
    return b


def add_phase(db: Session, b: VehicleBreakdown, phase: str, lat: Optional[float], lng: Optional[float]) -> None:
    if b.ended_at:
        raise HTTPException(status_code=409, detail="This breakdown is already resolved")
    if phase not in PHASES:
        raise HTTPException(status_code=400, detail=f"Choose one of: {', '.join(PHASES)}")
    b.phases = [*(b.phases or []), {"phase": phase, "at": datetime.now(timezone.utc).isoformat(), "lat": lat, "lng": lng}]
    db.commit()


def resolve(db: Session, b: VehicleBreakdown, lat: Optional[float], lng: Optional[float], notes: Optional[str]) -> None:
    """Stop the clock and complete the maintenance job. Commits."""
    if b.ended_at:
        raise HTTPException(status_code=409, detail="This breakdown is already resolved")
    b.ended_at = datetime.now(timezone.utc)
    b.end_lat, b.end_lng = lat, lng
    b.notes = (notes or "").strip()[:2000] or None
    job = db.get(VehicleMaintenance, b.job_id) if b.job_id else None
    if job and not job.actual_end:
        job.actual_end = b.ended_at
        if b.notes:
            job.notes = f"{job.notes or ''}\n{b.notes}".strip()
    db.commit()


def evidence(db: Session, b: VehicleBreakdown, with_track: bool = False) -> dict:
    """What the vehicle's tracker shows for the breakdown window, and flags for anything that doesn't fit."""
    start, end = _utc(b.started_at), _utc(b.ended_at) or datetime.now(timezone.utc)
    events = (db.query(DeviceEvent.recorded_at, DeviceEvent.latitude, DeviceEvent.longitude, DeviceEvent.speed, DeviceEvent.io)
              .filter(DeviceEvent.imei == b.imei, DeviceEvent.recorded_at >= start - timedelta(hours=2),
                      DeviceEvent.recorded_at <= end)
              .order_by(DeviceEvent.recorded_at).all())
    before = [e for e in events if _utc(e.recorded_at) < start]
    during = [e for e in events if _utc(e.recorded_at) >= start]
    # Where the vehicle was when the breakdown was logged: its last fix before, else its first during
    anchor = next((e for e in reversed(before) if e.latitude is not None), None) \
        or next((e for e in during if e.latitude is not None), None)
    fixes = [e for e in during if e.latitude is not None]

    # Distance: the odometer (IO 16, metres) if the device sends it, else the GPS path without jitter
    odo = [e.io.get("16") for e in ([anchor] if anchor else []) + during if e.io and isinstance(e.io.get("16"), (int, float))]
    moved_m = max(0.0, odo[-1] - odo[0]) if len(odo) >= 2 else None
    if moved_m is None and fixes:
        path, last = 0.0, (anchor.latitude, anchor.longitude) if anchor else (fixes[0].latitude, fixes[0].longitude)
        for e in fixes:
            step = _m(last[0], last[1], e.latitude, e.longitude)
            if step >= JITTER_M:
                path += step
                last = (e.latitude, e.longitude)
        moved_m = path
    furthest_m = max((_m(anchor.latitude, anchor.longitude, e.latitude, e.longitude) for e in fixes), default=0.0) if anchor else None

    # Ignition (IO 239) on-time within the window, from the state before it
    ign_on_s, state, since = 0.0, None, start
    for e in before:
        if e.io and e.io.get("239") is not None:
            state = bool(e.io.get("239"))
    for e in during:
        if e.io and e.io.get("239") is not None:
            if state:
                ign_on_s += (_utc(e.recorded_at) - since).total_seconds()
            state, since = bool(e.io.get("239")), _utc(e.recorded_at)
    if state and during:
        ign_on_s += (min(end, _utc(during[-1].recorded_at) + timedelta(minutes=5)) - since).total_seconds()

    trips = (db.query(Trip).filter(Trip.imei == b.imei, Trip.real(), Trip.started_at >= start, Trip.started_at < end)
             .order_by(Trip.started_at).all())
    trip_km = sum((t.distance_m or 0) for t in trips) / 1000
    phone_gap = (_m(b.start_lat, b.start_lng, anchor.latitude, anchor.longitude)
                 if anchor and b.start_lat is not None and b.start_lng is not None else None)
    towed = any(p.get("phase") == "Being towed" for p in (b.phases or []))

    flags = []   # (level, text): warn = needs checking, info = worth knowing
    km = (moved_m or 0) / 1000
    if km >= MOVED_KM:
        flags.append(("info" if towed and ign_on_s < IGNITION_MIN * 60 else "warn",
                      f"Vehicle moved {km:.1f} km during the breakdown" + (" (logged as towed)" if towed else "")))
    if trips:
        flags.append(("warn", f"{len(trips)} trip{'s' if len(trips) != 1 else ''} started during the breakdown ({trip_km:.1f} km)"))
    if ign_on_s >= IGNITION_MIN * 60:
        flags.append(("warn", f"Ignition on for {_dur(ign_on_s)} during the breakdown"))
    if phone_gap is not None and phone_gap >= PHONE_GAP_M:
        flags.append(("warn", f"Logged {phone_gap / 1000:.1f} km away from the vehicle"))
    if not during and (end - start).total_seconds() > 1800:
        flags.append(("info", "No tracker data during the breakdown, so it can't be confirmed"))
    if (end - start).total_seconds() > LONG_HOURS * 3600:
        flags.append(("info", f"Longer than {LONG_HOURS} hours"))
    verdict = "check" if any(lvl == "warn" for lvl, _ in flags) else ("unconfirmed" if not during and (end - start).total_seconds() > 1800 else "consistent")

    out = {
        "verdict": verdict, "flags": [{"level": lvl, "text": text} for lvl, text in flags],
        "moved_km": None if moved_m is None else round(moved_m / 1000, 2),
        "furthest_m": None if furthest_m is None else round(furthest_m),
        "ignition_on_s": round(ign_on_s), "trips": len(trips), "trip_km": round(trip_km, 1),
        "max_speed": max((e.speed or 0 for e in during), default=0),
        "phone_gap_m": None if phone_gap is None else round(phone_gap),
        "vehicle_position": [anchor.latitude, anchor.longitude] if anchor else None,
        "reports": len(during), "last_report": _utc(during[-1].recorded_at).isoformat() if during else None,
    }
    if with_track:
        out["track"] = [[e.latitude, e.longitude] for e in fixes]
    return out


def _safe_evidence(db: Session, b: VehicleBreakdown, with_track: bool) -> dict:
    """evidence(), or an "unconfirmed" stand-in if the tracker data can't be read (logged), so the driver's
    breakdown is never lost to a reporting problem."""
    try:
        with db.begin_nested():
            return evidence(db, b, with_track)
    except Exception:
        logger.exception("Breakdown %s: tracker check failed", b.id)
        return {"verdict": "unconfirmed", "flags": [{"level": "info", "text": "The tracker data couldn't be checked"}],
                "moved_km": None, "furthest_m": None, "ignition_on_s": 0, "trips": 0, "trip_km": 0, "max_speed": 0,
                "phone_gap_m": None, "vehicle_position": None, "reports": 0, "last_report": None,
                **({"track": []} if with_track else {})}


def _safe_place(db: Session, describe, lat, lng) -> Optional[str]:
    if describe is None or lat is None or lng is None:
        return None
    try:
        with db.begin_nested():
            return describe(lat, lng)
    except Exception:
        logger.exception("Describing %s,%s failed", lat, lng)
        return None


def row(db: Session, b: VehicleBreakdown, names: dict, describe=None, with_track: bool = False) -> dict:
    """A breakdown for the dashboard and the app: times, downtime, place, phases and the evidence."""
    start, end = _utc(b.started_at), _utc(b.ended_at)
    ev = _safe_evidence(db, b, with_track)
    lat, lng = (b.start_lat, b.start_lng) if b.start_lat is not None else tuple(ev["vehicle_position"] or (None, None))
    return {
        "id": str(b.id), "imei": b.imei, "vehicle": names.get(b.imei, b.imei), "job_id": str(b.job_id) if b.job_id else None,
        "reported_by": b.reported_by, "driver": b.driver, "cause": b.cause,
        "started_at": start.isoformat(), "ended_at": end.isoformat() if end else None,
        "downtime_s": round(((end or datetime.now(timezone.utc)) - start).total_seconds()),
        "status": "resolved" if end else "active",
        "latitude": lat, "longitude": lng, "accuracy": b.start_accuracy,
        "location": _safe_place(db, describe, lat, lng),
        "end_latitude": b.end_lat, "end_longitude": b.end_lng,
        "phases": b.phases or [], "notes": b.notes,
        "review": b.review, "review_note": b.review_note, "reviewed_by": b.reviewed_by,
        "evidence": ev,
    }
