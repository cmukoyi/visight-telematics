"""Customer app API — dashboard KPIs, workspace events, inbox, reports and report schedules.

Mounted under /api/portal next to routes_portal; every endpoint is scoped to
the caller's user group.
"""
import os
from datetime import datetime, timedelta, timezone
from typing import List, Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import Response
from pydantic import BaseModel, EmailStr, field_validator
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.database import get_db
from app.dataprofiler.dictionary import CATEGORIES, EVENTS, describe_io, event_label
from app.models import PortalAlert
from app.models_dataprofiler import DeviceEvent, ReportSchedule, Trip
from app.models import UserGroup
from app.routes_portal import _portal_alert_dict, _scope_alerts, get_portal_user_from_request
from app.services import access_service, reports_service

router = APIRouter(prefix="/api/portal", tags=["portal-fleet"])


# ---------------------------------------------------------------------------
# Dashboard
# ---------------------------------------------------------------------------

def _week_stats(db: Session, group_id, imeis: list, start: datetime, end: datetime) -> dict:
    count, distance, duration = (db.query(func.count(Trip.id), func.coalesce(func.sum(Trip.distance_m), 0),
                                          func.coalesce(func.sum(Trip.duration_s), 0))
                                 .filter(Trip.usergroup_id == group_id, Trip.imei.in_(imeis), Trip.real(),
                                         Trip.started_at >= start, Trip.started_at < end).one())
    return {"trips": count, "distance_km": round(distance / 1000, 1), "driving_hours": round(duration / 3600, 1),
            "avg_trip_km": round(distance / 1000 / count, 1) if count else 0}


@router.get("/dashboard/kpis")
def dashboard_kpis(request: Request, db: Session = Depends(get_db), category: Optional[str] = None):
    """Trip totals for this week and last week (weeks start Monday, UTC), optionally for one vehicle group."""
    me = get_portal_user_from_request(request, db)
    visible = access_service.for_user(me, db).visible_imeis(db)
    imeis = list(reports_service.group_devices(db, me.usergroup_id, category, visible))
    today = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
    this_week = today - timedelta(days=today.weekday())
    last_week = this_week - timedelta(days=7)
    return {
        "vehicles": len(imeis),
        "current_week": _week_stats(db, me.usergroup_id, imeis, this_week, this_week + timedelta(days=7)),
        "previous_week": _week_stats(db, me.usergroup_id, imeis, last_week, this_week),
    }


# ---------------------------------------------------------------------------
# Events (workspace)
# ---------------------------------------------------------------------------

@router.get("/event-types")
def event_types(request: Request, db: Session = Depends(get_db)):
    """Our event codes with labels (the group's own names where set), grouped by category (for filters)."""
    me = get_portal_user_from_request(request, db)
    from app.routes_catalog import event_labels
    custom = event_labels(db, me.usergroup_id)
    return {"categories": CATEGORIES,
            "events": [{"code": c, "label": custom.get(c) or l, "category": cat, "kind": k} for c, (l, cat, k) in EVENTS.items()]}


