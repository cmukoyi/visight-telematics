"""Customer portal — Custom reports: design, preview, run (with history) and schedule.

Mounted under /api/portal/custom-reports. Viewing and running needs
reports.view, designing reports.design, scheduling reports.schedule. Runs are
kept with their file; schedules are report_schedules with report_key "custom".
"""
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional
from uuid import UUID
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import Response
from pydantic import BaseModel, EmailStr, field_validator
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import AnalyticsExpression, Driver, PortalUser, UserGroup
from app.models_dataprofiler import ReportSchedule
from app.models_reports import CustomReport, CustomReportCategory, CustomReportRun
from app.routes_portal import get_portal_user_from_request
from app.services import access_service, reports_service
from app.services import custom_reports_service as cr

router = APIRouter(prefix="/api/portal/custom-reports", tags=["portal-custom-reports"])

KEY = "custom"   # report_schedules.report_key for a custom report
KEEP_RUNS = 50


def _me(request: Request, db: Session, perm: str = "reports.view"):
    me = get_portal_user_from_request(request, db)
    access = access_service.for_user(me, db)
    access.require("reports.view")
    if perm != "reports.view":
        access.require(perm)
    return me, access


def _uuid(v: str, what: str) -> UUID:
    try:
        return UUID(str(v))
    except ValueError:
        raise HTTPException(status_code=404, detail=f"{what} not found")


def _expressions(db: Session, group_id) -> dict:
    return {str(e.id): (e.name, e.expression, e.decimals, e.unit)
            for e in db.query(AnalyticsExpression).filter(AnalyticsExpression.usergroup_id == group_id)}


def _tz(db: Session, group_id) -> ZoneInfo:
    group = db.get(UserGroup, group_id)
    try:
        return ZoneInfo((group.timezone if group else None) or "Africa/Johannesburg")
    except Exception:
        return ZoneInfo("UTC")


# ---------------------------------------------------------------------------
# Catalogue
# ---------------------------------------------------------------------------

@router.get("/meta")
def meta(request: Request, db: Session = Depends(get_db)):
    _me(request, db)
    return {"entities": cr.entity_list(),
            "parameters": [{"key": k, "label": label, "kind": kind} for k, (label, kind) in cr.PARAMETERS.items()],
            "operators": [{"key": k, "label": v} for k, v in cr.OP_LABELS.items()]}


@router.get("/columns/{entity}")
def columns(entity: str, request: Request, db: Session = Depends(get_db)):
    me, _ = _me(request, db)
    if entity not in cr.ENTITIES:
        raise HTTPException(status_code=404, detail="Unknown row type")
    return cr.columns_for(entity, _expressions(db, me.usergroup_id))


# ---------------------------------------------------------------------------
# Categories
# ---------------------------------------------------------------------------

class CategoryIn(BaseModel):
    name: str

    @field_validator("name")
    @classmethod
    def _n(cls, v):
        v = (v or "").strip()
        if not v or len(v) > 120:
            raise ValueError("Enter a category name")
        return v


@router.get("/categories")
def categories(request: Request, db: Session = Depends(get_db)):
    me, _ = _me(request, db)
    counts = dict(db.query(CustomReport.category_id, func.count(CustomReport.id))
                  .filter(CustomReport.usergroup_id == me.usergroup_id).group_by(CustomReport.category_id).all())
    return [{"id": str(c.id), "name": c.name, "reports": counts.get(c.id, 0)} for c in
            db.query(CustomReportCategory).filter(CustomReportCategory.usergroup_id == me.usergroup_id)
            .order_by(func.lower(CustomReportCategory.name))]


@router.post("/categories", status_code=201)
def create_category(data: CategoryIn, request: Request, db: Session = Depends(get_db)):
    me, _ = _me(request, db, "reports.design")
    c = CustomReportCategory(usergroup_id=me.usergroup_id, name=data.name)
    db.add(c)
    db.commit()
    return {"id": str(c.id), "name": c.name, "reports": 0}


