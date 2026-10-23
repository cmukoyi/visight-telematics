"""Custom reports — build a report's rows from its definition and the values it's run with.

Row entities (ENTITIES) come in three kinds:
  record     one row per trip / event / place visit / alert / job / cost item
  aggregate  one row per vehicle / driver / vehicle group / day / week / month,
             with Analytics measures and Expressions computed by analytics_service
Columns are "a:<attribute>" (the entity's own fields), "m:<measure>" (Analytics
measures) or "expr:<id>" (the group's Expressions). A trip row computes its
measures with the same rules as Analytics, so the numbers always agree.

Pipeline: rows → column filters (numeric: > < ≥ ≤ = between) → sort (columns
with a sort, in column order) → Top N → formatted values and conditional colours.
"""
import io
import re
import zipfile
from datetime import date, datetime, timedelta, timezone
from typing import Callable, Optional
from zoneinfo import ZoneInfo

from sqlalchemy.orm import Session

from app.models import BLETag, Driver, PortalAlert
from app.models_dataprofiler import DeviceEvent, Trip
from app.services import analytics_service as an

MAX_ROWS = 50_000
PREVIEW_ROWS = 10

# ---------------------------------------------------------------------------
# Parameters
# ---------------------------------------------------------------------------

# key: (label, kind) — kind tells the run dialog which input to show
PARAMETERS = {
    "date_range":       ("Date range", "date_range"),
    "vehicle":          ("Vehicle", "vehicle"),
    "vehicle_group":    ("Vehicle group", "vehicle_group"),
    "driver":           ("Driver", "driver"),
    "event_type":       ("Event type", "event_types"),
    "trip_events_only": ("Include only events from trips", "boolean"),
    "place":            ("Place", "place"),
    "alert_type":       ("Alert type", "alert_type"),
    "job_status":       ("Maintenance status", "job_status"),
    "cost_category":    ("Cost category", "cost_category"),
}

# ---------------------------------------------------------------------------
# Entities and their own columns
# ---------------------------------------------------------------------------

def _a(label: str, category: str, type_: str = "text", unit: str = "", decimals: Optional[int] = None) -> dict:
    return {"label": label, "category": category, "type": type_, "unit": unit, "decimals": decimals}


_VEHICLE_ATTRS = {
    "vehicle": _a("Vehicle", "Vehicle"), "registration": _a("Registration", "Vehicle"), "imei": _a("IMEI", "Vehicle"),
    "vehicle_group": _a("Vehicle group", "Vehicle"),
}

