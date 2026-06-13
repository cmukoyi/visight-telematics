"""Pareto Anywhere bridge — subscribes to the local Pareto Anywhere
Socket.IO `raddec` stream, resolves the nearest XIAO gateway, and upserts
TagIndoorPosition rows for the PinPlot floor-plan UI.

Design assumptions (per Pinplot floorplan spec v1.0 §5, §7):

  * One Pareto Anywhere container per deployment. PinPlot (staging) and
    every future tenant deployment (beacon, new customers) each get
    their own dedicated Pareto. No cross-tenant Pareto sharing.
  * Receiver IDs are unique within a deployment. Tenant scoping is
    derived via gateway → floor → building → usergroup.
  * `rssiSignature[0]` is always the strongest receiver — no sorting
    needed in this process.

Lifecycle:
  * `start_bridge()` is called from FastAPI startup; spawns two background
    tasks: the Socket.IO reconnect loop and the offline detector.
  * `stop_bridge()` is called from FastAPI shutdown; cancels tasks and
    disconnects cleanly.

This module never raises out of the raddec handler — bad payloads are
logged and dropped so a single malformed advert can't bring the bridge
down.
"""
from __future__ import annotations

import asyncio
import logging
import os
from datetime import datetime, timedelta, timezone
from typing import Optional

import socketio  # python-socketio[client]

from app.database import SessionLocal
from app.models import IndoorGateway, Floor, Building, Room, TagIndoorPosition

logger = logging.getLogger(__name__)

# ── Config (env-overridable) ────────────────────────────────────────────────
# Per-deployment Pareto — defaults to the docker service name on the
# pinplot_network. Beacon / new-customer servers override via env.
PARETO_URL = os.getenv("PARETO_URL", "http://pareto-anywhere:3001")

# Liveness thresholds (seconds).
ONLINE_RSSI_DBM   = -85   # > -85   → online
IDLE_RSSI_DBM     = -95   # > -95   → idle, else offline
OFFLINE_AFTER_SEC = 60    # no sighting within → status='offline'
OFFLINE_SWEEP_SEC = 15    # how often the detector runs

# ── In-process state ────────────────────────────────────────────────────────
_sio: Optional[socketio.AsyncClient] = None
_reconnect_task: Optional[asyncio.Task] = None
_offline_task: Optional[asyncio.Task] = None
_connected: bool = False
_last_raddec_at: Optional[datetime] = None
_raddec_count: int = 0
_unregistered_gateways: set[str] = set()   # receiver_ids we've seen but don't know


# ── Helpers ────────────────────────────────────────────────────────────────-

def _classify_status(rssi: int) -> str:
    if rssi > ONLINE_RSSI_DBM:
        return "online"
    if rssi > IDLE_RSSI_DBM:
        return "idle"
    return "offline"


def _normalize_tag_id(raw: str) -> str:
    """raddec transmitterId comes lowercase hex without colons already, but
    we strip and lowercase defensively in case a producer ever sends MAC
    with colons."""
    return (raw or "").replace(":", "").replace("-", "").lower()


def _normalize_receiver_id(raw: str) -> str:
    """Gateway receiver IDs should normalize the same way as admin-side
    storage to avoid case/colon/dash mismatches."""
    return (raw or "").strip().lower().replace(":", "").replace("-", "")


def _resolve_zone(db, gateway: IndoorGateway) -> Optional[str]:
    """Find the room (if any) on the same floor that contains the gateway's
    (x, y). Returns the room name, or None if the gateway is in a corridor /
    not inside any defined room rectangle."""
    rooms = db.query(Room).filter(Room.floor_id == gateway.floor_id).all()
    for r in rooms:
        if r.x <= gateway.x <= (r.x + r.w) and r.y <= gateway.y <= (r.y + r.h):
            return r.name
    return gateway.label  # fall back to the gateway's own label


def _process_raddec_sync(payload: dict) -> None:
    """Synchronous DB work for one raddec. Called from a thread executor so
    the asyncio event loop is never blocked by Postgres I/O."""
    global _unregistered_gateways

    tag_id = _normalize_tag_id(payload.get("transmitterId", ""))
    sigs = payload.get("rssiSignature") or []
    if not tag_id or not sigs:
        return

    nearest = sigs[0] or {}
    receiver_id = _normalize_receiver_id(nearest.get("receiverId") or "")
    rssi = int(nearest.get("rssi", -99))
    if not receiver_id:
        return

    db = SessionLocal()
    try:
        gateway = db.query(IndoorGateway).filter(
            IndoorGateway.receiver_id == receiver_id
        ).first()

        if gateway is None:
            # Don't spam the log — record once per unique unknown receiver.
            if receiver_id not in _unregistered_gateways:
                _unregistered_gateways.add(receiver_id)
                logger.warning("pareto_bridge: unregistered gateway receiver_id=%s "
                               "(tag=%s rssi=%d) — register via admin /floors/{id}/gateways",
                               receiver_id, tag_id, rssi)
            return

        floor = db.query(Floor).filter(Floor.id == gateway.floor_id).first()
        if floor is None:
            logger.warning("pareto_bridge: gateway %s references missing floor %s",
                           receiver_id, gateway.floor_id)
            return

        building = db.query(Building).filter(Building.id == floor.building_id).first()
        if building is None or building.usergroup_id is None:
            logger.warning("pareto_bridge: floor %s has no building/usergroup", floor.id)
            return

        zone = _resolve_zone(db, gateway)
        status = _classify_status(rssi)

        # Battery from Pareto's decoded dynamb (Minew sensor packets).
        battery: Optional[int] = None
        dynamb = payload.get("dynamb") or {}
        if isinstance(dynamb, dict) and isinstance(dynamb.get("batteryPercentage"), (int, float)):
            battery = int(dynamb["batteryPercentage"])

        now = datetime.now(timezone.utc)

        row = db.query(TagIndoorPosition).filter(
            TagIndoorPosition.tag_id == tag_id
        ).first()
        if row is None:
            row = TagIndoorPosition(
                tag_id=tag_id,
                floor_id=floor.id,
                gateway_id=gateway.id,
                usergroup_id=building.usergroup_id,
                x=gateway.x, y=gateway.y,
                zone=zone, rssi=rssi, battery=battery,
                status=status, last_seen=now,
            )
            db.add(row)
        else:
            row.floor_id = floor.id
            row.gateway_id = gateway.id
            row.usergroup_id = building.usergroup_id
            row.x = gateway.x
            row.y = gateway.y
            row.zone = zone
            row.rssi = rssi
            if battery is not None:   # keep last known battery if this packet didn't carry it
                row.battery = battery
            row.status = status
            row.last_seen = now

        db.commit()
    except Exception:
        db.rollback()
        logger.exception("pareto_bridge: failed to process raddec for tag=%s gw=%s",
                         tag_id, receiver_id)
    finally:
        db.close()


