"""Classify green driving records sent with event IO 243 (duration) or 254 (value).

These were stored unclassified (shown as "Unmapped (IO 243)"); the type is in
IO 253. Sets their event_type, unless the device already has that event within
10 s (the same manoeuvre's IO 253 record, see trip_builder.is_repeat), and
recounts the harsh counters of their trips.

Revision ID: 076_green_driving_io
Revises: 075_portal_user_language
Create Date: 2026-10-23
"""
from alembic import op
from sqlalchemy import text

revision = "076_green_driving_io"
down_revision = "075_portal_user_language"
branch_labels = None
depends_on = None

COUNTERS = {
    "harsh_acceleration": "harsh_acceleration_count",
    "harsh_braking": "harsh_braking_count",
    "harsh_cornering": "harsh_cornering_count",
}


def upgrade():
    conn = op.get_bind()
    if not conn.execute(text("SELECT to_regclass('device_events') IS NOT NULL")).scalar():
        return
    trips = conn.execute(text("""
        WITH typed AS (
            SELECT id, imei, recorded_at, CASE io->>'253' WHEN '1' THEN 'harsh_acceleration'
                WHEN '2' THEN 'harsh_braking' WHEN '3' THEN 'harsh_cornering' END AS code
            FROM device_events
            WHERE event_type IS NULL AND event_io_id IN (243, 254) AND io->>'253' IN ('1', '2', '3')
        ), firsts AS (
            SELECT t.id, t.code FROM typed t
            WHERE NOT EXISTS (
                SELECT 1 FROM device_events p WHERE p.imei = t.imei AND p.event_type = t.code
                  AND p.recorded_at BETWEEN t.recorded_at - interval '10 seconds' AND t.recorded_at + interval '10 seconds')
              AND NOT EXISTS (
                SELECT 1 FROM typed o WHERE o.imei = t.imei AND o.code = t.code AND o.id < t.id
                  AND o.recorded_at BETWEEN t.recorded_at - interval '10 seconds' AND t.recorded_at + interval '10 seconds')
        )
        UPDATE device_events d SET event_type = f.code FROM firsts f WHERE d.id = f.id
        RETURNING d.trip_id
    """)).scalars().all()
    trip_ids = list({str(t) for t in trips if t is not None})
    if not trip_ids:
        return
    for code, column in COUNTERS.items():
        conn.execute(text(f"""
            UPDATE trips t SET {column} = (
                SELECT count(*) FROM device_events e WHERE e.trip_id = t.id AND e.event_type = :code)
            WHERE t.id::text = ANY(:ids)
        """), {"code": code, "ids": trip_ids})


def downgrade():
    pass
