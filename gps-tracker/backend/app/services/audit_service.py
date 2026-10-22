"""Customer-portal audit trail — who changed what in their user group, and when.

AuditMiddleware records every successful (and every refused) change made
through /api/portal — adding a user, editing a role, deleting a vehicle,
arming a place — without each endpoint having to remember to log. Sign-ins
are recorded by the login endpoint (record()). Entries are read in
Configuration → Security → Audit Trail (audit.view) and, per user group, in
the admin portal.
"""
import json
import logging
import re
from typing import Optional

from starlette.concurrency import run_in_threadpool

logger = logging.getLogger(__name__)

MUTATING = {"POST", "PUT", "PATCH", "DELETE"}
_VERB = {"POST": "Added", "PUT": "Updated", "PATCH": "Updated", "DELETE": "Deleted"}
_MAX_BODY = 64 * 1024

# (path pattern under /api/portal, area, noun, {method: verb override}); None area = not audited
ROUTES = [
    (r"/login|/auth/.*|/alerts/.*", None, None, {}),
    (r"/users/(?P<id>[^/]+)/reset-password", "Users", "user", {"POST": "Reset password"}),
    (r"/users(?:/(?P<id>[^/]+))?", "Users", "user", {}),
    (r"/roles(?:/(?P<id>[^/]+))?", "Roles", "role", {}),
    (r"/security-groups(?:/(?P<id>[^/]+))?", "Security groups", "security group", {}),
    (r"/tags", "Vehicles", "vehicles", {"DELETE": "Deleted"}),
    (r"/tags/(?P<id>[^/]+)", "Vehicles", "vehicle", {}),
    (r"/categories(?:/(?P<id>[^/]+))?", "Vehicle groups", "vehicle group", {}),
    (r"/locations/bulk-upload", "Places", "places", {"POST": "Imported"}),
    (r"/locations/(?P<id>[^/]+)/arm/(?P<tag>[^/]+)", "Places", "place", {"POST": "Armed", "DELETE": "Disarmed"}),
    (r"/locations(?:/(?P<id>[^/]+))?", "Places", "place", {}),
    (r"/place-groups(?:/(?P<id>[^/]+))?", "Place groups", "place group", {}),
    (r"/notification-rules(?:/(?P<id>[^/]+))?", "Notification rules", "rule", {}),
    (r"/event-type-list/(?P<id>[^/]+)", "Event types", "event type", {"PUT": "Renamed"}),
    (r"/event-type-groups(?:/(?P<id>[^/]+))?", "Event type groups", "event type group", {}),
    (r"/report-schedules/(?P<id>[^/]+)/send-now", "Reports", "scheduled report", {"POST": "Sent"}),
    (r"/report-schedules(?:/(?P<id>[^/]+))?", "Reports", "scheduled report", {}),
    (r"/theme", "Theme and settings", "user group settings", {}),
    (r"/data-exchange/link", "Data Exchange", "Data Exchange", {"POST": "Linked"}),
    (r"/notifications", "My account", "notification preferences", {}),
    (r"/account/change-password", "My account", "password", {"POST": "Changed"}),
    (r"/account/change-email", "My account", "email address", {"POST": "Changed"}),
]
_COMPILED = [(re.compile(rf"^{p}/?$"), area, noun, verbs) for p, area, noun, verbs in ROUTES]
AREAS = sorted({area for _, area, _, _ in ROUTES if area})


def describe(method: str, path: str) -> Optional[dict]:
    """What a portal request changes, or None when it isn't audited. path is relative to /api/portal."""
    for rx, area, noun, verbs in _COMPILED:
        m = rx.match(path)
        if m:
            if area is None:
                return None
            ids = m.groupdict()
            return {"area": area, "noun": noun, "action": verbs.get(method, _VERB[method]),
                    "id": ids.get("id"), "tag": ids.get("tag")}
    return {"area": "Other", "noun": path, "action": _VERB[method], "id": None, "tag": None}


