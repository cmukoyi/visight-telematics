"""SMS sending service using Twilio.

Reads credentials from environment variables:
    TWILIO_ACCOUNT_SID   — Twilio Account SID (starts with AC...)
    TWILIO_AUTH_TOKEN    — Twilio Auth Token
    TWILIO_FROM_NUMBER   — E.164 sender number, e.g. +447700123456

If any of these are missing the service is disabled and send() returns False
without raising, so the rest of the alert pipeline is unaffected.
"""
import logging
import os
import re

logger = logging.getLogger(__name__)

_E164_RE = re.compile(r"^\+[1-9]\d{7,14}$")


def _normalise_number(raw: str) -> str | None:
    """Strip spaces/dashes and validate E.164 format. Returns None if invalid."""
    if not raw:
        return None
    cleaned = re.sub(r"[\s\-\(\)]", "", raw.strip())
    if not cleaned.startswith("+"):
        # Attempt to add UK prefix for bare 07xxx numbers
        if cleaned.startswith("07") and len(cleaned) == 11:
            cleaned = "+44" + cleaned[1:]
        else:
            return None
    return cleaned if _E164_RE.match(cleaned) else None


class SMSService:
    def __init__(self):
        self.account_sid = os.getenv("TWILIO_ACCOUNT_SID", "")
        self.auth_token  = os.getenv("TWILIO_AUTH_TOKEN", "")
        self.from_number = os.getenv("TWILIO_FROM_NUMBER", "")
        self.enabled = bool(self.account_sid and self.auth_token and self.from_number)
        if not self.enabled:
            logger.info("SMS service disabled — TWILIO_* env vars not set")

    def send(self, to_number: str, body: str) -> bool:
        """Send an SMS. Returns True on success, False on any failure."""
        if not self.enabled:
            logger.debug("SMS not sent (service disabled): %s", body[:60])
            return False

        to = _normalise_number(to_number)
        if not to:
            logger.warning("SMS skipped — invalid number: %r", to_number)
            return False

        try:
            from twilio.rest import Client  # lazy import — optional dependency
            client = Client(self.account_sid, self.auth_token)
            msg = client.messages.create(body=body, from_=self.from_number, to=to)
            logger.info("📱 SMS sent to %s sid=%s", to, msg.sid)
            return True
        except ImportError:
            logger.error("twilio package not installed — run: pip install twilio")
            return False
        except Exception as exc:
            logger.error("SMS send failed to %s: %s", to, exc)
            return False

    def send_alert(self, to_number: str, alert_type: str, title: str, message: str) -> bool:
        """Send a formatted alert SMS."""
        type_emoji = {
            "geofence_entry":        "📍",
            "geofence_exit":         "🚪",
            "battery_low":           "🔋",
            "tag_offline":           "📡",
            "gdpr_deletion_warning": "⚠️",
        }
        emoji = type_emoji.get(alert_type, "🔔")
        body = f"{emoji} {os.getenv('BRAND_NAME', 'ViSight Track')} Alert\n{title}\n{message}"
        # Truncate to 160 chars for single SMS
        if len(body) > 160:
            body = body[:157] + "..."
        return self.send(to_number, body)


# Shared singleton
sms_service = SMSService()
