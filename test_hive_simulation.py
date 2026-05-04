#!/usr/bin/env python3
"""
test_hive_simulation.py
=======================
Simulates one tag drifting away from a group to verify end-to-end HIVE breach detection.

Creates its own synthetic BLETag rows (fake IMEIs like HIVE_TEST_SIM_001) so no real
customer data is needed and the location poller will never match these IMEIs against a
real device.  All synthetic rows are deleted on cleanup.

Data flow mirrors production exactly:
  1. Synthetic BLETag rows inserted directly in Postgres
  2. BLETag.latitude/longitude/last_seen updated (same as location_poller_service)
  3. POST /api/portal/hive/{id}/evaluate triggers the state machine
  4. GET /api/portal/hive/{id} reads back the result

Requirements:
  pip install requests psycopg2-binary sqlalchemy

Usage (against production — safe because synthetic tags have fake IMEIs):
  python test_hive_simulation.py \
    --db-url "postgresql://pinplot_db_user:PASSWORD@host:5432/pinplot_db" \
    --api-url "https://pinplot.co.uk" \
    --email  "your@email.com" \
    --password "yourpassword"

  Or set environment variables:
    HIVE_TEST_DB_URL, HIVE_TEST_API_URL, HIVE_TEST_EMAIL, HIVE_TEST_PASSWORD

  Dry-run (just verify login, no DB writes):
    python test_hive_simulation.py ... --dry-run

  Use existing real tags instead of creating synthetic ones:
    python test_hive_simulation.py ... --use-real-tags
"""

import argparse
import base64
import json
import math
import os
import sys
import time
import uuid
from datetime import datetime, timedelta, timezone

import requests

try:
    from sqlalchemy import create_engine, text
except ImportError:
    print("ERROR: sqlalchemy not installed.  pip install sqlalchemy psycopg2-binary")
    sys.exit(1)

# ─── JWT payload decode (no signature verification — we only need the user_id) ─
def _jwt_user_id(token: str) -> str:
    """Extract 'sub' or 'user_id' claim from a JWT without verifying signature."""
    try:
        payload_b64 = token.split(".")[1]
        # Add padding if needed
        payload_b64 += "=" * (-len(payload_b64) % 4)
        payload = json.loads(base64.urlsafe_b64decode(payload_b64))
        uid = payload.get("sub") or payload.get("user_id") or payload.get("id")
        if not uid:
            fail(f"JWT payload has no sub/user_id/id claim: {list(payload.keys())}")
        return str(uid)
    except Exception as e:
        fail(f"Could not decode JWT: {e}")

# ─── colour helpers ────────────────────────────────────────────────────────────
GREEN  = "\033[92m"
RED    = "\033[91m"
YELLOW = "\033[93m"
CYAN   = "\033[96m"
BOLD   = "\033[1m"
RESET  = "\033[0m"

def ok(msg):    print(f"  {GREEN}✓  {msg}{RESET}")
def fail(msg):  print(f"  {RED}✗  {msg}{RESET}"); sys.exit(1)
def warn(msg):  print(f"  {YELLOW}!  {msg}{RESET}")
def info(msg):  print(f"  {CYAN}→  {msg}{RESET}")
def step(n, msg): print(f"\n{BOLD}[{n}] {msg}{RESET}")

# ─── haversine (for display) ───────────────────────────────────────────────────
def _haversine_m(lat1, lon1, lat2, lon2):
    R = 6_371_000
    φ1, φ2 = math.radians(lat1), math.radians(lat2)
    dφ = math.radians(lat2 - lat1)
    dλ = math.radians(lon2 - lon1)
    a = math.sin(dφ/2)**2 + math.cos(φ1)*math.cos(φ2)*math.sin(dλ/2)**2
    return 2 * R * math.asin(math.sqrt(a))

