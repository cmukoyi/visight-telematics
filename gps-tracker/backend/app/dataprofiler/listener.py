"""GPRS listener — accepts Teltonika TCP sessions and queues raw AVL packets.

    python -m app.dataprofiler.listener

Only IMEIs registered to an active reseller in DataProfiler are accepted;
other attempts are logged as rejected connections. Each AVL packet is
CRC-checked, published to RabbitMQ with publisher confirms, and only then
acknowledged to the device. If anything fails before the ACK the device keeps
the data and resends it, so nothing is lost.

Sessions are recorded in the events store (device_sessions) so the admin
portal can show which IMEIs are online. Tracking is best-effort and never
blocks or fails the data path.

GPRS commands (Codec 12) queued in the portal (device_commands) go out on the
device's newest open session, once its first AVL packet has been acknowledged.
One command is in flight per session at a time; every write to the socket
holds the session's lock, so a command frame never splits an AVL ACK. Frames
the device sends with codec 12 are command replies and never reach the AVL path.
"""
import asyncio
import logging
import struct
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional

import aio_pika
from sqlalchemy import text

from app.database import SessionLocal
from app.dataprofiler import config
from app.dataprofiler.events_db import ensure_schema, get_engine
from app.dataprofiler.teltonika import (
    CODEC_12, ProtocolError, encode_command, frame_avl_packet, packet_codec, parse_avl_header, parse_command_response,
    parse_imei,
)
from app.services import device_command_service as commands_db

logger = logging.getLogger("dataprofiler.listener")

IDLE_TIMEOUT_S = 15 * 60       # devices keep sessions open between sends
HANDSHAKE_TIMEOUT_S = 30
IMEI_REFRESH_S = 60
IMEI_MISS_REFRESH_S = 10       # re-check sooner after an unknown IMEI so new devices connect quickly
COMMAND_POLL_S = 2             # how often the listener looks for commands queued in the portal
COMMAND_EXPIRE_S = 30          # how often queued commands past their expiry are marked expired


class ImeiRegistry:
    """Cached set of IMEIs allowed to connect (active resellers only)."""

    def __init__(self):
        self._imeis: set[str] = set()
        self._loaded_at = 0.0

    def _load(self) -> set[str]:
        with SessionLocal() as db:
            rows = db.execute(text(
                "SELECT d.imei FROM reseller_devices d "
                "JOIN resellers r ON r.id = d.reseller_id WHERE r.is_active"
            )).scalars().all()
        return set(rows)

    async def refresh(self) -> None:
        self._imeis = await asyncio.to_thread(self._load)
        self._loaded_at = time.monotonic()
        logger.info("IMEI registry loaded: %d devices", len(self._imeis))

    async def allowed(self, imei: str) -> bool:
        age = time.monotonic() - self._loaded_at
        if age > IMEI_REFRESH_S or (imei not in self._imeis and age > IMEI_MISS_REFRESH_S):
            try:
                await self.refresh()
            except Exception:
                logger.exception("IMEI registry refresh failed; using cached list")
        return imei in self._imeis


class SessionTracker:
    """Records sessions and rejected IMEIs in the events store. Never raises."""

    def __init__(self, engine):
        self.engine = engine

    def _exec(self, sql: str, params: dict):
        with self.engine.begin() as conn:
            return conn.execute(text(sql), params)

    async def _run(self, sql: str, params: dict):
        try:
            return await asyncio.to_thread(self._exec, sql, params)
        except Exception:
            logger.exception("Session tracking write failed")
            return None

    async def close_stale(self) -> None:
        """Sessions left open by a previous listener process are no longer connected."""
        await self._run("UPDATE device_sessions SET disconnected_at = now(), close_reason = 'listener restart' "
                        "WHERE disconnected_at IS NULL", {})

    async def opened(self, imei: str, remote: str):
        res = await self._run("INSERT INTO device_sessions (imei, remote_addr) VALUES (:i, :r) RETURNING id",
                              {"i": imei, "r": remote})
        return res.scalar() if res is not None else None

    async def packet(self, session_id, records: int) -> None:
        if session_id is not None:
            await self._run("UPDATE device_sessions SET last_packet_at = now(), packets = packets + 1, "
                            "records = records + :n WHERE id = :id", {"n": records, "id": session_id})

    async def closed(self, session_id, reason: str) -> None:
        if session_id is not None:
            await self._run("UPDATE device_sessions SET disconnected_at = now(), close_reason = :r WHERE id = :id",
                            {"r": reason[:64], "id": session_id})

    async def rejected(self, imei: str, remote: str) -> None:
        await self._run("INSERT INTO rejected_connections (imei, remote_addr) VALUES (:i, :r)",
                        {"i": imei, "r": remote})