@router.get("/events")
def list_events(request: Request, db: Session = Depends(get_db),
                imei: Optional[str] = None, date_from: Optional[datetime] = None,
                date_to: Optional[datetime] = None, codes: Optional[str] = None,
                include_parked: bool = False, before_id: Optional[int] = None,
                limit: int = Query(500, ge=1, le=5000)):
    """Device events, newest first. codes: comma-separated event codes."""
    me = get_portal_user_from_request(request, db)
    access = access_service.for_user(me, db)
    access.require("events.view")
    q = db.query(DeviceEvent).filter(DeviceEvent.usergroup_id == me.usergroup_id)
    visible = access.visible_imeis(db)
    if visible is not None:
        q = q.filter(DeviceEvent.imei.in_(list(visible)))
    if imei:
        q = q.filter(DeviceEvent.imei == imei.strip())
    if date_from:
        q = q.filter(DeviceEvent.recorded_at >= date_from)
    if date_to:
        q = q.filter(DeviceEvent.recorded_at < date_to)
    if codes:
        q = q.filter(DeviceEvent.event_type.in_([c.strip() for c in codes.split(",") if c.strip()]))
    else:
        # Our events only: records we can't classify are in the admin data profiler.
        q = q.filter(DeviceEvent.event_type.isnot(None))
        if not include_parked:
            q = q.filter(DeviceEvent.event_type != "parked_position")
    if before_id:
        q = q.filter(DeviceEvent.id < before_id)
    rows = q.order_by(DeviceEvent.recorded_at.desc(), DeviceEvent.id.desc()).limit(limit).all()
    names = reports_service.group_devices(db, me.usergroup_id)
    from app.routes_catalog import event_labels
    custom = event_labels(db, me.usergroup_id)
    return {
        "rows": [{
            "id": e.id, "imei": e.imei, "device_name": names.get(e.imei, e.imei),
            "code": e.event_type, "label": custom.get(e.event_type) or event_label(e.event_type, e.event_io_id),
            "kind": EVENTS[e.event_type][2] if e.event_type in EVENTS else "info",
            "recorded_at": e.recorded_at, "latitude": e.latitude, "longitude": e.longitude,
            "speed": e.speed, "trip_id": str(e.trip_id) if e.trip_id else None,
            "odometer_km": round(e.io["16"] / 1000, 1) if isinstance((e.io or {}).get("16"), int) else None,
            "io": describe_io(e.io or {}),
        } for e in rows],
        "next_before_id": rows[-1].id if len(rows) == limit else None,
    }


# ---------------------------------------------------------------------------
# Live tracking
# ---------------------------------------------------------------------------

@router.get("/live")
def live(request: Request, db: Session = Depends(get_db), imei: str = Query(...),
         trail_minutes: int = Query(60, ge=5, le=720)):
    """A vehicle's latest position, speed, heading and ignition, and its trail.

    The trail is the current (open) trip's route, or the last trail_minutes
    of positions when the vehicle isn't on a trip. Polled every few seconds by
    the live-tracking view.
    """
    me = get_portal_user_from_request(request, db)
    access = access_service.for_user(me, db)
    access.require("live.track")
    if not access.can_see(db, imei):
        raise HTTPException(status_code=404, detail="Vehicle not found")
    base = db.query(DeviceEvent).filter(DeviceEvent.usergroup_id == me.usergroup_id, DeviceEvent.imei == imei,
                                        DeviceEvent.latitude.isnot(None))
    last = base.order_by(DeviceEvent.recorded_at.desc(), DeviceEvent.id.desc()).first()
    if not last:
        return {"imei": imei, "position": None, "trip": None, "trail": []}
    trip = (db.query(Trip).filter(Trip.usergroup_id == me.usergroup_id, Trip.imei == imei, Trip.status == "open")
            .order_by(Trip.started_at.desc()).first())
    since = trip.started_at if trip else last.recorded_at - timedelta(minutes=trail_minutes)
    # The newest 5000 points, oldest first, so a long trip's line reaches the vehicle.
    trail = (base.filter(DeviceEvent.recorded_at >= since).order_by(DeviceEvent.recorded_at.desc(), DeviceEvent.id.desc())
             .limit(5000).all())[::-1]
    io = last.io or {}
    return {
        "imei": imei,
        "position": {"latitude": last.latitude, "longitude": last.longitude, "speed": last.speed or 0,
                     "heading": last.angle, "recorded_at": last.recorded_at, "received_at": last.created_at,
                     "ignition": None if io.get("239") is None else bool(io.get("239")),
                     "event": event_label(last.event_type, last.event_io_id)},
        "trip": None if not trip else {"id": str(trip.id), "started_at": trip.started_at,
                                       "distance_km": round((trip.distance_m or 0) / 1000, 1),
                                       "max_speed": trip.max_speed, "duration_s": trip.duration_s},
        "trail": [[e.latitude, e.longitude] for e in trail],
    }


