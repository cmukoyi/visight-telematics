"""Analytics (Reports → Analytics): measures over the fleet's trips and alerts, by a dimension.

A query asks for some MEASURES (and/or expressions built from them) broken
down by one DIMENSION over a period, for the vehicles the user may see:

    query(db, group_id, devices, start, end, tz, dimension="vehicle",
          measures=["Trip_distance_km", "expr:<id>"])

Trips are attributed to the local day/hour they started in. Expressions are
arithmetic over measures (m.Trip_distance_km / m.Trip_count), parsed safely
(numbers, + - * /, brackets and m.<measure> only) and evaluated per row after
aggregation; dividing by zero gives no value.
"""
import ast
from collections import defaultdict
from datetime import date, datetime, time, timedelta, timezone
from typing import Optional
from zoneinfo import ZoneInfo

from sqlalchemy.orm import Session

from app.models import BLETag, PortalAlert
from app.models_dataprofiler import Trip

NIGHT_START, NIGHT_END = 20, 5          # trips starting 20:00–04:59 local are night trips
BUSINESS_START, BUSINESS_END = 7, 18    # Mon–Fri 07:00–17:59

# key: (label, unit, category, decimals)
MEASURES: dict = {
    "Trip_count":               ("Trip count", "", "Trips", 0),
    "Trip_distance_km":         ("Trip distance", "km", "Trips", 1),
    "Trip_duration_hours":      ("Driving time", "h", "Trips", 1),
    "Max_speed_kmh":            ("Top speed", "km/h", "Trips", 0),
    "Idling_count":             ("Idling events", "", "Trips", 0),
    "Speeding_count":           ("Speeding count", "", "Exceptions", 0),
    "Harsh_braking_count":      ("Harsh braking count", "", "Exceptions", 0),
    "Harsh_acceleration_count": ("Harsh acceleration count", "", "Exceptions", 0),
    "Harsh_cornering_count":    ("Harsh cornering count", "", "Exceptions", 0),
    "Total_exception_count":    ("Total exception count", "", "Exceptions", 0),
    "Night_trip_count":         ("Trips at night", "", "Time of day", 0),
    "Night_distance_km":        ("Distance at night", "km", "Time of day", 1),
    "Night_duration_hours":     ("Driving time at night", "h", "Time of day", 1),
    "Weekend_distance_km":      ("Distance at weekends", "km", "Time of day", 1),
    "Business_hours_distance_km": ("Distance in business hours", "km", "Time of day", 1),
    "Active_vehicle_count":     ("Active vehicles", "", "Utilisation", 0),
    "Vehicle_count":            ("Vehicles", "", "Utilisation", 0),
    "Utilization_days":         ("Vehicle utilisation (days)", "days", "Utilisation", 0),
    "Downtime_days":            ("Vehicle downtime (days)", "days", "Utilisation", 0),
    "Alert_count":              ("Alerts", "", "Alerts", 0),
    "Geofence_entry_count":     ("Place entries", "", "Alerts", 0),
    "Geofence_exit_count":      ("Place exits", "", "Alerts", 0),
}
_SUMS = [k for k in MEASURES if k not in ("Max_speed_kmh", "Active_vehicle_count", "Vehicle_count",
                                          "Utilization_days", "Downtime_days")]

# key: label; "" = one row for everything
DIMENSIONS: dict = {
    "": "Total",
    "vehicle": "Vehicle",
    "vehicle_group": "Vehicle group",
    "driver": "Driver",
    "day": "Day",
    "week": "Week",
    "month": "Month",
    "hour": "Hour of day",
    "weekday": "Day of week",
}
_TIME_DIMS = {"day", "week", "month"}
_WEEKDAYS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]


# ---------------------------------------------------------------------------
# Expressions
# ---------------------------------------------------------------------------

class ExpressionError(ValueError):
    pass


