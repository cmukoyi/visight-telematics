"""Customer portal — Reports → Analytics (pages of visuals) and Expressions.

Mounted under /api/portal; scoped to the caller's user group and the vehicles
they may see. Viewing needs reports.view; changing pages or expressions needs
analytics.manage.
"""
from datetime import datetime, timedelta, timezone
from typing import List, Optional
from uuid import UUID
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, field_validator
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import AnalyticsExpression, AnalyticsPage, PortalUser, UserGroup
from app.routes_portal import get_portal_user_from_request
from app.services import access_service
from app.services import analytics_service as an

router = APIRouter(prefix="/api/portal/analytics", tags=["portal-analytics"])

VISUAL_TYPES = {"kpi", "table", "column", "bar", "stacked", "line", "area", "pie", "donut", "text"}
DATE_PRESETS = {"today", "yesterday", "last_7_days", "this_week", "last_week", "this_month", "last_month", "last_30_days",
                "last_90_days", "this_year"}


def _me(request: Request, db: Session, manage: bool = False):
    me = get_portal_user_from_request(request, db)
    access = access_service.for_user(me, db)
    access.require("reports.view")
    if manage:
        access.require("analytics.manage")
    return me, access


def _uuid(value: str, what: str) -> UUID:
    try:
        return UUID(value)
    except ValueError:
        raise HTTPException(status_code=404, detail=f"{what} not found")


def _tz(db: Session, group_id) -> ZoneInfo:
    group = db.get(UserGroup, group_id)
    try:
        return ZoneInfo((group.timezone if group else None) or "Africa/Johannesburg")
    except Exception:
        return ZoneInfo("UTC")


def _expressions(db: Session, group_id) -> dict:
    return {str(e.id): (e.name, e.expression, e.decimals, e.unit)
            for e in db.query(AnalyticsExpression).filter(AnalyticsExpression.usergroup_id == group_id)}


def ensure_defaults(db: Session, group_id, user_id=None) -> None:
    """Give a user group the starting expressions and pages the first time it opens Analytics,
    and the fleet dashboards (scores, costs, utilisation) once."""
    if db.query(AnalyticsPage.id).filter(AnalyticsPage.usergroup_id == group_id).first():
        _ensure_fleet_dashboards(db, group_id, user_id)
        return
    have = {e.name: e for e in db.query(AnalyticsExpression).filter(AnalyticsExpression.usergroup_id == group_id)}
    for name, category, expression, description, unit, decimals in an.DEFAULT_EXPRESSIONS:
        if name not in have:
            have[name] = AnalyticsExpression(usergroup_id=group_id, name=name, category=category, expression=expression,
                                             description=description or None, unit=unit or None, decimals=decimals,
                                             created_by=user_id)
            db.add(have[name])
    db.flush()
    ids = {name: f"expr:{e.id}" for name, e in have.items()}
    for i, (name, preset, visuals) in enumerate(an.default_pages(ids)):
        db.add(AnalyticsPage(usergroup_id=group_id, name=name, position=i, date_preset=preset, visuals=visuals,
                             created_by=user_id))
    db.commit()
    _ensure_fleet_dashboards(db, group_id, user_id)


FLEET_SEED = "fleet_dashboards_v1"
BREAKDOWN_SEED = "breakdown_dashboard_v1"