@router.get("/fleet-status")
def fleet_status(request: Request, db: Session = Depends(get_db)):
    """Latest event, speed, odometer and street address for every vehicle the user may see.

    For the Workspace vehicle grid. Addresses come from the geocode cache only
    (the ingest fills it for vehicles' current positions), so this stays fast
    for big fleets.
    """
    from sqlalchemy import text
    from app.models_dataprofiler import GeocodeCache
    from app.routes_catalog import event_labels
    me = get_portal_user_from_request(request, db)
    access = access_service.for_user(me, db)
    if not (access.can("map.view") or access.can("history.view")):
        access.require("map.view")
    visible = access.visible_imeis(db)
    rows = db.execute(text(
        "SELECT DISTINCT ON (imei) imei, event_type, event_io_id, recorded_at, speed, latitude, longitude, "
        "io->>'16' AS odometer, io->>'239' AS ignition FROM device_events WHERE usergroup_id = :g "
        "ORDER BY imei, recorded_at DESC, id DESC"), {"g": str(me.usergroup_id)}).mappings().all()
    custom = event_labels(db, me.usergroup_id)
    keys = {(round(r["latitude"] * 10000), round(r["longitude"] * 10000)) for r in rows if r["latitude"] is not None}
    addresses = {}
    if keys:
        lats = {k[0] for k in keys}
        for c in db.query(GeocodeCache).filter(GeocodeCache.lat_e4.in_(lats)):
            if (c.lat_e4, c.lng_e4) in keys:
                addresses[(c.lat_e4, c.lng_e4)] = c.address or None
    out = []
    for r in rows:
        if visible is not None and r["imei"] not in visible:
            continue
        key = (round(r["latitude"] * 10000), round(r["longitude"] * 10000)) if r["latitude"] is not None else None
        odo = r["odometer"]
        out.append({
            "imei": r["imei"], "event": custom.get(r["event_type"]) or event_label(r["event_type"], r["event_io_id"]),
            "recorded_at": r["recorded_at"], "speed": r["speed"] or 0,
            "ignition": None if r["ignition"] is None else r["ignition"] == "1",
            "odometer_km": round(int(odo) / 1000, 1) if odo and odo.isdigit() else None,
            "address": addresses.get(key) if key else None,
        })
    return out


@router.get("/vehicle-status")
def vehicle_status(request: Request, db: Session = Depends(get_db), imei: str = Query(...)):
    """Everything the Workspace details panel shows for one vehicle.

    Readings are the latest value of each IO element across the vehicle's
    recent records (devices send some, like the SIM number, only now and then),
    plus the last position's street address and today's trip totals in the
    user group's timezone.
    """
    from zoneinfo import ZoneInfo
    from app.services import address_service
    me = get_portal_user_from_request(request, db)
    access = access_service.for_user(me, db)
    if not (access.can("map.view") or access.can("history.view")):
        access.require("map.view")
    if not access.can_see(db, imei):
        raise HTTPException(status_code=404, detail="Vehicle not found")
    recent = (db.query(DeviceEvent).filter(DeviceEvent.usergroup_id == me.usergroup_id, DeviceEvent.imei == imei)
              .order_by(DeviceEvent.recorded_at.desc(), DeviceEvent.id.desc()).limit(300).all())
    latest_io: dict = {}
    for e in recent:
        for k, v in (e.io or {}).items():
            latest_io.setdefault(k, v)
    fix = next((e for e in recent if e.latitude is not None), None)
    position = None
    if fix:
        position = {"latitude": fix.latitude, "longitude": fix.longitude, "speed": fix.speed or 0,
                    "heading": fix.angle, "satellites": fix.satellites, "recorded_at": fix.recorded_at,
                    "address": address_service.lookup(db, fix.latitude, fix.longitude) or None}
        db.commit()   # keep the address in the cache
    iccid = None
    if latest_io.get("11") is not None and latest_io.get("14") is not None:
        iccid = f"{latest_io['11']}{latest_io['14']}"
    group = db.get(UserGroup, me.usergroup_id)
    try:
        tz = ZoneInfo((group.timezone if group else None) or "Africa/Johannesburg")
    except Exception:
        tz = timezone.utc
    day_start = datetime.now(tz).replace(hour=0, minute=0, second=0, microsecond=0)
    count, distance, driving = (db.query(func.count(Trip.id), func.coalesce(func.sum(Trip.distance_m), 0),
                                         func.coalesce(func.sum(Trip.duration_s), 0))
                                .filter(Trip.usergroup_id == me.usergroup_id, Trip.imei == imei, Trip.real(),
                                        Trip.started_at >= day_start).one())
    return {
        "imei": imei,
        "last_report": recent[0].recorded_at if recent else None,
        "last_event": event_label(recent[0].event_type, recent[0].event_io_id) if recent else None,
        "position": position,
        "readings": describe_io(latest_io),
        "iccid": iccid,
        "today": {"trips": count, "distance_km": round(distance / 1000, 1), "driving_s": int(driving)},
    }


