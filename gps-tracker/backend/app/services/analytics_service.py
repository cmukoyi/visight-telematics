"""Analytics (Reports → Analytics): measures over the fleet's trips and alerts, by a dimension.

A query asks for some MEASURES (and/or expressions built from them) broken
down by one DIMENSION over a period, for the vehicles the user may see:

    query(db, group_id, devices, start, end, tz, dimension="vehicle",
          measures=["Trip_distance_km", "expr:<id>"])

Trips are attributed to the local day/hour they started in. Expressions are
arithmetic over measures (m.Trip_distance_km / m.Trip_count), parsed safely
(numbers, + - * /, brackets and m.<measure> only) and evaluated per row after
aggregation; dividing by zero gives no value.

Dimensions are summaries (one row per vehicle, day, place …) or lists (one
row per trip or per place visit, with text columns such as start and end).
Each measure has a scope — trips, fleet, alerts or places — and a dimension
only offers the measures that make sense for it (a place visit has a time in
place, not a trip count). check_visual() also keeps each chart type to the
data it can show honestly: pies only for shares of an additive total, lines
only over time, lists only as tables or bars.
"""
import ast
from collections import defaultdict
from datetime import date, datetime, time, timedelta, timezone
from typing import Optional
from zoneinfo import ZoneInfo

from sqlalchemy.orm import Session

from app.models import POI, BLETag, PlaceVisit, PortalAlert
from app.models_dataprofiler import Trip
from app.services import vehicle_fuel

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
    "Fuel_used_l":              ("Fuel used", "L", "Fuel and costs", 1),
    "Alert_count":              ("Alerts", "", "Alerts", 0),
    "Geofence_entry_count":     ("Place entries", "", "Places", 0),
    "Geofence_exit_count":      ("Place exits", "", "Places", 0),
    "Place_visit_count":        ("Place visits", "", "Places", 0),
    "Time_in_place_hours":      ("Time in place", "h", "Places", 1),
}
_SUMS = [k for k in MEASURES if k not in ("Max_speed_kmh", "Active_vehicle_count", "Vehicle_count",
                                          "Utilization_days", "Downtime_days")]

# Where a measure's data comes from
SCOPE = {k: "trip" for k in MEASURES}
SCOPE.update({k: "fleet" for k in ("Active_vehicle_count", "Vehicle_count", "Utilization_days", "Downtime_days")})
SCOPE["Alert_count"] = "alert"
SCOPE.update({k: "place" for k in ("Geofence_entry_count", "Geofence_exit_count", "Place_visit_count", "Time_in_place_hours")})
_PLACE_MEASURES = {k for k, sc in SCOPE.items() if sc == "place"}

# Measures whose rows can't be added up into a total or a share (a top speed, a count of distinct vehicles)
NOT_ADDITIVE = {"Max_speed_kmh", "Active_vehicle_count", "Vehicle_count"}

# What a single trip / place visit has (a list row is one record, so counts of trips etc. mean nothing there)
RECORD_MEASURES = {
    "trip": ["Trip_distance_km", "Trip_duration_hours", "Fuel_used_l", "Max_speed_kmh", "Idling_count", "Speeding_count",
             "Harsh_braking_count", "Harsh_acceleration_count", "Harsh_cornering_count", "Total_exception_count"],
    "place_visit": ["Time_in_place_hours"],
}
RECORD_LIMIT = 2000

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
    "place": "Place",
    "trip": "Each trip",
    "place_visit": "Each place visit",
}
# total · category (who/where) · time (a trend) · cycle (hour/weekday profile) · record (a list)
DIM_KIND = {"": "total", "vehicle": "category", "vehicle_group": "category", "driver": "category", "place": "category",
            "day": "time", "week": "time", "month": "time", "hour": "cycle", "weekday": "cycle",
            "trip": "record", "place_visit": "record"}
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