@router.put("/categories/{cid}")
def rename_category(cid: str, data: CategoryIn, request: Request, db: Session = Depends(get_db)):
    me, _ = _me(request, db, "reports.design")
    c = db.query(CustomReportCategory).filter(CustomReportCategory.id == _uuid(cid, "Category"),
                                              CustomReportCategory.usergroup_id == me.usergroup_id).first()
    if not c:
        raise HTTPException(status_code=404, detail="Category not found")
    c.name = data.name
    db.commit()
    return {"id": str(c.id), "name": c.name}


@router.delete("/categories/{cid}", status_code=204)
def delete_category(cid: str, request: Request, db: Session = Depends(get_db)):
    """Delete the category; its reports stay, without one."""
    me, _ = _me(request, db, "reports.design")
    db.query(CustomReportCategory).filter(CustomReportCategory.id == _uuid(cid, "Category"),
                                          CustomReportCategory.usergroup_id == me.usergroup_id).delete(synchronize_session=False)
    db.commit()


# ---------------------------------------------------------------------------
# Reports
# ---------------------------------------------------------------------------

class ColumnIn(BaseModel):
    key: str
    title: Optional[str] = None
    sort: Optional[str] = None
    decimals: Optional[int] = None
    show_unit: bool = False
    format: Optional[Dict[str, Any]] = None

    @field_validator("sort")
    @classmethod
    def _sort(cls, v):
        return v if v in ("asc", "desc") else None


class ParameterIn(BaseModel):
    key: str
    required: bool = False


class FilterIn(BaseModel):
    column: str
    op: str = "gt"
    required: bool = False

    @field_validator("op")
    @classmethod
    def _op(cls, v):
        if v not in cr.OPS:
            raise ValueError("Unknown filter operator")
        return v


class ReportIn(BaseModel):
    title: str = "Untitled report"
    description: Optional[str] = None
    category_id: Optional[str] = None
    row_entity: str
    top_n: Optional[int] = None
    columns: List[ColumnIn] = []
    parameters: List[ParameterIn] = []
    column_filters: List[FilterIn] = []
    file: Dict[str, Any] = {}

    @field_validator("title")
    @classmethod
    def _title(cls, v):
        v = (v or "").strip()
        if not v or len(v) > 160:
            raise ValueError("Enter a title")
        return v

    @field_validator("row_entity")
    @classmethod
    def _entity(cls, v):
        if v not in cr.ENTITIES:
            raise ValueError("Unknown row type")
        return v

    @field_validator("top_n")
    @classmethod
    def _top(cls, v):
        if v is not None and not 1 <= v <= cr.MAX_ROWS:
            raise ValueError(f"Top N: 1–{cr.MAX_ROWS}")
        return v

    @field_validator("file")
    @classmethod
    def _file(cls, v):
        fmt = v.get("format") or "xlsx"
        if fmt not in ("xlsx", "csv", "pdf"):
            raise ValueError("File type: Excel, CSV or PDF")
        return {"format": fmt, "csv_separator": v.get("csv_separator") if v.get("csv_separator") in ("comma", "semicolon", "tab") else "comma",
                "orientation": "portrait" if v.get("orientation") == "portrait" else "landscape",
                "include_parameters": bool(v.get("include_parameters"))}


def _clean(data: ReportIn, expressions: dict) -> dict:
    """The definition as stored: known columns only, the entity's parameters (date range always, required), filters on number columns."""
    catalog = {c["key"]: c for c in cr.columns_for(data.row_entity, expressions)}
    cols = [c.model_dump() for c in data.columns if c.key in catalog]
    if not cols:
        raise HTTPException(status_code=400, detail="Add at least one column")
    allowed = cr.ENTITIES[data.row_entity][4]
    params = [{"key": "date_range", "required": True}] + [
        {"key": p.key, "required": p.required} for p in data.parameters if p.key in allowed and p.key != "date_range"]
    numeric = {c["key"] for c in cols if catalog[c["key"]]["type"] == "number"}
    filters = [f.model_dump() for f in data.column_filters if f.column in numeric]
    return {"title": data.title, "description": (data.description or "").strip() or None, "row_entity": data.row_entity,
            "top_n": data.top_n, "columns": cols, "parameters": params, "column_filters": filters, "file": data.file}


