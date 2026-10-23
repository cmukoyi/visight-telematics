"""Public API v2 — vehicles, trips, events, places, reports and analytics (documented at /docs).

Every endpoint takes the bearer token from POST /api/auth/login and answers
exactly what that user may see in the web app: their user group, the vehicles
in their security group, and only what their roles allow (e.g. trips need
"Trips and routes"). Responses are the same data the web app uses, so the API
grows with the platform.
"""
from datetime import datetime
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, Query, Request
from fastapi.security import HTTPBearer
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.database import get_db
from app import routes_analytics, routes_fleet, routes_portal

bearer = HTTPBearer(auto_error=False, description="The access_token from POST /api/auth/login")
router = APIRouter(prefix="/api/v2", dependencies=[Depends(bearer)])

DT = "ISO 8601 date-time, e.g. 2026-10-01T00:00:00+02:00"


# ---------------------------------------------------------------------------
# Response models (for the docs; the data is the web app's)
# ---------------------------------------------------------------------------

class Me(BaseModel):
    id: str
    email: str
    first_name: Optional[str] = None
    last_name: Optional[str] = None
    usergroup: Optional[str] = Field(None, description="The user group (company) the user belongs to")
    roles: List[str] = []
    permissions: List[str] = Field([], description="Features the user's roles allow")
    is_admin: bool = False
    security_group: Optional[str] = Field(None, description="Whose vehicles the user sees (none = all, for administrators)")
    language: Optional[str] = None


class Vehicle(BaseModel):
    id: str
    imei: str
    name: str = Field(..., description="The vehicle's description, or its device name")
    device_model: Optional[str] = None
    vehicle_group: Optional[str] = None
    registration: Optional[str] = None
    make: Optional[str] = None
    model: Optional[str] = None
    year: Optional[str] = None
    driver: Optional[str] = None
    status: str = Field(..., description="active | idle | offline")
    last_seen: Optional[datetime] = None
    latitude: Optional[float] = None
    longitude: Optional[float] = None


class Trip(BaseModel):
    id: str
    imei: str
    device_name: Optional[str] = None
    driver: Optional[str] = None
    status: str = Field(..., description="open (in progress) | closed")
    started_at: datetime
    ended_at: Optional[datetime] = None
    start_address: Optional[str] = None
    end_address: Optional[str] = None
    start: Optional[List[float]] = Field(None, description="[latitude, longitude]")
    end: Optional[List[float]] = Field(None, description="[latitude, longitude]")
    distance_m: int
    duration_s: int
    max_speed: int = Field(..., description="km/h")
    avg_speed: Optional[float] = Field(None, description="km/h")
    speeding_count: int
    harsh_acceleration_count: int
    harsh_braking_count: int
    harsh_cornering_count: int
    idling_count: int


class TripEvent(BaseModel):
    id: int
    code: Optional[str] = Field(None, description="Event code, see GET /api/v2/event-types")
    label: str
    kind: str
    recorded_at: datetime
    latitude: Optional[float] = None
    longitude: Optional[float] = None
    speed: Optional[int] = None
    io: List[Dict[str, Any]] = Field([], description="Decoded readings (name, value, display)")


class TripDetail(Trip):
    points: List[List[Any]] = Field([], description="Route: [latitude, longitude, speed km/h, recorded_at]")
    events: List[TripEvent] = []


class Event(TripEvent):
    imei: str
    device_name: Optional[str] = None
    trip_id: Optional[str] = None
    odometer_km: Optional[float] = None


class EventPage(BaseModel):
    rows: List[Event]
    next_before_id: Optional[int] = Field(None, description="Pass as before_id to get the next (older) page; null when there are no more")


class Place(BaseModel):
    id: str
    name: str
    description: Optional[str] = None
    address: Optional[str] = None
    latitude: float
    longitude: float
    radius: Optional[float] = Field(None, description="Metres (circles)")
    shape_type: Optional[str] = Field(None, description="circle | polygon")
    coordinates: Optional[str] = Field(None, description="Polygon corners as JSON [[lat, lng], ...]")
    place_group_id: Optional[str] = None


class ReportInfo(BaseModel):
    key: str
    title: str
    category: Optional[str] = None
    description: Optional[str] = None


class ReportResult(BaseModel):
    columns: List[str]
    rows: List[List[Any]]


