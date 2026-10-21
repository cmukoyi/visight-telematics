import asyncio
import logging
import os
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import or_

from app.database import SessionLocal
from app.models_admin import (
    AppLog,
    CriticalServiceAlertSubscription,
    CriticalServiceCategory,
)
from app.services.email_service import EmailService

logger = logging.getLogger(__name__)


CATEGORY_DEFS: dict[str, dict[str, Any]] = {
    "email_delivery": {
        "label": "Email Delivery",
        "description": "SMTP/SendGrid/Twilio email send failures",
        "patterns": [
            "error sending email",
            "failed to send alert email",
            "sendgrid",
            "smtp",
            "twilio",
        ],
    },
    "database_errors": {
        "label": "Database Errors",
        "description": "Database constraint, rollback, and transaction failures",
        "patterns": [
            "sqlalchemy",
            "integrityerror",
            "foreignkeyviolation",
            "notnullviolation",
            "pendingrollbackerror",
            "infailedsqltransaction",
            "rollback",
        ],
    },
    "container_health": {
        "label": "Container Health",
        "description": "Unhealthy, restarting, or exited service containers",
        "patterns": [],
    },
}


class CriticalServiceAlertService:
    def __init__(self) -> None:
        self.running = False
        self._email = EmailService()
        self._interval_seconds = 60

    @staticmethod
    def _now_utc() -> datetime:
        return datetime.utcnow()

    def _ensure_defaults(self, db) -> None:
        existing = {
            row.category.value if hasattr(row.category, "value") else str(row.category): row
            for row in db.query(CriticalServiceAlertSubscription).all()
        }
        created = 0
        for key in CATEGORY_DEFS.keys():
            if key in existing:
                continue
            db.add(
                CriticalServiceAlertSubscription(
                    category=CriticalServiceCategory(key),
                    is_enabled=False,
                    failure_threshold=5,
                    window_minutes=15,
                    cooldown_minutes=60,
                    recipient_emails=[],
                )
            )
            created += 1
        if created:
            db.commit()

    def _sanitize_recipients(self, emails: list[str] | None) -> list[str]:
        if not emails:
            return []
        cleaned: list[str] = []
        seen = set()
        for raw in emails:
            if not isinstance(raw, str):
                continue
            value = raw.strip().lower()
            if not value or "@" not in value:
                continue
            if value in seen:
                continue
            seen.add(value)
            cleaned.append(value)
        return cleaned

    def _count_log_failures(self, db, category_key: str, window_minutes: int) -> int:
        cfg = CATEGORY_DEFS.get(category_key, {})
        patterns = cfg.get("patterns") or []
        if not patterns:
            return 0

        cutoff = self._now_utc() - timedelta(minutes=window_minutes)
        query = db.query(AppLog).filter(
            AppLog.created_at >= cutoff,
            AppLog.level.in_(["ERROR", "CRITICAL"]),
        )

        clauses = [AppLog.message.ilike(f"%{p}%") for p in patterns]
        if not clauses:
            return 0
        return query.filter(or_(*clauses)).count()

    def _count_container_failures(self) -> tuple[int, list[dict[str, str]]]:
        prefix = os.getenv("ADMIN_OPS_CONTAINER_PREFIX", "visight_telematics_")
        try:
            import docker

            client = docker.from_env()
            failures = []
            for c in client.containers.list(all=True):
                if not c.name.startswith(prefix):
                    continue
                state = c.attrs.get("State", {})
                status = c.status
                health_obj = state.get("Health", {})
                health = health_obj.get("Status", "none") if health_obj else "none"
                if status != "running" or health in ("unhealthy",):
                    failures.append({"name": c.name, "status": status, "health": health})
            return len(failures), failures
        except Exception as exc:
            logger.error("Container health probe failed: %s", exc)
            return 1, [{"name": "docker-socket", "status": "unavailable", "health": "error"}]

    def _should_send(self, sub: CriticalServiceAlertSubscription, failures: int) -> bool:
        if not sub.is_enabled:
            return False
        if failures < max(1, sub.failure_threshold or 1):
            return False
        if sub.last_alert_sent_at is None:
            return True

        last = sub.last_alert_sent_at.replace(tzinfo=None) if sub.last_alert_sent_at.tzinfo else sub.last_alert_sent_at
        cooldown = timedelta(minutes=max(1, sub.cooldown_minutes or 1))
        return (self._now_utc() - last) >= cooldown

    def _send_category_alert(
        self,
        recipients: list[str],
        category_key: str,
        failures: int,
        window_minutes: int,
        extra_lines: list[str] | None = None,
    ) -> bool:
        cfg = CATEGORY_DEFS[category_key]
        title = f"Critical service failures: {cfg['label']}"
        message = (
            f"{cfg['label']} recorded {failures} failures in the last {window_minutes} minutes. "
            f"This crossed the configured threshold."
        )
        meta_data = {
            "category": category_key,
            "failures": failures,
            "window_minutes": window_minutes,
        }
        if extra_lines:
            meta_data["details"] = "; ".join(extra_lines)[:1000]
            message = message + "\n\n" + "\n".join(extra_lines[:8])

        success = False
        for email in recipients:
            ok = self._email.send_portal_alert_email(
                to_email=email,
                alert_type="critical_service_failure",
                title=title,
                message=message,
                meta_data=meta_data,
            )
            success = success or ok
        return success

    def evaluate_once(self) -> None:
        db = SessionLocal()
        try:
            self._ensure_defaults(db)
            subs = db.query(CriticalServiceAlertSubscription).all()
            for sub in subs:
                category_key = sub.category.value if hasattr(sub.category, "value") else str(sub.category)
                recipients = self._sanitize_recipients(sub.recipient_emails)
                if not sub.is_enabled or not recipients:
                    continue

                if category_key == "container_health":
                    failures, detail_rows = self._count_container_failures()
                    detail_lines = [
                        f"{row['name']}: status={row['status']} health={row['health']}"
                        for row in detail_rows
                    ]
                else:
                    failures = self._count_log_failures(db, category_key, sub.window_minutes)
                    detail_lines = None

                if not self._should_send(sub, failures):
                    continue

                sent = self._send_category_alert(
                    recipients=recipients,
                    category_key=category_key,
                    failures=failures,
                    window_minutes=sub.window_minutes,
                    extra_lines=detail_lines,
                )
                if sent:
                    sub.last_alert_sent_at = self._now_utc()
                    db.commit()
                    logger.warning(
                        "Critical alert sent: category=%s failures=%d recipients=%d",
                        category_key,
                        failures,
                        len(recipients),
                    )
        except Exception as exc:
            logger.error("Critical service alert evaluation failed: %s", exc)
            db.rollback()
        finally:
            db.close()

    async def start(self) -> None:
        if self.running:
            return
        self.running = True
        logger.info("Critical service alert monitor started")
        while self.running:
            self.evaluate_once()
            await asyncio.sleep(self._interval_seconds)

    def stop(self) -> None:
        self.running = False
        logger.info("Critical service alert monitor stopped")


critical_service_alerts = CriticalServiceAlertService()
