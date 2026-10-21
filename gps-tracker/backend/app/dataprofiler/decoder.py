"""Event decoder — events_incoming → events_processed → customer dashboard.

    python -m app.dataprofiler.decoder

Three steps, each safe to run in several processes at once (rows are claimed
with FOR UPDATE SKIP LOCKED) and safe to retry:

  decode   raw packets → one processed row per AVL record, tagged with its
           event type and whether the device's package makes it visible.
           A device seen for the first time is routed (auto-provisioned on
           the dashboard) if its reseller's exchange is linked.
  forward  visible records with a GPS fix → device_positions + the tag's
           live location in the main database (idempotent upserts).
  purge    raw packets older than DP_RAW_RETENTION_DAYS.
"""
import json
import logging
import time
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import text
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from app.database import SessionLocal
from app.dataprofiler import config
from app.dataprofiler.events_db import ensure_schema, get_engine
from app.dataprofiler.teltonika import ProtocolError, SUPPORTED_CODECS, classify_event, decode_avl_packet
from app.models import BLETag, DevicePosition
from app.models_admin import TagPackage
from app.models_dataprofiler import ResellerDevice
from app.services import dataprofiler_service as dp

logger = logging.getLogger("dataprofiler.decoder")

DECODE_BATCH = 500
FORWARD_BATCH = 1000
PURGE_INTERVAL_S = 3600

IO_IGNITION = 239


def _utc(dt: Optional[datetime]) -> Optional[datetime]:
    if dt is None:
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


# ---------------------------------------------------------------------------
# Device context (main database)
# ---------------------------------------------------------------------------

def load_device_context(db: Session, imeis: set[str]) -> dict:
    """Per-IMEI routing info; routes devices that are still pending.

    Returns {imei: {"reseller_id", "usergroup_id", "live", "allowed"}} where
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
    "priority, latitude, longitude, altitude, angle, satellites, speed, event_io_id, event_type, io, visible) "
    "VALUES (:incoming_id, :imei, :reseller_id, :usergroup_id, :recorded_at, :received_at, :priority, "
    ":latitude, :longitude, :altitude, :angle, :satellites, :speed, :event_io_id, :event_type, "
    "CAST(:io AS JSONB), :visible)"
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
                    "visible": is_visible(ctx, event_type),
                })
            statuses.append({"id": r["id"], "status": "decoded", "error": None})

        if processed:
            ev.execute(_INSERT_PROCESSED, processed)
        ev.execute(text(
            "UPDATE events_incoming SET status = :status, error = :error, decoded_at = now() WHERE id = :id"
        ), statuses)
    return len(rows)


# ---------------------------------------------------------------------------
# Forward
# ---------------------------------------------------------------------------

def forward_batch(events_engine, main_session_factory=SessionLocal) -> int:
    """Push visible, not-yet-forwarded records to the dashboard. Returns the number claimed."""
    with events_engine.begin() as ev:
        rows = ev.execute(text(
            "SELECT id, imei, recorded_at, latitude, longitude, angle, speed, satellites, io "
            "FROM events_processed WHERE visible AND NOT forwarded "
            "ORDER BY id LIMIT :n FOR UPDATE SKIP LOCKED"
        ), {"n": FORWARD_BATCH}).mappings().all()
        if not rows:
            return 0

        fixes = [r for r in rows if r["latitude"] is not None and r["longitude"] is not None]
        if fixes:
            with main_session_factory() as db:
                positions = []
                for r in fixes:
                    ignition = (r["io"] or {}).get(str(IO_IGNITION))
                    positions.append({
                        "device_imei": r["imei"], "lat": r["latitude"], "lng": r["longitude"],
                        "observed_at": r["recorded_at"], "direction": r["angle"],
                        "gps_speed": float(r["speed"]), "satellite": r["satellites"],
                        "ignition": None if ignition is None else ("ON" if ignition else "OFF"),
                        "pos_type": 1, "source": "teltonika",
                    })
                db.execute(pg_insert(DevicePosition.__table__).values(positions)
                           .on_conflict_do_nothing(index_elements=["device_imei", "observed_at"]))

                latest: dict[str, dict] = {}
                for r in fixes:
                    if r["imei"] not in latest or r["recorded_at"] > latest[r["imei"]]["recorded_at"]:
                        latest[r["imei"]] = r
                for imei, r in latest.items():
                    _update_tag_location(db, imei, r)
                db.commit()

        ev.execute(text("UPDATE events_processed SET forwarded = true WHERE id = ANY(:ids)"),
                   {"ids": [r["id"] for r in rows]})
    return len(rows)


def _update_tag_location(db: Session, imei: str, r: dict) -> None:
    tag = db.query(BLETag).filter(BLETag.imei == imei).first()
    if not tag:
        return
    observed = _utc(r["recorded_at"])
    if tag.last_seen and _utc(tag.last_seen) >= observed:
        return  # late, buffered record — history only
    tag.latitude, tag.longitude, tag.last_seen = str(r["latitude"]), str(r["longitude"]), observed
    if not tag.activation_date:
        # First GPS fix starts the package period, as for polled trackers.
        tag.activation_date = observed
        pkg = db.query(TagPackage).filter(TagPackage.id == tag.package_id).first() if tag.package_id else None
        if pkg:
            tag.expiry_date = pkg.expiry_from(observed.replace(tzinfo=None))


# ---------------------------------------------------------------------------
# Purge + loop
# ---------------------------------------------------------------------------

def purge_raw(events_engine) -> int:
    with events_engine.begin() as ev:
        return ev.execute(text(
            "DELETE FROM events_incoming WHERE status <> 'new' "
            "AND received_at < now() - make_interval(days => :days)"
        ), {"days": config.RAW_RETENTION_DAYS}).rowcount


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    engine = get_engine()
    ensure_schema(engine)
    logger.info("Decoder started")
    last_purge = 0.0
    while True:
        try:
            decoded = decode_batch(engine)
            forwarded = forward_batch(engine)
            if time.monotonic() - last_purge > PURGE_INTERVAL_S:
                purged = purge_raw(engine)
                last_purge = time.monotonic()
                if purged:
                    logger.info("Purged %d raw packets older than %d days", purged, config.RAW_RETENTION_DAYS)
        except Exception:
            logger.exception("Decoder cycle failed")
            time.sleep(5)
            continue
        if not decoded and not forwarded:
            time.sleep(1)


if __name__ == "__main__":
    main()