# ---------------------------------------------------------------------------
# Address search (for drawing places)
# ---------------------------------------------------------------------------

_GEOCODE_COUNTRIES = os.getenv("GEOCODE_COUNTRIES", "za")


@router.get("/geocode")
async def geocode(request: Request, q: str = Query(..., min_length=3, max_length=200), db: Session = Depends(get_db)):
    """Addresses and places matching q (OpenStreetMap Nominatim), for the place editor."""
    get_portal_user_from_request(request, db)
    import httpx
    params = {"q": q, "format": "jsonv2", "limit": 6, "addressdetails": 0}
    if _GEOCODE_COUNTRIES:
        params["countrycodes"] = _GEOCODE_COUNTRIES
    try:
        async with httpx.AsyncClient(timeout=8) as client:
            resp = await client.get("https://nominatim.openstreetmap.org/search", params=params,
                                    headers={"User-Agent": "ViSight-Track/1.0 (place search)"})
        resp.raise_for_status()
    except httpx.HTTPError:
        raise HTTPException(status_code=502, detail="Address search is unavailable right now")
    return [{"label": r.get("display_name"), "latitude": float(r["lat"]), "longitude": float(r["lon"])}
            for r in resp.json()]


# ---------------------------------------------------------------------------
# Inbox
# ---------------------------------------------------------------------------

@router.get("/inbox")
def inbox(request: Request, db: Session = Depends(get_db),
          date_from: Optional[datetime] = None, date_to: Optional[datetime] = None,
          status: Optional[str] = Query(None, pattern="^(read|unread)$"),
          alert_type: Optional[str] = None, imei: Optional[str] = None, search: Optional[str] = None,
          limit: int = Query(500, ge=1, le=2000)):
    """Alerts for this group, filterable by date, read status, type, vehicle and text."""
    me = get_portal_user_from_request(request, db)
    access_service.for_user(me, db).require("inbox.view")
    q = _scope_alerts(db.query(PortalAlert), db, me).filter(PortalAlert.usergroup_id == str(me.usergroup_id))
    if date_from:
        q = q.filter(PortalAlert.created_at >= date_from)
    if date_to:
        q = q.filter(PortalAlert.created_at < date_to)
    if status:
        q = q.filter(PortalAlert.is_read == (status == "read"))
    if alert_type:
        q = q.filter(PortalAlert.alert_type == alert_type)
    if search:
        like = f"%{search.strip()}%"
        q = q.filter(PortalAlert.title.ilike(like) | PortalAlert.message.ilike(like))
    alerts = q.order_by(PortalAlert.created_at.desc()).limit(limit).all()
    out = [_portal_alert_dict(a) for a in alerts]
    if imei:
        out = [a for a in out if a["tag_imei"] == imei]
    return out


@router.get("/inbox/{alert_id}")
def inbox_alert(alert_id: str, request: Request, db: Session = Depends(get_db)):
    """One alert for the Inbox details panel, with the street address where it happened."""
    from app.services import address_service
    me = get_portal_user_from_request(request, db)
    access_service.for_user(me, db).require("inbox.view")
    try:
        UUID(alert_id)
    except ValueError:
        raise HTTPException(status_code=404, detail="Alert not found")
    alert = (_scope_alerts(db.query(PortalAlert), db, me)
             .filter(PortalAlert.id == alert_id, PortalAlert.usergroup_id == str(me.usergroup_id)).first())
    if not alert:
        raise HTTPException(status_code=404, detail="Alert not found")
    meta = alert.meta_data or {}
    lat, lng = meta.get("latitude"), meta.get("longitude")
    address = address_service.lookup(db, float(lat), float(lng)) if lat not in (None, "") and lng not in (None, "") else None
    db.commit()   # keep the address in the cache
    return {**_portal_alert_dict(alert), "address": address or None}


# ---------------------------------------------------------------------------
# Reports
# ---------------------------------------------------------------------------

@router.get("/reports")
def report_catalogue(request: Request, db: Session = Depends(get_db)):
    get_portal_user_from_request(request, db)
    return reports_service.catalogue()


