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
    """Give a user group the starting expressions and pages the first time it opens Analytics."""
    if db.query(AnalyticsPage.id).filter(AnalyticsPage.usergroup_id == group_id).first():
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


# ---------------------------------------------------------------------------
# Catalogue and query
# ---------------------------------------------------------------------------

@router.get("/catalog")
def catalog(request: Request, db: Session = Depends(get_db)):
    """Measures, dimensions, visual types and the group's expressions, for the visual editor."""
    me, _ = _me(request, db)
    exprs = db.query(AnalyticsExpression).filter(AnalyticsExpression.usergroup_id == me.usergroup_id).order_by(AnalyticsExpression.name).all()
    return {
        "measures": [{"key": k, "label": l, "unit": u, "category": c, "decimals": d} for k, (l, u, c, d) in an.MEASURES.items()],
        "expressions": [_expr_out(e) for e in exprs],
        "dimensions": [{"key": k, "label": l} for k, l in an.DIMENSIONS.items()],
    }


class QueryIn(BaseModel):
    date_from: datetime
    date_to: datetime
    dimension: str = ""
    measures: List[str]
    category: Optional[str] = None
    imei: Optional[str] = None
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
                        descending=data.descending, limit=max(1, min(data.limit, 500)) if data.limit else None)
    except an.ExpressionError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


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
    return {"id": str(e.id), "key": f"expr:{e.id}", "name": e.name, "category": e.category, "expression": e.expression,
            "description": e.description, "unit": e.unit, "decimals": e.decimals}


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
    for page in db.query(AnalyticsPage).filter(AnalyticsPage.usergroup_id == group_id):
        for v in page.visuals or []:
            for m in v.get("measures") or []:
                if m.startswith("expr:"):
                    out.setdefault(m, []).append(f"{page.name} · {v.get('title') or 'Untitled'}")
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
    p = db.query(AnalyticsPage).filter(AnalyticsPage.id == _uuid(page_id, "Page"),
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


@router.get("/pages")
def list_pages(request: Request, db: Session = Depends(get_db)):
    me, _ = _me(request, db)
    ensure_defaults(db, me.usergroup_id, me.id)
    rows = db.query(AnalyticsPage).filter(AnalyticsPage.usergroup_id == me.usergroup_id).order_by(AnalyticsPage.position, AnalyticsPage.name).all()
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
    me, _ = _me(request, db, manage=True)
    db.delete(_own_page(db, me, page_id))
    db.commit()