def _report_out(r: CustomReport, categories: Optional[dict] = None) -> dict:
    return {"id": str(r.id), "title": r.title, "description": r.description, "category_id": str(r.category_id) if r.category_id else None,
            "category": (categories or {}).get(r.category_id), "row_entity": r.row_entity,
            "row_entity_label": cr.ENTITIES.get(r.row_entity, (r.row_entity,))[0], "top_n": r.top_n,
            "columns": r.columns or [], "parameters": r.parameters or [], "column_filters": r.column_filters or [],
            "file": r.file or {}, "updated_at": r.updated_at or r.created_at}


def _own(db: Session, me: PortalUser, rid: str) -> CustomReport:
    r = db.query(CustomReport).filter(CustomReport.id == _uuid(rid, "Report"), CustomReport.usergroup_id == me.usergroup_id).first()
    if not r:
        raise HTTPException(status_code=404, detail="Report not found")
    return r


def _category(db: Session, me: PortalUser, cid: Optional[str]):
    if not cid:
        return None
    c = db.query(CustomReportCategory).filter(CustomReportCategory.id == _uuid(cid, "Category"),
                                              CustomReportCategory.usergroup_id == me.usergroup_id).first()
    if not c:
        raise HTTPException(status_code=404, detail="Category not found")
    return c.id


@router.get("")
def list_reports(request: Request, db: Session = Depends(get_db)):
    me, _ = _me(request, db)
    cats = {c.id: c.name for c in db.query(CustomReportCategory).filter(CustomReportCategory.usergroup_id == me.usergroup_id)}
    return [_report_out(r, cats) for r in db.query(CustomReport).filter(CustomReport.usergroup_id == me.usergroup_id)
            .order_by(func.lower(CustomReport.title))]


@router.get("/{rid}")
def get_report(rid: str, request: Request, db: Session = Depends(get_db)):
    me, _ = _me(request, db)
    cats = {c.id: c.name for c in db.query(CustomReportCategory).filter(CustomReportCategory.usergroup_id == me.usergroup_id)}
    return _report_out(_own(db, me, rid), cats)


@router.post("", status_code=201)
def create_report(data: ReportIn, request: Request, db: Session = Depends(get_db)):
    me, _ = _me(request, db, "reports.design")
    r = CustomReport(usergroup_id=me.usergroup_id, created_by=me.id, category_id=_category(db, me, data.category_id),
                     **_clean(data, _expressions(db, me.usergroup_id)))
    db.add(r)
    db.commit()
    return _report_out(r)


@router.put("/{rid}")
def update_report(rid: str, data: ReportIn, request: Request, db: Session = Depends(get_db)):
    me, _ = _me(request, db, "reports.design")
    r = _own(db, me, rid)
    for k, v in _clean(data, _expressions(db, me.usergroup_id)).items():
        setattr(r, k, v)
    r.category_id = _category(db, me, data.category_id)
    db.commit()
    return _report_out(r)


@router.post("/{rid}/copy", status_code=201)
def copy_report(rid: str, request: Request, db: Session = Depends(get_db)):
    """A copy of the definition (not its schedules or history)."""
    me, _ = _me(request, db, "reports.design")
    r = _own(db, me, rid)
    c = CustomReport(usergroup_id=me.usergroup_id, created_by=me.id, category_id=r.category_id, title=f"{r.title} (copy)"[:160],
                     description=r.description, row_entity=r.row_entity, top_n=r.top_n, columns=r.columns,
                     parameters=r.parameters, column_filters=r.column_filters, file=r.file)
    db.add(c)
    db.commit()
    return _report_out(c)


@router.delete("/{rid}", status_code=204)
def delete_report(rid: str, request: Request, db: Session = Depends(get_db)):
    me, _ = _me(request, db, "reports.design")
    r = _own(db, me, rid)
    for s in _schedules_q(db, me, r):
        db.delete(s)
    db.delete(r)
    db.commit()


# ---------------------------------------------------------------------------
# Preview and runs
# ---------------------------------------------------------------------------

