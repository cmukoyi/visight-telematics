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
    "After_hours_trip_count":   ("After-hours trips", "", "Time of day", 0),
    "After_hours_distance_km":  ("After-hours distance", "km", "Time of day", 1),
    "After_hours_duration_hours": ("After-hours driving time", "h", "Time of day", 1),
    "Active_vehicle_count":     ("Active vehicles", "", "Utilisation", 0),
    "Vehicle_count":            ("Vehicles", "", "Utilisation", 0),
    "Utilization_days":         ("Vehicle utilisation (days)", "days", "Utilisation", 0),
    "Downtime_days":            ("Vehicle downtime (days)", "days", "Utilisation", 0),
    "Speeding_duration_hours":  ("Speeding duration", "h", "Exceptions", 2),
    "Idle_duration_hours":      ("Idle duration", "h", "Exceptions", 2),
    "Excess_idle_hours":        ("Excess idle duration", "h", "Exceptions", 2),
    "Vehicle_days":             ("Vehicle-days", "days", "Utilisation", 0),
    "Workshop_days":            ("Vehicle-days in the workshop", "days", "Utilisation", 0),
    "Period_days":              ("Days in the period", "days", "Utilisation", 0),
    "Driver_count":             ("Drivers", "", "Drivers", 0),
    "Active_driver_count":      ("Drivers who drove", "", "Drivers", 0),
    "Driver_utilization_days":  ("Driver-days driven", "days", "Drivers", 0),
    "Fuel_used_l":              ("Fuel used", "L", "Fuel and costs", 1),
    "Fuel_cost":                ("Fuel cost", "R", "Fuel and costs", 0),
    "Speeding_cost":            ("Speeding cost", "R", "Fuel and costs", 0),
    "Excess_idle_cost":         ("Excess idle cost", "R", "Fuel and costs", 0),
    "After_hours_cost":         ("After-hours cost", "R", "Fuel and costs", 0),
    "Maintenance_cost":         ("Maintenance cost", "R", "Fleet costs", 0),
    "Tracking_cost":            ("Tracking cost", "R", "Fleet costs", 0),
    "Licence_cost":             ("Licence cost", "R", "Fleet costs", 0),
    "Fines_cost":               ("Fines cost", "R", "Fleet costs", 0),
    "Insurance_cost":           ("Insurance cost", "R", "Fleet costs", 0),
    "Other_cost":               ("Other costs", "R", "Fleet costs", 0),
    "TCO":                      ("Total cost of ownership (TCO)", "R", "Fleet costs", 0),
    "Alert_count":              ("Alerts", "", "Alerts", 0),
    "Geofence_entry_count":     ("Place entries", "", "Places", 0),
    "Geofence_exit_count":      ("Place exits", "", "Places", 0),
    "Place_visit_count":        ("Place visits", "", "Places", 0),
    "Time_in_place_hours":      ("Time in place", "h", "Places", 1),
    "Breakdown_count":          ("Breakdowns", "", "Breakdowns", 0),
    "Breakdown_hours":          ("Breakdown downtime", "h", "Breakdowns", 1),
    "Breakdown_avg_hours":      ("Average breakdown", "h", "Breakdowns", 1),
    "Breakdown_check_count":    ("Breakdowns to check", "", "Breakdowns", 0),
    "Breakdown_disputed_count": ("Disputed breakdowns", "", "Breakdowns", 0),
}
_SUMS = [k for k in MEASURES if k not in ("Max_speed_kmh", "Active_vehicle_count", "Vehicle_count",
                                          "Utilization_days", "Downtime_days", "Vehicle_days", "Period_days",
                                          "Driver_count", "Active_driver_count", "Driver_utilization_days", "TCO",
                                          "Breakdown_avg_hours")]

# Where a measure's data comes from
SCOPE = {k: "trip" for k in MEASURES}
SCOPE.update({k: "fleet" for k in ("Active_vehicle_count", "Vehicle_count", "Utilization_days", "Downtime_days",
                                    "Vehicle_days", "Workshop_days", "Period_days")})