def _ensure_fleet_dashboards(db: Session, group_id, user_id=None) -> None:
    """Add the score / KPI expressions (missing ones, by name) and the three fleet pages, once per group;
    and the breakdowns page, once."""
    from app.services import fleet_settings_service
    seeded = fleet_settings_service.seeded(db, group_id)
    if BREAKDOWN_SEED not in seeded:
        names = {n for (n,) in db.query(AnalyticsPage.name).filter(AnalyticsPage.usergroup_id == group_id)}
        last = db.query(func.max(AnalyticsPage.position)).filter(AnalyticsPage.usergroup_id == group_id).scalar()
        for name, preset, visuals in an.breakdown_pages():
            if name not in names:
                db.add(AnalyticsPage(usergroup_id=group_id, name=name, position=(last or 0) + 1, date_preset=preset,
                                     visuals=visuals, created_by=user_id))
        fleet_settings_service.mark_seeded(db, group_id, BREAKDOWN_SEED)
        db.commit()
    if FLEET_SEED in seeded:
        return
    have = {e.name: e for e in db.query(AnalyticsExpression).filter(AnalyticsExpression.usergroup_id == group_id)}
    for name, category, expression, description, unit, decimals in an.FLEET_EXPRESSIONS:
        if name not in have:
            have[name] = AnalyticsExpression(usergroup_id=group_id, name=name, category=category, expression=expression,
                                             description=description or None, unit=unit or None, decimals=decimals,
                                             created_by=user_id)
            db.add(have[name])
    db.flush()
    ids = {name: f"expr:{e.id}" for name, e in have.items()}
    names = {n for (n,) in db.query(AnalyticsPage.name).filter(AnalyticsPage.usergroup_id == group_id)}
    for i, (name, preset, visuals) in enumerate(an.fleet_pages(ids)):
        if name not in names:
            db.add(AnalyticsPage(usergroup_id=group_id, name=name, position=-3 + i,   # first in the list
                                 date_preset=preset, visuals=visuals, created_by=user_id))
    fleet_settings_service.mark_seeded(db, group_id, FLEET_SEED)
    db.commit()


# ---------------------------------------------------------------------------
# Catalogue and query
# ---------------------------------------------------------------------------

@router.get("/catalog")
def catalog(request: Request, db: Session = Depends(get_db)):
    """Measures, dimensions, visual types and the group's expressions, for the visual editor."""
    me, _ = _me(request, db)
    exprs = db.query(AnalyticsExpression).filter(AnalyticsExpression.usergroup_id == me.usergroup_id).order_by(AnalyticsExpression.name).all()
    return {
        "measures": [{"key": k, "label": l, "unit": u, "category": c, "decimals": d, "scope": an.SCOPE[k],
                      "additive": k not in an.NOT_ADDITIVE} for k, (l, u, c, d) in an.MEASURES.items()],
        "expressions": [_expr_out(e) for e in exprs],
        "dimensions": [{"key": k, "label": l, "kind": an.DIM_KIND[k], "measures": an.allowed_measures(k)}
                       for k, l in an.DIMENSIONS.items()],
    }


class QueryIn(BaseModel):
    date_from: datetime
    date_to: datetime
    dimension: str = ""
    measures: List[str]
    category: Optional[str] = None
    imei: Optional[str] = None
    place_id: Optional[str] = None
    sort: Optional[str] = None
    descending: bool = True
    limit: Optional[int] = None

    @field_validator("measures")
    @classmethod
    def _measures(cls, v):
        if not v:
            raise ValueError("Choose at least one value")
        if len(v) > 12:
            raise ValueError("At most 12 values in one visual")
        return v


@router.post("/query")
def run_query(data: QueryIn, request: Request, db: Session = Depends(get_db)):
    me, access = _me(request, db)
    start = data.date_from if data.date_from.tzinfo else data.date_from.replace(tzinfo=timezone.utc)
    end = data.date_to if data.date_to.tzinfo else data.date_to.replace(tzinfo=timezone.utc)
    if end <= start:
        raise HTTPException(status_code=400, detail="The period ends before it starts")
    if end - start > timedelta(days=400):
        raise HTTPException(status_code=400, detail="Choose a period of at most a year")
    devices = an.devices_for(db, me.usergroup_id, access.visible_imeis(db), data.category, data.imei)
    try:
        return an.query(db, me.usergroup_id, devices, start, end, _tz(db, me.usergroup_id), dimension=data.dimension,
                        measures=data.measures, expressions=_expressions(db, me.usergroup_id), sort=data.sort,
                        descending=data.descending, limit=max(1, min(data.limit, 500)) if data.limit else None,
                        place_id=str(_uuid(data.place_id, "Place")) if data.place_id else None)
    except an.ExpressionError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


