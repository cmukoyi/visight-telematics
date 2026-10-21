"""Events store — a separate Postgres database for raw and decoded device events.

events_incoming     raw AVL packets exactly as received (one row per packet)
events_processed    decoded records (one row per AVL record), with the event
                    type, whether the device's package makes it visible, and
                    whether it has been delivered to its Data Exchange queue
device_sessions     one row per listener TCP session (open = device online)
rejected_connections IMEIs that tried to connect but aren't on the platform

DataProfiler keeps DP_RAW_RETENTION_DAYS (30) of history; the customer
dashboard keeps what it receives from its exchange queue permanently.
The schema is created idempotently on service start; it lives outside the
main database's Alembic history.
"""
from functools import lru_cache

from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine

from app.dataprofiler.config import events_db_url

SCHEMA = """
CREATE TABLE IF NOT EXISTS events_incoming (
    id            BIGSERIAL PRIMARY KEY,
    received_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
    imei          VARCHAR(20) NOT NULL,
    codec         SMALLINT NOT NULL,
    record_count  INTEGER NOT NULL,
    payload       BYTEA NOT NULL,
    remote_addr   VARCHAR(64),
    status        VARCHAR(12) NOT NULL DEFAULT 'new',   -- new | decoded | failed | unsupported
    error         TEXT,
    decoded_at    TIMESTAMPTZ
);
CREATE INDEX IF NOT EXISTS ix_events_incoming_new ON events_incoming (id) WHERE status = 'new';
CREATE INDEX IF NOT EXISTS ix_events_incoming_received ON events_incoming (received_at);
CREATE INDEX IF NOT EXISTS ix_events_incoming_imei ON events_incoming (imei, received_at DESC);

CREATE TABLE IF NOT EXISTS events_processed (
    id            BIGSERIAL PRIMARY KEY,
    incoming_id   BIGINT REFERENCES events_incoming (id) ON DELETE SET NULL,  -- NULL once raw is purged
    imei          VARCHAR(20) NOT NULL,
    reseller_id   UUID,
    usergroup_id  UUID,
    recorded_at   TIMESTAMPTZ NOT NULL,
    received_at   TIMESTAMPTZ NOT NULL,
    priority      SMALLINT,
    latitude      DOUBLE PRECISION,
    longitude     DOUBLE PRECISION,
    altitude      INTEGER,
    angle         INTEGER,
    satellites    SMALLINT,
    speed         INTEGER,
    event_io_id   INTEGER NOT NULL,
    event_type    VARCHAR(32),
    io            JSONB NOT NULL DEFAULT '{}',
    visible       BOOLEAN NOT NULL DEFAULT false,
    exchange_key  VARCHAR(64),                              -- delivery queue when visible
    delivered     BOOLEAN NOT NULL DEFAULT false,
    created_at    TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS ix_events_processed_imei ON events_processed (imei, recorded_at DESC);
CREATE INDEX IF NOT EXISTS ix_events_processed_group ON events_processed (usergroup_id, recorded_at DESC);
CREATE INDEX IF NOT EXISTS ix_events_processed_created ON events_processed (created_at);
CREATE INDEX IF NOT EXISTS ix_events_processed_incoming ON events_processed (incoming_id);
CREATE INDEX IF NOT EXISTS ix_events_processed_undelivered ON events_processed (id)
    WHERE visible AND NOT delivered;

CREATE TABLE IF NOT EXISTS device_sessions (
    id              BIGSERIAL PRIMARY KEY,
    imei            VARCHAR(20) NOT NULL,
    remote_addr     VARCHAR(64),
    connected_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    last_packet_at  TIMESTAMPTZ,
    packets         INTEGER NOT NULL DEFAULT 0,
    records         INTEGER NOT NULL DEFAULT 0,
    disconnected_at TIMESTAMPTZ,                             -- NULL while the device is connected
    close_reason    VARCHAR(64)
);
CREATE INDEX IF NOT EXISTS ix_device_sessions_imei ON device_sessions (imei, connected_at DESC);
CREATE INDEX IF NOT EXISTS ix_device_sessions_open ON device_sessions (imei) WHERE disconnected_at IS NULL;

CREATE TABLE IF NOT EXISTS rejected_connections (
    id            BIGSERIAL PRIMARY KEY,
    imei          VARCHAR(20) NOT NULL,
    remote_addr   VARCHAR(64),
    attempted_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS ix_rejected_connections_time ON rejected_connections (attempted_at DESC);
"""


@lru_cache(maxsize=1)
def get_engine(url: str = None) -> Engine:
    return create_engine(url or events_db_url(), pool_pre_ping=True, pool_size=5, max_overflow=5)


def ensure_schema(engine: Engine) -> None:
    with engine.begin() as conn:
        # Serialise concurrent service starts on the same DDL.
        conn.execute(text("SELECT pg_advisory_xact_lock(724001)"))
        conn.execute(text(SCHEMA))