def expression_additive(expression: str) -> bool:
    """True when the expression's rows add up: no division and only additive measures (fuel cost, not km per trip)."""
    tree = parse(expression)
    return (not any(isinstance(n, ast.Div) for n in ast.walk(tree))
            and not (measures_used(expression) & NOT_ADDITIVE))


def allowed_measures(dimension: str) -> list:
    """The measures that make sense for a dimension, in catalogue order."""
    if dimension in RECORD_MEASURES:
        return RECORD_MEASURES[dimension]
    if dimension == "place":
        return [k for k in MEASURES if k in _PLACE_MEASURES]
    return list(MEASURES)


def _uses(key: str, expressions: dict) -> set:
    return {key} if key in MEASURES else measures_used(expressions[key[5:]][1])


def _additive(key: str, expressions: dict) -> bool:
    return key not in NOT_ADDITIVE if key in MEASURES else expression_additive(expressions[key[5:]][1])


def _label(key: str, expressions: dict) -> str:
    return MEASURES[key][0] if key in MEASURES else expressions[key[5:]][0]


def check_measures(dimension: str, measures: list, expressions: dict) -> None:
    """Raise ValueError when a value can't be shown for this dimension."""
    allowed = set(allowed_measures(dimension))
    for key in measures:
        if key.startswith("expr:") and key[5:] not in expressions:
            raise ValueError("Unknown expression")
        if not key.startswith("expr:") and key not in MEASURES:
            raise ValueError(f"Unknown measure {key}")
        if not _uses(key, expressions) <= allowed:
            raise ValueError(f"“{_label(key, expressions)}” can't be shown by {DIMENSIONS[dimension].lower()}")


def check_visual(vtype: str, dimension: str, measures: list, expressions: dict) -> None:
    """Raise ValueError when the chart type can't show this data honestly."""
    if vtype == "text":
        return
    check_measures(dimension, measures, expressions)
    kind = DIM_KIND[dimension]
    non_additive = [_label(k, expressions) for k in measures if not _additive(k, expressions)]
    if kind == "record" and vtype not in ("table", "column", "bar"):
        raise ValueError(f"{DIMENSIONS[dimension]} is a list — show it as a table, column or bar chart")
    if vtype in ("pie", "donut"):
        if kind not in ("category", "cycle"):
            raise ValueError("A pie or donut shows shares of a whole — break it down by vehicle, group, driver, place, "
                             "hour or day of week")
        if non_additive:
            raise ValueError(f"“{non_additive[0]}” doesn't add up to a whole, so it can't be a pie — use a bar chart")
    if vtype in ("line", "area") and kind not in ("time", "cycle"):
        raise ValueError("Line and area charts show a trend — break them down by day, week, month or hour")
    if vtype == "stacked":
        if kind == "total":
            raise ValueError("Stacked columns need a breakdown")
        if non_additive:
            raise ValueError(f"“{non_additive[0]}” can't be stacked — stacked parts must add up")
    if vtype == "kpi" and kind != "total" and non_additive:
        raise ValueError(f"A number adds its breakdown up, and “{non_additive[0]}” doesn't add up — use Total")


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


def _local_text(dt: Optional[datetime], tz: ZoneInfo) -> str:
    return _utc(dt).astimezone(tz).strftime("%d %b %Y %H:%M") if dt else ""


def _columns(measures: list, trees: dict, expressions: dict) -> list:
    columns = []
    for m in measures:
        if m in trees:
            label, _, decimals, unit = expressions[m[5:]]
            columns.append({"key": m, "label": label, "unit": unit or "", "decimals": 2 if decimals is None else decimals})
        else:
            label, unit, _, decimals = MEASURES[m]
            columns.append({"key": m, "label": label, "unit": unit, "decimals": decimals})
    return columns


def _cells(measures: list, trees: dict, values: dict) -> dict:
    cells = {}
    for m in measures:
        if m in trees:
            v = evaluate(trees[m], values)
            cells[m] = None if v is None else round(v, 4)
        else:
            cells[m] = values.get(m)
    return cells