class ExportIn(QueryIn):
    title: str = "Analytics"
    format: str = "xlsx"

    @field_validator("format")
    @classmethod
    def _format(cls, v):
        if v not in ("xlsx", "csv", "pdf"):
            raise ValueError("format must be xlsx, csv or pdf")
        return v


@router.post("/export")
def export(data: ExportIn, request: Request, db: Session = Depends(get_db)):
    """A visual's data as an XLSX, CSV or PDF file (with the group's report logo)."""
    from fastapi.responses import Response
    from app.models import UserGroup
    from app.services import reports_service
    result = run_query(data, request, db)
    me, _ = _me(request, db)
    group = db.get(UserGroup, me.usergroup_id)
    tz = _tz(db, me.usergroup_id)
    cols, rows = reports_service.result_table(result)
    period = f"{data.date_from.astimezone(tz):%d %b %Y} – {(data.date_to - timedelta(seconds=1)).astimezone(tz):%d %b %Y}"
    filters = " · ".join(x for x in (data.category, ) if x)
    content, mime, ext = reports_service.to_file(data.title[:120] or "Analytics", cols, rows, data.format,
                                                 subtitle=" · ".join(x for x in (group.name if group else "", period, filters) if x),
                                                 logo=group.report_logo_data if group else None)
    name = "".join(ch if ch.isalnum() or ch in " -_" else "_" for ch in (data.title or "analytics")).strip().replace(" ", "_")
    return Response(content, media_type=mime, headers={"Content-Disposition": f'attachment; filename="{name or "analytics"}.{ext}"'})


# ---------------------------------------------------------------------------
# Expressions
# ---------------------------------------------------------------------------

class ExpressionIn(BaseModel):
    name: str
    category: Optional[str] = None
    expression: str
    description: Optional[str] = None
    unit: Optional[str] = None
    decimals: int = 2

    @field_validator("name")
    @classmethod
    def _name(cls, v):
        v = v.strip()
        if not v or len(v) > 120:
            raise ValueError("Enter a name (up to 120 characters)")
        return v

    @field_validator("decimals")
    @classmethod
    def _decimals(cls, v):
        return max(0, min(v, 4))


def _expr_out(e: AnalyticsExpression) -> dict:
    try:
        uses, additive = sorted(an.measures_used(e.expression)), an.expression_additive(e.expression)
    except an.ExpressionError:
        uses, additive = [], False
    return {"id": str(e.id), "key": f"expr:{e.id}", "name": e.name, "category": e.category, "expression": e.expression,
            "description": e.description, "unit": e.unit, "decimals": e.decimals, "uses": uses, "additive": additive}


def _check_expression(text: str) -> None:
    try:
        an.parse(text)
    except an.ExpressionError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


def _own_expr(db: Session, me: PortalUser, expr_id: str) -> AnalyticsExpression:
    e = db.query(AnalyticsExpression).filter(AnalyticsExpression.id == _uuid(expr_id, "Expression"),
                                             AnalyticsExpression.usergroup_id == me.usergroup_id).first()
    if not e:
        raise HTTPException(status_code=404, detail="Expression not found")
    return e


def _unique_name(db: Session, me: PortalUser, name: str, exclude=None):
    q = db.query(AnalyticsExpression).filter(AnalyticsExpression.usergroup_id == me.usergroup_id,
                                             func.lower(AnalyticsExpression.name) == name.lower())
    if exclude is not None:
        q = q.filter(AnalyticsExpression.id != exclude)
    if q.first():
        raise HTTPException(status_code=409, detail=f"An expression called '{name}' already exists")


def _apply_expr(e: AnalyticsExpression, data: ExpressionIn) -> None:
    e.name, e.expression, e.decimals = data.name, data.expression.strip(), data.decimals
    e.category = (data.category or "").strip()[:60] or None
    e.description = (data.description or "").strip()[:255] or None
    e.unit = (data.unit or "").strip()[:20] or None