# key: (label, kind, analytics dimension, own columns, parameters, default columns)
ENTITIES: dict = {
    "trip": ("Trip", "record", "trip", {
        "start_time": _a("Trip start", "Trip", "datetime"), "end_time": _a("Trip end", "Trip", "datetime"),
        **_VEHICLE_ATTRS, "driver": _a("Driver", "Driver"), "driver_key": _a("Driver from key", "Driver"),
        "start_location": _a("Start location", "Trip"), "end_location": _a("End location", "Trip"),
        "start_lat": _a("Start latitude", "Trip", "number", decimals=5), "start_lng": _a("Start longitude", "Trip", "number", decimals=5),
        "end_lat": _a("End latitude", "Trip", "number", decimals=5), "end_lng": _a("End longitude", "Trip", "number", decimals=5),
        "start_link": _a("Start location link", "Trip", "link"), "end_link": _a("End location link", "Trip", "link"),
        "start_odometer": _a("Start odometer", "Trip", "number", "km", 1), "end_odometer": _a("End odometer", "Trip", "number", "km", 1),
        "avg_speed": _a("Average speed", "Trip", "number", "km/h", 0), "close_reason": _a("Ended by", "Trip"),
    }, ["date_range", "vehicle", "vehicle_group", "driver"], ["a:start_time", "a:end_time", "a:vehicle"]),
    "event": ("Event", "record", None, {
        "time": _a("Event timestamp", "Event", "datetime"), **_VEHICLE_ATTRS, "driver": _a("Driver", "Driver"),
        "event": _a("Event", "Event"), "speed": _a("Speed", "Event", "number", "km/h", 0),
        "over_speed": _a("Speed at speeding (IO 255)", "Event", "number", "km/h", 0),
        "lat": _a("Latitude", "Event", "number", decimals=5), "lng": _a("Longitude", "Event", "number", decimals=5),
        "location": _a("Location", "Event"), "link": _a("Location link", "Event", "link"),
        "odometer": _a("Odometer", "Event", "number", "km", 1), "ignition": _a("Ignition", "Event"),
        "voltage": _a("External voltage", "Event", "number", "V", 2),
    }, ["date_range", "vehicle", "vehicle_group", "driver", "event_type", "trip_events_only"], ["a:time", "a:vehicle", "a:event"]),
    "vehicle": ("Vehicle", "aggregate", "vehicle", {
        **_VEHICLE_ATTRS, "make": _a("Make", "Vehicle"), "model": _a("Model", "Vehicle"), "year": _a("Year", "Vehicle"),
        "vehicle_type": _a("Vehicle type", "Vehicle"), "driver": _a("Assigned driver", "Driver"),
        "fuel_consumption": _a("Travelling consumption", "Vehicle", "number", "L/100 km", 1),
        "licence_start": _a("Licence start", "Vehicle", "date"), "licence_expires": _a("Licence expires", "Vehicle", "date"),
        "last_seen": _a("Last seen", "Vehicle", "datetime"),
    }, ["date_range", "vehicle", "vehicle_group"], ["a:vehicle", "a:registration"]),
    "driver": ("Driver", "aggregate", "driver", {
        "driver": _a("Driver", "Driver"), "first_name": _a("First name", "Driver"), "last_name": _a("Last name", "Driver"),
        "employee_number": _a("Employee number", "Driver"), "key_code": _a("Driver key code", "Driver"),
        "phone": _a("Phone", "Driver"), "vehicles": _a("Assigned vehicles", "Driver"),
    }, ["date_range", "vehicle_group", "driver"], ["a:driver", "a:employee_number"]),
    "vehicle_group": ("Vehicle group", "aggregate", "vehicle_group", {"vehicle_group": _a("Vehicle group", "Vehicle group")},
                      ["date_range", "vehicle_group"], ["a:vehicle_group"]),
    "day": ("Date - Day", "aggregate", "day", {"period": _a("Day", "Date")}, ["date_range", "vehicle", "vehicle_group"], ["a:period"]),
    "week": ("Date - Week", "aggregate", "week", {"period": _a("Week", "Date")}, ["date_range", "vehicle", "vehicle_group"], ["a:period"]),
    "month": ("Date - Month", "aggregate", "month", {"period": _a("Month", "Date")}, ["date_range", "vehicle", "vehicle_group"], ["a:period"]),
    "place_visit": ("Place vehicle entry exit", "record", "place_visit", {
        **_VEHICLE_ATTRS, "place": _a("Place", "Place"), "entered": _a("Entered", "Place", "datetime"),
        "exited": _a("Exited", "Place", "datetime"),
    }, ["date_range", "vehicle", "vehicle_group", "place"], ["a:place", "a:vehicle", "a:entered", "a:exited"]),
    "alert": ("Alert", "record", None, {
        "time": _a("Time", "Alert", "datetime"), "type": _a("Alert type", "Alert"), "title": _a("Title", "Alert"),
        "message": _a("Message", "Alert"), **_VEHICLE_ATTRS, "read": _a("Read", "Alert"), "read_by": _a("Read by", "Alert"),
        "read_at": _a("Read at", "Alert", "datetime"), "notes": _a("Notes", "Alert"),
    }, ["date_range", "vehicle", "vehicle_group", "alert_type"], ["a:time", "a:type", "a:vehicle", "a:title"]),
    "maintenance_job": ("Maintenance job", "record", None, {
        **_VEHICLE_ATTRS, "description": _a("Description", "Maintenance"), "type": _a("Maintenance type", "Maintenance"),
        "status": _a("Status", "Maintenance"), "planned_start": _a("Planned start", "Maintenance", "datetime"),
        "actual_start": _a("Actual start", "Maintenance", "datetime"), "actual_end": _a("Actual end", "Maintenance", "datetime"),
        "odometer": _a("Odometer", "Maintenance", "number", "km", 0), "workshop": _a("Workshop", "Maintenance"),
        "reference": _a("Reference number", "Maintenance"), "cost": _a("Cost", "Maintenance", "number", "R", 2),
    }, ["date_range", "vehicle", "vehicle_group", "job_status"], ["a:vehicle", "a:description", "a:status", "a:planned_start"]),
    "cost_item": ("Cost item", "record", None, {
        "date": _a("Date", "Cost", "date"), **_VEHICLE_ATTRS, "category": _a("Category", "Cost"),
        "item": _a("Maintenance item", "Cost"), "maintenance": _a("Maintenance", "Cost"), "description": _a("Description", "Cost"),
        "amount": _a("Cost", "Cost", "number", "R", 2), "cost_centre": _a("Cost centre", "Cost"),
    }, ["date_range", "vehicle", "vehicle_group", "cost_category"], ["a:date", "a:vehicle", "a:description", "a:amount"]),
}