def _sort_rows(out: list, measures: list, sort: Optional[str], descending: bool) -> None:
    by = sort if sort in measures else (measures[0] if measures else None)
    if by:
        out.sort(key=lambda r: (r["values"].get(by) is None,
                                -(r["values"].get(by) or 0) if descending else (r["values"].get(by) or 0)))
    else:
        out.sort(key=lambda r: r["label"].lower())


def _places(db: Session, group_id, place_id: Optional[str]) -> dict:
    """{poi_id str: name} of the group's active places (or the one chosen)."""
    q = db.query(POI.id, POI.name).filter(POI.usergroup_id == group_id, POI.is_active == True)  # noqa: E712
    if place_id:
        q = q.filter(POI.id == place_id)
    return {str(pid): name for pid, name in q}


def _visits(db: Session, group_id, imeis: list, places: dict, start: datetime, end: datetime) -> list:
    """Place visits of these vehicles at these places that overlap the period."""
    if not imeis or not places:
        return []
    return (db.query(PlaceVisit)
            .filter(PlaceVisit.usergroup_id == group_id, PlaceVisit.imei.in_(imeis),
                    PlaceVisit.poi_id.in_(list(places)),
                    (PlaceVisit.entered_at.is_(None)) | (PlaceVisit.entered_at < end),
                    (PlaceVisit.exited_at.is_(None)) | (PlaceVisit.exited_at >= start))
            .order_by(PlaceVisit.entered_at.asc().nullsfirst(), PlaceVisit.id).all())


def _hours_in(v: PlaceVisit, start: datetime, end: datetime) -> Optional[float]:
    """Hours of the visit inside [start, end); None when its entry is unknown."""
    if v.entered_at is None:
        return None
    a = max(_utc(v.entered_at), start)
    b = min(_utc(v.exited_at) if v.exited_at else datetime.now(timezone.utc), end)
    return max(0.0, (b - a).total_seconds() / 3600)


def _trip_values(t: Trip, rate: Optional[float]) -> dict:
    exceptions = (t.speeding_count or 0) + (t.harsh_braking_count or 0) + (t.harsh_acceleration_count or 0) \
        + (t.harsh_cornering_count or 0)
    return {"Trip_distance_km": (t.distance_m or 0) / 1000, "Trip_duration_hours": (t.duration_s or 0) / 3600,
            "Fuel_used_l": vehicle_fuel.litres(t.distance_m, rate), "Max_speed_kmh": t.max_speed or 0,
            "Idling_count": t.idling_count or 0, "Speeding_count": t.speeding_count or 0,
            "Harsh_braking_count": t.harsh_braking_count or 0,
            "Harsh_acceleration_count": t.harsh_acceleration_count or 0,
            "Harsh_cornering_count": t.harsh_cornering_count or 0, "Total_exception_count": exceptions}


def _trip_list(db, group_id, devices, start, end, tz, measures, trees, sort, descending, limit) -> tuple:
    info_columns = [{"key": "vehicle", "label": "Vehicle"}, {"key": "driver", "label": "Driver"},
                    {"key": "start", "label": "Start"}, {"key": "end", "label": "End"},
                    {"key": "from", "label": "From"}, {"key": "to", "label": "To"}]
    trips = (db.query(Trip).filter(Trip.usergroup_id == group_id, Trip.imei.in_(list(devices)), Trip.real(),
                                   Trip.started_at >= start, Trip.started_at < end)
             .order_by(Trip.started_at).limit(RECORD_LIMIT + 1).all()) if devices else []
    out = []
    for t in trips[:RECORD_LIMIT]:
        info = devices[t.imei]
        values = {k: (None if v is None else round(v, 3)) for k, v in _trip_values(t, info.get("fuel_rate")).items()}
        out.append({"key": str(t.id), "label": f"{_utc(t.started_at).astimezone(tz).strftime('%d %b %H:%M')} · {info['name']}",
                    "values": _cells(measures, trees, values),
                    "info": {"vehicle": info["name"], "driver": info.get("driver") or "",
                             "start": _local_text(t.started_at, tz),
                             "end": _local_text(t.ended_at, tz) if t.ended_at else "In progress",
                             "from": t.start_address or "", "to": t.end_address or ""}})
    if sort in measures:
        _sort_rows(out, measures, sort, descending)
    return info_columns, out[:limit] if limit else out, len(trips) > RECORD_LIMIT