# Costs: from cost items (amortised by day), fixed fees spread over the days, and fuel from trips
SCOPE.update({k: "cost" for k in ("Fuel_cost", "Maintenance_cost", "Tracking_cost", "Licence_cost", "Fines_cost",
                                   "Insurance_cost", "Other_cost", "TCO")})
SCOPE.update({k: "drivers" for k in ("Driver_count", "Active_driver_count", "Driver_utilization_days")})
COST_MEASURE = {"maintenance": "Maintenance_cost", "fuel": "Fuel_cost", "tracking": "Tracking_cost",
                "licence": "Licence_cost", "fines": "Fines_cost", "insurance": "Insurance_cost", "other": "Other_cost"}
TCO_PARTS = list(COST_MEASURE.values())
SCOPE["Alert_count"] = "alert"
SCOPE.update({k: "place" for k in ("Geofence_entry_count", "Geofence_exit_count", "Place_visit_count", "Time_in_place_hours")})
_PLACE_MEASURES = {k for k, sc in SCOPE.items() if sc == "place"}
# Breakdowns logged in the mobile app (counted when they start; downtime up to the end of the period)
SCOPE.update({k: "breakdown" for k in ("Breakdown_count", "Breakdown_hours", "Breakdown_avg_hours", "Breakdown_check_count",
                                        "Breakdown_disputed_count")})
_BREAKDOWN_MEASURES = {k for k, sc in SCOPE.items() if sc == "breakdown"}

# Measures whose rows can't be added up into a total or a share (a top speed, a count of distinct vehicles)
NOT_ADDITIVE = {"Max_speed_kmh", "Active_vehicle_count", "Vehicle_count", "Period_days", "Driver_count",
                "Active_driver_count", "Breakdown_avg_hours"}

# What a single trip / place visit has (a list row is one record, so counts of trips etc. mean nothing there)
RECORD_MEASURES = {
    "trip": ["Trip_distance_km", "Trip_duration_hours", "Fuel_used_l", "After_hours_distance_km", "After_hours_duration_hours",
             "Speeding_duration_hours", "Idle_duration_hours", "Excess_idle_hours", "Speeding_cost", "Excess_idle_cost",
             "After_hours_cost", "Max_speed_kmh", "Idling_count", "Speeding_count",
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
    "breakdown_cause": "Breakdown cause",
}
# total · category (who/where) · time (a trend) · cycle (hour/weekday profile) · record (a list)
DIM_KIND = {"": "total", "vehicle": "category", "vehicle_group": "category", "driver": "category", "place": "category",
            "day": "time", "week": "time", "month": "time", "hour": "cycle", "weekday": "cycle",
            "trip": "record", "place_visit": "record", "breakdown_cause": "category"}
_TIME_DIMS = {"day", "week", "month"}
_WEEKDAYS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]


# ---------------------------------------------------------------------------
# Expressions
# ---------------------------------------------------------------------------

class ExpressionError(ValueError):
    pass


FUNCTIONS = {"min": min, "max": max}   # e.g. a score kept within 0–100: max(0, min(100, …))


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
        if isinstance(node, ast.Call):
            if not (isinstance(node.func, ast.Name) and node.func.id in FUNCTIONS) or node.keywords or len(node.args) < 2:
                raise ExpressionError("Functions: min(a, b, …) and max(a, b, …), e.g. max(0, 100 - m.Speeding_count)")
            continue
        if isinstance(node, ast.Name) and node.id in FUNCTIONS:
            continue
        raise ExpressionError("Only numbers, + − × ÷, brackets, min(), max() and m.<measure> are allowed")
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
        if isinstance(node, ast.Call):
            args = [ev(a) for a in node.args]
            return None if any(a is None for a in args) else FUNCTIONS[node.func.id](args)
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
    return (not any(isinstance(n, (ast.Div, ast.Call)) for n in ast.walk(tree))
            and not (measures_used(expression) & NOT_ADDITIVE))