@router.get("/expressions")
def list_expressions(request: Request, db: Session = Depends(get_db)):
    me, _ = _me(request, db)
    ensure_defaults(db, me.usergroup_id, me.id)
    rows = db.query(AnalyticsExpression).filter(AnalyticsExpression.usergroup_id == me.usergroup_id).order_by(AnalyticsExpression.name).all()
    used = _expression_use(db, me.usergroup_id)
    return [{**_expr_out(e), "used_in": used.get(f"expr:{e.id}", [])} for e in rows]


def _expression_use(db: Session, group_id) -> dict:
    """{"expr:<id>": ["Page · Visual", ...]}"""
    out = {}
    for page in db.query(AnalyticsPage).filter(AnalyticsPage.usergroup_id == group_id, AnalyticsPage.deleted_at.is_(None)):
        for v in page.visuals or []:
            for m in v.get("measures") or []:
                if m.startswith("expr:"):
                    out.setdefault(m, []).append(f"{page.name} · {v.get('title') or 'Untitled'}")
    from app.models_reports import CustomReport
    for r in db.query(CustomReport).filter(CustomReport.usergroup_id == group_id):
        for c in r.columns or []:
            if str(c.get("key", "")).startswith("expr:"):
                out.setdefault(c["key"], []).append(f"Custom report · {r.title}")
    return out


class ExpressionTest(BaseModel):
    expression: str
    date_from: datetime
    date_to: datetime


@router.post("/expressions/test")
def test_expression(data: ExpressionTest, request: Request, db: Session = Depends(get_db)):
    """The expression's value for the whole fleet over a period, to check it while writing it."""
    me, access = _me(request, db)
    _check_expression(data.expression)
    devices = an.devices_for(db, me.usergroup_id, access.visible_imeis(db))
    result = an.query(db, me.usergroup_id, devices, data.date_from, data.date_to, _tz(db, me.usergroup_id),
                      measures=["expr:test"], expressions={"test": ("Test", data.expression, 4, "")})
    used = sorted(an.measures_used(data.expression))
    totals = an.query(db, me.usergroup_id, devices, data.date_from, data.date_to, _tz(db, me.usergroup_id), measures=used) if used else None
    return {"value": result["rows"][0]["values"]["expr:test"] if result["rows"] else None,
            "measures": {m: totals["rows"][0]["values"][m] for m in used} if totals and totals["rows"] else {}}


@router.post("/expressions", status_code=201)
def create_expression(data: ExpressionIn, request: Request, db: Session = Depends(get_db)):
    me, _ = _me(request, db, manage=True)
    _check_expression(data.expression)
    _unique_name(db, me, data.name)
    e = AnalyticsExpression(usergroup_id=me.usergroup_id, created_by=me.id)
    _apply_expr(e, data)
    db.add(e)
    db.commit()
    return _expr_out(e)


@router.put("/expressions/{expr_id}")
def update_expression(expr_id: str, data: ExpressionIn, request: Request, db: Session = Depends(get_db)):
    me, _ = _me(request, db, manage=True)
    e = _own_expr(db, me, expr_id)
    _check_expression(data.expression)
    _unique_name(db, me, data.name, exclude=e.id)
    _apply_expr(e, data)
    db.commit()
    return _expr_out(e)


@router.delete("/expressions/{expr_id}", status_code=204)
def delete_expression(expr_id: str, request: Request, db: Session = Depends(get_db)):
    me, _ = _me(request, db, manage=True)
    e = _own_expr(db, me, expr_id)
    used = _expression_use(db, me.usergroup_id).get(f"expr:{e.id}")
    if used:
        raise HTTPException(status_code=409, detail=f"Used in {', '.join(used[:3])} — remove it from those visuals first")
    db.delete(e)
    db.commit()


# ---------------------------------------------------------------------------
# Pages
# ---------------------------------------------------------------------------

