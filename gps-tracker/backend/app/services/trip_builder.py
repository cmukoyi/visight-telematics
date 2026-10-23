"""Trip builder — turns stored device_events into trips.

A trip is the sequence a Teltonika device reports while driving:

    trip_start → position … (overspeed, harsh_braking, …) … position → trip_end

Events are processed per device in device time, from a bookmark
(trip_builder_state.last_event_id), so the builder can run repeatedly and
pick up where it stopped; it also re-classifies each event with the current
dictionary, which back-fills older rows.

Durations: speeding_s is time between records driven above the group's speed
limit (each gap counted up to SPEED_GAP_MAX); idle_s pairs idling start / end
(IO 251), and each idle period's time beyond the excess-idle threshold adds to
excess_idle_s (fleet settings).

The trip's driver is whoever's one-wire key (IO 78) appears on it first, when
it matches a driver's key code (drivers_service); otherwise trips show the
vehicle's assigned driver.

Opening:  trip_start, or a driving position when trip_start was missed.
Closing:  trip_end, ignition_off, a parked position, a gap > MAX_GAP between
          events (closed at the last event before the gap), or nothing received
          from the device for STALE_AFTER (closed by the sweep).
"""
import logging
import math
from datetime import datetime, timedelta, timezone
from typing import Optional

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.dataprofiler.dictionary import IO_ODOMETER, classify, io_value
from app.models_dataprofiler import DeviceEvent, Trip, TripBuilderState
from app.services import drivers_service, fleet_settings_service

logger = logging.getLogger(__name__)

MAX_GAP = timedelta(minutes=30)
# A device can send two start records milliseconds apart (e.g. a driving position, then trip start);
# a trip_start this soon after the open trip began belongs to it rather than restarting it.
RESTART_GRACE = timedelta(seconds=10)
STALE_AFTER = timedelta(hours=2)
BATCH = 2000

_CLOSE_REASON = {"trip_end": "trip_end", "ignition_off": "ignition_off", "parked_position": "parked"}
_COUNTERS = {
    "overspeed": "speeding_count",
    "harsh_acceleration": "harsh_acceleration_count",
    "harsh_braking": "harsh_braking_count",
    "harsh_cornering": "harsh_cornering_count",
    "idling_start": "idling_count",
}


SPEED_GAP_MAX = timedelta(minutes=2)


def _utc(dt: datetime) -> datetime:
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def _haversine_m(lat1, lng1, lat2, lng2) -> float:
    r = 6371000.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp, dl = p2 - p1, math.radians(lng2 - lng1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))


def _open(db: Session, e: DeviceEvent, reason: str) -> Trip:
    trip = Trip(imei=e.imei, usergroup_id=e.usergroup_id, status="open", start_reason=reason,
                started_at=e.recorded_at, last_event_at=e.recorded_at, distance_m=0, duration_s=0,
                max_speed=0, point_count=0, speeding_count=0, harsh_acceleration_count=0,
                harsh_braking_count=0, harsh_cornering_count=0, idling_count=0)
    db.add(trip)
    db.flush()
    return trip


def _end_idle(trip: Trip, at: datetime, settings: Optional[dict]) -> None:
    if trip.idle_since is None:
        return
    secs = max(0, int((_utc(at) - _utc(trip.idle_since)).total_seconds()))
    limit = int((settings or {}).get("excess_idle_minutes", 5) * 60)
    trip.idle_s = (trip.idle_s or 0) + secs
    trip.excess_idle_s = (trip.excess_idle_s or 0) + max(0, secs - limit)
    trip.idle_since = None


def _durations(trip: Trip, e: DeviceEvent, code: Optional[str], settings: Optional[dict]) -> None:
    """Speeding and idle time up to this record (before last_event_at moves on)."""
    at = _utc(e.recorded_at)
    limit = (settings or {}).get("speed_limit_kmh", 120)
    if trip.last_speed is not None and trip.last_speed > limit and trip.point_count:
        gap = at - _utc(trip.last_event_at)
        if timedelta(0) < gap <= SPEED_GAP_MAX:
            trip.speeding_s = (trip.speeding_s or 0) + int(gap.total_seconds())
    if e.speed is not None:
        trip.last_speed = e.speed
    if code == "idling_start" and trip.idle_since is None:
        trip.idle_since = at
    elif code == "idling_end" or (trip.idle_since is not None and (e.speed or 0) > 5):
        _end_idle(trip, at, settings)


