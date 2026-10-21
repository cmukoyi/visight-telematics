"""Event decoder — events_incoming → events_processed → Data Exchange queues.

    python -m app.dataprofiler.decoder

  decode   raw packets → one processed row per AVL record, tagged with its
           event type, whether the device's package makes it visible, and
           the Data Exchange it routes to. A device seen for the first time
           is routed (auto-provisioned on the dashboard) if its reseller's
           exchange is linked. Rows are claimed with FOR UPDATE SKIP LOCKED.
  deliver  visible records → the exchange's durable RabbitMQ queue
           (dp.exchange.<exchange_key>), one message per IMEI per batch,
           marked delivered after the broker confirms. Delivery is
           at-least-once; each event carries dp_event_id so the dashboard
           consumer drops duplicates.
  purge    DataProfiler history older than DP_RAW_RETENTION_DAYS (30). Visible
           records are kept until delivered, so nothing is purged unsent.
"""
import asyncio
import json
import logging
import time
from datetime import datetime, timezone
from typing import Awaitable, Callable, Optional

import aio_pika
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.database import SessionLocal
from app.dataprofiler import config
from app.dataprofiler.events_db import ensure_schema, get_engine
from app.dataprofiler.teltonika import ProtocolError, SUPPORTED_CODECS, classify_event, decode_avl_packet
from app.models import BLETag
from app.models_admin import TagPackage
from app.models_dataprofiler import ResellerDevice
from app.services import dataprofiler_service as dp

logger = logging.getLogger("dataprofiler.decoder")

DECODE_BATCH = 500
DELIVER_BATCH = 1000
PURGE_INTERVAL_S = 3600

DELIVER_EXCHANGE = "dp.deliver"


def exchange_queue(exchange_key: str) -> str:
    return f"dp.exchange.{exchange_key}"


def _utc(dt: Optional[datetime]) -> Optional[datetime]:
    if dt is None:
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


# ---------------------------------------------------------------------------
# Device context (main database)
# ---------------------------------------------------------------------------

def load_device_context(db: Session, imeis: set[str]) -> dict:
    """Per-IMEI routing info; routes devices that are still pending.

    Returns {imei: {"reseller_id", "usergroup_id", "exchange_key", "live", "allowed"}} where
    live means the device is on the dashboard with an unexpired tag and
    allowed is the package's event filter (None = all events).
    """
    now = datetime.now(timezone.utc)
    context = {}
    devices = db.query(ResellerDevice).filter(ResellerDevice.imei.in_(imeis)).all()
    routed_any = False
    for device in devices:
        if device.status != "routed" or not device.ble_tag_id:
            routed_any |= dp.route_device(db, device) == "routed"
        exchange = device.reseller.exchange if device.reseller else None
        tag = db.query(BLETag).filter(BLETag.id == device.ble_tag_id).first() if device.ble_tag_id else None
        pkg = db.query(TagPackage).filter(TagPackage.id == tag.package_id).first() if tag and tag.package_id else None
        expired = bool(tag and tag.expiry_date and _utc(tag.expiry_date) < now)
        context[device.imei] = {
            "reseller_id": str(device.reseller_id),
            "usergroup_id": str(exchange.usergroup_id) if exchange and exchange.usergroup_id else None,
            "exchange_key": exchange.exchange_key if exchange and exchange.usergroup_id else None,
            "live": bool(tag and tag.is_active and not expired and device.status == "routed"),
            "allowed": set(pkg.allowed_event_types) if pkg and pkg.allowed_event_types is not None else None,
        }
    if routed_any:
        logger.info("Auto-routed devices on first event")
    return context


def is_visible(ctx: Optional[dict], event_type: Optional[str]) -> bool:
    if not ctx or not ctx["live"]:
        return False
    allowed = ctx["allowed"]
    return allowed is None or (event_type is not None and event_type in allowed)


# ---------------------------------------------------------------------------
# Decode
# ---------------------------------------------------------------------------