def entity_list() -> list:
    return [{"key": k, "label": v[0], "kind": v[1], "parameters": v[4], "default_columns": v[5]} for k, v in ENTITIES.items()]


def _measure_keys(entity: str) -> list:
    dim = ENTITIES[entity][2]
    return an.allowed_measures(dim) if dim else []


def columns_for(entity: str, expressions: dict) -> list:
    """Every column the entity offers: its fields, then measures and expressions that fit it."""
    out = [{"key": f"a:{k}", **v} for k, v in ENTITIES[entity][3].items()]
    allowed = set(_measure_keys(entity))
    for k in _measure_keys(entity):
        label, unit, category, decimals = an.MEASURES[k]
        out.append({"key": f"m:{k}", "label": label, "category": category, "type": "number", "unit": unit, "decimals": decimals})
    for eid, (name, text, decimals, unit) in expressions.items():
        try:
            fits = allowed and an.measures_used(text) <= allowed
        except an.ExpressionError:
            fits = False
        if fits:
            out.append({"key": f"expr:{eid}", "label": name, "category": "Expressions", "type": "number", "unit": unit or "",
                        "decimals": 2 if decimals is None else decimals, "expression": True})
    return out


# ---------------------------------------------------------------------------
# Rows
# ---------------------------------------------------------------------------

def _utc(dt):
    return dt if dt is None or dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def _link(lat, lng) -> Optional[str]:
    return f"https://maps.google.com/?q={lat:.6f},{lng:.6f}" if lat is not None and lng is not None else None


def _vehicles(db: Session, group_id, only: Optional[set], params: dict) -> dict:
    """{imei: tag info} the report covers (user's scope, then the Vehicle / Vehicle group parameters)."""
    out = {}
    for tag in db.query(BLETag).filter(BLETag.attributes.op("->>")("_created_usergroup_id") == str(group_id)):
        if only is not None and tag.imei not in only:
            continue
        attrs = tag.attributes or {}
        val = lambda k: ((attrs.get(k) or {}).get("value") if isinstance(attrs.get(k), dict) else None)  # noqa: E731
        if params.get("vehicle") and tag.imei != params["vehicle"]:
            continue
        if params.get("vehicle_group") and val("category") != params["vehicle_group"]:
            continue
        out[tag.imei] = {"tag": tag, "attrs": attrs, "vehicle": tag.description or tag.device_name or tag.imei,
                         "registration": val("registration"), "imei": tag.imei, "vehicle_group": val("category"),
                         "driver": val("driver"), "driver_id": val("driver_id")}
    return out


def _vehicle_cols(v: Optional[dict]) -> dict:
    v = v or {}
    return {k: v.get(k) for k in ("vehicle", "registration", "imei", "vehicle_group")}


def _expr_values(expressions: dict, measures: list, values: dict) -> dict:
    out = {}
    for key in measures:
        if key.startswith("expr:"):
            try:
                out[key] = an.evaluate(an.parse(expressions[key[5:]][1]), values)
            except (KeyError, an.ExpressionError):
                out[key] = None
        else:
            out[key] = values.get(key[2:])
    return out


def _trip_rows(db, group_id, vehicles, start, end, tz, params, measures, expressions) -> list:
    from app.services import drivers_service, fleet_settings_service, time_profiles, vehicle_fuel
    from app.services.address_service import Describer
    if not vehicles:
        return []
    settings = fleet_settings_service.get(db, group_id)
    by_id, default = time_profiles.profiles(db, group_id)
    names = drivers_service.names(db, group_id)
    q = (db.query(Trip).filter(Trip.usergroup_id == group_id, Trip.imei.in_(list(vehicles)), Trip.real(),
                               Trip.started_at >= start, Trip.started_at < end).order_by(Trip.started_at).limit(MAX_ROWS))
    rows = []
    trips = q.all()
    describe = Describer(db, group_id).prefetch(
        [(t.start_latitude, t.start_longitude) for t in trips] + [(t.end_latitude, t.end_longitude) for t in trips])
    where = lambda address, lat, lng: describe(lat, lng, address) if address is not None else None
    for t in trips:
        v = vehicles[t.imei]
        driver_id = str(t.driver_id) if t.driver_id else v["driver_id"]
        if params.get("driver") and driver_id != params["driver"]:
            continue
        values = an._trip_values(t, vehicle_fuel.rate(v["attrs"]), time_profiles.for_vehicle(v["attrs"], by_id, default), tz, settings)
        values.update({"Trip_count": 1})
        rows.append({
            "a:start_time": _utc(t.started_at), "a:end_time": _utc(t.ended_at), **{f"a:{k}": x for k, x in _vehicle_cols(v).items()},
            "a:driver": names.get(driver_id) or v["driver"], "a:driver_key": "yes" if t.driver_id else "",
            "a:start_location": where(t.start_address, t.start_latitude, t.start_longitude),
            "a:end_location": where(t.end_address, t.end_latitude, t.end_longitude),
            "a:start_lat": t.start_latitude, "a:start_lng": t.start_longitude, "a:end_lat": t.end_latitude, "a:end_lng": t.end_longitude,
            "a:start_link": _link(t.start_latitude, t.start_longitude), "a:end_link": _link(t.end_latitude, t.end_longitude),
            "a:start_odometer": t.start_odometer_m / 1000 if t.start_odometer_m else None,
            "a:end_odometer": t.end_odometer_m / 1000 if t.end_odometer_m else None,
            "a:avg_speed": t.avg_speed, "a:close_reason": (t.close_reason or "").replace("_", " "),
            **_expr_values(expressions, measures, values),
        })
    return rows