def allowed_measures(dimension: str) -> list:
    """The measures that make sense for a dimension, in catalogue order."""
    if dimension in RECORD_MEASURES:
        return RECORD_MEASURES[dimension]
    if dimension == "place":
        return [k for k in MEASURES if k in _PLACE_MEASURES]
    if dimension == "breakdown_cause":
        return [k for k in MEASURES if k in _BREAKDOWN_MEASURES]
    kind = DIM_KIND[dimension]
    return [k for k in MEASURES
            if not (SCOPE[k] == "cost" and kind == "cycle")                         # a cost by hour of day means nothing
            and not (SCOPE[k] == "drivers" and dimension not in ("", "driver", "day", "week", "month"))]


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


def _trip_values(t: Trip, rate: Optional[float], windows: Optional[dict] = None, tz: Optional[ZoneInfo] = None,
                 settings: Optional[dict] = None) -> dict:
    """A trip's measures; after-hours ones split its time (and distance, in proportion) by the vehicle's working hours.

    Costs use the fleet settings: speeding h × R/h, excess idle h × L/h × fuel price, after-hours km × R/km,
    and fuel (km × the vehicle's L/100 km, or the default) × fuel price.
    """
    from app.services import fleet_settings_service, time_profiles
    st = settings or fleet_settings_service.DEFAULTS
    inside, outside = time_profiles.split(_utc(t.started_at), _utc(t.ended_at or t.last_event_at),
                                          windows if windows is not None else time_profiles.DEFAULT_WINDOWS, tz or timezone.utc)
    share = outside / (inside + outside) if inside + outside else 0.0
    km, speeding_h, excess_h = (t.distance_m or 0) / 1000, (t.speeding_s or 0) / 3600, (t.excess_idle_s or 0) / 3600
    exceptions = (t.speeding_count or 0) + (t.harsh_braking_count or 0) + (t.harsh_acceleration_count or 0) \
        + (t.harsh_cornering_count or 0)
    return {"Trip_distance_km": (t.distance_m or 0) / 1000, "Trip_duration_hours": (t.duration_s or 0) / 3600,
            "Fuel_used_l": vehicle_fuel.litres(t.distance_m, rate), "Max_speed_kmh": t.max_speed or 0,
            "Idling_count": t.idling_count or 0, "Speeding_count": t.speeding_count or 0,
            "Harsh_braking_count": t.harsh_braking_count or 0,
            "Harsh_acceleration_count": t.harsh_acceleration_count or 0,
            "Harsh_cornering_count": t.harsh_cornering_count or 0, "Total_exception_count": exceptions,
            "After_hours_trip_count": 1 if outside > 0 else 0,
            "After_hours_distance_km": km * share, "After_hours_duration_hours": outside / 3600,
            "Speeding_duration_hours": speeding_h, "Idle_duration_hours": (t.idle_s or 0) / 3600,
            "Excess_idle_hours": excess_h,
            "Speeding_cost": speeding_h * st["speeding_cost_per_hour"],
            "Excess_idle_cost": excess_h * st["idle_l_per_hour"] * st["fuel_price"],
            "After_hours_cost": km * share * st["after_hours_cost_per_km"],
            "_fuel_cost": km * fleet_settings_service.fuel_cost_per_km(st, rate)}


