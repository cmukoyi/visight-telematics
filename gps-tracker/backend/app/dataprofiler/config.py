"""Connection settings for the DataProfiler event pipeline.

Secrets come from backend/.env (EVENTS_DB_PASSWORD, RABBITMQ_PASSWORD). The
pipeline containers fail fast if they're missing; the backend API treats the
pipeline as "not configured" instead, so a missing secret never takes the
main app down.
"""
import os
from typing import Optional
from urllib.parse import quote

from app._env_guard import required_env

RAW_QUEUE = "dp.raw"            # listener → writer (durable, FIFO)
RAW_EXCHANGE = "dp.ingest"      # direct exchange the listener publishes to

LISTENER_PORT = int(os.getenv("DP_LISTENER_PORT", "5027"))
RAW_RETENTION_DAYS = int(os.getenv("DP_RAW_RETENTION_DAYS", "30"))


def _secret(name: str, required: bool) -> Optional[str]:
    if required:
        return required_env(name)  # also rejects unfilled .env.example placeholders
    try:
        return required_env(name)
    except RuntimeError:
        return None


def rabbitmq_url(required: bool = True) -> Optional[str]:
    password = _secret("RABBITMQ_PASSWORD", required)
    if not password:
        return None
    user = os.getenv("RABBITMQ_USER", "dataprofiler")
    host = os.getenv("RABBITMQ_HOST", "rabbitmq")
    return f"amqp://{quote(user)}:{quote(password)}@{host}:5672/"


def rabbitmq_management(required: bool = True) -> Optional[tuple[str, str, str]]:
    """(base_url, user, password) for the RabbitMQ management HTTP API."""
    password = _secret("RABBITMQ_PASSWORD", required)
    if not password:
        return None
    host = os.getenv("RABBITMQ_HOST", "rabbitmq")
    return f"http://{host}:15672/api", os.getenv("RABBITMQ_USER", "dataprofiler"), password


def events_db_url(required: bool = True) -> Optional[str]:
    password = _secret("EVENTS_DB_PASSWORD", required)
    if not password:
        return None
    user = os.getenv("EVENTS_DB_USER", "dataprofiler")
    host = os.getenv("EVENTS_DB_HOST", "events-db")
    name = os.getenv("EVENTS_DB_NAME", "dataprofiler_events")
    return f"postgresql://{quote(user)}:{quote(password)}@{host}:5432/{name}"