def parse(expression: str) -> ast.Expression:
    """Parse and check an expression; raises ExpressionError with a readable message."""
    text = (expression or "").strip()
    if not text:
        raise ExpressionError("Enter an expression, e.g. m.Trip_distance_km / m.Trip_count")
    if len(text) > 500:
        raise ExpressionError("Keep the expression under 500 characters")
    try:
        tree = ast.parse(text, mode="eval")
    except SyntaxError:
        raise ExpressionError("That isn't a valid expression — check the brackets and operators")
    for node in ast.walk(tree):
        if isinstance(node, (ast.Expression, ast.BinOp, ast.UnaryOp, ast.Add, ast.Sub, ast.Mult, ast.Div,
                             ast.USub, ast.UAdd, ast.Load)):
            continue
        if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)) and not isinstance(node.value, bool):
            continue
        if isinstance(node, ast.Attribute):
            if not (isinstance(node.value, ast.Name) and node.value.id == "m"):
                raise ExpressionError("Measures are written m.<name>, e.g. m.Trip_count")
            if node.attr not in MEASURES:
                raise ExpressionError(f"Unknown measure m.{node.attr}")
            continue
        if isinstance(node, ast.Name) and node.id == "m":
            continue
        raise ExpressionError("Only numbers, + − × ÷, brackets and m.<measure> are allowed")
    return tree


def measures_used(expression: str) -> set:
    return {n.attr for n in ast.walk(parse(expression)) if isinstance(n, ast.Attribute)}


def evaluate(tree: ast.Expression, values: dict) -> Optional[float]:
    """The expression's value for one row of measure values; None when undefined (e.g. ÷ 0)."""
    def ev(node):
        if isinstance(node, ast.Expression):
            return ev(node.body)
        if isinstance(node, ast.Constant):
            return float(node.value)
        if isinstance(node, ast.Attribute):
            v = values.get(node.attr)
            return None if v is None else float(v)
        if isinstance(node, ast.UnaryOp):
            v = ev(node.operand)
            return None if v is None else (-v if isinstance(node.op, ast.USub) else v)
        a, b = ev(node.left), ev(node.right)
        if a is None or b is None:
            return None
        if isinstance(node.op, ast.Add):
            return a + b
        if isinstance(node.op, ast.Sub):
            return a - b
        if isinstance(node.op, ast.Mult):
            return a * b
        return None if b == 0 else a / b
    return ev(tree)


# ---------------------------------------------------------------------------
# Query
# ---------------------------------------------------------------------------

def _utc(dt: datetime) -> datetime:
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def _bucket(dimension: str, local: datetime) -> tuple:
    """(sort key, label) of a local time for a time dimension."""
    d = local.date()
    if dimension == "day":
        return d.isoformat(), d.strftime("%d %b")
    if dimension == "week":
        monday = d - timedelta(days=d.weekday())
        return monday.isoformat(), f"Week of {monday.strftime('%d %b')}"
    if dimension == "month":
        return d.strftime("%Y-%m"), d.strftime("%b %Y")
    if dimension == "hour":
        return f"{local.hour:02d}", f"{local.hour:02d}:00"
    return str(d.weekday()), _WEEKDAYS[d.weekday()]


def _all_buckets(dimension: str, start: datetime, end: datetime, tz: ZoneInfo) -> list:
    """Every bucket in the period (so days without trips still show), as (key, label, days in bucket)."""
    if dimension == "hour":
        return [(f"{h:02d}", f"{h:02d}:00", None) for h in range(24)]
    if dimension == "weekday":
        return [(str(i), _WEEKDAYS[i], None) for i in range(7)]
    first, last = start.astimezone(tz).date(), (end - timedelta(seconds=1)).astimezone(tz).date()
    out, seen, d = [], {}, first
    while d <= last:
        key, label = _bucket(dimension, datetime.combine(d, time(12)))
        if key not in seen:
            seen[key] = len(out)
            out.append([key, label, 0])
        out[seen[key]][2] += 1
        d += timedelta(days=1)
    return [tuple(x) for x in out]