class CommandQueue:
    """device_commands in the main database, as the listener sees it (each call runs in a thread)."""
    reply_timeout_s = commands_db.REPLY_TIMEOUT_S

    async def queued_imeis(self) -> set[str]:
        return await asyncio.to_thread(commands_db.queued_imeis)

    async def claim(self, imei: str) -> Optional[tuple[str, str]]:
        return await asyncio.to_thread(commands_db.claim_next, imei)

    async def responded(self, command_id: str, response: str) -> None:
        await asyncio.to_thread(commands_db.mark_responded, command_id, response)

    async def failed(self, command_id: str, error: str) -> None:
        await asyncio.to_thread(commands_db.mark_failed, command_id, error)

    async def expire(self) -> int:
        return await asyncio.to_thread(commands_db.expire_due)


@dataclass
class _Session:
    """One device's open TCP session, as far as commands are concerned."""
    imei: str
    writer: asyncio.StreamWriter
    lock: asyncio.Lock = field(default_factory=asyncio.Lock)    # held for every write to the socket
    wake: asyncio.Event = field(default_factory=asyncio.Event)  # set when a command may be waiting
    reply: Optional[asyncio.Future] = None                      # the reply to the command in flight
    in_flight: Optional[str] = None                             # id of the command in flight
    sender: Optional[asyncio.Task] = None