_INSERT_PROCESSED = text(
    "INSERT INTO events_processed (incoming_id, imei, reseller_id, usergroup_id, recorded_at, received_at, "
    "priority, latitude, longitude, altitude, angle, satellites, speed, event_io_id, event_type, io, visible, "
    "exchange_key) "
    "VALUES (:incoming_id, :imei, :reseller_id, :usergroup_id, :recorded_at, :received_at, :priority, "
    ":latitude, :longitude, :altitude, :angle, :satellites, :speed, :event_io_id, :event_type, "
    "CAST(:io AS JSONB), :visible, :exchange_key)"
)


def decode_batch(events_engine, main_session_factory=SessionLocal) -> int:
    """Decode up to DECODE_BATCH new packets. Returns the number claimed."""
    with events_engine.begin() as ev:
        rows = ev.execute(text(
            "SELECT id, imei, codec, payload, received_at FROM events_incoming "
            "WHERE status = 'new' ORDER BY id LIMIT :n FOR UPDATE SKIP LOCKED"
        ), {"n": DECODE_BATCH}).mappings().all()
        if not rows:
            return 0

        with main_session_factory() as db:
            context = load_device_context(db, {r["imei"] for r in rows})
            last_seen: dict[str, datetime] = {}
            for r in rows:
                last_seen[r["imei"]] = max(last_seen.get(r["imei"], r["received_at"]), r["received_at"])
            for imei, ts in last_seen.items():
                db.query(ResellerDevice).filter(ResellerDevice.imei == imei).update(
                    {"last_event_at": ts}, synchronize_session=False)
            db.commit()

        processed, statuses = [], []
        for r in rows:
            ctx = context.get(r["imei"])
            if r["codec"] not in SUPPORTED_CODECS:
                statuses.append({"id": r["id"], "status": "unsupported", "error": f"codec 0x{r['codec']:02X}"})
                continue
            try:
                _, records = decode_avl_packet(bytes(r["payload"]))
            except ProtocolError as exc:
                statuses.append({"id": r["id"], "status": "failed", "error": str(exc)})
                continue
            for rec in records:
                event_type = classify_event(rec)
                visible = is_visible(ctx, event_type)
                processed.append({
                    "incoming_id": r["id"], "imei": r["imei"],
                    "reseller_id": ctx["reseller_id"] if ctx else None,
                    "usergroup_id": ctx["usergroup_id"] if ctx else None,
                    "recorded_at": rec.timestamp, "received_at": r["received_at"],
                    "priority": rec.priority,
                    "latitude": rec.latitude if rec.has_fix else None,
                    "longitude": rec.longitude if rec.has_fix else None,
                    "altitude": rec.altitude, "angle": rec.angle, "satellites": rec.satellites,
                    "speed": rec.speed, "event_io_id": rec.event_io_id, "event_type": event_type,
                    "io": json.dumps({str(k): v for k, v in rec.io.items()}),
                    "visible": visible,
                    "exchange_key": ctx["exchange_key"] if visible else None,
                })
            statuses.append({"id": r["id"], "status": "decoded", "error": None})

        if processed:
            ev.execute(_INSERT_PROCESSED, processed)
        ev.execute(text(
            "UPDATE events_incoming SET status = :status, error = :error, decoded_at = now() WHERE id = :id"
        ), statuses)
    return len(rows)


# ---------------------------------------------------------------------------
# Deliver
# ---------------------------------------------------------------------------

Publisher = Callable[[str, bytes], Awaitable[None]]  # (exchange_key, body) → confirmed publish


def _event_payload(r: dict) -> dict:
    iso = lambda dt: _utc(dt).isoformat() if dt else None
    return {
        "dp_event_id": r["id"], "recorded_at": iso(r["recorded_at"]), "received_at": iso(r["received_at"]),
        "event_type": r["event_type"], "event_io_id": r["event_io_id"], "priority": r["priority"],
        "latitude": r["latitude"], "longitude": r["longitude"], "altitude": r["altitude"],
        "angle": r["angle"], "satellites": r["satellites"], "speed": r["speed"], "io": r["io"] or {},
    }