def query(db: Session, group_id, devices: dict, start: datetime, end: datetime, tz: ZoneInfo, *,
          dimension: str = "", measures: list, expressions: Optional[dict] = None,
          sort: Optional[str] = None, descending: bool = True, limit: Optional[int] = None) -> dict:
    """devices: {imei: {"name", "group", "driver"}} the user may see. measures: measure keys and
    "expr:<id>" keys found in `expressions` ({id: (label, expression, decimals, unit)})."""
    if dimension not in DIMENSIONS:
        raise ValueError("Unknown dimension")
    expressions = expressions or {}
    trees = {}
    for key in measures:
        if key.startswith("expr:"):
            if key[5:] not in expressions:
                raise ValueError("Unknown expression")
            trees[key] = parse(expressions[key[5:]][1])
        elif key not in MEASURES:
            raise ValueError(f"Unknown measure {key}")
    period_days = max(1, round((end - start).total_seconds() / 86400))

    def key_of(imei: str, local: datetime) -> tuple:
        info = devices[imei]
        if dimension == "vehicle":
            return imei, info["name"]
        if dimension == "vehicle_group":
            g = info.get("group") or "No group"
            return g, g
        if dimension == "driver":
            d = info.get("driver") or "No driver"
            return d, d
        if dimension in ("day", "week", "month", "hour", "weekday"):
            return _bucket(dimension, local)
        return "all", "Total"

    acc = defaultdict(lambda: defaultdict(float))
    labels = {}
    active = defaultdict(set)
    used_days = defaultdict(set)
    vehicles_in = defaultdict(set)            # which vehicles belong to each row (for downtime)
    imeis = list(devices)
    if imeis:
        trips = (db.query(Trip).filter(Trip.usergroup_id == group_id, Trip.imei.in_(imeis),
                                       Trip.started_at >= start, Trip.started_at < end).all())
    else:
        trips = []
    for t in trips:
        local = _utc(t.started_at).astimezone(tz)
        key, label = key_of(t.imei, local)
        labels[key] = label
        row = acc[key]
        km, hours = (t.distance_m or 0) / 1000, (t.duration_s or 0) / 3600
        exceptions = (t.speeding_count or 0) + (t.harsh_braking_count or 0) + (t.harsh_acceleration_count or 0) \
            + (t.harsh_cornering_count or 0)
        row["Trip_count"] += 1
        row["Trip_distance_km"] += km
        row["Trip_duration_hours"] += hours
        row["Max_speed_kmh"] = max(row["Max_speed_kmh"], t.max_speed or 0)
        row["Idling_count"] += t.idling_count or 0
        row["Speeding_count"] += t.speeding_count or 0
        row["Harsh_braking_count"] += t.harsh_braking_count or 0
        row["Harsh_acceleration_count"] += t.harsh_acceleration_count or 0
        row["Harsh_cornering_count"] += t.harsh_cornering_count or 0
        row["Total_exception_count"] += exceptions
        if local.hour >= NIGHT_START or local.hour < NIGHT_END:
            row["Night_trip_count"] += 1
            row["Night_distance_km"] += km
            row["Night_duration_hours"] += hours
        if local.weekday() >= 5:
            row["Weekend_distance_km"] += km
        elif BUSINESS_START <= local.hour < BUSINESS_END:
            row["Business_hours_distance_km"] += km
        active[key].add(t.imei)
        used_days[key].add((t.imei, local.date()))

    alerts_wanted = {"Alert_count", "Geofence_entry_count", "Geofence_exit_count"} & {
        m for k in measures for m in ([k] if k in MEASURES else measures_used(expressions[k[5:]][1]))}
    if alerts_wanted and imeis:
        tag_imei = {str(tid): imei for tid, imei in db.query(BLETag.id, BLETag.imei).filter(BLETag.imei.in_(imeis))}
        rows = (db.query(PortalAlert.tag_id, PortalAlert.alert_type, PortalAlert.created_at)
                .filter(PortalAlert.usergroup_id == group_id, PortalAlert.created_at >= start,
                        PortalAlert.created_at < end, PortalAlert.tag_id.isnot(None)).all())
        for tag_id, alert_type, created in rows:
            imei = tag_imei.get(str(tag_id))
            if imei is None:
                continue
            key, label = key_of(imei, _utc(created).astimezone(tz))
            labels[key] = label
            acc[key]["Alert_count"] += 1
            if alert_type == "geofence_entry":
                acc[key]["Geofence_entry_count"] += 1
            elif alert_type == "geofence_exit":
                acc[key]["Geofence_exit_count"] += 1

    # Rows: every vehicle / group / bucket in scope, even those with nothing to count
    order = []
    if dimension in _TIME_DIMS or dimension in ("hour", "weekday"):
        buckets = _all_buckets(dimension, start, end, tz)
        order = [(k, lbl) for k, lbl, _ in buckets]
        bucket_days = {k: n for k, _, n in buckets}
        for k, _ in order:
            vehicles_in[k] = set(imeis)
    else:
        bucket_days = {}
        for imei, info in devices.items():
            k, lbl = key_of(imei, datetime.now(tz))
            vehicles_in[k].add(imei)
            labels.setdefault(k, lbl)
        order = [(k, labels[k]) for k in labels]

    out = []
    for key, label in order:
        row = acc.get(key, {})
        values = {m: round(row.get(m, 0.0), 3) for m in _SUMS + ["Max_speed_kmh"]}
        values["Active_vehicle_count"] = len(active.get(key, ()))
        values["Vehicle_count"] = len(vehicles_in.get(key, ()))
        values["Utilization_days"] = len(used_days.get(key, ()))
        days = bucket_days.get(key) if dimension in _TIME_DIMS else (None if dimension in ("hour", "weekday") else period_days)
        values["Downtime_days"] = (max(0, values["Vehicle_count"] * days - values["Utilization_days"])
                                   if days is not None else None)
        cells = {}
        for m in measures:
            if m in trees:
                v = evaluate(trees[m], values)
                cells[m] = None if v is None else round(v, 4)
            else:
                cells[m] = values[m]
        out.append({"key": key, "label": label, "values": cells})

    if dimension not in _TIME_DIMS and dimension not in ("hour", "weekday"):
        by = sort if sort in measures else (measures[0] if measures else None)
        if by:
            out.sort(key=lambda r: (r["values"].get(by) is None, -(r["values"].get(by) or 0) if descending else (r["values"].get(by) or 0)))
        else:
            out.sort(key=lambda r: r["label"].lower())
    else:
        out.sort(key=lambda r: r["key"])
    if limit and dimension not in _TIME_DIMS:
        out = out[:limit]

    columns = []
    for m in measures:
        if m in trees:
            label, _, decimals, unit = expressions[m[5:]]
            columns.append({"key": m, "label": label, "unit": unit or "", "decimals": 2 if decimals is None else decimals})
        else:
            label, unit, _, decimals = MEASURES[m]
            columns.append({"key": m, "label": label, "unit": unit, "decimals": decimals})
    return {"dimension": dimension, "dimension_label": DIMENSIONS[dimension], "columns": columns, "rows": out}


