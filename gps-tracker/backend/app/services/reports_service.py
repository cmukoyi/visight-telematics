"""Customer reports — catalogue, generation, export and scheduled email delivery.

Every report is a function of (group, period, optional vehicle/vehicle group)
returning columns + rows, so the same code serves on-screen viewing, file
download and scheduled emails.
"""
import csv
import io
import logging
from datetime import datetime, timedelta, timezone
from typing import Callable, Optional
from zoneinfo import ZoneInfo

from sqlalchemy.orm import Session

from app.dataprofiler.dictionary import EVENTS, event_label
from app.models import BLETag, PortalAlert
from app.models_dataprofiler import DeviceEvent, ReportSchedule, Trip

logger = logging.getLogger(__name__)

FREQUENCIES = ("daily", "weekly", "monthly")
FORMATS = ("xlsx", "csv")
MAX_ROWS = 50_000


# ---------------------------------------------------------------------------
# Scope helpers
# ---------------------------------------------------------------------------

def group_devices(db: Session, group_id, category: Optional[str] = None) -> dict:
    """{imei: display name} for the group's devices, optionally one vehicle group (category)."""
    tags = db.query(BLETag).filter(
        BLETag.attributes.op("->>")("_created_usergroup_id") == str(group_id)).all()
    out = {}
    for tag in tags:
        if category and ((tag.attributes or {}).get("category") or {}).get("value") != category:
            continue
        out[tag.imei] = tag.description or tag.device_name or tag.imei
    return out


def _local(dt: Optional[datetime], tz: ZoneInfo) -> str:
    return dt.astimezone(tz).strftime("%Y-%m-%d %H:%M:%S") if dt else ""


def _dur(seconds: Optional[int]) -> str:
    s = int(seconds or 0)
    return f"{s // 3600}:{s % 3600 // 60:02d}:{s % 60:02d}"


# ---------------------------------------------------------------------------
# Reports: (columns, rows) for a period
# ---------------------------------------------------------------------------

def _trips_q(db, group_id, imeis, start, end):
    return (db.query(Trip).filter(Trip.usergroup_id == group_id, Trip.imei.in_(list(imeis)),
                                  Trip.started_at >= start, Trip.started_at < end)
            .order_by(Trip.started_at))


def report_trips(db, group_id, devices, start, end, tz):
    cols = ["Vehicle", "IMEI", "Start", "End", "Duration", "Distance (km)", "Max speed (km/h)",
            "Avg speed (km/h)", "Speeding", "Harsh braking", "Harsh acceleration", "Harsh cornering",
            "Start position", "End position"]
    rows = []
    for t in _trips_q(db, group_id, devices, start, end).limit(MAX_ROWS):
        rows.append([devices.get(t.imei, t.imei), t.imei, _local(t.started_at, tz),
                     _local(t.ended_at, tz) if t.ended_at else "in progress", _dur(t.duration_s),
                     round((t.distance_m or 0) / 1000, 2), t.max_speed, t.avg_speed or "",
                     t.speeding_count, t.harsh_braking_count, t.harsh_acceleration_count, t.harsh_cornering_count,
                     f"{t.start_latitude:.5f}, {t.start_longitude:.5f}" if t.start_latitude is not None else "",
                     f"{t.end_latitude:.5f}, {t.end_longitude:.5f}" if t.end_latitude is not None else ""])
    return cols, rows


def report_vehicle_summary(db, group_id, devices, start, end, tz):
    cols = ["Vehicle", "IMEI", "Trips", "Distance (km)", "Driving time", "Avg trip (km)",
            "Max speed (km/h)", "Speeding", "Harsh events"]
    agg: dict = {imei: [0, 0, 0, 0, 0, 0] for imei in devices}
    for t in _trips_q(db, group_id, devices, start, end):
        a = agg[t.imei]
        a[0] += 1
        a[1] += t.distance_m or 0
        a[2] += t.duration_s or 0
        a[3] = max(a[3], t.max_speed or 0)
        a[4] += t.speeding_count
        a[5] += t.harsh_braking_count + t.harsh_acceleration_count + t.harsh_cornering_count
    rows = [[name, imei, a[0], round(a[1] / 1000, 2), _dur(a[2]),
             round(a[1] / 1000 / a[0], 2) if a[0] else 0, a[3], a[4], a[5]]
            for imei, name in sorted(devices.items(), key=lambda x: x[1].lower()) for a in [agg[imei]]]
    return cols, rows