class VisualIn(BaseModel):
    id: str
    type: str
    title: str = ""
    dimension: str = ""
    measures: List[str] = []
    width: int = 6
    height: str = "m"
    sort: Optional[str] = None
    descending: bool = True
    limit: Optional[int] = None
    category: Optional[str] = None
    imei: Optional[str] = None
    place_id: Optional[str] = None
    text: Optional[str] = None
    show_values: bool = False

    @field_validator("type")
    @classmethod
    def _type(cls, v):
        if v not in VISUAL_TYPES:
            raise ValueError("Unknown visual type")
        return v

    @field_validator("dimension")
    @classmethod
    def _dim(cls, v):
        if v not in an.DIMENSIONS:
            raise ValueError("Unknown dimension")
        return v

    @field_validator("width")
    @classmethod
    def _width(cls, v):
        return max(2, min(v, 12))

    @field_validator("height")
    @classmethod
    def _height(cls, v):
        return v if v in ("s", "m", "l") else "m"


class PageIn(BaseModel):
    name: str
    date_preset: str = "this_month"
    visuals: List[VisualIn] = []

    @field_validator("name")
    @classmethod
    def _name(cls, v):
        v = v.strip()
        if not v or len(v) > 120:
            raise ValueError("Enter a page name (up to 120 characters)")
        return v

    @field_validator("date_preset")
    @classmethod
    def _preset(cls, v):
        return v if v in DATE_PRESETS else "this_month"

    @field_validator("visuals")
    @classmethod
    def _visuals(cls, v):
        if len(v) > 40:
            raise ValueError("At most 40 visuals on a page")
        return v


def _page_out(p: AnalyticsPage) -> dict:
    return {"id": str(p.id), "name": p.name, "position": p.position, "date_preset": p.date_preset,
            "visuals": p.visuals or [], "updated_at": p.updated_at or p.created_at}


def _own_page(db: Session, me: PortalUser, page_id: str) -> AnalyticsPage:
    p = db.query(AnalyticsPage).filter(AnalyticsPage.id == _uuid(page_id, "Page"), AnalyticsPage.deleted_at.is_(None),
                                       AnalyticsPage.usergroup_id == me.usergroup_id).first()
    if not p:
        raise HTTPException(status_code=404, detail="Page not found")
    return p


def _check_visual_measures(db: Session, me: PortalUser, data: PageIn) -> None:
    exprs = _expressions(db, me.usergroup_id)
    for v in data.visuals:
        for m in v.measures:
            if m.startswith("expr:") and m[5:] not in exprs:
                raise HTTPException(status_code=400, detail=f"“{v.title or 'A visual'}” uses an expression that no longer exists")
            if not m.startswith("expr:") and m not in an.MEASURES:
                raise HTTPException(status_code=400, detail=f"Unknown measure {m}")
        if v.type != "text" and not v.measures:
            raise HTTPException(status_code=400, detail=f"“{v.title or 'A visual'}” needs at least one value")
        try:
            an.check_visual(v.type, v.dimension, v.measures, exprs)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=f"“{v.title or 'A visual'}”: {exc}")


@router.get("/pages")
def list_pages(request: Request, db: Session = Depends(get_db)):
    me, _ = _me(request, db)
    ensure_defaults(db, me.usergroup_id, me.id)
    rows = (db.query(AnalyticsPage).filter(AnalyticsPage.usergroup_id == me.usergroup_id, AnalyticsPage.deleted_at.is_(None))
            .order_by(AnalyticsPage.position, AnalyticsPage.name).all())
    return [_page_out(p) for p in rows]


@router.post("/pages", status_code=201)
def create_page(data: PageIn, request: Request, db: Session = Depends(get_db)):
    me, _ = _me(request, db, manage=True)
    _check_visual_measures(db, me, data)
    last = db.query(func.max(AnalyticsPage.position)).filter(AnalyticsPage.usergroup_id == me.usergroup_id).scalar()
    p = AnalyticsPage(usergroup_id=me.usergroup_id, name=data.name, date_preset=data.date_preset,
                      visuals=[v.model_dump() for v in data.visuals], position=(last or 0) + 1, created_by=me.id)
    db.add(p)
    db.commit()
    return _page_out(p)