def _trip_list(db, group_id, devices, start, end, tz, measures, trees, sort, descending, limit) -> tuple:
    from app.services import drivers_service, fleet_settings_service
    settings = fleet_settings_service.get(db, group_id)
    driver_names = drivers_service.names(db, group_id)
    info_columns = [{"key": "vehicle", "label": "Vehicle"}, {"key": "driver", "label": "Driver"},
                    {"key": "start", "label": "Start"}, {"key": "end", "label": "End"},
                    {"key": "from", "label": "From"}, {"key": "to", "label": "To"}]
    trips = (db.query(Trip).filter(Trip.usergroup_id == group_id, Trip.imei.in_(list(devices)), Trip.real(),
                                   Trip.started_at >= start, Trip.started_at < end)
             .order_by(Trip.started_at).limit(RECORD_LIMIT + 1).all()) if devices else []
    from app.services.address_service import Describer
    describe = Describer(db, group_id).prefetch(
        [(t.start_latitude, t.start_longitude) for t in trips] + [(t.end_latitude, t.end_longitude) for t in trips])
    where = lambda address, lat, lng: (describe(lat, lng, address) or "") if address is not None else ""
    out = []
    for t in trips[:RECORD_LIMIT]:
        info = devices[t.imei]
        values = {k: (None if v is None else round(v, 3)) for k, v in
                  _trip_values(t, info.get("fuel_rate"), info.get("windows"), tz, settings).items() if not k.startswith("_")}
        out.append({"key": str(t.id), "label": f"{_utc(t.started_at).astimezone(tz).strftime('%d %b %H:%M')} · {info['name']}",
                    "values": _cells(measures, trees, values),
                    "info": {"vehicle": info["name"], "driver": (driver_names.get(str(t.driver_id)) if t.driver_id else None) or info.get("driver") or "",
                             "start": _local_text(t.started_at, tz),
                             "end": _local_text(t.ended_at, tz) if t.ended_at else "In progress",
                             "from": where(t.start_address, t.start_latitude, t.start_longitude),
                             "to": where(t.end_address, t.end_latitude, t.end_longitude)}})
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
    from app.services import fleet_settings_service
    settings = fleet_settings_service.get(db, group_id)

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
    trip_wanted = bool(used & {k for k, sc in SCOPE.items() if sc in ("trip", "fleet", "cost", "drivers")})
    drivers_used, driver_days = defaultdict(set), defaultdict(set)   # who drove, and on which days, per row
    trips = (db.query(Trip).filter(Trip.usergroup_id == group_id, Trip.imei.in_(imeis), Trip.real(),
                                   Trip.started_at >= start, Trip.started_at < end).all()) if imeis and trip_wanted else []
    driver_names = {}
    if dimension == "driver" and trips:
        from app.services import drivers_service
        driver_names = drivers_service.names(db, group_id)
    for t in trips:
        local = _utc(t.started_at).astimezone(tz)
        if dimension == "driver" and t.driver_id and str(t.driver_id) in driver_names:
            key = label = driver_names[str(t.driver_id)]   # the driver whose key was on this trip
        else:
            key, label = key_of(t.imei, local)
        labels[key] = label
        row = acc[key]
        tv = _trip_values(t, devices[t.imei].get("fuel_rate"), devices[t.imei].get("windows"), tz, settings)
        km, hours = tv["Trip_distance_km"], tv["Trip_duration_hours"]
        row["Trip_count"] += 1
        for k in ("Trip_distance_km", "Trip_duration_hours", "Idling_count", "Speeding_count", "Harsh_braking_count",
                  "Harsh_acceleration_count", "Harsh_cornering_count", "Total_exception_count", "After_hours_trip_count",
                  "After_hours_distance_km", "After_hours_duration_hours", "Speeding_duration_hours", "Idle_duration_hours",
                  "Excess_idle_hours", "Speeding_cost", "Excess_idle_cost", "After_hours_cost"):
            row[k] += tv[k]
        row["Fuel_cost"] += tv["_fuel_cost"]
        did = str(t.driver_id) if t.driver_id else devices[t.imei].get("driver_id")
        if did:
            drivers_used[key].add(did)
            driver_days[key].add((did, local.date()))
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

    if used & _BREAKDOWN_MEASURES and imeis:
        _add_breakdowns(db, group_id, imeis, start, end, tz, dimension, key_of, acc, labels,
                        check="Breakdown_check_count" in used)

    # Costs: cost items (amortised by day) and fixed fees spread over the vehicle-days
    if used & {k for k, sc in SCOPE.items() if sc == "cost"} and imeis:
        _add_costs(db, group_id, devices, start, end, tz, settings, dimension, key_of, acc, labels)
    workshop = defaultdict(set)
    if "Workshop_days" in used and imeis:
        for imei, d in _workshop_days(db, group_id, imeis, start, end, tz):
            key, label = key_of(imei, datetime.combine(d, time(12), tzinfo=tz))
            labels.setdefault(key, label)
            workshop[key].add((imei, d))

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
    elif dimension == "breakdown_cause":
        from app.services.breakdown_service import CAUSES
        bucket_days = {}
        for c in CAUSES:
            labels.setdefault(c, c)
        order = [(k, labels[k]) for k in labels]
    else:
        bucket_days = {}
        for imei in devices:
            k, lbl = key_of(imei, datetime.now(tz))
            vehicles_in[k].add(imei)
            labels.setdefault(k, lbl)
        if dimension == "driver":
            for name in _active_driver_names(db, group_id):
                labels.setdefault(name, name)
        order = [(k, labels[k]) for k in labels]
    group_drivers = (len(_active_driver_names(db, group_id))
                     if used & {"Driver_count", "Driver_utilization_days"} else 0)

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
        values["Vehicle_days"] = values["Vehicle_count"] * days if days is not None else None
        values["Period_days"] = days
        values["Workshop_days"] = len(workshop.get(key, ()))
        values["Driver_count"] = ((0 if key == "No driver" else 1) if dimension == "driver" else group_drivers)
        values["Active_driver_count"] = len(drivers_used.get(key, ()))
        values["Driver_utilization_days"] = len(driver_days.get(key, ()))
        values["TCO"] = round(sum(values.get(k) or 0 for k in TCO_PARTS), 2)
        values["Breakdown_avg_hours"] = (round(values["Breakdown_hours"] / values["Breakdown_count"], 3)
                                         if values.get("Breakdown_count") else None)
        r = {"key": key, "label": label, "values": _cells(measures, trees, values)}
        if dimension == "vehicle":
            r["info"] = {"registration": devices.get(key, {}).get("registration") or ""}
        out.append(r)

    if kind in ("time", "cycle"):
        out.sort(key=lambda r: r["key"])
    else:
        _sort_rows(out, measures, sort, descending)
    if limit and dimension not in _TIME_DIMS:
        # A top / bottom N: rows without a value (e.g. a driver with no trips has no score) aren't ranked
        by = sort if sort in measures else (measures[0] if measures else None)
        out = [r for r in out if by is None or r["values"].get(by) is not None][:limit]
    if dimension == "vehicle":
        result["info_columns"] = [{"key": "registration", "label": "Registration"}]
    return {**result, "rows": out}