def devices_for(db: Session, group_id, only: Optional[set], category: Optional[str] = None,
                imei: Optional[str] = None) -> dict:
    """{imei: {name, group, driver}} of the group's vehicles the user may see."""
    out = {}
    for tag in db.query(BLETag).filter(BLETag.attributes.op("->>")("_created_usergroup_id") == str(group_id)).all():
        if only is not None and tag.imei not in only:
            continue
        attrs = tag.attributes or {}
        group = (attrs.get("category") or {}).get("value")
        if category and group != category:
            continue
        if imei and tag.imei != imei:
            continue
        out[tag.imei] = {"name": tag.description or tag.device_name or tag.imei, "group": group,
                         "driver": (attrs.get("driver") or {}).get("value")}
    return out


# ---------------------------------------------------------------------------
# Starting content for a user group: useful expressions and three pages
# ---------------------------------------------------------------------------

DEFAULT_EXPRESSIONS = [
    # (name, category, expression, description, unit, decimals)
    ("Average trip distance", "Trips", "m.Trip_distance_km / m.Trip_count", "Distance per trip", "km", 1),
    ("Average speed", "Trips", "m.Trip_distance_km / m.Trip_duration_hours", "Distance over driving time", "km/h", 0),
    ("Driving hours per vehicle", "Utilisation", "m.Trip_duration_hours / m.Active_vehicle_count", "Among vehicles that drove", "h", 1),
    ("Utilisation", "Utilisation", "m.Utilization_days / (m.Utilization_days + m.Downtime_days) * 100", "Share of vehicle-days with at least one trip", "%", 0),
    ("Exceptions per 100 km", "Exceptions", "m.Total_exception_count / m.Trip_distance_km * 100", "Speeding and harsh driving events per 100 km", "", 2),
    ("Speeding per 100 km", "Exceptions", "m.Speeding_count / m.Trip_distance_km * 100", "", "", 2),
    ("Harsh braking per 100 km", "Exceptions", "m.Harsh_braking_count / m.Trip_distance_km * 100", "", "", 2),
    ("Night driving share", "Time of day", "m.Night_distance_km / m.Trip_distance_km * 100", "Distance driven 20:00–05:00", "%", 0),
    ("Estimated fuel (12 L/100 km)", "Fuel and costs", "m.Trip_distance_km * 12 / 100", "Edit the 12 to your fleet's consumption", "L", 0),
    ("Estimated fuel cost (R23/L)", "Fuel and costs", "m.Trip_distance_km * 12 / 100 * 23", "Edit the consumption and fuel price", "R", 0),
]