def _name_of(db, area: str, rid: Optional[str]) -> Optional[str]:
    """The current name of the thing a request points at (looked up before it changes or is deleted)."""
    if not rid:
        return None
    from uuid import UUID
    from app import models
    from app.models_dataprofiler import ReportSchedule
    if area == "Event types":
        from app.dataprofiler.dictionary import EVENTS
        return EVENTS[rid][0] if rid in EVENTS else rid
    table = {
        "Users": (models.PortalUser, lambda o: o.email),
        "Roles": (models.PortalRole, lambda o: o.name),
        "Security groups": (models.SecurityGroup, lambda o: o.name),
        "Vehicles": (models.BLETag, lambda o: o.description or o.device_name or o.imei),
        "Vehicle groups": (models.TagCategory, lambda o: o.name),
        "Places": (models.POI, lambda o: o.name),
        "Place groups": (models.PlaceGroup, lambda o: o.name),
        "Notification rules": (models.NotificationRule, lambda o: o.name),
        "Event type groups": (models.EventTypeGroup, lambda o: o.name),
        "Reports": (ReportSchedule, lambda o: o.name or o.report_key),
    }.get(area)
    if not table:
        return None
    try:
        UUID(str(rid))
        obj = db.get(table[0], rid)
        return table[1](obj) if obj is not None else None
    except Exception:
        db.rollback()
        return None


def _clean(value, depth=0):
    """The request body without passwords or images, with long text cut short."""
    if depth > 4:
        return "…"
    if isinstance(value, dict):
        out = {}
        for k, v in value.items():
            key = str(k).lower()
            if "password" in key or "secret" in key or "token" in key:
                out[k] = "••••"
            elif key.endswith("_data") and isinstance(v, str) and v.startswith("data:"):
                out[k] = "(image)"
            else:
                out[k] = _clean(v, depth + 1)
        return out
    if isinstance(value, list):
        return [_clean(v, depth + 1) for v in value[:50]]
    if isinstance(value, str) and len(value) > 300:
        return value[:300] + "…"
    return value


def _summary(info: dict, name: Optional[str], tag_name: Optional[str]) -> str:
    noun = info["noun"]
    if info["area"] == "Other":
        return f"{info['action']} {noun}"
    text = f"{info['action']} {noun}" + (f" “{name}”" if name else "")
    if tag_name:
        text += f" for “{tag_name}”"
    return text


def record(db, user, action: str, area: str, summary: str, *, resource_id=None, details=None,
           outcome: str = "success", ip: Optional[str] = None) -> None:
    """Add one audit entry for a portal user (does not commit)."""
    from app.models import PortalAuditLog
    db.add(PortalAuditLog(
        usergroup_id=user.usergroup_id, user_id=user.id, user_email=user.email,
        user_name=" ".join(filter(None, [user.first_name, user.last_name])) or None,
        action=action[:30], area=area[:50], summary=summary[:500], resource_id=(str(resource_id)[:100] if resource_id else None),
        details=details, outcome=outcome, ip_address=(ip or None) and ip[:45]))


def _user_from_token(db, token: str):
    from app.models import PortalUser
    from app.routes_portal import _decode_portal_token
    payload = _decode_portal_token(token)
    if not payload:
        return None
    return db.query(PortalUser).filter(PortalUser.id == payload.get("portal_user_id")).first()


