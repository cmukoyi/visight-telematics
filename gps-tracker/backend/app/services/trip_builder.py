"""Trip builder — turns stored device_events into trips.

A trip is the sequence a Teltonika device reports while driving:

    trip_start → position … (overspeed, harsh_braking, …) … position → trip_end

Events are processed per device in device time, from a bookmark
(trip_builder_state.last_event_id), so the builder can run repeatedly and
pick up where it stopped; it also re-classifies each event with the current
dictionary, which back-fills older rows.

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

logger = logging.getLogger(__name__)

MAX_GAP = timedelta(minutes=30)
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
# One harsh manoeuvre can arrive as two records (event IO 253, and 243 with
# its duration). Only the first is kept as the event; a second of the same
# code this close is stored unclassified, so maps, counts, reports and
# notifications see it once.
REPEAT_WINDOW = timedelta(seconds=10)
GREEN_DRIVING = ("harsh_acceleration", "harsh_braking", "harsh_cornering")


def is_repeat(db: Session, imei: str, code: Optional[str], at: datetime, exclude_id: Optional[int] = None) -> bool:
    """True when the device already has a stored `code` event within REPEAT_WINDOW of `at`."""
    if code not in GREEN_DRIVING:
        return False
    q = db.query(DeviceEvent.id).filter(DeviceEvent.imei == imei, DeviceEvent.event_type == code,
                                        DeviceEvent.recorded_at >= at - REPEAT_WINDOW,
                                        DeviceEvent.recorded_at <= at + REPEAT_WINDOW)
    if exclude_id is not None:
        q = q.filter(DeviceEvent.id != exclude_id)
    return db.query(q.exists()).scalar()


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


def _add(trip: Trip, e: DeviceEvent, code: Optional[str]) -> None:
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


def _close(trip: Trip, reason: str) -> None:
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

    for e in events:
        code = classify(e.event_io_id, e.io or {})
        if is_repeat(db, imei, code, e.recorded_at, exclude_id=e.id):
            code = None
        if e.event_type != code:
            e.event_type = code
        at = _utc(e.recorded_at)
        if trip and at - _utc(trip.last_event_at) > MAX_GAP:
            _close(trip, "gap")
            trip = None
        if trip and at < _utc(trip.started_at):
            continue  # late, buffered record from before the open trip

        if code == "trip_start":
            if trip:
                _close(trip, "restarted")
            trip = _open(db, e, "trip_start")
            _add(trip, e, code)
        elif code in _CLOSE_REASON:
            if trip:
                _add(trip, e, code)
                _close(trip, _CLOSE_REASON[code])
                trip = None
        elif code == "position" and trip is None:
            trip = _open(db, e, "implicit")
            _add(trip, e, code)
        elif trip:
            _add(trip, e, code)

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
        _close(trip, "stale")
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