def _visit_list(db, group_id, devices, places, start, end, tz, measures, trees, sort, descending, limit) -> tuple:
    info_columns = [{"key": "vehicle", "label": "Vehicle"}, {"key": "place", "label": "Place"},
                    {"key": "entered", "label": "Entered"}, {"key": "exited", "label": "Exited"}]
    visits = _visits(db, group_id, list(devices), places, start, end)
    out = []
    for v in visits[:RECORD_LIMIT]:
        name, place = devices[v.imei]["name"], places.get(str(v.poi_id), "")
        # The whole stay (not clipped to the period): how long it was there; still inside = so far
        hours = None if v.entered_at is None else max(0.0, (
            (_utc(v.exited_at) if v.exited_at else datetime.now(timezone.utc)) - _utc(v.entered_at)).total_seconds() / 3600)
        when = v.entered_at or v.exited_at
        out.append({"key": str(v.id), "label": f"{_utc(when).astimezone(tz).strftime('%d %b %H:%M') if when else '—'} · {place} · {name}",
                    "values": _cells(measures, trees, {"Time_in_place_hours": None if hours is None else round(hours, 3)}),
                    "info": {"vehicle": name, "place": place,
                             "entered": _local_text(v.entered_at, tz) if v.entered_at else "Before tracking began",
                             "exited": _local_text(v.exited_at, tz) if v.exited_at else "Still inside"}})
    if sort in measures:
        _sort_rows(out, measures, sort, descending)
    return info_columns, out[:limit] if limit else out, len(visits) > RECORD_LIMIT