def _add_breakdowns(db, group_id, imeis, start, end, tz, dimension, key_of, acc, labels, check: bool) -> None:
    """Breakdowns that started in the period: count, downtime (to the end of the period or now), flagged, disputed."""
    from app.models_maintenance import VehicleBreakdown
    from app.services import breakdown_service
    now = datetime.now(timezone.utc)
    for b in (db.query(VehicleBreakdown).filter(VehicleBreakdown.usergroup_id == group_id, VehicleBreakdown.imei.in_(imeis),
                                                VehicleBreakdown.started_at >= start, VehicleBreakdown.started_at < end)):
        began = _utc(b.started_at)
        if dimension == "breakdown_cause":
            key = label = b.cause or "Not given"
        elif dimension == "driver":
            key = label = b.driver or "No driver"
        else:
            key, label = key_of(b.imei, began.astimezone(tz))
        labels[key] = label
        row = acc[key]
        row["Breakdown_count"] += 1
        row["Breakdown_hours"] += max(0.0, (min(_utc(b.ended_at) if b.ended_at else now, end, now) - began).total_seconds()) / 3600
        row["Breakdown_disputed_count"] += b.review == "disputed"
        if check:
            row["Breakdown_check_count"] += breakdown_service.evidence(db, b)["verdict"] == "check"


def _active_driver_names(db: Session, group_id) -> list:
    from app.models import Driver
    return [d.name for d in db.query(Driver).filter(Driver.usergroup_id == group_id, Driver.is_active == True)]  # noqa: E712


def _days(a: date, b: date):
    d = a
    while d <= b:
        yield d
        d += timedelta(days=1)


