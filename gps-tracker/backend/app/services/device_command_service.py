"""GPRS commands for Teltonika trackers: validation (portal API) and the queue (GPRS listener).

The portal queues a command in device_commands; the listener, which holds the
device's TCP socket, claims it, sends it as a Codec 12 frame and stores the
reply. Commands can only travel while the device is connected, so a command for
an offline device waits until it next connects, or expires.

    queued ──claim──▶ sent ──reply──▶ responded
       │                └──no reply in REPLY_TIMEOUT_S / socket closed──▶ failed
       └──not sent before expires_at──▶ expired
"""
import re
from datetime import timedelta
from typing import Optional

from sqlalchemy import text

from app.database import SessionLocal

WEB_CONNECT = "web_connect"
DEFAULT_TTL = timedelta(hours=24)
REPLY_TIMEOUT_S = 60
MAX_LENGTH = 256

QUEUED, SENT, RESPONDED, FAILED, EXPIRED = "queued", "sent", "responded", "failed", "expired"

_PRINTABLE = re.compile(r"[\x20-\x7E]+")   # used with fullmatch: "$" would let a trailing newline through


def validate(command: Optional[str]) -> str:
    """The command without surrounding spaces, or ValueError: printable ASCII only, 1–256 characters.
    Only spaces are trimmed, so a newline or other control character is refused, not silently removed."""
    cmd = (command or "").strip(" ")
    if not cmd:
        raise ValueError("Enter a command")
    if len(cmd) > MAX_LENGTH:
        raise ValueError(f"A command can be at most {MAX_LENGTH} characters")
    if not _PRINTABLE.fullmatch(cmd):
        raise ValueError("Use plain ASCII letters, digits and punctuation only (no control characters)")
    return cmd


# ---------------------------------------------------------------------------
# Queue operations used by the GPRS listener (synchronous; it runs them in a thread)
# ---------------------------------------------------------------------------

def queued_imeis() -> set[str]:
    """IMEIs with at least one command waiting to be sent."""
    with SessionLocal() as db:
        return set(db.execute(text(
            "SELECT DISTINCT imei FROM device_commands WHERE status = 'queued' AND expires_at > now()"
        )).scalars().all())


def claim_next(imei: str) -> Optional[tuple[str, str]]:
    """Mark the oldest queued command for this IMEI as sent and return (id, command), or None."""
    with SessionLocal() as db:
        row = db.execute(text(
            "UPDATE device_commands SET status = 'sent', sent_at = now() WHERE id = ("
            "  SELECT id FROM device_commands WHERE imei = :i AND status = 'queued' AND expires_at > now()"
            "  ORDER BY created_at LIMIT 1 FOR UPDATE SKIP LOCKED"
            ") RETURNING id, command"
        ), {"i": imei}).first()
        db.commit()
        return (str(row.id), row.command) if row else None


def mark_responded(command_id: str, response: str) -> None:
    with SessionLocal() as db:
        db.execute(text("UPDATE device_commands SET status = 'responded', responded_at = now(), response = :r "
                        "WHERE id = :id AND status = 'sent'"), {"r": response, "id": command_id})
        db.commit()


def mark_failed(command_id: str, error: str) -> None:
    with SessionLocal() as db:
        db.execute(text("UPDATE device_commands SET status = 'failed', error = :e WHERE id = :id AND status = 'sent'"),
                   {"e": error[:255], "id": command_id})
        db.commit()


def expire_due() -> int:
    """Expire queued commands past their expiry, and fail sent ones the listener lost track of
    (e.g. it restarted while waiting for the reply). Returns the number of rows changed."""
    with SessionLocal() as db:
        expired = db.execute(text(
            "UPDATE device_commands SET status = 'expired', error = 'Not sent: the device did not connect before it expired' "
            "WHERE status = 'queued' AND expires_at <= now()")).rowcount
        lost = db.execute(text(
            "UPDATE device_commands SET status = 'failed', error = 'No reply from the device' "
            "WHERE status = 'sent' AND sent_at < now() - make_interval(secs => :s)"), {"s": REPLY_TIMEOUT_S * 3}).rowcount
        db.commit()
        return expired + lost