def _events(db, group_id, devices, start, end, codes=None):
    q = db.query(DeviceEvent).filter(DeviceEvent.usergroup_id == group_id, DeviceEvent.imei.in_(list(devices)),
                                     DeviceEvent.recorded_at >= start, DeviceEvent.recorded_at < end)
    if codes:
        q = q.filter(DeviceEvent.event_type.in_(codes))
    return q.order_by(DeviceEvent.recorded_at).limit(MAX_ROWS)


def report_events(db, group_id, devices, start, end, tz):
    cols = ["Vehicle", "IMEI", "Time", "Event", "Latitude", "Longitude", "Speed (km/h)", "Odometer (km)"]
    rows = []
    for e in _events(db, group_id, devices, start, end, [c for c in EVENTS if c != "parked_position"]):
        odo = (e.io or {}).get("16")
        rows.append([devices.get(e.imei, e.imei), e.imei, _local(e.recorded_at, tz),
                     event_label(e.event_type, e.event_io_id), e.latitude, e.longitude, e.speed,
                     round(odo / 1000, 1) if isinstance(odo, int) else ""])
    return cols, rows


def report_driver_behaviour(db, group_id, devices, start, end, tz):
    cols = ["Vehicle", "IMEI", "Time", "Event", "Speed (km/h)", "Detail", "Latitude", "Longitude"]
    codes = ["overspeed", "harsh_braking", "harsh_acceleration", "harsh_cornering", "idling_start", "crash"]
    rows = []
    for e in _events(db, group_id, devices, start, end, codes):
        io = e.io or {}
        detail = (f"{io.get('255')} km/h" if e.event_type == "overspeed" and io.get("255") is not None
                  else f"{io['254'] / 100:.2f} g" if isinstance(io.get("254"), int) else "")
        rows.append([devices.get(e.imei, e.imei), e.imei, _local(e.recorded_at, tz),
                     event_label(e.event_type, e.event_io_id), e.speed, detail, e.latitude, e.longitude])
    return cols, rows


def report_alerts(db, group_id, devices, start, end, tz):
    cols = ["Time", "Type", "Title", "Message", "Vehicle", "Read"]
    alerts = (db.query(PortalAlert).filter(PortalAlert.usergroup_id == str(group_id),
                                           PortalAlert.created_at >= start, PortalAlert.created_at < end)
              .order_by(PortalAlert.created_at).limit(MAX_ROWS).all())
    rows = []
    for a in alerts:
        imei = a.tag.imei if a.tag else None
        if imei and imei not in devices:
            continue
        rows.append([_local(a.created_at, tz), a.alert_type, a.title, a.message,
                     devices.get(imei, imei or ""), "yes" if a.is_read else "no"])
    return cols, rows


# key → (title, category, description, generator)
REPORTS: dict[str, tuple[str, str, str, Callable]] = {
    "trips":            ("Trip detail", "Trips", "Every trip with duration, distance, speeds and driving events.", report_trips),
    "vehicle_summary":  ("Vehicle summary", "Utilisation", "Trips, distance and driving time per vehicle.", report_vehicle_summary),
    "driver_behaviour": ("Driving behaviour", "Driving", "Speeding, harsh driving, idling and crash events.", report_driver_behaviour),
    "events":           ("Event detail", "Events", "All decoded device events (excluding parked updates).", report_events),
    "alerts":           ("Alert history", "Alerts", "Notifications raised for your vehicles.", report_alerts),
}


def catalogue() -> list[dict]:
    return [{"key": k, "title": t, "category": c, "description": d} for k, (t, c, d, _) in REPORTS.items()]


def generate(db: Session, group_id, key: str, start: datetime, end: datetime,
             imei: Optional[str] = None, category: Optional[str] = None,
             tz_name: str = "Africa/Johannesburg") -> tuple[list, list]:
    if key not in REPORTS:
        raise KeyError(key)
    devices = group_devices(db, group_id, category)
    if imei:
        devices = {k: v for k, v in devices.items() if k == imei}
    return REPORTS[key][3](db, group_id, devices, start, end, ZoneInfo(tz_name))