def _add_costs(db, group_id, devices, start, end, tz, settings, dimension, key_of, acc, labels) -> None:
    """Cost items (spread by day when amortised) and the daily share of fixed fees, into each row's cost measures."""
    from app.models_maintenance import MaintenanceCost
    from app.services.maintenance_service import cost_in_period
    d0, d1 = start.astimezone(tz).date(), (end - timedelta(seconds=1)).astimezone(tz).date()
    noon = lambda d: datetime.combine(d, time(12), tzinfo=tz)  # noqa: E731
    imeis = list(devices)
    costs = (db.query(MaintenanceCost)
             .filter(MaintenanceCost.usergroup_id == group_id, MaintenanceCost.imei.in_(imeis),
                     ((MaintenanceCost.amortise_from.is_(None)) & (MaintenanceCost.cost_date >= d0) & (MaintenanceCost.cost_date <= d1))
                     | ((MaintenanceCost.amortise_from <= d1) & (MaintenanceCost.amortise_to >= d0))).all())
    for c in costs:
        measure = COST_MEASURE.get(c.category or "maintenance", "Other_cost")
        if c.amortise_from and c.amortise_to:
            span = (c.amortise_to - c.amortise_from).days + 1
            for d in _days(max(d0, c.amortise_from), min(d1, c.amortise_to)):
                key, label = key_of(c.imei, noon(d))
                labels.setdefault(key, label)
                acc[key][measure] += float(c.amount) / span
        else:
            key, label = key_of(c.imei, noon(c.cost_date))
            labels.setdefault(key, label)
            acc[key][measure] += cost_in_period(c, d0, d1)
    daily = {"Tracking_cost": settings["tracking_fee_per_month"] * 12 / 365, "Licence_cost": settings["licence_fee_per_year"] / 365}
    if not any(daily.values()):
        return
    if dimension in _TIME_DIMS:
        for d in _days(d0, d1):
            key, label = _bucket(dimension, noon(d))
            labels.setdefault(key, label)
            for measure, rate in daily.items():
                acc[key][measure] += rate * len(imeis)
    else:
        n = (d1 - d0).days + 1
        for imei in imeis:
            key, label = key_of(imei, noon(d0))
            labels.setdefault(key, label)
            for measure, rate in daily.items():
                acc[key][measure] += rate * n


def _workshop_days(db, group_id, imeis, start, end, tz) -> set:
    """{(imei, local date)} on which a vehicle was in the workshop (a job started and not yet ended)."""
    from app.models_maintenance import VehicleMaintenance
    jobs = (db.query(VehicleMaintenance)
            .filter(VehicleMaintenance.usergroup_id == group_id, VehicleMaintenance.imei.in_(imeis),
                    VehicleMaintenance.actual_start.isnot(None), VehicleMaintenance.actual_start < end,
                    (VehicleMaintenance.actual_end.is_(None)) | (VehicleMaintenance.actual_end >= start)).all())
    out = set()
    now = datetime.now(timezone.utc)
    for j in jobs:
        a = max(_utc(j.actual_start), start).astimezone(tz).date()
        b = min(_utc(j.actual_end) if j.actual_end else now, end - timedelta(seconds=1)).astimezone(tz).date()
        out.update((j.imei, d) for d in _days(a, b))
    return out


def devices_for(db: Session, group_id, only: Optional[set], category: Optional[str] = None,
                imei: Optional[str] = None) -> dict:
    """{imei: {name, group, driver, fuel_rate, windows}} of the group's vehicles the user may see."""
    from app.services import time_profiles
    by_id, default = time_profiles.profiles(db, group_id)
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
                         "driver": (attrs.get("driver") or {}).get("value"), "fuel_rate": vehicle_fuel.rate(attrs),
                         "driver_id": (attrs.get("driver_id") or {}).get("value"),
                         "registration": (attrs.get("registration") or {}).get("value"),
                         "windows": time_profiles.for_vehicle(attrs, by_id, default)}
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


# ---------------------------------------------------------------------------
# Fleet dashboards: scores, costs, utilisation (added once to every group; all editable)
# ---------------------------------------------------------------------------

def _score(measure: str, points: int) -> str:
    """100, less `points` for each event per 100 km, kept within 0–100."""
    return f"max(0, min(100, 100 - m.{measure} / m.Trip_distance_km * 100 * {points}))"