class Listener:
    def __init__(self, registry: ImeiRegistry, exchange: aio_pika.abc.AbstractExchange, tracker: SessionTracker,
                 commands: Optional[CommandQueue] = None):
        self.registry = registry
        self.exchange = exchange
        self.tracker = tracker
        self.commands = commands       # None: GPRS commands are not sent
        self.sessions = 0
        self.live: dict[str, _Session] = {}   # IMEI → its newest open session

    # -- GPRS commands -------------------------------------------------------

    async def poll_commands(self) -> None:
        """Wake the sessions of devices that have commands queued; expire old commands. Runs forever."""
        last_expire = 0.0
        while True:
            try:
                if time.monotonic() - last_expire >= COMMAND_EXPIRE_S:
                    last_expire = time.monotonic()
                    if n := await self.commands.expire():
                        logger.info("Commands expired or timed out: %d", n)
                for imei in await self.commands.queued_imeis():
                    if (s := self.live.get(imei)) is not None:
                        s.wake.set()
            except Exception:
                logger.exception("Command poll failed")
            await asyncio.sleep(COMMAND_POLL_S)

    async def _send_commands(self, s: _Session) -> None:
        """Send this session's queued commands one at a time, waiting for each reply. Runs until cancelled."""
        while True:
            if self.live.get(s.imei) is not s:
                return  # a newer session for this device has taken over
            try:
                claimed = await self.commands.claim(s.imei)
            except Exception:
                logger.exception("Command claim failed: IMEI %s", s.imei)
                claimed = None
            if claimed is None:
                s.wake.clear()
                await s.wake.wait()
                continue
            s.in_flight, command = claimed
            s.reply = asyncio.get_running_loop().create_future()
            try:
                async with s.lock:
                    s.writer.write(encode_command(command))
                    await s.writer.drain()
            except (ProtocolError, ConnectionError) as exc:
                await self.commands.failed(s.in_flight, f"Not sent: {exc}")
            else:
                logger.info("Command sent: IMEI %s: %s", s.imei, command)
                try:
                    response = await asyncio.wait_for(s.reply, self.commands.reply_timeout_s)
                except asyncio.TimeoutError:
                    await self.commands.failed(s.in_flight, f"No reply within {self.commands.reply_timeout_s} s")
                except ProtocolError as exc:
                    await self.commands.failed(s.in_flight, f"Unreadable reply: {exc}")
                else:
                    await self.commands.responded(s.in_flight, response)
                    logger.info("Command reply: IMEI %s: %s", s.imei, response)
            s.in_flight, s.reply = None, None

    def _on_command_reply(self, s: _Session, raw: bytes) -> None:
        """A Codec 12 frame from the device: the reply to the command in flight."""
        try:
            response = parse_command_response(raw)
        except ProtocolError as exc:
            response, error = None, exc
        if s.reply is None or s.reply.done():
            logger.warning("Unexpected command reply from IMEI %s: %r", s.imei, response)
        elif response is None:
            s.reply.set_exception(error)
        else:
            s.reply.set_result(response)

    async def _end_commands(self, s: _Session) -> None:
        if s.sender is not None:
            s.sender.cancel()
            try:
                await s.sender
            except BaseException:
                pass
        if s.in_flight:
            await self.commands.failed(s.in_flight, "The device disconnected before it replied")
        if self.live.get(s.imei) is s:
            del self.live[s.imei]

    # -- Sessions ------------------------------------------------------------

    async def handle(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        peer = writer.get_extra_info("peername")
        remote = f"{peer[0]}:{peer[1]}" if peer else "unknown"
        imei = None
        session_id = None
        session: Optional[_Session] = None
        close_reason = "closed by device"
        self.sessions += 1
        try:
            header = await asyncio.wait_for(reader.readexactly(2), HANDSHAKE_TIMEOUT_S)
            (length,) = struct.unpack(">H", header)
            if not 1 <= length <= 20:
                raise ProtocolError("Bad IMEI length")
            imei = parse_imei(header + await asyncio.wait_for(reader.readexactly(length), HANDSHAKE_TIMEOUT_S))

            if not await self.registry.allowed(imei):
                logger.warning("Rejected unknown IMEI %s from %s", imei, remote)
                writer.write(b"\x00")
                await writer.drain()
                await self.tracker.rejected(imei, remote)
                return
            writer.write(b"\x01")
            await writer.drain()
            session_id = await self.tracker.opened(imei, remote)
            logger.info("Session open: IMEI %s from %s", imei, remote)
            session = _Session(imei=imei, writer=writer)
            self.live[imei] = session

            while True:
                head = await asyncio.wait_for(reader.readexactly(8), IDLE_TIMEOUT_S)
                data_len = parse_avl_header(head)
                raw = head + await asyncio.wait_for(reader.readexactly(data_len + 4), HANDSHAKE_TIMEOUT_S)
                if packet_codec(raw) == CODEC_12:
                    self._on_command_reply(session, raw)
                    continue
                packet = frame_avl_packet(raw)
                await self.exchange.publish(
                    aio_pika.Message(
                        body=packet.raw,
                        delivery_mode=aio_pika.DeliveryMode.PERSISTENT,
                        headers={
                            "imei": imei,
                            "codec": packet.codec,
                            "record_count": packet.record_count,
                            "received_at": datetime.now(timezone.utc).isoformat(),
                            "remote_addr": remote,
                        },
                    ),
                    routing_key=config.RAW_QUEUE,
                )
                # Publisher confirm received — safe to tell the device we have the records.
                async with session.lock:
                    writer.write(struct.pack(">I", packet.record_count))
                    await writer.drain()
                await self.tracker.packet(session_id, packet.record_count)
                if self.commands is not None and session.sender is None:
                    # First AVL packet acknowledged: queued commands may go out now
                    session.sender = asyncio.create_task(self._send_commands(session))
        except (asyncio.IncompleteReadError, ConnectionError):
            pass  # device closed the session
        except asyncio.TimeoutError:
            close_reason = "idle timeout"
            logger.info("Session idle timeout: IMEI %s", imei)
        except ProtocolError as exc:
            close_reason = f"protocol error: {exc}"
            logger.warning("Protocol error from IMEI %s (%s): %s", imei, remote, exc)
        except Exception as exc:
            close_reason = f"error: {exc.__class__.__name__}"
            logger.exception("Session failed: IMEI %s (%s)", imei, remote)
        finally:
            if session is not None:
                try:
                    await self._end_commands(session)
                except Exception:
                    logger.exception("Command cleanup failed: IMEI %s", imei)
            await self.tracker.closed(session_id, close_reason)
            self.sessions -= 1
            writer.close()
            try:
                await writer.wait_closed()
            except Exception:
                pass


async def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    connection = await aio_pika.connect_robust(config.rabbitmq_url())
    channel = await connection.channel(publisher_confirms=True)
    exchange = await channel.declare_exchange(config.RAW_EXCHANGE, aio_pika.ExchangeType.DIRECT, durable=True)
    queue = await channel.declare_queue(config.RAW_QUEUE, durable=True)
    await queue.bind(exchange, routing_key=config.RAW_QUEUE)

    engine = get_engine()
    await asyncio.to_thread(ensure_schema, engine)
    tracker = SessionTracker(engine)
    await tracker.close_stale()

    registry = ImeiRegistry()
    await registry.refresh()
    listener = Listener(registry, exchange, tracker, CommandQueue())
    poller = asyncio.create_task(listener.poll_commands())  # keep a reference so it is not garbage-collected
    server = await asyncio.start_server(listener.handle, "0.0.0.0", config.LISTENER_PORT)
    logger.info("GPRS listener on port %d", config.LISTENER_PORT)
    async with server:
        await server.serve_forever()
    poller.cancel()


if __name__ == "__main__":
    asyncio.run(main())