def _add(trip: Trip, e: DeviceEvent, code: Optional[str], settings: Optional[dict] = None) -> None:
    _durations(trip, e, code, settings)
    e.trip_id = trip.id
    trip.last_event_at = max(_utc(trip.last_event_at), _utc(e.recorded_at))
    if e.latitude is not None and e.longitude is not None:
        if trip.point_count == 0:
            trip.start_latitude, trip.start_longitude = e.latitude, e.longitude
        elif trip.end_latitude is not None and trip.start_odometer_m is None:
            # No odometer from the device: accumulate GPS distance instead.
            trip.distance_m += int(_haversine_m(trip.end_latitude, trip.end_longitude, e.latitude, e.longitude))
        trip.end_latitude, trip.end_longitude = e.latitude, e.longitude
        trip.point_count += 1
    odometer = io_value(e.io or {}, IO_ODOMETER)
    if isinstance(odometer, int) and odometer > 0:
        if trip.start_odometer_m is None:
            trip.start_odometer_m = odometer
        trip.end_odometer_m = max(trip.end_odometer_m or 0, odometer)
        trip.distance_m = trip.end_odometer_m - trip.start_odometer_m
    trip.max_speed = max(trip.max_speed or 0, e.speed or 0)
    if code in _COUNTERS:
        setattr(trip, _COUNTERS[code], getattr(trip, _COUNTERS[code]) + 1)
    trip.duration_s = int((_utc(trip.last_event_at) - _utc(trip.started_at)).total_seconds())
    trip.avg_speed = round(trip.distance_m / trip.duration_s * 3.6, 1) if trip.duration_s > 0 else None


def _close(trip: Trip, reason: str, settings: Optional[dict] = None) -> None:
    _end_idle(trip, trip.last_event_at, settings)
    trip.status = "closed"
    trip.close_reason = reason
    trip.ended_at = trip.last_event_at


def process_device(db: Session, imei: str) -> int:
    """Process the next batch of unprocessed events for one device. Does not commit."""
    state = db.get(TripBuilderState, imei)
    if state is None:
        state = TripBuilderState(imei=imei, last_event_id=0)
        db.add(state)
    events = (db.query(DeviceEvent)
              .filter(DeviceEvent.imei == imei, DeviceEvent.id > state.last_event_id)
              .order_by(DeviceEvent.recorded_at, DeviceEvent.id).limit(BATCH).all())
    if not events:
        return 0
    trip = (db.query(Trip).filter(Trip.imei == imei, Trip.status == "open")
            .order_by(Trip.started_at.desc()).first())
    keys = None   # the group's driver keys, loaded when a key first shows up
    group_id = next((e.usergroup_id for e in events if e.usergroup_id), None) or (trip.usergroup_id if trip else None)
    settings = fleet_settings_service.get(db, group_id)   # speed limit, excess-idle threshold

    for e in events:
        code = classify(e.event_io_id, e.io or {})
        if e.event_type != code:
            e.event_type = code
        at = _utc(e.recorded_at)
        if trip and at - _utc(trip.last_event_at) > MAX_GAP:
            _close(trip, "gap", settings)
            trip = None
        if trip and at < _utc(trip.started_at):
            continue  # late, buffered record from before the open trip

        if code == "trip_start" and trip and at - _utc(trip.started_at) <= RESTART_GRACE:
            _add(trip, e, code, settings)
        elif code == "trip_start":
            if trip:
                _close(trip, "restarted", settings)
            trip = _open(db, e, "trip_start")
            _add(trip, e, code, settings)
        elif code in _CLOSE_REASON:
            if trip:
                _add(trip, e, code, settings)
                _close(trip, _CLOSE_REASON[code], settings)
                trip = None
        elif code == "position" and trip is None:
            trip = _open(db, e, "implicit")
            _add(trip, e, code, settings)
        elif trip:
            _add(trip, e, code, settings)
        if trip and trip.driver_id is None and e.usergroup_id:
            key = drivers_service.normalise_key(io_value(e.io or {}, int(drivers_service.IO_DRIVER_KEY)))
            if key:
                keys = keys if keys is not None else drivers_service.key_index(db, e.usergroup_id)
                trip.driver_id = keys.get(key)

    state.last_event_id = max(state.last_event_id, max(e.id for e in events))
    return len(events)