def to_file(title: str, cols: list, rows: list, fmt: str) -> tuple[bytes, str, str]:
    """(content, mime type, extension)."""
    if fmt == "csv":
        buf = io.StringIO()
        writer = csv.writer(buf)
        writer.writerow(cols)
        writer.writerows(rows)
        return buf.getvalue().encode("utf-8-sig"), "text/csv", "csv"
    from openpyxl import Workbook
    from openpyxl.styles import Font
    wb = Workbook()
    ws = wb.active
    ws.title = title[:31]
    ws.append(cols)
    for cell in ws[1]:
        cell.font = Font(bold=True)
    for row in rows:
        ws.append(row)
    for i, col in enumerate(cols, start=1):
        width = max([len(str(col))] + [len(str(r[i - 1])) for r in rows[:500]]) + 2
        ws.column_dimensions[ws.cell(row=1, column=i).column_letter].width = min(width, 50)
    ws.freeze_panes = "A2"
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue(), "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", "xlsx"


# ---------------------------------------------------------------------------
# Scheduling
# ---------------------------------------------------------------------------

def period_for(frequency: str, run_at: datetime, tz: ZoneInfo) -> tuple[datetime, datetime]:
    """The whole previous day / week (Mon–Sun) / month before run_at, in tz, as UTC."""
    local = run_at.astimezone(tz).replace(hour=0, minute=0, second=0, microsecond=0)
    if frequency == "daily":
        start, end = local - timedelta(days=1), local
    elif frequency == "weekly":
        end = local - timedelta(days=local.weekday())
        start = end - timedelta(days=7)
    else:
        end = local.replace(day=1)
        start = (end - timedelta(days=1)).replace(day=1)
    return start.astimezone(timezone.utc), end.astimezone(timezone.utc)


def next_run(frequency: str, send_hour: int, tz_name: str, after: datetime) -> datetime:
    """First send time strictly after `after`: daily at send_hour, weekly Mondays, monthly on the 1st."""
    tz = ZoneInfo(tz_name)
    local = after.astimezone(tz)
    candidate = local.replace(hour=send_hour, minute=0, second=0, microsecond=0)
    while True:
        if candidate > local and (frequency == "daily"
                                  or (frequency == "weekly" and candidate.weekday() == 0)
                                  or (frequency == "monthly" and candidate.day == 1)):
            return candidate.astimezone(timezone.utc)
        candidate += timedelta(days=1)


def run_schedule(db: Session, schedule: ReportSchedule, email_service, now: datetime) -> str:
    title = REPORTS[schedule.report_key][0]
    tz = ZoneInfo(schedule.timezone)
    start, end = period_for(schedule.frequency, now, tz)
    params = schedule.params or {}
    cols, rows = generate(db, schedule.usergroup_id, schedule.report_key, start, end,
                          imei=params.get("imei"), category=params.get("category"), tz_name=schedule.timezone)
    content, mime, ext = to_file(title, cols, rows, schedule.file_format)
    period = f"{start.astimezone(tz):%d %b %Y}" + (
        "" if schedule.frequency == "daily" else f" – {(end - timedelta(seconds=1)).astimezone(tz):%d %b %Y}")
    name = schedule.name or title
    filename = f"{name.replace(' ', '_')}_{start.astimezone(tz):%Y-%m-%d}.{ext}"
    subject = f"{name} — {period}"
    text_body = f"Your {schedule.frequency} report \"{name}\" for {period} is attached ({len(rows)} rows)."
    html_body = (f"<p>Your {schedule.frequency} report <strong>{name}</strong> for {period} is attached "
                 f"({len(rows)} rows).</p><p style='color:#888;font-size:12px'>Manage scheduled reports under "
                 f"Reports in {email_service.brand_name}.</p>")
    sent = sum(email_service.send_report_email(to, subject, text_body, html_body, filename, content, mime)
               for to in schedule.recipients or [])
    return f"sent to {sent}/{len(schedule.recipients or [])} recipients ({len(rows)} rows)"


def run_due(db: Session, email_service=None, now: Optional[datetime] = None) -> int:
    """Send every schedule that is due, then move it to its next run. Commits per schedule."""
    if email_service is None:
        from app.services.email_service import EmailService
        email_service = EmailService()
    now = now or datetime.now(timezone.utc)
    due = db.query(ReportSchedule).filter(ReportSchedule.is_active == True, ReportSchedule.next_run_at <= now).all()
    for schedule in due:
        try:
            schedule.last_status = run_schedule(db, schedule, email_service, now)
        except Exception as exc:
            logger.exception("Scheduled report %s failed", schedule.id)
            schedule.last_status = f"failed: {exc.__class__.__name__}"
        schedule.last_run_at = now
        schedule.next_run_at = next_run(schedule.frequency, schedule.send_hour, schedule.timezone, now)
        db.commit()
    return len(due)