class AnalyticsQuery(BaseModel):
    date_from: datetime = Field(..., description=DT)
    date_to: datetime = Field(..., description=DT)
    dimension: str = Field("", description="'' (total), vehicle, vehicle_group, driver, day, week, month, hour, weekday")
    measures: List[str] = Field(..., description="Measure keys (GET /api/v2/analytics/catalog) or expr:<id> for your Expressions",
                                examples=[["Trip_count", "Trip_distance_km"]])
    category: Optional[str] = Field(None, description="Only this vehicle group")
    imei: Optional[str] = Field(None, description="Only this vehicle")
    sort: Optional[str] = None
    descending: bool = True
    limit: Optional[int] = None


# ---------------------------------------------------------------------------
# Account
# ---------------------------------------------------------------------------

@router.get("/me", response_model=Me, tags=["Account"], summary="Who the token belongs to")
def me(request: Request, db: Session = Depends(get_db)):
    """The signed-in user, their roles and permissions, and their security group."""
    from app.models import UserGroup
    from app.services import access_service
    user = routes_portal.get_portal_user_from_request(request, db)
    profile = access_service.profile(db, access_service.for_user(user, db))
    group = db.get(UserGroup, user.usergroup_id)
    return Me(id=str(user.id), email=user.email, first_name=user.first_name, last_name=user.last_name,
              usergroup=group.name if group else None, roles=profile["role_names"], permissions=profile["permissions"],
              is_admin=profile["is_admin"], security_group=profile["security_group_name"], language=profile.get("language"))


# ---------------------------------------------------------------------------
# Vehicles
# ---------------------------------------------------------------------------

@router.get("/vehicles", response_model=List[Vehicle], tags=["Vehicles"], summary="List vehicles")
def vehicles(request: Request, db: Session = Depends(get_db)):
    """Every vehicle the user may see, with its details and last known position.

    ```bash
    curl https://track.visighttelematics.co.za/api/v2/vehicles -H "Authorization: Bearer $TOKEN"
    ```
    """
    rows = routes_portal.list_group_tags(request, db)
    out = []
    for t in rows:
        t = t.model_dump() if hasattr(t, "model_dump") else dict(t)
        attrs = t.get("attributes") or {}
        val = lambda k: ((attrs.get(k) or {}).get("value") or None)  # noqa: E731
        lat, lng = t.get("latitude"), t.get("longitude")
        out.append(Vehicle(id=str(t["id"]), imei=t["imei"], name=t.get("description") or t.get("device_name") or t["imei"],
                           device_model=t.get("device_model"), vehicle_group=t.get("category_name"),
                           registration=val("registration"), make=val("make"), model=val("model"), year=val("year"),
                           driver=val("driver"), status=t.get("activity_status") or "offline", last_seen=t.get("last_seen"),
                           latitude=float(lat) if lat not in (None, "") else None, longitude=float(lng) if lng not in (None, "") else None))
    return out


@router.get("/fleet-status", tags=["Vehicles"], summary="Every vehicle's latest event and address")
def fleet_status(request: Request, db: Session = Depends(get_db)):
    """Latest event, speed, ignition, odometer and street address for every vehicle the user may see."""
    return routes_fleet.fleet_status(request, db)


@router.get("/vehicles/{imei}/status", tags=["Vehicles"], summary="A vehicle's current status and readings")
def vehicle_status(imei: str, request: Request, db: Session = Depends(get_db)):
    """Position and address, ignition, speed, odometer, voltages, GSM signal, satellites, SIM, last event and today's totals."""
    return routes_fleet.vehicle_status(request, db, imei=imei)


@router.get("/vehicles/{imei}/live", tags=["Vehicles"], summary="Live position and trail")
def vehicle_live(imei: str, request: Request, db: Session = Depends(get_db),
                 trail_minutes: int = Query(60, ge=5, le=720, description="Trail length when not on a trip")):
    """The latest position, speed, heading and ignition, the current trip (if any) and its trail as [lat, lng] pairs.
    Needs the "Follow a vehicle live" feature."""
    return routes_fleet.live(request, db, imei=imei, trail_minutes=trail_minutes)


# ---------------------------------------------------------------------------
# Trips and events
# ---------------------------------------------------------------------------

@router.get("/trips", response_model=List[Trip], tags=["Trips"], summary="List trips")
def trips(request: Request, db: Session = Depends(get_db),
          date_from: Optional[datetime] = Query(None, description=f"Trips that started at or after this. {DT}"),
          date_to: Optional[datetime] = Query(None, description="Trips that started before this"),
          imei: Optional[str] = Query(None, description="Only this vehicle"),
          limit: int = Query(200, ge=1, le=1000)):
    """Trips, newest first, with distance, duration, speeds, exception counts and reverse-geocoded start/end addresses.

    ```bash
    curl "https://track.visighttelematics.co.za/api/v2/trips?date_from=2026-10-01T00:00:00Z" -H "Authorization: Bearer $TOKEN"
    ```
    """
    return routes_portal.list_trips(request, db, imei=imei, date_from=date_from, date_to=date_to, limit=limit)