@router.put("/pages/{page_id}")
def update_page(page_id: str, data: PageIn, request: Request, db: Session = Depends(get_db)):
    me, _ = _me(request, db, manage=True)
    p = _own_page(db, me, page_id)
    _check_visual_measures(db, me, data)
    p.name, p.date_preset, p.visuals = data.name, data.date_preset, [v.model_dump() for v in data.visuals]
    db.commit()
    return _page_out(p)


@router.delete("/pages/{page_id}", status_code=204)
def delete_page(page_id: str, request: Request, db: Session = Depends(get_db)):
    """Move the page to Recently deleted (restorable for KEEP_DELETED_DAYS)."""
    me, _ = _me(request, db, manage=True)
    _own_page(db, me, page_id).deleted_at = datetime.now(timezone.utc)
    db.commit()


# ---------------------------------------------------------------------------
# Getting things back: recently deleted pages, starting pages (templates), starting expressions
# ---------------------------------------------------------------------------

KEEP_DELETED_DAYS = 30


@router.get("/pages-deleted")
def deleted_pages(request: Request, db: Session = Depends(get_db)):
    me, _ = _me(request, db)
    cutoff = datetime.now(timezone.utc) - timedelta(days=KEEP_DELETED_DAYS)
    db.query(AnalyticsPage).filter(AnalyticsPage.usergroup_id == me.usergroup_id,
                                   AnalyticsPage.deleted_at < cutoff).delete(synchronize_session=False)
    db.commit()
    rows = (db.query(AnalyticsPage).filter(AnalyticsPage.usergroup_id == me.usergroup_id, AnalyticsPage.deleted_at.isnot(None))
            .order_by(AnalyticsPage.deleted_at.desc()).all())
    return [{**_page_out(p), "deleted_at": p.deleted_at,
             "purge_at": p.deleted_at + timedelta(days=KEEP_DELETED_DAYS)} for p in rows]


@router.post("/pages/{page_id}/restore")
def restore_page(page_id: str, request: Request, db: Session = Depends(get_db)):
    me, _ = _me(request, db, manage=True)
    p = db.query(AnalyticsPage).filter(AnalyticsPage.id == _uuid(page_id, "Page"), AnalyticsPage.usergroup_id == me.usergroup_id,
                                       AnalyticsPage.deleted_at.isnot(None)).first()
    if not p:
        raise HTTPException(status_code=404, detail="Page not found in Recently deleted")
    missing = [m for v in p.visuals or [] for m in v.get("measures") or []
               if m.startswith("expr:") and m[5:] not in _expressions(db, me.usergroup_id)]
    p.deleted_at = None
    if missing:   # an expression it used has gone since: keep the page, drop the values that can't work
        p.visuals = [{**v, "measures": [m for m in v.get("measures") or [] if m not in missing]} for v in p.visuals]
    last = db.query(func.max(AnalyticsPage.position)).filter(AnalyticsPage.usergroup_id == me.usergroup_id,
                                                             AnalyticsPage.deleted_at.is_(None)).scalar()
    p.position = (last or 0) + 1
    db.commit()
    return {**_page_out(p), "dropped_values": len(missing)}


@router.delete("/pages/{page_id}/permanent", status_code=204)
def delete_page_permanently(page_id: str, request: Request, db: Session = Depends(get_db)):
    me, _ = _me(request, db, manage=True)
    db.query(AnalyticsPage).filter(AnalyticsPage.id == _uuid(page_id, "Page"), AnalyticsPage.usergroup_id == me.usergroup_id,
                                   AnalyticsPage.deleted_at.isnot(None)).delete(synchronize_session=False)
    db.commit()