def close_stale(db: Session, now: Optional[datetime] = None) -> int:
    """Close open trips whose device has sent nothing for STALE_AFTER. Does not commit.

    Judged by when events were stored (server time), not device time, so a
    device uploading an old backlog keeps its trip open while data arrives.
    """
    cutoff = (now or datetime.now(timezone.utc)) - STALE_AFTER
    quiet = (db.query(DeviceEvent.id)
             .filter(DeviceEvent.imei == Trip.imei, DeviceEvent.created_at >= cutoff)
             .exists())
    stale = db.query(Trip).filter(Trip.status == "open", ~quiet).all()
    for trip in stale:
        _close(trip, "stale", fleet_settings_service.get(db, trip.usergroup_id))
    return len(stale)


def run_once(db: Session) -> dict:
    """Process every device with new events, then sweep stale trips. Commits per device."""
    imeis = db.execute(text(
        "SELECT DISTINCT de.imei FROM device_events de "
        "LEFT JOIN trip_builder_state s ON s.imei = de.imei "
        "WHERE de.id > COALESCE(s.last_event_id, 0)"
    )).scalars().all()
    processed = 0
    for imei in imeis:
        while True:
            n = process_device(db, imei)
            db.commit()
            processed += n
            if n < BATCH:
                break
    closed = close_stale(db)
    db.commit()
    return {"devices": len(imeis), "events": processed, "stale_closed": closed}


def durations(events: list, settings: dict) -> tuple:
    """(speeding s, idle s, excess idle s) of a trip's events in time order — the same rules as the builder."""
    limit, excess = settings["speed_limit_kmh"], int(settings["excess_idle_minutes"] * 60)
    speeding = idle = over = 0
    prev_at = prev_speed = idle_since = None
    for e in events:
        at = _utc(e.recorded_at)
        if prev_speed is not None and prev_speed > limit and prev_at is not None:
            gap = at - prev_at
            if timedelta(0) < gap <= SPEED_GAP_MAX:
                speeding += int(gap.total_seconds())
        code = e.event_type
        if code == "idling_start" and idle_since is None:
            idle_since = at
        elif idle_since is not None and (code == "idling_end" or (e.speed or 0) > 5):
            secs = max(0, int((at - idle_since).total_seconds()))
            idle, over, idle_since = idle + secs, over + max(0, secs - excess), None
        if e.speed is not None:
            prev_speed = e.speed
        prev_at = at
    if idle_since is not None and prev_at is not None:
        secs = max(0, int((prev_at - idle_since).total_seconds()))
        idle, over = idle + secs, over + max(0, secs - excess)
    return speeding, idle, over


def recompute_recent(db: Session, days: int = 120, group_id=None) -> int:
    """Work out speeding / idle durations again for recent closed trips (after a settings change). Commits."""
    since = datetime.now(timezone.utc) - timedelta(days=days)
    cache, n = {}, 0
    q = db.query(Trip).filter(Trip.started_at >= since, Trip.status == "closed")
    if group_id is not None:
        q = q.filter(Trip.usergroup_id == group_id)
    for trip in q.all():
        if trip.usergroup_id not in cache:
            cache[trip.usergroup_id] = fleet_settings_service.get(db, trip.usergroup_id)
        settings = cache[trip.usergroup_id]
        events = (db.query(DeviceEvent).filter(DeviceEvent.trip_id == trip.id)
                  .order_by(DeviceEvent.recorded_at, DeviceEvent.id).all())
        trip.speeding_s, trip.idle_s, trip.excess_idle_s = durations(events, settings)
        trip.idle_since = None
        n += 1
    db.commit()
    return n