_AFTER_HOURS_SCORE = "max(0, min(100, 100 - m.After_hours_distance_km / m.Trip_distance_km * 100))"
FLEET_EXPRESSIONS = [
    # (name, category, expression, description, unit, decimals)
    ("Speeding score", "Scores", _score("Speeding_count", 5), "100 less 5 points per speeding event per 100 km", "", 0),
    ("Acceleration score", "Scores", _score("Harsh_acceleration_count", 10), "100 less 10 points per harsh acceleration per 100 km", "", 0),
    ("Braking score", "Scores", _score("Harsh_braking_count", 10), "100 less 10 points per harsh braking per 100 km", "", 0),
    ("Cornering score", "Scores", _score("Harsh_cornering_count", 10), "100 less 10 points per harsh cornering per 100 km", "", 0),
    ("After-hours score", "Scores", _AFTER_HOURS_SCORE, "100 less the share of km driven after hours", "", 0),
    ("Driving score", "Scores",
     f"({_score('Speeding_count', 5)} + {_score('Harsh_acceleration_count', 10)} + {_score('Harsh_braking_count', 10)} + "
     f"{_score('Harsh_cornering_count', 10)} + {_AFTER_HOURS_SCORE}) / 5",
     "Average of the speeding, acceleration, braking, cornering and after-hours scores", "", 0),
    ("Cost per km (CPK)", "Fuel and costs", "m.TCO / m.Trip_distance_km", "Total cost of ownership per km driven", "R", 2),
    ("Vehicle utilisation %", "Utilisation", "m.Utilization_days / m.Vehicle_days * 100", "Vehicle-days with at least one trip", "%", 0),
    ("Vehicle availability %", "Utilisation", "(m.Vehicle_days - m.Workshop_days) / m.Vehicle_days * 100", "Vehicle-days not in the workshop", "%", 0),
    ("Driver utilisation %", "Utilisation", "m.Driver_utilization_days / (m.Driver_count * m.Period_days) * 100", "Driver-days with a trip, of all driver-days", "%", 0),
    ("Driver availability %", "Utilisation", "m.Active_driver_count / m.Driver_count * 100", "Drivers who drove in the period", "%", 0),
    ("Speeding exceptions per hour", "Exceptions", "m.Speeding_count / m.Trip_duration_hours", "Per driving hour", "", 2),
    ("Braking exceptions per hour", "Exceptions", "m.Harsh_braking_count / m.Trip_duration_hours", "Per driving hour", "", 2),
]


