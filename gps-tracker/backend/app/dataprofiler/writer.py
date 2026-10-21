"""Event writer — drains the RabbitMQ raw queue into events_incoming.

    python -m app.dataprofiler.writer

Messages are written in batches and acknowledged only after the insert
commits, so a crash re-delivers them instead of dropping them.
"""
import asyncio
import logging
from datetime import datetime, timezone

import aio_pika
from sqlalchemy import text

from app.dataprofiler import config
from app.dataprofiler.events_db import ensure_schema, get_engine

logger = logging.getLogger("dataprofiler.writer")

BATCH_SIZE = 200
FLUSH_INTERVAL_S = 0.5

_INSERT = text(
    "INSERT INTO events_incoming (received_at, imei, codec, record_count, payload, remote_addr) "
    "VALUES (:received_at, :imei, :codec, :record_count, :payload, :remote_addr)"
)


def _row(message: aio_pika.abc.AbstractIncomingMessage) -> dict:
    h = message.headers or {}
    received = h.get("received_at")
    return {
        "received_at": datetime.fromisoformat(received) if received else datetime.now(timezone.utc),
        "imei": str(h.get("imei", "")),
        "codec": int(h.get("codec", 0)),
        "record_count": int(h.get("record_count", 0)),
        "payload": message.body,
        "remote_addr": h.get("remote_addr"),
    }


def _insert(engine, rows: list[dict]) -> None:
    with engine.begin() as conn:
        conn.execute(_INSERT, rows)


async def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    engine = get_engine()
    await asyncio.to_thread(ensure_schema, engine)

    connection = await aio_pika.connect_robust(config.rabbitmq_url())
    channel = await connection.channel()
    await channel.set_qos(prefetch_count=BATCH_SIZE * 2)
    exchange = await channel.declare_exchange(config.RAW_EXCHANGE, aio_pika.ExchangeType.DIRECT, durable=True)
    queue = await channel.declare_queue(config.RAW_QUEUE, durable=True)
    await queue.bind(exchange, routing_key=config.RAW_QUEUE)

    pending: list[aio_pika.abc.AbstractIncomingMessage] = []
    wake = asyncio.Event()

    async def on_message(message: aio_pika.abc.AbstractIncomingMessage) -> None:
        pending.append(message)
        if len(pending) >= BATCH_SIZE:
            wake.set()

    await queue.consume(on_message)
    logger.info("Writer consuming %s", config.RAW_QUEUE)

    while True:
        try:
            await asyncio.wait_for(wake.wait(), FLUSH_INTERVAL_S)
        except asyncio.TimeoutError:
            pass
        wake.clear()
        if not pending:
            continue
        batch, pending[:] = pending[:BATCH_SIZE], pending[BATCH_SIZE:]
        good, rows = [], []
        for m in batch:
            try:
                rows.append(_row(m))
                good.append(m)
            except Exception:
                logger.exception("Dropping malformed message %s", m.delivery_tag)
                await m.reject(requeue=False)
        if not good:
            continue
        try:
            await asyncio.to_thread(_insert, engine, rows)
        except Exception:
            logger.exception("Insert of %d packets failed; requeueing", len(good))
            for m in good:
                await m.nack(requeue=True)
            await asyncio.sleep(2)
            continue
        # The batch is always the oldest unsettled deliveries on this channel,
        # so acking its newest with multiple=True settles exactly this batch.
        await good[-1].ack(multiple=True)


if __name__ == "__main__":
    asyncio.run(main())