def _v(type_, title, dimension, measures, width=6, height="m", **extra):
    import uuid
    return {"id": uuid.uuid4().hex[:12], "type": type_, "title": title, "dimension": dimension, "measures": measures,
            "width": width, "height": height, **extra}


def default_pages(expr_ids: dict) -> list:
    """expr_ids: {expression name: "expr:<id>"} for the seeded expressions."""
    e = expr_ids
    return [
        ("Fleet overview", "this_month", [
            _v("kpi", "Trips", "", ["Trip_count"], 3, "s"),
            _v("kpi", "Distance driven", "", ["Trip_distance_km"], 3, "s"),
            _v("kpi", "Driving time", "", ["Trip_duration_hours"], 3, "s"),
            _v("kpi", "Active vehicles", "", ["Active_vehicle_count"], 3, "s"),
            _v("column", "Distance per day", "day", ["Trip_distance_km"], 8, "m"),
            _v("donut", "Distance by vehicle group", "vehicle_group", ["Trip_distance_km"], 4, "m"),
            _v("table", "Vehicles", "vehicle", ["Trip_count", "Trip_distance_km", "Trip_duration_hours",
                                                e["Average speed"], "Max_speed_kmh", "Total_exception_count"], 12, "l"),
        ]),
        ("Driver behaviour", "this_month", [
            _v("kpi", "Exceptions per 100 km", "", [e["Exceptions per 100 km"]], 4, "s"),
            _v("kpi", "Speeding events", "", ["Speeding_count"], 4, "s"),
            _v("kpi", "Harsh braking events", "", ["Harsh_braking_count"], 4, "s"),
            _v("stacked", "Exceptions per week", "week", ["Speeding_count", "Harsh_braking_count",
                                                          "Harsh_acceleration_count", "Harsh_cornering_count"], 7, "m"),
            _v("bar", "Exceptions per 100 km by vehicle", "vehicle", [e["Exceptions per 100 km"]], 5, "m", limit=10),
            _v("table", "Drivers", "driver", ["Trip_distance_km", "Speeding_count", "Harsh_braking_count",
                                              "Harsh_acceleration_count", "Harsh_cornering_count", e["Exceptions per 100 km"]], 12, "l"),
        ]),
        ("Utilisation", "this_month", [
            _v("kpi", "Utilisation", "", [e["Utilisation"]], 4, "s"),
            _v("kpi", "Driving hours per vehicle", "", [e["Driving hours per vehicle"]], 4, "s"),
            _v("kpi", "Night driving share", "", [e["Night driving share"]], 4, "s"),
            _v("stacked", "Vehicle utilisation and downtime (days)", "vehicle", ["Utilization_days", "Downtime_days"], 6, "m"),
            _v("column", "Trips by hour of day", "hour", ["Trip_count"], 6, "m"),
            _v("column", "Distance by day of week", "weekday", ["Trip_distance_km"], 6, "m"),
            _v("line", "Driving time per day", "day", ["Trip_duration_hours"], 6, "m"),
        ]),
    ]