def _event_rows(db, group_id, vehicles, start, end, tz, params) -> list:
    from app.dataprofiler.dictionary import EVENTS, event_label
    from app.routes_catalog import event_labels
    from app.services import address_service, drivers_service
    if not vehicles:
        return []
    custom = event_labels(db, group_id)
    names = drivers_service.names(db, group_id)
    q = db.query(DeviceEvent).filter(DeviceEvent.usergroup_id == group_id, DeviceEvent.imei.in_(list(vehicles)),
                                     DeviceEvent.recorded_at >= start, DeviceEvent.recorded_at < end)
    codes = params.get("event_type") or []
    if codes:
        q = q.filter(DeviceEvent.event_type.in_(codes))
    else:
        q = q.filter(DeviceEvent.event_type.isnot(None), DeviceEvent.event_type.notin_(["position", "parked_position"]))
    if params.get("trip_events_only"):
        q = q.filter(DeviceEvent.trip_id.isnot(None))
    events = q.order_by(DeviceEvent.recorded_at).limit(MAX_ROWS).all()
    trips = {t.id: t for t in db.query(Trip).filter(Trip.id.in_({e.trip_id for e in events if e.trip_id}))} if events else {}
    describe = address_service.Describer(db, group_id).prefetch((e.latitude, e.longitude) for e in events)
    rows = []
    for e in events:
        v, io = vehicles[e.imei], e.io or {}
        t = trips.get(e.trip_id)
        driver_id = str(t.driver_id) if t and t.driver_id else v["driver_id"]
        if params.get("driver") and driver_id != params["driver"]:
            continue
        odo, volts, over = io.get("16"), io.get("66"), io.get("255")
        rows.append({
            "a:time": _utc(e.recorded_at), **{f"a:{k}": x for k, x in _vehicle_cols(v).items()},
            "a:driver": names.get(driver_id) or v["driver"],
            "a:event": custom.get(e.event_type) or (EVENTS[e.event_type][0] if e.event_type in EVENTS else event_label(e.event_type, e.event_io_id)),
            "a:speed": e.speed, "a:over_speed": over if isinstance(over, (int, float)) and over > 0 else None,
            "a:lat": e.latitude, "a:lng": e.longitude, "a:link": _link(e.latitude, e.longitude),
            "a:location": describe(e.latitude, e.longitude),
            "a:odometer": odo / 1000 if isinstance(odo, (int, float)) else None,
            "a:ignition": None if io.get("239") is None else ("On" if io.get("239") else "Off"),
            "a:voltage": volts / 1000 if isinstance(volts, (int, float)) else None,
        })
    return rows