class RunValues(BaseModel):
    date_from: datetime
    date_to: datetime
    vehicle: Optional[str] = None
    vehicle_group: Optional[str] = None
    driver: Optional[str] = None
    event_type: Optional[List[str]] = None
    trip_events_only: Optional[bool] = None
    place: Optional[str] = None
    alert_type: Optional[str] = None
    job_status: Optional[str] = None
    cost_category: Optional[str] = None
    filters: Dict[str, Dict[str, Any]] = {}

    def as_dict(self) -> dict:
        d = self.model_dump()
        d["date_range"] = (self.date_from, self.date_to)
        return d


def _period(v: RunValues) -> tuple:
    a = v.date_from if v.date_from.tzinfo else v.date_from.replace(tzinfo=timezone.utc)
    b = v.date_to if v.date_to.tzinfo else v.date_to.replace(tzinfo=timezone.utc)
    if b <= a:
        raise HTTPException(status_code=400, detail="The period ends before it starts")
    if b - a > timedelta(days=400):
        raise HTTPException(status_code=400, detail="Choose a period of at most a year")
    return a, b


def parameters_text(db: Session, report, values: dict, start: datetime, end: datetime, tz: ZoneInfo) -> str:
    """"01-Oct-2026 .. 31-Oct-2026 / Vehicle group: Fleet / Driver: Mary Dube" for the history and file headings."""
    parts = [f"{start.astimezone(tz):%d-%b-%Y} .. {(end - timedelta(seconds=1)).astimezone(tz):%d-%b-%Y}"]
    for p in report.parameters or []:
        k, v = p["key"], values.get(p["key"])
        if k == "date_range" or v in (None, "", [], False):
            continue
        if k == "driver":
            d = db.get(Driver, _uuid(v, "Driver"))
            v = d.name if d else v
        elif k == "vehicle":
            from app.models import BLETag
            tag = db.query(BLETag).filter(BLETag.imei == v).first()
            v = (tag.description or tag.device_name or v) if tag else v
        elif isinstance(v, list):
            v = ", ".join(v)
        elif v is True:
            v = "yes"
        parts.append(f"{cr.PARAMETERS[k][0]}: {v}")
    for f in report.column_filters or []:
        given = (values.get("filters") or {}).get(f["column"]) or {}
        if given.get("value") not in (None, ""):
            parts.append(f"{f['column'].split(':', 1)[-1]} {cr.OP_LABELS[f['op']]} {given['value']}"
                         + (f" and {given.get('value2')}" if f["op"] == "between" else ""))
    return " / ".join(parts)


class PreviewIn(BaseModel):
    report: ReportIn
    values: Optional[RunValues] = None


@router.post("/preview")
def preview(data: PreviewIn, request: Request, db: Session = Depends(get_db)):
    """The first rows of a (possibly unsaved) definition, once the required parameters have values."""
    me, access = _me(request, db)
    expressions = _expressions(db, me.usergroup_id)
    definition = CustomReport(usergroup_id=me.usergroup_id, **_clean(data.report, expressions))
    if data.values is None:
        return {"ready": False, "message": "Select all required parameters", "columns": [], "rows": []}
    values = data.values.as_dict()
    try:
        cr.check_values(definition, values)
    except cr.ReportError as exc:
        return {"ready": False, "message": str(exc), "columns": [], "rows": []}
    start, end = _period(data.values)
    tz = _tz(db, me.usergroup_id)
    try:
        cols, rows = cr.build(db, definition, values, start, end, tz, access.visible_imeis(db), expressions, limit=cr.PREVIEW_ROWS)
    except cr.ReportError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    styles = cr.colours(cols, rows)
    return {"ready": True, "columns": [{"key": c["key"], "title": c["title"], "unit": c["unit"], "type": c["type"]} for c in cols],
            "rows": [[cr.display(r.get(c["key"]), c, tz) for c in cols] for r in rows], "styles": styles}


class GenerateIn(BaseModel):
    values: RunValues
    file_name: Optional[str] = None
    compress: bool = False