def fleet_pages(e: dict) -> list:
    """e: {expression name: "expr:<id>"}."""
    scores = ["Speeding score", "Acceleration score", "Braking score", "Cornering score", "After-hours score", "Driving score"]
    return [
        ("Fleet dashboard", "this_month", [
            _v("kpi", "Total cost of ownership", "", ["TCO", e["Cost per km (CPK)"]], 4, "s"),
            _v("kpi", "Distance travelled", "", ["Trip_distance_km", "Trip_count"], 4, "s"),
            _v("kpi", "Trip duration", "", ["Trip_duration_hours", "Active_vehicle_count"], 4, "s"),
            _v("kpi", "Speeding", "", ["Speeding_duration_hours", "Speeding_cost"], 4, "s"),
            _v("kpi", "Excess idling", "", ["Excess_idle_hours", "Excess_idle_cost"], 4, "s"),
            _v("kpi", "After hours", "", ["After_hours_distance_km", "After_hours_cost"], 4, "s"),
            *[_v("kpi", name, "", [e[name]], 2, "s") for name in scores],
            _v("bar", "Top 10 drivers (driving score)", "driver", [e["Driving score"]], 6, "m", limit=10, descending=True, show_values=True),
            _v("bar", "Worst 10 drivers (driving score)", "driver", [e["Driving score"]], 6, "m", limit=10, descending=False, show_values=True),
            _v("table", "Vehicles", "vehicle", ["Trip_distance_km", e["Cost per km (CPK)"], "Trip_duration_hours",
                                               "Speeding_duration_hours", "Speeding_cost", "Excess_idle_cost",
                                               "After_hours_distance_km", "After_hours_duration_hours"], 12, "l"),
            _v("table", "Driving scores by vehicle group (click a group to drill down)", "vehicle_group",
               [e[n] for n in scores], 12, "m"),
        ]),
        ("Fleet cost", "this_year", [
            _v("kpi", "Total cost of ownership", "", ["TCO", e["Cost per km (CPK)"]], 4, "s"),
            _v("kpi", "Maintenance", "", ["Maintenance_cost"], 4, "s"),
            _v("kpi", "After hours", "", ["After_hours_cost", "After_hours_distance_km"], 4, "s"),
            _v("stacked", "Monthly fleet cost", "month", ["Maintenance_cost", "Tracking_cost", "Licence_cost", "Fines_cost",
                                                          "After_hours_cost", "Fuel_cost"], 12, "l"),
            _v("table", "Monthly fleet cost", "month", ["Maintenance_cost", "Tracking_cost", "Licence_cost", "Fines_cost",
                                                        "After_hours_cost", "Fuel_cost", "TCO"], 12, "m"),
            _v("table", "Cost by vehicle group", "vehicle_group", ["Maintenance_cost", "Tracking_cost", "Licence_cost",
                                                                   "Fines_cost", "After_hours_cost", "TCO",
                                                                   e["Cost per km (CPK)"]], 12, "m"),
        ]),
        ("Utilisation and availability", "last_month", [
            _v("kpi", "Vehicles utilised", "", ["Active_vehicle_count", "Vehicle_count"], 3, "s"),
            _v("kpi", "Distance travelled", "", ["Trip_distance_km"], 3, "s"),
            _v("kpi", "Vehicle utilisation", "", [e["Vehicle utilisation %"], e["Vehicle availability %"]], 3, "s"),
            _v("kpi", "Driver utilisation", "", [e["Driver utilisation %"], e["Driver availability %"]], 3, "s"),
            _v("kpi", "Speeding exceptions per hour", "", [e["Speeding exceptions per hour"]], 3, "s"),
            _v("kpi", "Braking exceptions per hour", "", [e["Braking exceptions per hour"]], 3, "s"),
            _v("line", "Vehicle utilisation and availability per week", "week",
               [e["Vehicle utilisation %"], e["Vehicle availability %"]], 6, "s"),
            _v("table", "Utilisation per week", "week",
               ["Active_vehicle_count", "Trip_distance_km", e["Vehicle utilisation %"], e["Vehicle availability %"],
                e["Driver utilisation %"], e["Driver availability %"], e["Speeding exceptions per hour"],
                e["Braking exceptions per hour"]], 12, "m"),
            _v("table", "Utilisation by vehicle group", "vehicle_group",
               ["Active_vehicle_count", "Vehicle_count", "Trip_distance_km", e["Vehicle utilisation %"],
                e["Vehicle availability %"], e["Speeding exceptions per hour"], e["Braking exceptions per hour"]], 12, "m"),
        ]),
    ]


def breakdown_pages() -> list:
    """Downtime from breakdowns drivers log in the mobile app (added once to every group; editable)."""
    every = ["Breakdown_count", "Breakdown_hours", "Breakdown_avg_hours", "Breakdown_check_count", "Breakdown_disputed_count"]
    return [
        ("Breakdowns and downtime", "this_year", [
            _v("kpi", "Breakdowns", "", ["Breakdown_count"], 3, "s"),
            _v("kpi", "Breakdown downtime", "", ["Breakdown_hours"], 3, "s"),
            _v("kpi", "Average breakdown", "", ["Breakdown_avg_hours"], 3, "s"),
            _v("kpi", "To check (tracker disagrees)", "", ["Breakdown_check_count", "Breakdown_disputed_count"], 3, "s"),
            _v("column", "Downtime per month", "month", ["Breakdown_hours"], 8, "m"),
            _v("donut", "Downtime by cause", "breakdown_cause", ["Breakdown_hours"], 4, "m"),
            _v("bar", "Most downtime (top 10 vehicles)", "vehicle", ["Breakdown_hours"], 6, "m", limit=10, descending=True,
               show_values=True),
            _v("column", "Breakdowns by hour of day", "hour", ["Breakdown_count"], 6, "m"),
            _v("table", "Downtime by vehicle", "vehicle", every, 12, "l"),
            _v("table", "Downtime by driver", "driver", every, 12, "m"),
        ]),
    ]