def _aggregate_rows(db, group_id, entity, vehicles, start, end, tz, params, measures, expressions) -> list:
    """Vehicle / driver / vehicle group / day / week / month: Analytics rows, with the entity's own fields."""
    from app.services import drivers_service, licence_service, vehicle_fuel
    from app.models_maintenance import MaintenanceLookup
    dim = ENTITIES[entity][2]
    full = an.devices_for(db, group_id, set(vehicles))   # name, group, driver, fuel rate, working hours …
    devices = {imei: full[imei] for imei in vehicles if imei in full}
    result = an.query(db, group_id, devices, start, end, tz, dimension=dim, measures=list(measures) or ["Trip_count"],
                      expressions=expressions)
    rows = []
    drivers = {d.name: d for d in db.query(Driver).filter(Driver.usergroup_id == group_id)}
    assigned = {}
    for v in vehicles.values():
        if v["driver"]:
            assigned.setdefault(v["driver"], []).append(v["vehicle"])
    types = {str(r.id): r.name for r in db.query(MaintenanceLookup).filter(MaintenanceLookup.usergroup_id == group_id,
                                                                           MaintenanceLookup.kind == "vehicle_type")}
    today = datetime.now(tz).date()
    for r in result["rows"]:
        row = {k: r["values"].get(k[2:] if k.startswith("m:") else k) for k in measures}
        if entity == "vehicle":
            v = vehicles.get(r["key"], {})
            attrs = v.get("attrs") or {}
            val = lambda k: ((attrs.get(k) or {}).get("value") if isinstance(attrs.get(k), dict) else None)  # noqa: E731
            lic = licence_service.status(licence_service.licence_start(attrs), today)
            row.update({f"a:{k}": x for k, x in _vehicle_cols(v).items()})
            row.update({"a:make": val("make"), "a:model": val("model"), "a:year": val("year"),
                        "a:vehicle_type": types.get(val("vehicle_type") or ""), "a:driver": v.get("driver"),
                        "a:fuel_consumption": vehicle_fuel.rate(attrs), "a:licence_start": lic["start"],
                        "a:licence_expires": lic["expires"], "a:last_seen": _utc(v["tag"].last_seen) if v.get("tag") else None})
        elif entity == "driver":
            d = drivers.get(r["label"])
            if params.get("driver") and (not d or str(d.id) != params["driver"]):
                continue
            row.update({"a:driver": r["label"], "a:first_name": d.first_name if d else None, "a:last_name": d.last_name if d else None,
                        "a:employee_number": d.employee_number if d else None, "a:key_code": d.key_code if d else None,
                        "a:phone": d.phone if d else None, "a:vehicles": ", ".join(assigned.get(r["label"], []))})
        elif entity == "vehicle_group":
            row["a:vehicle_group"] = r["label"]
        else:
            row["a:period"] = r["label"]
        rows.append(row)
    return rows


def _visit_rows(db, group_id, vehicles, start, end, tz, params, measures, expressions) -> list:
    from app.models import POI
    places = {}
    q = db.query(POI.id, POI.name).filter(POI.usergroup_id == group_id, POI.is_active == True)  # noqa: E712
    if params.get("place"):
        q = q.filter(POI.id == params["place"])
    places = {str(pid): name for pid, name in q}
    rows = []
    for v in an._visits(db, group_id, list(vehicles), places, start, end):
        hours = None if v.entered_at is None else max(0.0, ((_utc(v.exited_at) or datetime.now(timezone.utc)) - _utc(v.entered_at)).total_seconds() / 3600)
        rows.append({**{f"a:{k}": x for k, x in _vehicle_cols(vehicles.get(v.imei)).items()},
                     "a:place": places.get(str(v.poi_id)), "a:entered": _utc(v.entered_at), "a:exited": _utc(v.exited_at),
                     **_expr_values(expressions, measures, {"Time_in_place_hours": hours})})
    return rows


def _alert_rows(db, group_id, vehicles, start, end, tz, params) -> list:
    by_tag = {str(v["tag"].id): v for v in vehicles.values()}
    q = (db.query(PortalAlert).filter(PortalAlert.usergroup_id == str(group_id), PortalAlert.created_at >= start,
                                      PortalAlert.created_at < end))
    if params.get("alert_type"):
        q = q.filter(PortalAlert.alert_type == params["alert_type"])
    rows = []
    for a in q.order_by(PortalAlert.created_at).limit(MAX_ROWS):
        v = by_tag.get(str(a.tag_id)) if a.tag_id else None
        if a.tag_id and v is None:
            continue   # a vehicle outside the report's scope
        if v is None and (params.get("vehicle") or params.get("vehicle_group")):
            continue
        rows.append({"a:time": _utc(a.created_at), "a:type": a.alert_type.replace("_", " ").capitalize(), "a:title": a.title,
                     "a:message": a.message, **{f"a:{k}": x for k, x in _vehicle_cols(v).items()},
                     "a:read": "yes" if a.is_read else "no", "a:read_by": a.read_by, "a:read_at": _utc(a.read_at), "a:notes": a.notes})
    return rows


