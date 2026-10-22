"""Dashboard ingest — consumes each linked Data Exchange queue into the main database.

    python -m app.dataprofiler.dashboard_ingest

For every exchange linked to a user group, events published by the decoder
wait in the durable queue dp.exchange.<exchange_key> until this consumer
stores them. A message is acknowledged only after the database commit, so
if the dashboard is down or a write fails the events stay queued.

Stored permanently:
  device_events     every delivered event (deduplicated on dp_event_id)
  device_positions  events with a GPS fix (history / trips)
  ble_tags          the device's live location, and activation on first fix

It also runs the trip builder (app/services/trip_builder.py) every
TRIP_BUILD_INTERVAL_S, turning stored events into trips.
"""
import asyncio
import json
import logging
from datetime import datetime, timezone

import aio_pika
from sqlalchemy import text
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from app.database import SessionLocal
from app.dataprofiler import config
from app.dataprofiler.decoder import DELIVER_EXCHANGE, exchange_queue
from app.models import BLETag, DevicePosition
from app.models_admin import TagPackage
from app.models_dataprofiler import DeviceEvent
from app.services import address_service, geofence_engine, trip_builder

logger = logging.getLogger("dataprofiler.dashboard_ingest")

REFRESH_S = 60
TRIP_BUILD_INTERVAL_S = 15
IO_IGNITION = "239"


def _ts(value):
    return datetime.fromisoformat(value) if value else None


def store_delivery(db: Session, message: dict) -> int:
    """Persist one delivery message. Idempotent. Returns the number of new events."""
    imei, group_id = message["imei"], message.get("usergroup_id")
    events = message.get("events", [])
    if not events:
        return 0

    rows = [{
        "dp_event_id": e["dp_event_id"], "imei": imei, "usergroup_id": group_id,
        "recorded_at": _ts(e["recorded_at"]), "received_at": _ts(e.get("received_at")),
        "event_type": e.get("event_type"), "event_io_id": e["event_io_id"], "priority": e.get("priority"),
        "latitude": e.get("latitude"), "longitude": e.get("longitude"), "altitude": e.get("altitude"),
        "angle": e.get("angle"), "satellites": e.get("satellites"), "speed": e.get("speed"), "io": e.get("io") or {},
    } for e in events]
    inserted = db.execute(
        pg_insert(DeviceEvent.__table__).values(rows)
        .on_conflict_do_nothing(index_elements=["dp_event_id"])
        .returning(DeviceEvent.__table__.c.dp_event_id)
    ).scalars().all()

    fixes = [r for r in rows if r["latitude"] is not None and r["longitude"] is not None]
    new_ids = set(inserted)
    if fixes:
        db.execute(pg_insert(DevicePosition.__table__).values([{
            "device_imei": imei, "lat": r["latitude"], "lng": r["longitude"],
            "observed_at": r["recorded_at"], "direction": r["angle"],
            "gps_speed": float(r["speed"] or 0), "satellite": r["satellites"],
            "ignition": None if r["io"].get(IO_IGNITION) is None else ("ON" if r["io"][IO_IGNITION] else "OFF"),
            "pos_type": 1, "source": "teltonika",
        } for r in fixes]).on_conflict_do_nothing(index_elements=["device_imei", "observed_at"]))
        tag = _update_tag_location(db, imei, max(fixes, key=lambda r: r["recorded_at"]))
        new_fixes = [r for r in fixes if r["dp_event_id"] in new_ids]
        if tag is not None and new_fixes:
            geofence_engine.check_positions(db, tag, new_fixes)
    return len(inserted)


def _update_tag_location(db: Session, imei: str, r: dict):
    """Move the device to its newest fix. Returns the tag (None if the device isn't on the dashboard)."""
    tag = db.query(BLETag).filter(BLETag.imei == imei).first()
    if not tag:
        return None
    observed = r["recorded_at"]
    last_seen = tag.last_seen if not tag.last_seen or tag.last_seen.tzinfo else tag.last_seen.replace(tzinfo=timezone.utc)
    if last_seen and last_seen >= observed:
        return tag  # late, buffered record — history only
    tag.latitude, tag.longitude, tag.last_seen = str(r["latitude"]), str(r["longitude"]), observed
    if not tag.activation_date:
        # First GPS fix starts the package period, as for polled trackers.
        tag.activation_date = observed
        pkg = db.query(TagPackage).filter(TagPackage.id == tag.package_id).first() if tag.package_id else None
        if pkg:
            tag.expiry_date = pkg.expiry_from(observed.astimezone(timezone.utc).replace(tzinfo=None))
    return tag


def _store(body: bytes) -> int:
    with SessionLocal() as db:
        n = store_delivery(db, json.loads(body))
        db.commit()
        return n


def _build_trips() -> dict:
    with SessionLocal() as db:
        return trip_builder.run_once(db)


async def trip_builder_loop() -> None:
    while True:
        try:
            result = await asyncio.to_thread(_build_trips)
            if result["events"] or result["stale_closed"]:
                logger.info("Trip builder: %s", result)
        except Exception:
            logger.exception("Trip builder cycle failed")
        await asyncio.sleep(TRIP_BUILD_INTERVAL_S)


ADDRESS_INTERVAL_S = 20


def _fill_addresses() -> int:
    with SessionLocal() as db:
        return address_service.fill_trip_addresses(db)


async def address_loop() -> None:
    """Street addresses for trip start and end points (reverse geocoding)."""
    while True:
        try:
            n = await asyncio.to_thread(_fill_addresses)
            if n:
                logger.info("Trip addresses: %d trips updated", n)
        except Exception:
            logger.exception("Trip address cycle failed")
        await asyncio.sleep(ADDRESS_INTERVAL_S)


def _linked_exchange_keys() -> set[str]:
    with SessionLocal() as db:
        return set(db.execute(text(
            "SELECT exchange_key FROM data_exchanges WHERE status = 'linked' AND usergroup_id IS NOT NULL"
        )).scalars().all())


async def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    connection = await aio_pika.connect_robust(config.rabbitmq_url())
    channel = await connection.channel()
    await channel.set_qos(prefetch_count=20)
    exchange = await channel.declare_exchange(DELIVER_EXCHANGE, aio_pika.ExchangeType.DIRECT, durable=True)

    async def on_message(message: aio_pika.abc.AbstractIncomingMessage) -> None:
        try:
            new = await asyncio.to_thread(_store, message.body)
        except json.JSONDecodeError:
            logger.error("Dropping malformed delivery %s", message.delivery_tag)
            await message.reject(requeue=False)
            return
        except Exception:
            logger.exception("Storing delivery failed; requeueing")
            await asyncio.sleep(2)
            await message.nack(requeue=True)
            return
        await message.ack()
        if new:
            logger.info("Stored %d events from %s", new, message.routing_key)

    consuming: set[str] = set()
    trip_task = asyncio.create_task(trip_builder_loop())  # keep a reference so it is not garbage-collected
    address_task = asyncio.create_task(address_loop())  # noqa: F841 (kept for the same reason)
    logger.info("Dashboard ingest started")
    while True:
        try:
            for key in await asyncio.to_thread(_linked_exchange_keys) - consuming:
                queue = await channel.declare_queue(exchange_queue(key), durable=True)
                await queue.bind(exchange, routing_key=key)
                await queue.consume(on_message)
                consuming.add(key)
                logger.info("Consuming %s", queue.name)
        except Exception:
            logger.exception("Refreshing exchange queues failed")
        await asyncio.sleep(REFRESH_S)


if __name__ == "__main__":
    asyncio.run(main())