# ─── offset a coordinate by metres ───────────────────────────────────────────
def _offset(lat, lon, north_m, east_m):
    """Return (lat, lon) offset by north_m metres north and east_m metres east."""
    new_lat = lat + (north_m / 111_320)
    new_lon = lon + (east_m  / (111_320 * math.cos(math.radians(lat))))
    return round(new_lat, 7), round(new_lon, 7)


# ─── DB helpers ────────────────────────────────────────────────────────────────

SYNTHETIC_IMEI_PREFIX = "HIVE_TEST_SIM_"  # location poller never polls these

def _create_synthetic_tags(engine, user_id: str, count: int = 3) -> list[dict]:
    """
    Insert fake BLETag rows owned by user_id with IMEIs like HIVE_TEST_SIM_001.
    The location poller ignores these — it only polls IMEIs returned by TrackSolid/MZone APIs.
    Returns list of dicts with keys: tag_id, imei, label.
    """
    tags = []
    with engine.connect() as conn:
        for i in range(1, count + 1):
            tag_id  = str(uuid.uuid4())
            imei    = f"{SYNTHETIC_IMEI_PREFIX}{tag_id[:8].upper()}"
            label   = f"SIM-TAG-{i:02d}"
            conn.execute(text("""
                INSERT INTO ble_tags (id, user_id, imei, device_name, tag_type, is_active)
                VALUES (:id, :uid, :imei, :name, 'series1', true)
            """), {"id": tag_id, "uid": user_id, "imei": imei, "name": label})
            tags.append({"tag_id": tag_id, "imei": imei, "label": label})
        conn.commit()
    return tags


def _delete_synthetic_tags(engine, tag_ids: list[str]):
    """Remove the synthetic rows (hive memberships are cascade-deleted or archived first)."""
    if not tag_ids:
        return
    with engine.connect() as conn:
        # Remove memberships first in case the hive archive didn't cascade
        conn.execute(text(
            "DELETE FROM hive_tag_membership WHERE tag_id = ANY(:ids)"
        ), {"ids": tag_ids})
        conn.execute(text(
            "DELETE FROM ble_tags WHERE id = ANY(:ids) AND imei LIKE :prefix"
        ), {"ids": tag_ids, "prefix": f"{SYNTHETIC_IMEI_PREFIX}%"})
        conn.commit()


def _set_tag_position(engine, tag_id: str, lat: float, lon: float):
    """Write lat/lon/last_seen to BLETag row — same columns the location poller writes."""
    now = datetime.utcnow().isoformat()
    with engine.connect() as conn:
        conn.execute(text(
            "UPDATE ble_tags SET latitude=:lat, longitude=:lon, last_seen=:ls WHERE id=:id"
        ), {"lat": str(lat), "lon": str(lon), "ls": now, "id": tag_id})
        conn.commit()


def _reset_hive_live_state(engine, hive_id: str):
    """Reset alert state to OK so each test run starts clean."""
    with engine.connect() as conn:
        conn.execute(text(
            "UPDATE hive_live_state SET alert_state='OK', consecutive_confirms=0, "
            "pending_breach_since=NULL, pending_clear_since=NULL, "
            "current_diameter_m=NULL, outlier_tag_id=NULL WHERE hive_id=:hid"
        ), {"hid": hive_id})
        conn.commit()


def _get_live_state(engine, hive_id: str) -> dict:
    with engine.connect() as conn:
        row = conn.execute(text(
            "SELECT alert_state, current_diameter_m, outlier_tag_id, consecutive_confirms "
            "FROM hive_live_state WHERE hive_id=:hid"
        ), {"hid": hive_id}).fetchone()
    if row:
        return dict(row._mapping)
    return {}