def _job_rows(db, group_id, vehicles, start, end, tz, params) -> list:
    from app.models_maintenance import VehicleMaintenance
    from app.services import maintenance_service as ms
    fleet = {imei: {"name": v["vehicle"], "tag_id": str(v["tag"].id), "group": v["vehicle_group"], "type_id": None}
             for imei, v in vehicles.items()}
    types, workshops, schedules = ms.lookups(db, group_id)
    jobs = (db.query(VehicleMaintenance).filter(VehicleMaintenance.usergroup_id == group_id,
                                                VehicleMaintenance.imei.in_(list(vehicles)),
                                                VehicleMaintenance.planned_start >= start, VehicleMaintenance.planned_start < end).all()
            if vehicles else [])
    costs = ms.job_costs(db, [j.id for j in jobs])
    out = [ms.job_row(j, fleet, types, workshops, schedules, costs) for j in jobs]
    for imei, v in vehicles.items():
        fleet[imei]["type_id"] = ms.vehicle_type_id(v["attrs"])
    for s, t, imei, occ in ms.projections(db, group_id, fleet):
        r = ms.projected_row(s, t, imei, occ, fleet)
        if occ.status == "Overdue" or (occ.planned and start.date() <= occ.planned < end.date()):
            out.append(r)
    rows = []
    for r in out:
        if params.get("job_status") and r["status"] != params["job_status"]:
            continue
        dt = lambda x: datetime.fromisoformat(x) if x else None  # noqa: E731
        rows.append({**{f"a:{k}": x for k, x in _vehicle_cols(vehicles.get(r["imei"])).items()},
                     "a:description": r["description"], "a:type": r["type"], "a:status": r["status"],
                     "a:planned_start": dt(r["planned_start"]), "a:actual_start": dt(r["actual_start"]),
                     "a:actual_end": dt(r["actual_end"]), "a:odometer": r["odometer_km"], "a:workshop": r["workshop"],
                     "a:reference": r["reference"], "a:cost": r["cost"]})
    return rows


def _cost_rows(db, group_id, vehicles, start, end, tz, params) -> list:
    from app.models_maintenance import COST_CATEGORIES, MaintenanceCost, MaintenanceItem, MaintenanceLookup, VehicleMaintenance
    if not vehicles:
        return []
    d0, d1 = start.astimezone(tz).date(), (end - timedelta(seconds=1)).astimezone(tz).date()
    q = db.query(MaintenanceCost).filter(MaintenanceCost.usergroup_id == group_id, MaintenanceCost.imei.in_(list(vehicles)),
                                         MaintenanceCost.cost_date >= d0, MaintenanceCost.cost_date <= d1)
    if params.get("cost_category"):
        q = q.filter(MaintenanceCost.category == params["cost_category"])
    items = {i.id: i.name for i in db.query(MaintenanceItem).filter(MaintenanceItem.usergroup_id == group_id)}
    centres = {c.id: c.name for c in db.query(MaintenanceLookup).filter(MaintenanceLookup.usergroup_id == group_id)}
    jobs = {j.id: j.description for j in db.query(VehicleMaintenance).filter(VehicleMaintenance.usergroup_id == group_id)}
    return [{"a:date": c.cost_date, **{f"a:{k}": x for k, x in _vehicle_cols(vehicles.get(c.imei)).items()},
             "a:category": COST_CATEGORIES.get(c.category or "maintenance"), "a:item": items.get(c.item_id),
             "a:maintenance": jobs.get(c.maintenance_id), "a:description": c.description, "a:amount": float(c.amount),
             "a:cost_centre": centres.get(c.cost_centre_id)}
            for c in q.order_by(MaintenanceCost.cost_date).limit(MAX_ROWS)]


# ---------------------------------------------------------------------------
# Run
# ---------------------------------------------------------------------------

OPS: dict = {"gt": lambda v, a, b: v > a, "lt": lambda v, a, b: v < a, "ge": lambda v, a, b: v >= a,
             "le": lambda v, a, b: v <= a, "eq": lambda v, a, b: v == a, "between": lambda v, a, b: a <= v <= b}
OP_LABELS = {"gt": "greater than", "lt": "less than", "ge": "greater than or equal", "le": "less than or equal",
             "eq": "equal", "between": "between"}


class ReportError(ValueError):
    pass


def check_values(report, values: dict) -> None:
    """Required parameters and column filters must have values."""
    for p in report.parameters or []:
        v = values.get(p["key"])
        if p.get("required") and (v is None or v == "" or v == []):
            raise ReportError(f"{PARAMETERS.get(p['key'], (p['key'],))[0]} is required")
    for f in report.column_filters or []:
        given = (values.get("filters") or {}).get(f["column"]) or {}
        if f.get("required") and given.get("value") in (None, ""):
            raise ReportError("A required column filter has no value")