def _all_starting_expressions() -> list:
    return list(an.DEFAULT_EXPRESSIONS) + list(an.FLEET_EXPRESSIONS)


def _ensure_expressions(db: Session, group_id, user_id=None) -> tuple:
    """Add any starting expression the group no longer has (matched by name). ({name: "expr:<id>"}, added count)"""
    have = {e.name: e for e in db.query(AnalyticsExpression).filter(AnalyticsExpression.usergroup_id == group_id)}
    added = 0
    for name, category, expression, description, unit, decimals in _all_starting_expressions():
        if name not in have:
            have[name] = AnalyticsExpression(usergroup_id=group_id, name=name, category=category, expression=expression,
                                             description=description or None, unit=unit or None, decimals=decimals,
                                             created_by=user_id)
            db.add(have[name])
            added += 1
    db.flush()
    return {name: f"expr:{e.id}" for name, e in have.items()}, added


def _templates(ids: dict) -> list:
    """[(key, name, preset, visuals)] — every starting page."""
    import re
    pages = list(an.fleet_pages(ids)) + list(an.default_pages(ids)) + list(an.breakdown_pages())
    return [(re.sub(r"[^a-z0-9]+", "_", name.lower()).strip("_"), name, preset, visuals) for name, preset, visuals in pages]


@router.get("/templates")
def templates(request: Request, db: Session = Depends(get_db)):
    """The starting pages, to add again at any time."""
    _me(request, db)
    dummy = {name: "expr:x" for name, *_ in _all_starting_expressions()}
    descriptions = {
        "fleet_dashboard": "TCO, distance, speeding, idling, after hours, driving scores, top and worst drivers, vehicles",
        "fleet_cost": "Monthly fleet cost by category, cost by vehicle group",
        "utilisation_and_availability": "Vehicles and drivers used and available, exceptions per hour",
        "fleet_overview": "Trips, distance, driving time and vehicles",
        "driver_behaviour": "Exceptions per 100 km, speeding and harsh driving by week and driver",
        "utilisation": "Utilisation and downtime, trips by hour, distance by weekday",
        "breakdowns_and_downtime": "Breakdowns logged in the mobile app: downtime per month, by cause, vehicle and driver",
    }
    return [{"key": key, "name": name, "date_preset": preset, "visuals": len(visuals), "description": descriptions.get(key, "")}
            for key, name, preset, visuals in _templates(dummy)]


class TemplateIn(BaseModel):
    key: str


@router.post("/pages/from-template", status_code=201)
def page_from_template(data: TemplateIn, request: Request, db: Session = Depends(get_db)):
    """Add a starting page again (with any expressions it needs that were deleted)."""
    me, _ = _me(request, db, manage=True)
    ids, _ = _ensure_expressions(db, me.usergroup_id, me.id)
    found = next((t for t in _templates(ids) if t[0] == data.key), None)
    if not found:
        raise HTTPException(status_code=404, detail="Unknown template")
    _, name, preset, visuals = found
    taken = {n for (n,) in db.query(AnalyticsPage.name).filter(AnalyticsPage.usergroup_id == me.usergroup_id,
                                                              AnalyticsPage.deleted_at.is_(None))}
    title, n = name, 2
    while title in taken:
        title, n = f"{name} ({n})", n + 1
    last = db.query(func.max(AnalyticsPage.position)).filter(AnalyticsPage.usergroup_id == me.usergroup_id).scalar()
    p = AnalyticsPage(usergroup_id=me.usergroup_id, name=title, date_preset=preset, visuals=visuals,
                      position=(last or 0) + 1, created_by=me.id)
    db.add(p)
    db.commit()
    return _page_out(p)


@router.post("/expressions/restore")
def restore_expressions(request: Request, db: Session = Depends(get_db)):
    """Add back any starting expression (scores, CPK, utilisation …) that was deleted."""
    me, _ = _me(request, db, manage=True)
    _, added = _ensure_expressions(db, me.usergroup_id, me.id)
    db.commit()
    return {"added": added}