def _sweep_offline_sync() -> int:
    """Mark stale positions offline. Returns count of rows updated."""
    cutoff = datetime.now(timezone.utc) - timedelta(seconds=OFFLINE_AFTER_SEC)
    db = SessionLocal()
    try:
        n = db.query(TagIndoorPosition).filter(
            TagIndoorPosition.last_seen < cutoff,
            TagIndoorPosition.status != "offline",
        ).update({"status": "offline"}, synchronize_session=False)
        db.commit()
        return n
    except Exception:
        db.rollback()
        logger.exception("pareto_bridge: offline sweep failed")
        return 0
    finally:
        db.close()


# ── Socket.IO handlers ─────────────────────────────────────────────────────

def _register_handlers(sio: socketio.AsyncClient) -> None:

    @sio.event
    async def connect():
        global _connected
        _connected = True
        logger.info("pareto_bridge: connected to %s", PARETO_URL)

    @sio.event
    async def disconnect():
        global _connected
        _connected = False
        logger.warning("pareto_bridge: disconnected from %s", PARETO_URL)

    @sio.on("raddec")
    async def on_raddec(data):
        global _last_raddec_at, _raddec_count
        _last_raddec_at = datetime.now(timezone.utc)
        _raddec_count += 1
        try:
            loop = asyncio.get_running_loop()
            await loop.run_in_executor(None, _process_raddec_sync, data)
        except Exception:
            logger.exception("pareto_bridge: raddec dispatch failed")


# ── Background tasks ───────────────────────────────────────────────────────

async def _reconnect_loop():
    """Keeps the Socket.IO client connected. Pareto isn't always up at
    backend startup (e.g. fresh deploy where docker-compose brings Pareto
    up after the backend), so we retry forever with backoff."""
    global _sio
    backoff = 5
    while True:
        try:
            _sio = socketio.AsyncClient(reconnection=False, logger=False, engineio_logger=False)
            _register_handlers(_sio)
            # Use default transport order (polling first, then upgrade to
            # websocket) so the Engine.IO handshake gets a sid before the
            # WS upgrade attempt. Passing ["websocket", ...] makes python-
            # socketio skip the polling handshake and fail with
            # "no OPEN packet" against Pareto's Engine.IO server.
            await _sio.connect(PARETO_URL)
            await _sio.wait()
        except asyncio.CancelledError:
            raise
        except Exception as e:
            logger.warning("pareto_bridge: connect failed (%s) — retrying in %ds", e, backoff)
        # If we fall through, sleep then loop.
        try:
            await asyncio.sleep(backoff)
        except asyncio.CancelledError:
            raise


async def _offline_loop():
    while True:
        try:
            await asyncio.sleep(OFFLINE_SWEEP_SEC)
            loop = asyncio.get_running_loop()
            n = await loop.run_in_executor(None, _sweep_offline_sync)
            if n:
                logger.info("pareto_bridge: marked %d tag(s) offline", n)
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("pareto_bridge: offline loop iteration failed")


# ── Public API ─────────────────────────────────────────────────────────────

def start_bridge() -> None:
    """Schedule the bridge tasks on the running event loop."""
    global _reconnect_task, _offline_task
    if _reconnect_task is not None:
        return
    _reconnect_task = asyncio.create_task(_reconnect_loop(), name="pareto_bridge_reconnect")
    _offline_task = asyncio.create_task(_offline_loop(), name="pareto_bridge_offline")
    logger.info("pareto_bridge: started (PARETO_URL=%s)", PARETO_URL)


async def stop_bridge() -> None:
    """Cancel tasks and disconnect."""
    global _reconnect_task, _offline_task, _sio
    for t in (_reconnect_task, _offline_task):
        if t is not None and not t.done():
            t.cancel()
            try:
                await t
            except (asyncio.CancelledError, Exception):
                pass
    _reconnect_task = None
    _offline_task = None
    if _sio is not None and _sio.connected:
        try:
            await _sio.disconnect()
        except Exception:
            pass
    _sio = None
    logger.info("pareto_bridge: stopped")


def get_status() -> dict:
    """Snapshot of the bridge — exposed via /api/portal/floorplan/health."""
    return {
        "pareto_url": PARETO_URL,
        "connected": _connected,
        "raddec_count": _raddec_count,
        "last_raddec_at": _last_raddec_at.isoformat() if _last_raddec_at else None,
        "unregistered_gateways": sorted(_unregistered_gateways),
    }