# ─── API helpers ──────────────────────────────────────────────────────────────
class HiveAPI:
    def __init__(self, base_url: str, token: str):
        self.base = base_url.rstrip("/")
        self.headers = {"Authorization": f"Bearer {token}"}

    def get(self, path):
        r = requests.get(self.base + path, headers=self.headers, timeout=15)
        r.raise_for_status()
        return r.json()

    def post(self, path, json=None):
        r = requests.post(self.base + path, headers=self.headers, json=json or {}, timeout=15)
        r.raise_for_status()
        return r.json()

    def delete(self, path):
        r = requests.delete(self.base + path, headers=self.headers, timeout=15)
        r.raise_for_status()
        return r.json()

    def available_tags(self):
        return self.get("/api/portal/hive/tags/available")

    def create_hive(self, name, tag_ids, profile="mobile", threshold_m=200):
        return self.post("/api/portal/hive", {
            "name": name,
            "tag_ids": tag_ids,
            "mobility_profile": profile,
            "distance_threshold_m": threshold_m,
        })

    def evaluate(self, hive_id):
        return self.post(f"/api/portal/hive/{hive_id}/evaluate")

    def detail(self, hive_id):
        return self.get(f"/api/portal/hive/{hive_id}")

    def archive(self, hive_id):
        return self.delete(f"/api/portal/hive/{hive_id}")


def _portal_login(base_url: str, email: str, password: str) -> str:
    r = requests.post(
        base_url.rstrip("/") + "/api/portal/login",
        json={"email": email, "password": password},
        timeout=15,
    )
    if not r.ok:
        fail(f"Login failed: {r.status_code} {r.text[:200]}")
    return r.json()["access_token"]