class AuditMiddleware:
    """Pure ASGI middleware (the request body still reaches the endpoint untouched)."""

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http" or scope["method"] not in MUTATING or not scope["path"].startswith("/api/portal/"):
            return await self.app(scope, receive, send)
        info = describe(scope["method"], scope["path"][len("/api/portal"):])
        headers = {k.decode().lower(): v.decode() for k, v in scope.get("headers", [])}
        auth = headers.get("authorization", "")
        if info is None or not auth.startswith("Bearer "):
            return await self.app(scope, receive, send)

        before = {}
        try:
            before = await run_in_threadpool(self._before, auth[7:], info)
        except Exception:
            logger.exception("audit: lookup failed")
        if not before.get("user_id"):
            return await self.app(scope, receive, send)

        body = bytearray()
        status = {}

        async def recv():
            msg = await receive()
            if msg["type"] == "http.request" and len(body) < _MAX_BODY:
                body.extend(msg.get("body", b"")[: _MAX_BODY - len(body)])
            return msg

        async def snd(msg):
            if msg["type"] == "http.response.start":
                status["code"] = msg["status"]
            await send(msg)

        try:
            await self.app(scope, recv, snd)
        finally:
            code = status.get("code", 500)
            if 200 <= code < 300 or code == 403:
                ip = (headers.get("x-forwarded-for", "").split(",")[0].strip()
                      or (scope.get("client") or ("",))[0])
                try:
                    await run_in_threadpool(self._write, before, info, bytes(body), code, ip)
                except Exception:
                    logger.exception("audit: write failed")

    @staticmethod
    def _before(token: str, info: dict) -> dict:
        from app.database import SessionLocal
        db = SessionLocal()
        try:
            user = _user_from_token(db, token)
            if user is None:
                return {}
            return {"user_id": user.id, "name": _name_of(db, info["area"], info["id"]),
                    "tag_name": _name_of(db, "Vehicles", info["tag"]) if info.get("tag") else None}
        finally:
            db.close()

    @staticmethod
    def _write(before: dict, info: dict, raw: bytes, code: int, ip: str) -> None:
        from app.database import SessionLocal
        from app.models import PortalUser
        try:
            payload = json.loads(raw) if raw else None
        except Exception:
            payload = None
        name = before.get("name")
        if not name and isinstance(payload, dict):
            name = next((str(payload[k]) for k in ("name", "email", "description", "label", "report_title")
                         if payload.get(k)), None)
        if info["area"] == "Vehicles" and info["id"] is None and isinstance(payload, dict):
            name = f"{len(payload.get('tag_ids') or payload.get('ids') or [])} vehicles"
        summary = _summary(info, name, before.get("tag_name"))
        details = _clean(payload) if isinstance(payload, (dict, list)) else None
        db = SessionLocal()
        try:
            user = db.get(PortalUser, before["user_id"])
            if user is None:
                return
            if code == 403:
                summary = f"Not allowed: {summary[0].lower()}{summary[1:]}"
            record(db, user, info["action"], info["area"], summary, resource_id=info["id"], details=details,
                   outcome="denied" if code == 403 else "success", ip=ip)
            db.commit()
        finally:
            db.close()


def search(db, usergroup_id, *, date_from=None, date_to=None, user_id=None, area=None, outcome=None,
           text=None, limit: int = 500) -> list:
    """Audit entries for one user group, newest first."""
    from sqlalchemy import or_
    from app.models import PortalAuditLog
    q = db.query(PortalAuditLog).filter(PortalAuditLog.usergroup_id == usergroup_id)
    if date_from:
        q = q.filter(PortalAuditLog.created_at >= date_from)
    if date_to:
        q = q.filter(PortalAuditLog.created_at <= date_to)
    if user_id:
        q = q.filter(PortalAuditLog.user_id == user_id)
    if area:
        q = q.filter(PortalAuditLog.area == area)
    if outcome:
        q = q.filter(PortalAuditLog.outcome == outcome)
    if text:
        like = f"%{text.strip()}%"
        q = q.filter(or_(PortalAuditLog.summary.ilike(like), PortalAuditLog.user_email.ilike(like),
                         PortalAuditLog.user_name.ilike(like)))
    rows = q.order_by(PortalAuditLog.created_at.desc()).limit(max(1, min(limit, 5000))).all()
    return [{"id": str(r.id), "created_at": r.created_at, "user_id": str(r.user_id) if r.user_id else None,
             "user_email": r.user_email, "user_name": r.user_name, "action": r.action, "area": r.area,
             "summary": r.summary, "resource_id": r.resource_id, "details": r.details, "outcome": r.outcome,
             "ip_address": r.ip_address} for r in rows]