def generate(db: Session, report: CustomReport, values: dict, start: datetime, end: datetime, *, only: Optional[set],
             created_by: Optional[str], schedule_id=None, file_name: Optional[str] = None, compress: bool = False) -> CustomReportRun:
    """Build, render and keep one run (also on failure, with the error). Commits."""
    tz = _tz(db, report.usergroup_id)
    text = parameters_text(db, report, values, start, end, tz)
    run = CustomReportRun(usergroup_id=report.usergroup_id, report_id=report.id, schedule_id=schedule_id,
                          created_by=created_by, parameters={"text": text})
    try:
        cr.check_values(report, values)
        cols, rows = cr.build(db, report, values, start, end, tz, only, _expressions(db, report.usergroup_id))
        group = db.get(UserGroup, report.usergroup_id)
        content, mime, ext = cr.render(report, cols, rows, tz, group.name if group else "", group.report_logo_data if group else None, text)
        name = cr.file_name(file_name, report.title, start, end, tz, ext)
        if compress:
            content, mime, name = cr.zip_file(content, name)
        run.status, run.rows, run.file_name, run.mime, run.content, run.size_bytes = "done", len(rows), name, mime, content, len(content)
    except Exception as exc:   # kept in the history so people see why
        run.status, run.error = "failed", str(exc)[:500]
    db.add(run)
    db.flush()
    old = (db.query(CustomReportRun.id).filter(CustomReportRun.report_id == report.id)
           .order_by(CustomReportRun.created_at.desc()).offset(KEEP_RUNS).all())
    if old:
        db.query(CustomReportRun).filter(CustomReportRun.id.in_([i for (i,) in old])).delete(synchronize_session=False)
    db.commit()
    return run


def _run_out(r: CustomReportRun, schedules: Optional[dict] = None) -> dict:
    return {"id": str(r.id), "created_at": r.created_at, "created_by": r.created_by,
            "schedule": (schedules or {}).get(r.schedule_id) if r.schedule_id else None,
            "parameters": (r.parameters or {}).get("text"), "status": r.status, "error": r.error, "rows": r.rows,
            "file_name": r.file_name, "size_bytes": r.size_bytes}


@router.post("/{rid}/runs", status_code=201)
def run_report(rid: str, data: GenerateIn, request: Request, db: Session = Depends(get_db)):
    me, access = _me(request, db)
    report = _own(db, me, rid)
    start, end = _period(data.values)
    run = generate(db, report, data.values.as_dict(), start, end, only=access.visible_imeis(db), created_by=me.email,
                   file_name=data.file_name, compress=data.compress)
    if run.status == "failed":
        raise HTTPException(status_code=400, detail=run.error or "The report could not be generated")
    return _run_out(run)


@router.get("/{rid}/runs")
def runs(rid: str, request: Request, db: Session = Depends(get_db)):
    me, _ = _me(request, db)
    report = _own(db, me, rid)
    names = {s.id: s.name or "Schedule" for s in _schedules_q(db, me, report)}
    return [_run_out(r, names) for r in db.query(CustomReportRun).filter(CustomReportRun.report_id == report.id)
            .order_by(CustomReportRun.created_at.desc()).limit(KEEP_RUNS)]


@router.get("/runs/{run_id}/file")
def run_file(run_id: str, request: Request, db: Session = Depends(get_db)):
    me, _ = _me(request, db)
    r = db.query(CustomReportRun).filter(CustomReportRun.id == _uuid(run_id, "File"),
                                         CustomReportRun.usergroup_id == me.usergroup_id).first()
    if not r or not r.content:
        raise HTTPException(status_code=404, detail="File not found")
    return Response(r.content, media_type=r.mime or "application/octet-stream",
                    headers={"Content-Disposition": f'attachment; filename="{r.file_name or "report"}"'})


# ---------------------------------------------------------------------------
# Schedules (report_schedules, report_key "custom")
# ---------------------------------------------------------------------------

def _schedules_q(db: Session, me: PortalUser, report: CustomReport) -> list:
    return [s for s in db.query(ReportSchedule).filter(ReportSchedule.usergroup_id == me.usergroup_id, ReportSchedule.report_key == KEY)
            if (s.params or {}).get("report_id") == str(report.id)]