def build(db: Session, report, values: dict, start: datetime, end: datetime, tz: ZoneInfo,
          only: Optional[set] = None, expressions: Optional[dict] = None, limit: Optional[int] = None) -> tuple:
    """(columns [{key, title, unit, type, decimals, sort, format}], rows [{key: raw value}]) of a report run."""
    entity = report.row_entity
    if entity not in ENTITIES:
        raise ReportError("Unknown row type")
    expressions = expressions or {}
    catalog = {c["key"]: c for c in columns_for(entity, expressions)}
    cols = []
    for c in report.columns or []:
        meta = catalog.get(c.get("key"))
        if not meta:
            continue   # e.g. an expression that was deleted
        cols.append({"key": c["key"], "title": c.get("title") or meta["label"], "unit": meta.get("unit") or "",
                     "type": meta["type"], "decimals": c.get("decimals") if c.get("decimals") is not None else meta.get("decimals"),
                     "show_unit": bool(c.get("show_unit")), "sort": c.get("sort"), "format": c.get("format")})
    if not cols:
        raise ReportError("Add at least one column")
    params = {k: values.get(k) for k in PARAMETERS}
    allowed_params = set(ENTITIES[entity][4])
    params = {k: v for k, v in params.items() if k in allowed_params}
    vehicles = _vehicles(db, report.usergroup_id, only, params)
    measures = [c["key"] for c in cols if not c["key"].startswith("a:")]
    measures += [f["column"] for f in report.column_filters or [] if not f["column"].startswith("a:") and f["column"] not in measures]
    expr_by_id, expr_measures = expressions, measures
    g = report.usergroup_id
    kind = ENTITIES[entity][1]
    if entity == "trip":
        rows = _trip_rows(db, g, vehicles, start, end, tz, params, expr_measures, expr_by_id)
    elif entity == "event":
        rows = _event_rows(db, g, vehicles, start, end, tz, params)
    elif entity == "place_visit":
        rows = _visit_rows(db, g, vehicles, start, end, tz, params, expr_measures, expr_by_id)
    elif entity == "alert":
        rows = _alert_rows(db, g, vehicles, start, end, tz, params)
    elif entity == "maintenance_job":
        rows = _job_rows(db, g, vehicles, start, end, tz, params)
    elif entity == "cost_item":
        rows = _cost_rows(db, g, vehicles, start, end, tz, params)
    else:
        analytics_keys = [m[2:] if m.startswith("m:") else m for m in measures]
        rows = _aggregate_rows(db, g, entity, vehicles, start, end, tz, params, analytics_keys, expr_by_id)
        for r in rows:   # analytics keys back to column keys
            for m in measures:
                if m.startswith("m:"):
                    r[m] = r.pop(m[2:], None)
    # Column filters: numeric, from the run's values
    for f in report.column_filters or []:
        given = (values.get("filters") or {}).get(f["column"]) or {}
        a, b = given.get("value"), given.get("value2")
        if a in (None, ""):
            continue
        op = OPS.get(f.get("op") or given.get("op") or "gt")
        try:
            a, b = float(a), (float(b) if b not in (None, "") else None)
        except (TypeError, ValueError):
            raise ReportError("Column filter values must be numbers")
        if f.get("op") == "between" and b is None:
            raise ReportError("“between” needs two values")
        rows = [r for r in rows if isinstance(r.get(f["column"]), (int, float)) and op(r[f["column"]], a, b)]
    # Sort: each column with a sort, in column order (the first is the main sort)
    for c in reversed([c for c in cols if c["sort"] in ("asc", "desc")]):   # stable sorts: the first column wins
        k = c["key"]
        rows.sort(key=lambda r: (r.get(k) is None or r.get(k) == "",
                                 _asc(r.get(k)) if c["sort"] == "asc" else _neg(r.get(k))))
    if report.top_n:
        rows = rows[: report.top_n]
    if limit:
        rows = rows[:limit]
    return cols, rows


def _asc(v):
    """Sort key for ascending order: numbers, dates and text each compare among themselves."""
    if v is None:
        return 0
    if isinstance(v, datetime):
        return v.timestamp()
    if isinstance(v, date):
        return v.toordinal()
    if isinstance(v, str):
        return tuple(ord(ch) for ch in v.lower())
    return v


def _neg(v):
    """Sort key for descending order of numbers, dates and text."""
    if v is None:
        return 0
    if isinstance(v, (int, float)):
        return -v
    if isinstance(v, datetime):
        return -v.timestamp()
    if isinstance(v, date):
        return -v.toordinal()
    return tuple(-ord(ch) for ch in str(v).lower()) + (1,)   # a longer word after its prefix, as in reverse order