def _undelivered(events_engine) -> list:
    with events_engine.connect() as ev:
        return ev.execute(text(
            "SELECT id, imei, usergroup_id, exchange_key, recorded_at, received_at, event_type, event_io_id, "
            "priority, latitude, longitude, altitude, angle, satellites, speed, io "
            "FROM events_processed WHERE visible AND NOT delivered AND exchange_key IS NOT NULL "
            "ORDER BY id LIMIT :n"
        ), {"n": DELIVER_BATCH}).mappings().all()


def _mark_delivered(events_engine, ids: list[int]) -> None:
    with events_engine.begin() as ev:
        ev.execute(text("UPDATE events_processed SET delivered = true WHERE id = ANY(:ids)"), {"ids": ids})


async def deliver_batch(events_engine, publish: Publisher) -> int:
    """Publish visible, undelivered records to their exchange queues. Returns the number delivered."""
    rows = await asyncio.to_thread(_undelivered, events_engine)
    if not rows:
        return 0
    groups: dict[tuple, list] = {}
    for r in rows:
        groups.setdefault((r["exchange_key"], r["imei"]), []).append(r)
    delivered = 0
    for (exchange_key, imei), records in groups.items():
        body = json.dumps({
            "exchange_key": exchange_key, "imei": imei,
            "usergroup_id": str(records[0]["usergroup_id"]) if records[0]["usergroup_id"] else None,
            "events": [_event_payload(r) for r in records],
        }).encode()
        await publish(exchange_key, body)
        await asyncio.to_thread(_mark_delivered, events_engine, [r["id"] for r in records])
        delivered += len(records)
    return delivered


async def rabbit_publisher(channel: aio_pika.abc.AbstractChannel) -> Publisher:
    """Publisher that declares each exchange's durable queue on first use."""
    exchange = await channel.declare_exchange(DELIVER_EXCHANGE, aio_pika.ExchangeType.DIRECT, durable=True)
    declared: set[str] = set()

    async def publish(exchange_key: str, body: bytes) -> None:
        if exchange_key not in declared:
            queue = await channel.declare_queue(exchange_queue(exchange_key), durable=True)
            await queue.bind(exchange, routing_key=exchange_key)
            declared.add(exchange_key)
        await exchange.publish(
            aio_pika.Message(body=body, content_type="application/json",
                             delivery_mode=aio_pika.DeliveryMode.PERSISTENT),
            routing_key=exchange_key,
        )

    return publish


# ---------------------------------------------------------------------------
# Purge + loop
# ---------------------------------------------------------------------------

def purge_history(events_engine) -> int:
    """Drop DataProfiler history past the retention window (never undelivered visible records)."""
    params = {"days": config.RAW_RETENTION_DAYS}
    cutoff = "now() - make_interval(days => :days)"
    with events_engine.begin() as ev:
        n = ev.execute(text(
            f"DELETE FROM events_processed WHERE created_at < {cutoff} AND (delivered OR NOT visible)"
        ), params).rowcount
        n += ev.execute(text(
            f"DELETE FROM events_incoming WHERE status <> 'new' AND received_at < {cutoff}"
        ), params).rowcount
        ev.execute(text(f"DELETE FROM device_sessions WHERE disconnected_at < {cutoff}"), params)
        ev.execute(text(f"DELETE FROM rejected_connections WHERE attempted_at < {cutoff}"), params)
    return n


async def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    engine = get_engine()
    await asyncio.to_thread(ensure_schema, engine)
    connection = await aio_pika.connect_robust(config.rabbitmq_url())
    channel = await connection.channel(publisher_confirms=True)
    publish = await rabbit_publisher(channel)
    logger.info("Decoder started")
    last_purge = 0.0
    while True:
        try:
            decoded = await asyncio.to_thread(decode_batch, engine)
            delivered = await deliver_batch(engine, publish)
            if time.monotonic() - last_purge > PURGE_INTERVAL_S:
                purged = await asyncio.to_thread(purge_history, engine)
                last_purge = time.monotonic()
                if purged:
                    logger.info("Purged %d rows older than %d days", purged, config.RAW_RETENTION_DAYS)
        except Exception:
            logger.exception("Decoder cycle failed")
            await asyncio.sleep(5)
            continue
        if not decoded and not delivered:
            await asyncio.sleep(1)


if __name__ == "__main__":
    asyncio.run(main())