@router.get("/reports/{key}")
def run_report(key: str, request: Request, db: Session = Depends(get_db),
               date_from: datetime = Query(...), date_to: datetime = Query(...),
               imei: Optional[str] = None, category: Optional[str] = None,
               format: str = Query("json", pattern="^(json|csv|xlsx|pdf)$"),
               tz: Optional[str] = None):
    """Run a report for a period; format=json for on-screen, csv/xlsx to download.

    tz defaults to the user group's timezone.
    """
    me = get_portal_user_from_request(request, db)
    access = access_service.for_user(me, db)
    access.require("reports.view")
    group = db.get(UserGroup, me.usergroup_id)
    tz = tz or (group.timezone if group else None) or "Africa/Johannesburg"
    if key not in reports_service.REPORTS:
        raise HTTPException(status_code=404, detail="Unknown report")
    if date_to <= date_from or date_to - date_from > timedelta(days=93):
        raise HTTPException(status_code=400, detail="Choose a period of up to 3 months")
    try:
        cols, rows = reports_service.generate(db, me.usergroup_id, key, date_from, date_to,
                                              imei=imei, category=category, tz_name=tz,
                                              only=access.visible_imeis(db))
    except Exception as exc:  # e.g. unknown timezone
        raise HTTPException(status_code=400, detail=str(exc))
    if format == "json":
        return {"columns": cols, "rows": rows}
    title = reports_service.REPORTS[key][0]
    from zoneinfo import ZoneInfo
    zone = ZoneInfo(tz)
    period = f"{date_from.astimezone(zone):%d %b %Y} – {(date_to - timedelta(seconds=1)).astimezone(zone):%d %b %Y}"
    content, mime, ext = reports_service.to_file(title, cols, rows, format,
                                                 subtitle=f"{group.name if group else ''} · {period}".strip(" ·"),
                                                 logo=group.report_logo_data if group else None)
    filename = f"{title.replace(' ', '_')}_{date_from:%Y-%m-%d}.{ext}"
    return Response(content, media_type=mime, headers={"Content-Disposition": f'attachment; filename="{filename}"'})


class ScheduleIn(BaseModel):
    report_key: str
    name: Optional[str] = None
    frequency: str
    file_format: str = "xlsx"
    recipients: List[EmailStr]
    imei: Optional[str] = None
    category: Optional[str] = None
    timezone: str = "Africa/Johannesburg"
    send_hour: int = 6
    is_active: bool = True
    # A scheduled Analytics chart (report_key "analytics")
    page_id: Optional[str] = None
    visual_id: Optional[str] = None

    @field_validator("report_key")
    @classmethod
    def _key(cls, v):
        if v not in reports_service.REPORTS and v != reports_service.ANALYTICS_KEY:
            raise ValueError("Unknown report")
        return v

    @field_validator("frequency")
    @classmethod
    def _freq(cls, v):
        if v not in reports_service.FREQUENCIES:
            raise ValueError("frequency must be daily, weekly or monthly")
        return v

    @field_validator("file_format")
    @classmethod
    def _fmt(cls, v):
        if v not in reports_service.FORMATS:
            raise ValueError("file_format must be xlsx, csv or pdf")
        return v

    @field_validator("send_hour")
    @classmethod
    def _hour(cls, v):
        if not 0 <= v <= 23:
            raise ValueError("send_hour must be 0–23")
        return v

    @field_validator("recipients")
    @classmethod
    def _recipients(cls, v):
        if not v or len(v) > 20:
            raise ValueError("Add 1–20 recipients")
        return v


def _schedule_out(s: ReportSchedule, db: Optional[Session] = None) -> dict:
    params = s.params or {}
    title = reports_service.REPORTS.get(s.report_key, (s.report_key,))[0]
    if s.report_key == reports_service.ANALYTICS_KEY:
        title = "Analytics chart"
        if db is not None and params.get("page_id"):
            from app.models import AnalyticsPage
            try:
                page = db.get(AnalyticsPage, UUID(str(params["page_id"])))
            except ValueError:
                page = None
            visual = next((v for v in ((page.visuals if page else None) or []) if v.get("id") == params.get("visual_id")), None)
            title = f"{page.name} · {visual.get('title') or 'Chart'}" if visual else "Analytics chart (removed)"
    return {
        "id": str(s.id), "report_key": s.report_key, "page_id": params.get("page_id"), "visual_id": params.get("visual_id"),
        "report_title": title,
        "name": s.name, "frequency": s.frequency, "file_format": s.file_format,
        "recipients": s.recipients or [], "imei": params.get("imei"), "category": params.get("category"),
        "timezone": s.timezone, "send_hour": s.send_hour, "is_active": s.is_active,
        "next_run_at": s.next_run_at, "last_run_at": s.last_run_at, "last_status": s.last_status,
    }


