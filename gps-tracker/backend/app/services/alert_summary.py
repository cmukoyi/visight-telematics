"""One informative line per Inbox alert: which vehicle (with its registration), what happened, where, and
what's worth knowing next to it, e.g.

  Jeep Compass (DH68DMZN) left Home at 32 km/h after 2h 05m there · 35 Melville Ave, Rosebank
  Jeep Compass (DH68DMZN) broke down (engine) at 12 Van Santen Ave, Sundowner · logged by Sipho Dlamini · resolved after 1h 40m
  Truck 12 (CA 123-456): Minor service overdue · due at 40 000 km, 1 200 km over

Places come from the address cache only (no geocoding while listing), in the group's Location Description Format.
"""
from datetime import date, datetime, timedelta, timezone
from typing import Optional
from uuid import UUID

from sqlalchemy.orm import Session

from app.models import PlaceVisit, PortalAlert


def _utc(dt: Optional[datetime]) -> Optional[datetime]:
    return None if dt is None else (dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc))


def _dur(seconds: float) -> str:
    m = int(seconds // 60)
    if m >= 1440:
        return f"{m // 1440}d {m % 1440 // 60}h"
    return f"{m // 60}h {m % 60:02d}m" if m >= 60 else f"{max(m, 1)} min"


def _num(v) -> Optional[float]:
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def _km(v: float) -> str:
    return f"{v:,.0f}".replace(",", " ") + " km"


def _date(v) -> Optional[str]:
    try:
        return date.fromisoformat(str(v)[:10]).strftime("%d %b %Y")
    except ValueError:
        return None


def _place(where: str) -> str:
    """"at 35 Melville Ave, Rosebank", "near Home", "600 m SE of Home, …"."""
    if where.startswith("Near "):
        return f"near {where[5:]}"
    return where if where[:1].isdigit() and " of " in where.split(",")[0] else f"at {where}"


def summaries(db: Session, group_id, alerts: list) -> dict:
    """{alert id: summary line} for a page of alerts."""
    from app.models_maintenance import VehicleBreakdown
    from app.services.address_service import Describer

    def pos(a):
        m = a.meta_data or {}
        return _num(m.get("latitude")), _num(m.get("longitude"))

    describe = Describer(db, group_id).prefetch(pos(a) for a in alerts)
    # How long the vehicle was at the place, for "left" alerts (the visit that ended at the alert's fix)
    exits = [a for a in alerts if a.alert_type == "geofence_exit" and (a.meta_data or {}).get("recorded_at")]
    visits = {}
    if exits:
        times = [_utc(datetime.fromisoformat(a.meta_data["recorded_at"])) for a in exits]
        for v in (db.query(PlaceVisit).filter(PlaceVisit.usergroup_id == group_id,
                                              PlaceVisit.imei.in_({(a.meta_data or {}).get("imei") for a in exits}),
                                              PlaceVisit.exited_at >= min(times) - timedelta(minutes=5),
                                              PlaceVisit.exited_at <= max(times) + timedelta(minutes=5))):
            visits[(v.imei, str(v.poi_id))] = visits.get((v.imei, str(v.poi_id)), []) + [v]
    breakdowns = {}
    ids = []
    for a in alerts:
        try:
            if a.alert_type == "breakdown" and (a.meta_data or {}).get("breakdown_id"):
                ids.append(UUID(a.meta_data["breakdown_id"]))
        except ValueError:
            pass
    if ids:
        breakdowns = {str(b.id): b for b in db.query(VehicleBreakdown).filter(VehicleBreakdown.id.in_(ids))}

    out = {}
    now = datetime.now(timezone.utc)
    for a in alerts:
        m = a.meta_data or {}
        tag = a.tag
        attrs = (tag.attributes or {}) if tag else {}
        name = (tag.description or tag.device_name or tag.imei) if tag else None
        reg = m.get("registration") if m.get("registration") not in (None, "", "—") else ((attrs.get("registration") or {}).get("value"))
        who = f"{name} ({reg})" if name and reg else (name or "")
        lat, lng = pos(a)
        where = describe(lat, lng) if lat is not None and lng is not None else None
        speed = _num(m.get("speed"))
        at_speed = f" at {speed:.0f} km/h" if speed else ""
        t, parts = a.alert_type, []

        if t in ("geofence_entry", "geofence_exit"):
            place = m.get("poi_name") or "a place"
            if t == "geofence_entry":
                text = f"{who} entered {place}{at_speed}"
            else:
                text = f"{who} left {place}{at_speed}"
                when = _utc(datetime.fromisoformat(m["recorded_at"])) if m.get("recorded_at") else None
                match = [v for v in visits.get((m.get("imei"), m.get("poi_id")), [])
                         if when and v.exited_at and v.entered_at and abs((_utc(v.exited_at) - when).total_seconds()) < 300]
                if match:
                    text += f" after {_dur((_utc(match[0].exited_at) - _utc(match[0].entered_at)).total_seconds())} there"
            if where and place not in where:
                parts.append(where)
        elif t == "breakdown":
            b = breakdowns.get(m.get("breakdown_id"))
            cause = f" ({b.cause.lower()})" if b and b.cause else ""
            text = f"{who} broke down{cause}" + (f" {_place(where)}" if where else "")
            if b:
                if b.reported_by:
                    parts.append(f"logged by {b.reported_by}")
                if b.ended_at:
                    parts.append(f"resolved after {_dur((_utc(b.ended_at) - _utc(b.started_at)).total_seconds())}")
                else:
                    parts.append(f"still broken down ({_dur((now - _utc(b.started_at)).total_seconds())} so far)")
        elif t.startswith("event_"):
            text = f"{who}: {m.get('event_label') or a.title}{at_speed}" + (f" {_place(where)}" if where else "")
        elif t in ("licence_expiring", "licence_expired"):
            ends = _date(m.get("licence_expires"))
            if t == "licence_expired":
                text = f"{who}: vehicle licence expired" + (f" on {ends}" if ends else "")
                parts.append("renew it and update the licence date")
            else:
                left = m.get("days_left")
                text = f"{who}: vehicle licence expires" + (f" on {ends}" if ends else "") + \
                       (f", in {left} day{'s' if left != 1 else ''}" if isinstance(left, int) else "")
        elif t in ("maintenance_due", "maintenance_overdue"):
            what = m.get("schedule") or m.get("type") or "Maintenance"
            text = f"{who}: {what} {'overdue' if t == 'maintenance_overdue' else 'due'}"
            due_km, km_left, due_on, days_left = _num(m.get("due_km")), _num(m.get("km_left")), _date(m.get("due_date")), m.get("days_left")
            if due_km is not None:
                parts.append(f"due at {_km(due_km)}" + (f", {_km(abs(km_left))} {'over' if km_left < 0 else 'to go'}" if km_left is not None else ""))
            if due_on:
                parts.append(f"due on {due_on}" + (f", {abs(days_left)} days {'late' if days_left < 0 else 'to go'}" if isinstance(days_left, int) else ""))
        else:
            title = a.title or t.replace("_", " ").capitalize()
            if name and title.lower().startswith(name.lower()):
                rest = title[len(name):]
                # "Jeep Compass is offline" keeps its grammar; "Jeep Compass: …" keeps the colon
                text = f"{who}{rest}" if rest[:1] == " " else f"{who}: {rest.lstrip(' :·-')}"
            else:
                text = f"{who}: {title}" if who else title
            if where:
                parts.append(_place(where))
        out[str(a.id)] = " · ".join([text.strip(), *parts])
    return out