@router.get("/trips/{trip_id}", response_model=TripDetail, tags=["Trips"], summary="One trip with its route and events")
def trip(trip_id: str, request: Request, db: Session = Depends(get_db)):
    """The trip, every route point (lat, lng, speed, time) and the events during it (ignition, speeding, harsh driving…)."""
    return routes_portal.get_trip(trip_id, request, db)


@router.get("/events", response_model=EventPage, tags=["Events"], summary="List events")
def events(request: Request, db: Session = Depends(get_db),
           date_from: Optional[datetime] = Query(None, description=DT),
           date_to: Optional[datetime] = Query(None, description=DT),
           imei: Optional[str] = Query(None, description="Only this vehicle"),
           codes: Optional[str] = Query(None, description="Comma-separated event codes, e.g. overspeed,harsh_braking"),
           include_parked: bool = Query(False, description="Include parked position reports"),
           before_id: Optional[int] = Query(None, description="Paging: next_before_id from the previous page"),
           limit: int = Query(500, ge=1, le=5000)):
    """Decoded device events, newest first, with their readings. Page with before_id.

    ```bash
    curl "https://track.visighttelematics.co.za/api/v2/events?codes=overspeed&limit=100" -H "Authorization: Bearer $TOKEN"
    ```
    """
    return routes_fleet.list_events(request, db, imei=imei, date_from=date_from, date_to=date_to, codes=codes,
                                    include_parked=include_parked, before_id=before_id, limit=limit)


@router.get("/event-types", tags=["Events"], summary="Event codes and their names")
def event_types(request: Request, db: Session = Depends(get_db)):
    """Every event code we decode, with the user group's own names, grouped by category."""
    return routes_fleet.event_types(request, db)


# ---------------------------------------------------------------------------
# Places
# ---------------------------------------------------------------------------

@router.get("/places", response_model=List[Place], tags=["Places"], summary="List places (geofences)")
def places(request: Request, db: Session = Depends(get_db)):
    """The user group's places: circles (centre + radius) and polygons (corners)."""
    rows = routes_portal.list_locations(request, db)
    return [Place(**{k: (str(v) if k in ("id", "place_group_id") and v is not None else v) for k, v in dict(r).items() if k in Place.model_fields})
            for r in rows]


# ---------------------------------------------------------------------------
# Reports and analytics
# ---------------------------------------------------------------------------

@router.get("/reports", response_model=List[ReportInfo], tags=["Reports"], summary="List reports")
def reports(request: Request, db: Session = Depends(get_db)):
    return routes_fleet.report_catalogue(request, db)


@router.get("/reports/{key}", response_model=ReportResult, tags=["Reports"], summary="Run a report")
def run_report(key: str, request: Request, db: Session = Depends(get_db),
               date_from: datetime = Query(..., description=DT), date_to: datetime = Query(..., description=DT),
               imei: Optional[str] = None, category: Optional[str] = Query(None, description="Vehicle group"),
               tz: Optional[str] = Query(None, description="IANA timezone for the times in the report (default: the user group's)")):
    """The report's columns and rows for a period of up to 3 months (the same as the web app's Reports)."""
    return routes_fleet.run_report(key, request, db, date_from=date_from, date_to=date_to, imei=imei, category=category,
                                   format="json", tz=tz)


@router.get("/analytics/catalog", tags=["Analytics"], summary="Measures, dimensions and expressions")
def analytics_catalog(request: Request, db: Session = Depends(get_db)):
    """What can be asked for in POST /api/v2/analytics/query."""
    return routes_analytics.catalog(request, db)


@router.post("/analytics/query", tags=["Analytics"], summary="Measures by a dimension")
def analytics_query(data: AnalyticsQuery, request: Request, db: Session = Depends(get_db)):
    """E.g. distance and exceptions per vehicle this month, or trips per hour of day — the data behind Analytics charts.

    ```json
    {"date_from": "2026-10-01T00:00:00+02:00", "date_to": "2026-11-01T00:00:00+02:00",
     "dimension": "vehicle", "measures": ["Trip_distance_km", "Total_exception_count"]}
    ```
    """
    return routes_analytics.run_query(routes_analytics.QueryIn(**data.model_dump()), request, db)