# ---------------------------------------------------------------------------
# Output: values as shown, conditional colours, file
# ---------------------------------------------------------------------------

def display(value, col: dict, tz: ZoneInfo):
    """A value as it goes into the file: local dates, rounded numbers (unit appended when asked)."""
    if value is None:
        return ""
    if isinstance(value, datetime):
        return value.astimezone(tz).strftime("%Y-%m-%d %H:%M")
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        d = col.get("decimals")
        v = round(value, d if d is not None else 2)
        v = int(v) if d == 0 else v
        return f"{v} {col['unit']}" if col.get("show_unit") and col.get("unit") else v
    return str(value)


def colours(cols: list, rows: list) -> list:
    """Per row: {"row": (bg, fg) or None, "cells": {col index: (bg, fg)}} from the columns' conditional formats."""
    out = []
    peaks = {i: max([abs(r.get(c["key"])) for r in rows if isinstance(r.get(c["key"]), (int, float))] or [0])
             for i, c in enumerate(cols) if c.get("format")}
    for r in rows:
        row_style, cells = None, {}
        for i, c in enumerate(cols):
            fmt = c.get("format") or {}
            if not fmt:
                continue
            v = r.get(c["key"])
            colour = None
            if v is None or v == "":
                colour = fmt.get("empty_color")
            elif isinstance(v, (int, float)):
                x = v / peaks[i] * 100 if fmt.get("compare") == "percentage" and peaks[i] else v
                for rng in fmt.get("ranges") or []:
                    lo, hi = rng.get("min"), rng.get("max")
                    if (lo is None or x >= lo) and (hi is None or x <= hi):
                        colour = rng.get("color")
                        break
            if not colour:
                continue
            target = fmt.get("apply_to") or "cell_bg"
            style = (colour, None) if target.endswith("bg") else (None, colour)
            if target.startswith("row"):
                row_style = style
            else:
                cells[i] = style
        out.append({"row": row_style, "cells": cells})
    return out


def file_name(template: Optional[str], title: str, start: datetime, end: datetime, tz: ZoneInfo, ext: str) -> str:
    """{StartDate}, {EndDate}, {ReportDate}, optionally {StartDate:dd.mm.yyyy}."""
    template = template or "{Title}_{StartDate}_{EndDate}"
    dates = {"StartDate": start.astimezone(tz), "EndDate": (end - timedelta(seconds=1)).astimezone(tz),
             "ReportDate": datetime.now(tz)}

    def fmt(match):
        name, pattern = match.group(1), match.group(2)
        if name == "Title":
            return title
        if name not in dates:
            return match.group(0)
        if not pattern:
            return dates[name].strftime("%Y-%m-%d")
        py = (pattern.replace("yyyy", "%Y").replace("yy", "%y").replace("dd", "%d").replace("HH", "%H")
              .replace("mm", "%m").replace("MM", "%m").replace("nn", "%M"))
        return dates[name].strftime(py)

    name = re.sub(r"\{(\w+)(?::([^}]+))?\}", fmt, template)
    name = re.sub(r"[^\w.\- ]+", "_", name).strip().replace(" ", "_") or "report"
    return f"{name[:150]}.{ext}"


def render(report, cols: list, rows: list, tz: ZoneInfo, subtitle: str, logo: Optional[str], parameters_text: str) -> tuple:
    """(bytes, mime, extension) in the report's format, with conditional colours (Excel, PDF)."""
    from app.services import reports_service
    spec = report.file or {}
    fmt = spec.get("format") or "xlsx"
    headers = [f"{c['title']} ({c['unit']})" if c["unit"] and not c["show_unit"] and c["type"] == "number" else c["title"] for c in cols]
    values = [[display(r.get(c["key"]), c, tz) for c in cols] for r in rows]
    styles = colours(cols, rows)
    if fmt == "csv":
        import csv
        buf = io.StringIO()
        sep = {"semicolon": ";", "tab": "\t"}.get(spec.get("csv_separator") or "comma", ",")
        writer = csv.writer(buf, delimiter=sep)
        writer.writerow(headers)
        writer.writerows(values)
        return buf.getvalue().encode("utf-8-sig"), "text/csv", "csv"
    if spec.get("include_parameters") and parameters_text:
        subtitle = f"{subtitle} · {parameters_text}"
    return reports_service.to_file(report.title, headers, values, fmt, subtitle=subtitle, logo=logo, styles=styles,
                                   orientation=spec.get("orientation") or "landscape")


def zip_file(content: bytes, name: str) -> tuple:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr(name, content)
    return buf.getvalue(), "application/zip", name.rsplit(".", 1)[0] + ".zip"