# ─── main ──────────────────────────────────────────────────────────────────────
def main():
    parser = argparse.ArgumentParser(description="HIVE breach simulation test")
    parser.add_argument("--db-url",   default=os.getenv("HIVE_TEST_DB_URL"),
                        help="SQLAlchemy DB URL e.g. postgresql://user:pw@host/db")
    parser.add_argument("--api-url",  default=os.getenv("HIVE_TEST_API_URL", "http://localhost:8001"),
                        help="Backend API base URL")
    parser.add_argument("--email",    default=os.getenv("HIVE_TEST_EMAIL"),
                        help="Portal user email")
    parser.add_argument("--password", default=os.getenv("HIVE_TEST_PASSWORD"),
                        help="Portal user password")
    parser.add_argument("--threshold-m", type=float, default=200,
                        help="Breach threshold in metres (default: 200)")
    parser.add_argument("--runaway-m", type=float, default=500,
                        help="How far the runaway tag drifts in metres (default: 500)")
    parser.add_argument("--profile",  default="mobile",
                        choices=["stationary", "slow", "mobile", "fast"],
                        help="Mobility profile (default: mobile)")
    parser.add_argument("--hive-id",  default=None,
                        help="Use an existing hive ID instead of creating one")
    parser.add_argument("--dry-run",  action="store_true",
                        help="Just log in, do not create/evaluate")
    parser.add_argument("--no-cleanup", action="store_true",
                        help="Leave the test hive alive after the test")
    parser.add_argument("--use-real-tags", action="store_true",
                        help="Use available real tags instead of creating synthetic ones")
    args = parser.parse_args()

    if not args.email or not args.password:
        fail("--email and --password are required (or set HIVE_TEST_EMAIL / HIVE_TEST_PASSWORD)")
    if not args.db_url:
        fail("--db-url is required (or set HIVE_TEST_DB_URL)")

    print(f"\n{BOLD}══════════════════════════════════════════════")
    print(f"  HIVE Breach Simulation Test")
    print(f"══════════════════════════════════════════════{RESET}")
    info(f"API:       {args.api_url}")
    info(f"Profile:   {args.profile}")
    info(f"Threshold: {args.threshold_m}m")
    info(f"Runaway:   {args.runaway_m}m")

    # ── DB connection ─────────────────────────────────────────────────────────
    step(1, "Database connection")
    try:
        engine = create_engine(args.db_url, pool_pre_ping=True)
        with engine.connect() as c:
            c.execute(text("SELECT 1"))
        ok(f"Connected to {args.db_url.split('@')[-1]}")
    except Exception as e:
        fail(f"DB connection failed: {e}")

    # ── Login ────────────────────────────────────────────────────────────────
    step(2, "Portal login")
    try:
        token = _portal_login(args.api_url, args.email, args.password)
        ok(f"Logged in as {args.email}")
    except Exception as e:
        fail(f"Login error: {e}")
    api = HiveAPI(args.api_url, token)

    # Extract user_id from JWT — needed to create synthetic tags under the right owner
    user_id = _jwt_user_id(token)
    info(f"User ID from token: {user_id[:8]}…")

    if args.dry_run:
        ok("Dry-run complete — no DB writes, no hive created")
        print()
        return

    # ── Synthetic tags (default) or real available tags ───────────────────────
    synthetic_tag_ids = []   # tracked for cleanup

    if not args.hive_id:
        if args.use_real_tags:
            step(3, "Fetching available tags (real)")
            tags = api.available_tags()
            if len(tags) < 2:
                fail(f"Need at least 2 available real tags, found {len(tags)}. "
                     "Release tags from existing hives first.")
            selected   = tags[:min(3, len(tags))]
            tag_ids    = [t["tag_id"] for t in selected]
            for t in selected:
                info(f"  {t['tag_id'][:8]}…  label={t.get('label')}")
            ok(f"Using {len(tag_ids)} real tag(s)")
        else:
            step(3, "Creating synthetic test tags (fake IMEIs — safe on production)")
            synthetic = _create_synthetic_tags(engine, user_id, count=3)
            tag_ids            = [t["tag_id"] for t in synthetic]
            synthetic_tag_ids  = tag_ids[:]
            for t in synthetic:
                info(f"  {t['tag_id'][:8]}…  imei={t['imei']}  label={t['label']}")
            ok(f"Created {len(tag_ids)} synthetic tag(s)")

        # ── Create test hive ─────────────────────────────────────────────────
        step(4, "Create test hive")
        try:
            result  = api.create_hive(
                name=f"[TEST] Runaway Sim {datetime.utcnow():%H:%M:%S}",
                tag_ids=tag_ids,
                profile=args.profile,
                threshold_m=args.threshold_m,
            )
            hive_id = result["hive_id"]
            ok(f"Created hive {hive_id[:8]}…  ({len(tag_ids)} tags, threshold={args.threshold_m}m)")
        except Exception as e:
            # Clean up synthetic tags if hive creation fails
            _delete_synthetic_tags(engine, synthetic_tag_ids)
            fail(f"Create hive failed: {e}")

        selected_dicts = [{"tag_id": tid, "label": tid[:8]} for tid in tag_ids]
    else:
        step(3, "Using existing hive")
        hive_id = args.hive_id
        d = api.detail(hive_id)
        step(4, f"Hive {hive_id[:8]}… — {d.get('name')}")
        tag_ids        = [t["tag_id"] for t in d.get("tags", [])]
        selected_dicts = d.get("tags", [])
        ok(f"Found {len(tag_ids)} member tag(s)")
        if len(tag_ids) < 2:
            fail("Hive has fewer than 2 tags — cannot simulate breach")

    # Pick the "runaway" — last tag in the list
    runaway_tag_id   = tag_ids[-1]
    runaway_label    = next(
        (t.get("label", runaway_tag_id[:8]) for t in selected_dicts
         if t.get("tag_id") == runaway_tag_id),
        runaway_tag_id[:8]
    )
    group_tag_ids    = tag_ids[:-1]

    # ── Phase 1: cluster all tags together ───────────────────────────────────
    step(5, "Phase 1 — cluster all tags at the same location")

    # Base location: central London (easy to verify on a map)
    BASE_LAT, BASE_LON = 51.5074, -0.1278

    # Place grouped tags within 20m of each other
    offsets = [(0, 0), (10, 5), (-8, 12), (4, -9), (-5, -6)]
    for i, tid in enumerate(tag_ids):
        off_n, off_e = offsets[i % len(offsets)]
        lat, lon = _offset(BASE_LAT, BASE_LON, off_n, off_e)
        _set_tag_position(engine, tid, lat, lon)
        label = tid[:8]
        info(f"  Set tag {label}…  lat={lat}  lon={lon}  (offset +{off_n}m N / +{off_e}m E)")

    # Reset live state to OK so we start clean
    _reset_hive_live_state(engine, hive_id)
    ok("All tags positioned together, live state reset to OK")

    # ── Eval 1 — expect OK ────────────────────────────────────────────────────
    step(6, "Evaluate (expect: OK — group is together)")
    ev1 = api.evaluate(hive_id)
    d1  = api.detail(hive_id)
    state1 = d1.get("alert_state", "?")
    diam1  = d1.get("current_diameter_m")
    info(f"  alert_state={state1}  diameter={diam1 and round(diam1)+'m' or 'none'}")
    if state1 == "OK":
        ok("State is OK as expected")
    else:
        warn(f"State is {state1} (not ideal, but proceeding — tags may already have real positions)")

    # ── Phase 2: move the runaway tag far away ────────────────────────────────
    step(7, f"Phase 2 — move '{runaway_label}' {args.runaway_m}m away (north-east)")
    runaway_lat, runaway_lon = _offset(
        BASE_LAT, BASE_LON,
        north_m=args.runaway_m * 0.707,
        east_m =args.runaway_m * 0.707,
    )
    _set_tag_position(engine, runaway_tag_id, runaway_lat, runaway_lon)
    actual_dist = _haversine_m(BASE_LAT, BASE_LON, runaway_lat, runaway_lon)
    ok(f"Moved runaway tag to lat={runaway_lat}  lon={runaway_lon}")
    info(f"  Distance from group centre: ~{round(actual_dist)}m")
    info(f"  Breach threshold: {args.threshold_m}m")
    if actual_dist <= args.threshold_m:
        warn(f"Runaway distance {round(actual_dist)}m is within threshold {args.threshold_m}m — "
             "increase --runaway-m or decrease --threshold-m")

    # ── Eval 2 — expect BREACH_PENDING ───────────────────────────────────────
    step(8, "Evaluate cycle 1 (expect: BREACH_PENDING — breach just detected)")
    ev2 = api.evaluate(hive_id)
    d2  = api.detail(hive_id)
    state2 = d2.get("alert_state", "?")
    diam2  = d2.get("current_diameter_m")
    outlier2 = d2.get("outlier_tag_id")
    info(f"  alert_state={state2}  diameter={diam2 and round(diam2)+'m' or 'none'}  outlier={outlier2 and outlier2[:8]}")

    if state2 in ("BREACH_PENDING", "BREACHING"):
        ok(f"State is {state2} — breach detected!")
    elif state2 == "OK":
        warn("Still OK. Possible reasons:")
        warn("  • The runaway tag has freshness < fresh_window_s but confidence is 'low'")
        warn("  • Tag last_seen not updating (check BLETag row was updated)")
        db_state = _get_live_state(engine, hive_id)
        info(f"  DB live_state: {db_state}")

    # ── Eval 3 — expect BREACHING ─────────────────────────────────────────────
    step(9, "Evaluate cycle 2 (expect: BREACHING — confirmed)")
    time.sleep(0.5)  # tiny pause so timestamps differ
    ev3 = api.evaluate(hive_id)
    d3  = api.detail(hive_id)
    state3    = d3.get("alert_state", "?")
    diam3     = d3.get("current_diameter_m")
    outlier3  = d3.get("outlier_tag_id")
    confidence= d3.get("breach_confidence")
    info(f"  alert_state={state3}  diameter={diam3 and round(diam3)+'m' or 'none'}  "
         f"outlier={outlier3 and outlier3[:8]}  confidence={confidence}")

    if state3 == "BREACHING":
        ok("BREACHING confirmed!")
    elif state3 == "BREACH_PENDING":
        # Profile with confirmation_count > 2 needs another cycle
        warn("Still BREACH_PENDING — profile needs more confirmation cycles. "
             "Running extra evaluation...")
        for extra in range(3):
            time.sleep(0.3)
            api.evaluate(hive_id)
            dx = api.detail(hive_id)
            if dx.get("alert_state") == "BREACHING":
                state3 = "BREACHING"
                ok(f"BREACHING confirmed on extra eval #{extra+1}")
                break
        else:
            warn("Could not reach BREACHING after 3 extra cycles")
    else:
        warn(f"Unexpected state: {state3}")

    # ── Print tag breakdown ───────────────────────────────────────────────────
    step(10, "Tag breakdown from detail response")
    for t in d3.get("tags", []):
        role     = "OUTLIER" if t.get("is_outlier") else "core"
        fresh    = t.get("freshness", "?")
        dist     = t.get("distance_from_centre_m")
        dist_str = f"{round(dist)}m" if dist is not None else "—"
        tid_short = t.get("tag_id", "")[:8]
        flag = "  ← RUNAWAY" if t.get("tag_id") == runaway_tag_id else ""
        print(f"    {tid_short}…  label={t.get('label','?'):<20} role={role:<8}  "
              f"freshness={fresh:<8} distance={dist_str}{flag}")

    # ── Recent events ─────────────────────────────────────────────────────────
    step(11, "Recent events")
    for ev in (d3.get("recent_events") or [])[:5]:
        t    = ev.get("occurred_at", "")[:19].replace("T", " ")
        etype= ev.get("event_type", "")
        fstate = ev.get("from_state", "?")
        tstate = ev.get("to_state", "?")
        tag  = ev.get("triggering_tag_id") or ""
        print(f"    {t}  {etype:<30} {fstate} → {tstate}  tag={tag[:8] if tag else '—'}")

    # ── Result summary ────────────────────────────────────────────────────────
    print(f"\n{BOLD}══ TEST RESULT ══{RESET}")
    passed = state3 == "BREACHING"
    if passed:
        print(f"  {GREEN}{BOLD}PASS{RESET} — breach correctly detected")
        print(f"  {GREEN}Group diameter: {round(diam3 or 0)}m  (threshold: {args.threshold_m}m)")
        print(f"  Runaway tag: {runaway_label}  (~{round(actual_dist)}m from group){RESET}")
    else:
        print(f"  {RED}{BOLD}NEEDS REVIEW{RESET} — final state: {state3}")
        print(f"  {YELLOW}Check that:")
        print(f"    1. BLETag.last_seen was updated (tag must be 'fresh')")
        print(f"    2. Runaway distance ({round(actual_dist)}m) > threshold ({args.threshold_m}m)")
        print(f"    3. Hive is not in settling period{RESET}")
        db_state = _get_live_state(engine, hive_id)
        info(f"  DB live_state row: {db_state}")

    # ── Cleanup ───────────────────────────────────────────────────────────────
    if not args.no_cleanup and not args.hive_id:
        step(12, "Cleanup — archiving test hive + deleting synthetic tags")
        try:
            api.archive(hive_id)
            ok(f"Test hive {hive_id[:8]}… archived")
        except Exception as e:
            warn(f"Cleanup: archive failed: {e}")
        if synthetic_tag_ids:
            try:
                _delete_synthetic_tags(engine, synthetic_tag_ids)
                ok(f"{len(synthetic_tag_ids)} synthetic BLETag row(s) deleted")
            except Exception as e:
                warn(f"Cleanup: delete synthetic tags failed: {e}")
    elif args.no_cleanup:
        warn(f"--no-cleanup set — test hive {hive_id[:8]}… left alive")
        if synthetic_tag_ids:
            warn("Synthetic BLETag rows also left in DB — run with cleanup to remove them")
    elif args.hive_id:
        info("Used existing hive — skipping archive cleanup")

    print()


if __name__ == "__main__":
    main()