class ScheduleIn(BaseModel):
    name: Optional[str] = None
    is_active: bool = True
    frequency: str = "monthly"
    send_hour: int = 6
    timezone: Optional[str] = None
    values: Dict[str, Any] = {}          # parameter values except the date range (that follows the frequency)
    file_name: Optional[str] = None
    compress: bool = False
    recipients: List[EmailStr]
    subject: Optional[str] = None
    body: Optional[str] = None

    @field_validator("frequency")
    @classmethod
    def _freq(cls, v):
        if v not in reports_service.FREQUENCIES:
            raise ValueError("Frequency: daily, weekly or monthly")
        return v

    @field_validator("send_hour")
    @classmethod
    def _hour(cls, v):
        if not 0 <= v <= 23:
            raise ValueError("Send hour: 0–23")
        return v

    @field_validator("recipients")
    @classmethod
    def _to(cls, v):
        if not v or len(v) > 20:
            raise ValueError("Add 1–20 recipients")
        return v


def _schedule_out(s: ReportSchedule) -> dict:
    p = s.params or {}
    return {"id": str(s.id), "name": s.name, "is_active": s.is_active, "frequency": s.frequency, "send_hour": s.send_hour,
            "timezone": s.timezone, "values": p.get("values") or {}, "file_name": p.get("file_name"),
            "compress": bool(p.get("compress")), "recipients": s.recipients or [], "subject": p.get("subject"),
            "body": p.get("body"), "next_run_at": s.next_run_at, "last_run_at": s.last_run_at, "last_status": s.last_status}


def _apply_schedule(db: Session, me: PortalUser, s: ReportSchedule, report: CustomReport, data: ScheduleIn) -> None:
    tz = data.timezone or str(_tz(db, me.usergroup_id))
    try:
        ZoneInfo(tz)
    except Exception:
        raise HTTPException(status_code=400, detail="Unknown timezone")
    values = {k: v for k, v in data.values.items() if k in cr.PARAMETERS or k == "filters"}
    try:
        cr.check_values(report, {**values, "date_range": True})
    except cr.ReportError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    s.report_key, s.name, s.frequency, s.send_hour, s.timezone = KEY, data.name or report.title, data.frequency, data.send_hour, tz
    s.file_format = (report.file or {}).get("format") or "xlsx"
    s.recipients = [str(r).lower() for r in data.recipients]
    s.params = {"report_id": str(report.id), "values": values, "file_name": data.file_name, "compress": data.compress,
                "subject": (data.subject or "").strip() or None, "body": (data.body or "").strip() or None}
    s.is_active = data.is_active
    s.next_run_at = reports_service.next_run(data.frequency, data.send_hour, tz, datetime.now(timezone.utc))


@router.get("/{rid}/schedules")
def schedules(rid: str, request: Request, db: Session = Depends(get_db)):
    me, _ = _me(request, db)
    return [_schedule_out(s) for s in _schedules_q(db, me, _own(db, me, rid))]


@router.post("/{rid}/schedules", status_code=201)
def create_schedule(rid: str, data: ScheduleIn, request: Request, db: Session = Depends(get_db)):
    me, _ = _me(request, db, "reports.schedule")
    report = _own(db, me, rid)
    s = ReportSchedule(usergroup_id=me.usergroup_id, created_by=me.id)
    _apply_schedule(db, me, s, report, data)
    db.add(s)
    db.commit()
    return _schedule_out(s)


@router.put("/{rid}/schedules/{sid}")
def update_schedule(rid: str, sid: str, data: ScheduleIn, request: Request, db: Session = Depends(get_db)):
    me, _ = _me(request, db, "reports.schedule")
    report = _own(db, me, rid)
    s = next((x for x in _schedules_q(db, me, report) if str(x.id) == sid), None)
    if not s:
        raise HTTPException(status_code=404, detail="Schedule not found")
    _apply_schedule(db, me, s, report, data)
    db.commit()
    return _schedule_out(s)


@router.delete("/{rid}/schedules/{sid}", status_code=204)
def delete_schedule(rid: str, sid: str, request: Request, db: Session = Depends(get_db)):
    me, _ = _me(request, db, "reports.schedule")
    report = _own(db, me, rid)
    s = next((x for x in _schedules_q(db, me, report) if str(x.id) == sid), None)
    if s:
        db.delete(s)
        db.commit()