def query(db: Session, group_id, devices: dict, start: datetime, end: datetime, tz: ZoneInfo, *,
          dimension: str = "", measures: list, expressions: Optional[dict] = None,
          sort: Optional[str] = None, descending: bool = True, limit: Optional[int] = None,
          place_id: Optional[str] = None) -> dict:
    """devices: {imei: {"name", "group", "driver", "fuel_rate"}} the user may see. measures: measure keys and
    "expr:<id>" keys found in `expressions` ({id: (label, expression, decimals, unit)}). place_id narrows
    place measures (and the Place / Each place visit rows) to one place."""
    if dimension not in DIMENSIONS:
        raise ValueError("Unknown dimension")
    expressions = expressions or {}
    check_measures(dimension, measures, expressions)
    trees = {key: parse(expressions[key[5:]][1]) for key in measures if key.startswith("expr:")}
    used = set().union(*[_uses(k, expressions) for k in measures]) if measures else set()
    kind = DIM_KIND[dimension]
    result = {"dimension": dimension, "dimension_label": DIMENSIONS[dimension], "kind": kind,
              "columns": _columns(measures, trees, expressions), "info_columns": [], "truncated": False}

    if dimension == "trip":
        info_columns, rows, truncated = _trip_list(db, group_id, devices, start, end, tz, measures, trees, sort, descending, limit)
        return {**result, "info_columns": info_columns, "rows": rows, "truncated": truncated}
    places = _places(db, group_id, place_id) if (used & _PLACE_MEASURES or dimension in ("place", "place_visit")) else {}
    if dimension == "place_visit":
        info_columns, rows, truncated = _visit_list(db, group_id, devices, places, start, end, tz, measures, trees, sort,
                                                    descending, limit)
        return {**result, "info_columns": info_columns, "rows": rows, "truncated": truncated}

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
    trip_wanted = bool(used & {k for k, sc in SCOPE.items() if sc in ("trip", "fleet")})
    trips = (db.query(Trip).filter(Trip.usergroup_id == group_id, Trip.imei.in_(imeis), Trip.real(),
                                   Trip.started_at >= start, Trip.started_at < end).all()) if imeis and trip_wanted else []
    for t in trips:
        local = _utc(t.started_at).astimezone(tz)
        key, label = key_of(t.imei, local)
        labels[key] = label
        row = acc[key]
        tv = _trip_values(t, devices[t.imei].get("fuel_rate"))
        km, hours = tv["Trip_distance_km"], tv["Trip_duration_hours"]
        row["Trip_count"] += 1
        for k in ("Trip_distance_km", "Trip_duration_hours", "Idling_count", "Speeding_count", "Harsh_braking_count",
                  "Harsh_acceleration_count", "Harsh_cornering_count", "Total_exception_count"):
            row[k] += tv[k]
        row["Fuel_used_l"] += tv["Fuel_used_l"] or 0
        row["Max_speed_kmh"] = max(row["Max_speed_kmh"], tv["Max_speed_kmh"])
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

    if "Alert_count" in used and imeis:
        tag_imei = {str(tid): imei for tid, imei in db.query(BLETag.id, BLETag.imei).filter(BLETag.imei.in_(imeis))}
        rows = (db.query(PortalAlert.tag_id, PortalAlert.created_at)
                .filter(PortalAlert.usergroup_id == group_id, PortalAlert.created_at >= start,
                        PortalAlert.created_at < end, PortalAlert.tag_id.isnot(None)).all())
        for tag_id, created in rows:
            imei = tag_imei.get(str(tag_id))
            if imei is None:
                continue
            key, label = key_of(imei, _utc(created).astimezone(tz))
            labels[key] = label
            acc[key]["Alert_count"] += 1

    if used & _PLACE_MEASURES:
        def place_key(v: PlaceVisit, at: datetime) -> tuple:
            if dimension == "place":
                return str(v.poi_id), places.get(str(v.poi_id), "")
            return key_of(v.imei, at.astimezone(tz))
        for v in _visits(db, group_id, imeis, places, start, end):
            entered, exited = (_utc(v.entered_at) if v.entered_at else None), (_utc(v.exited_at) if v.exited_at else None)
            if entered and start <= entered < end:
                key, label = place_key(v, entered)
                labels[key] = label
                acc[key]["Geofence_entry_count"] += 1
                acc[key]["Place_visit_count"] += 1
            if exited and start <= exited < end:
                key, label = place_key(v, exited)
                labels[key] = label
                acc[key]["Geofence_exit_count"] += 1
            hours = _hours_in(v, start, end)
            if hours:
                key, label = place_key(v, max(entered, start))
                labels[key] = label
                acc[key]["Time_in_place_hours"] += hours

    # Rows: every vehicle / group / place / bucket in scope, even those with nothing to count
    if kind in ("time", "cycle"):
        buckets = _all_buckets(dimension, start, end, tz)
        order = [(k, lbl) for k, lbl, _ in buckets]
        bucket_days = {k: n for k, _, n in buckets}
        for k, _ in order:
            vehicles_in[k] = set(imeis)
    elif dimension == "place":
        bucket_days = {}
        for pid, name in places.items():
            labels.setdefault(pid, name)
        order = [(k, labels[k]) for k in labels]
    else:
        bucket_days = {}
        for imei in devices:
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
        days = bucket_days.get(key) if dimension in _TIME_DIMS else (None if kind == "cycle" else period_days)
        values["Downtime_days"] = (max(0, values["Vehicle_count"] * days - values["Utilization_days"])
                                   if days is not None else None)
        out.append({"key": key, "label": label, "values": _cells(measures, trees, values)})

    if kind in ("time", "cycle"):
        out.sort(key=lambda r: r["key"])
    else:
        _sort_rows(out, measures, sort, descending)
    if limit and dimension not in _TIME_DIMS:
        out = out[:limit]
    return {**result, "rows": out}


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
                         "driver": (attrs.get("driver") or {}).get("value"), "fuel_rate": vehicle_fuel.rate(attrs)}
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