def _apply(s: ReportSchedule, data: ScheduleIn) -> None:
    from zoneinfo import ZoneInfo
    try:
        ZoneInfo(data.timezone)
    except Exception:
        raise HTTPException(status_code=400, detail="Unknown timezone")
    s.report_key, s.name, s.frequency, s.file_format = data.report_key, data.name, data.frequency, data.file_format
    s.recipients = [str(r).lower() for r in data.recipients]
    s.params = {k: v for k, v in {"imei": data.imei, "category": data.category,
                                  "page_id": data.page_id, "visual_id": data.visual_id}.items() if v}
    if data.report_key == reports_service.ANALYTICS_KEY and not (data.page_id and data.visual_id):
        raise HTTPException(status_code=400, detail="Choose the Analytics chart to schedule")
    s.timezone, s.send_hour, s.is_active = data.timezone, data.send_hour, data.is_active
    s.next_run_at = reports_service.next_run(data.frequency, data.send_hour, data.timezone, datetime.now(timezone.utc))


def _own_schedule(db, me, schedule_id) -> ReportSchedule:
    try:
        UUID(schedule_id)
    except ValueError:
        raise HTTPException(status_code=404, detail="Schedule not found")
    s = db.query(ReportSchedule).filter(ReportSchedule.id == schedule_id,
                                        ReportSchedule.usergroup_id == me.usergroup_id).first()
    if not s:
        raise HTTPException(status_code=404, detail="Schedule not found")
    return s


def _require_reports_admin(me):
    access_service.for_user(me).require("reports.schedule")


@router.get("/report-schedules")
def list_schedules(request: Request, db: Session = Depends(get_db)):
    me = get_portal_user_from_request(request, db)
    _require_reports_admin(me)
    rows = (db.query(ReportSchedule).filter(ReportSchedule.usergroup_id == me.usergroup_id)
            .order_by(ReportSchedule.created_at.desc()).all())
    return [_schedule_out(s, db) for s in rows]


@router.post("/report-schedules", status_code=201)
def create_schedule(data: ScheduleIn, request: Request, db: Session = Depends(get_db)):
    me = get_portal_user_from_request(request, db)
    _require_reports_admin(me)
    s = ReportSchedule(usergroup_id=me.usergroup_id, created_by=me.id)
    _apply(s, data)
    db.add(s)
    db.commit()
    db.refresh(s)
    return _schedule_out(s, db)


@router.put("/report-schedules/{schedule_id}")
def update_schedule(schedule_id: str, data: ScheduleIn, request: Request, db: Session = Depends(get_db)):
    me = get_portal_user_from_request(request, db)
    _require_reports_admin(me)
    s = _own_schedule(db, me, schedule_id)
    _apply(s, data)
    db.commit()
    db.refresh(s)
    return _schedule_out(s, db)


@router.delete("/report-schedules/{schedule_id}", status_code=204)
def delete_schedule(schedule_id: str, request: Request, db: Session = Depends(get_db)):
    me = get_portal_user_from_request(request, db)
    _require_reports_admin(me)
    db.delete(_own_schedule(db, me, schedule_id))
    db.commit()


@router.post("/report-schedules/{schedule_id}/send-now")
def send_schedule_now(schedule_id: str, request: Request, db: Session = Depends(get_db)):
    """Send the most recent completed period now (does not change the next scheduled run)."""
    me = get_portal_user_from_request(request, db)
    _require_reports_admin(me)
    s = _own_schedule(db, me, schedule_id)
    from app.services.email_service import EmailService
    status = reports_service.run_schedule(db, s, EmailService(), datetime.now(timezone.utc))
    s.last_status, s.last_run_at = status, datetime.now(timezone.utc)
    db.commit()
    return {"status": status}
