"""Restore harsh driving events hidden as "repeats", and recount their trips.

Revision 076's code stored a second harsh event of the same type within 10 s
as unclassified, assuming the device sent each manoeuvre twice. It doesn't:
it sends one record with the type (event IO 253) plus a duration-only record
(IO 243, no type), and events seconds apart are real (e.g. two corners). This
re-classifies any record that has a green driving type in IO 253 but was left
unclassified, and recounts the harsh counters of their trips.

Revision ID: 079_restore_harsh_repeats
Revises: 078_place_visits
Create Date: 2026-10-24
"""
from alembic import op
from sqlalchemy import text

revision = "079_restore_harsh_repeats"
down_revision = "078_place_visits"
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
        UPDATE device_events SET event_type = CASE io->>'253'
            WHEN '1' THEN 'harsh_acceleration' WHEN '2' THEN 'harsh_braking' WHEN '3' THEN 'harsh_cornering' END
        WHERE event_type IS NULL AND event_io_id IN (243, 253, 254) AND io->>'253' IN ('1', '2', '3')
        RETURNING trip_id
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
