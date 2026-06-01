"""
tracksolid_poller.py
--------------------
Tracksolid / JIMI API polling service.
- Syncs device metadata (upsert by IMEI)
- Polls location + battery every 10 minutes
- Caches access_token in DB to avoid rate limits

Usage in FastAPI main.py:
    from tracksolid_poller import start_poller
    @app.on_event("startup")
    async def startup():
        start_poller()
"""

import hashlib
import logging
from datetime import datetime, timezone, timedelta

import httpx
import aiomysql
from apscheduler.schedulers.asyncio import AsyncIOScheduler

# ── Config ────────────────────────────────────────────────────────────────────

TRACKSOLID_CONFIG = {
    "app_key":    "8FB345B8693CCD00705B2242580910A0339A22A4105B6558",
    "app_secret": "860d274a6c50445d86a93ed89de79278",
    "user_id":    "Beacontelematics",
    "password":   "Transport01!",
    "base_url":   "https://eu-open.tracksolidpro.com/route/rest",
}

DB_CONFIG = {
    "host":     "db",           # docker-compose service name
    "port":     3306,
    "user":     "your_db_user",
    "password": "your_db_pass",
    "db":       "your_db_name",
    "autocommit": True,
}

POLL_INTERVAL_MINUTES = 10

# ── Logging ───────────────────────────────────────────────────────────────────

logging.basicConfig(level=logging.INFO)
log = logging.getLogger("tracksolid_poller")

# ── Helpers ───────────────────────────────────────────────────────────────────

def _utc_now_str() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")


def _build_sign(params: dict, app_secret: str) -> str:
    sorted_keys = sorted(params.keys())
    concat = "".join(k + str(params[k]) for k in sorted_keys if params[k])
    raw = app_secret + concat + app_secret
    return hashlib.md5(raw.encode("utf-8")).hexdigest().upper()


def _parse_dt(val: str | None) -> datetime | None:
    if not val:
        return None
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S.%fZ", "%Y-%m-%dT%H:%M:%SZ"):
        try:
            return datetime.strptime(val, fmt)
        except (ValueError, TypeError):
            continue
    return None


# ── DB helpers ────────────────────────────────────────────────────────────────

async def get_db() -> aiomysql.Connection:
    return await aiomysql.connect(**DB_CONFIG)


async def ensure_tables():
    """Create tables if they don't exist yet."""
    conn = await get_db()
    async with conn.cursor() as cur:
        await cur.execute("""
            CREATE TABLE IF NOT EXISTS api_tokens (
                id           INT PRIMARY KEY DEFAULT 1,
                access_token VARCHAR(200) NOT NULL,
                refresh_token VARCHAR(200),
                expires_at   DATETIME NOT NULL
            )
        """)
        await cur.execute("""
            CREATE TABLE IF NOT EXISTS tracksolid_devices (
                id              INT AUTO_INCREMENT PRIMARY KEY,
                imei            VARCHAR(20)  UNIQUE NOT NULL,
                device_name     VARCHAR(100),
                mc_type         VARCHAR(50),
                mc_type_scope   VARCHAR(50),
                sim             VARCHAR(50),
                vehicle_number  VARCHAR(50),
                vehicle_name    VARCHAR(100),
                driver_name     VARCHAR(100),
                driver_phone    VARCHAR(50),
                activation_time DATETIME,
                expiration      DATETIME,
                enabled_flag    TINYINT DEFAULT 1,
                device_group    VARCHAR(100),
                created_at      DATETIME DEFAULT CURRENT_TIMESTAMP,
                updated_at      DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP
            )
        """)
        await cur.execute("""
            CREATE TABLE IF NOT EXISTS tracksolid_locations (
                id          INT AUTO_INCREMENT PRIMARY KEY,
                imei        VARCHAR(20)  NOT NULL,
                lat         DOUBLE,
                lng         DOUBLE,
                speed       VARCHAR(10),
                acc_status  VARCHAR(5),
                gps_time    DATETIME,
                hb_time     DATETIME,
                pos_type    VARCHAR(10),
                battery     VARCHAR(10),
                power_value VARCHAR(10),
                gps_signal  VARCHAR(5),
                gps_num     VARCHAR(5),
                direction   VARCHAR(10),
                status      VARCHAR(5),
                expire_flag VARCHAR(5),
                recorded_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                INDEX idx_imei        (imei),
                INDEX idx_recorded_at (recorded_at)
            )
        """)
    conn.close()
    log.info("DB tables verified.")


# ── Token management ──────────────────────────────────────────────────────────

async def get_cached_token() -> str | None:
    """Return a valid cached token from DB, or None if expired/missing."""
    conn = await get_db()
    try:
        async with conn.cursor(aiomysql.DictCursor) as cur:
            await cur.execute("SELECT access_token, expires_at FROM api_tokens WHERE id = 1")
            row = await cur.fetchone()
            if not row:
                return None
            # Expire 5 min early to be safe
            if row["expires_at"] > datetime.utcnow() + timedelta(minutes=5):
                return row["access_token"]
            return None
    finally:
        conn.close()


async def save_token(access_token: str, refresh_token: str, expires_in: int):
    expires_at = datetime.utcnow() + timedelta(seconds=expires_in)
    conn = await get_db()
    try:
        async with conn.cursor() as cur:
            await cur.execute("""
                INSERT INTO api_tokens (id, access_token, refresh_token, expires_at)
                VALUES (1, %s, %s, %s)
                ON DUPLICATE KEY UPDATE
                    access_token  = VALUES(access_token),
                    refresh_token = VALUES(refresh_token),
                    expires_at    = VALUES(expires_at)
            """, (access_token, refresh_token, expires_at))
    finally:
        conn.close()


async def fetch_new_token() -> str:
    cfg = TRACKSOLID_CONFIG
    password_md5 = hashlib.md5(cfg["password"].encode()).hexdigest().lower()
    timestamp = _utc_now_str()

    params = {
        "app_key":      cfg["app_key"],
        "expires_in":   "7200",
        "format":       "json",
        "method":       "jimi.oauth.token.get",
        "sign_method":  "md5",
        "timestamp":    timestamp,
        "user_id":      cfg["user_id"],
        "user_pwd_md5": password_md5,
        "v":            "0.9",
    }
    params["sign"] = _build_sign(params, cfg["app_secret"])

    async with httpx.AsyncClient(timeout=15) as client:
        resp = await client.post(cfg["base_url"], data=params)
        data = resp.json()

    if data.get("code") != 0:
        raise RuntimeError(f"Token fetch failed: {data}")

    result = data["result"]
    access_token  = result["accessToken"]
    refresh_token = result.get("refreshToken", "")
    expires_in    = int(result.get("expiresIn", 7200))

    await save_token(access_token, refresh_token, expires_in)
    log.info("New access token fetched and cached.")
    return access_token


async def get_token() -> str:
    token = await get_cached_token()
    if token:
        return token
    return await fetch_new_token()


# ── API calls ─────────────────────────────────────────────────────────────────

async def api_post(method: str, extra_params: dict) -> dict:
    cfg = TRACKSOLID_CONFIG
    access_token = await get_token()
    timestamp = _utc_now_str()

    params = {
        "access_token": access_token,
        "app_key":      cfg["app_key"],
        "format":       "json",
        "method":       method,
        "sign_method":  "md5",
        "timestamp":    timestamp,
        "v":            "0.9",
        **extra_params,
    }
    params["sign"] = _build_sign(params, cfg["app_secret"])

    async with httpx.AsyncClient(timeout=20) as client:
        resp = await client.post(cfg["base_url"], data=params)
        return resp.json()


# ── Sync device metadata ──────────────────────────────────────────────────────

async def sync_devices():
    """
    Fetch full device list and upsert into tracksolid_devices.
    New devices are inserted. Existing devices have metadata updated.
    """
    log.info("Syncing device metadata...")
    data = await api_post(
        "jimi.user.device.list",
        {"target": TRACKSOLID_CONFIG["user_id"]}
    )

    if data.get("code") != 0:
        log.error(f"Device list error: {data}")
        return

    devices = data.get("result", [])
    if not devices:
        log.warning("No devices returned from device list.")
        return

    conn = await get_db()
    try:
        async with conn.cursor() as cur:
            for d in devices:
                await cur.execute("""
                    INSERT INTO tracksolid_devices
                        (imei, device_name, mc_type, mc_type_scope, sim,
                         vehicle_number, vehicle_name, driver_name, driver_phone,
                         activation_time, expiration, enabled_flag, device_group)
                    VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                    ON DUPLICATE KEY UPDATE
                        device_name    = VALUES(device_name),
                        mc_type        = VALUES(mc_type),
                        mc_type_scope  = VALUES(mc_type_scope),
                        sim            = VALUES(sim),
                        vehicle_number = VALUES(vehicle_number),
                        vehicle_name   = VALUES(vehicle_name),
                        driver_name    = VALUES(driver_name),
                        driver_phone   = VALUES(driver_phone),
                        activation_time= VALUES(activation_time),
                        expiration     = VALUES(expiration),
                        enabled_flag   = VALUES(enabled_flag),
                        device_group   = VALUES(device_group),
                        updated_at     = CURRENT_TIMESTAMP
                """, (
                    d.get("imei"),
                    d.get("deviceName"),
                    d.get("mcType"),
                    d.get("mcTypeUseScope"),
                    d.get("sim"),
                    d.get("vehicleNumber"),
                    d.get("vehicleName"),
                    d.get("driverName"),
                    d.get("driverPhone"),
                    _parse_dt(d.get("activationTime")),
                    _parse_dt(d.get("expiration")),
                    d.get("enabledFlag", 1),
                    d.get("deviceGroup"),
                ))
        log.info(f"Device sync complete — {len(devices)} devices upserted.")
    finally:
        conn.close()


# ── Poll locations ────────────────────────────────────────────────────────────

async def poll_locations():
    """
    Fetch latest location + telemetry for all devices and insert a new row.
    Always inserts — gives full history over time.
    """
    log.info("Polling device locations...")
    data = await api_post(
        "jimi.user.device.location.list",
        {"target": TRACKSOLID_CONFIG["user_id"]}
    )

    if data.get("code") != 0:
        log.error(f"Location list error: {data}")
        return

    devices = data.get("result", [])
    if not devices:
        log.warning("No location data returned.")
        return

    conn = await get_db()
    try:
        async with conn.cursor() as cur:
            rows_inserted = 0
            for d in devices:
                # Skip devices with no valid position
                lat = d.get("lat")
                lng = d.get("lng")
                if not lat or not lng or (lat == 0 and lng == 0):
                    continue

                await cur.execute("""
                    INSERT INTO tracksolid_locations
                        (imei, lat, lng, speed, acc_status, gps_time, hb_time,
                         pos_type, battery, power_value, gps_signal, gps_num,
                         direction, status, expire_flag)
                    VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                """, (
                    d.get("imei"),
                    lat,
                    lng,
                    d.get("speed"),
                    d.get("accStatus"),
                    _parse_dt(d.get("gpsTime")),
                    _parse_dt(d.get("hbTime")),
                    d.get("posType"),
                    d.get("electQuantity"),   # battery %
                    d.get("powerValue"),      # external voltage
                    d.get("gpsSignal"),
                    d.get("gpsNum"),
                    d.get("direction"),
                    d.get("status"),
                    d.get("expireFlag"),
                ))
                rows_inserted += 1

        log.info(f"Location poll complete — {rows_inserted}/{len(devices)} records inserted.")
    finally:
        conn.close()


# ── Main poll job ─────────────────────────────────────────────────────────────

async def poll_job():
    """Runs every 10 minutes. Syncs devices then polls locations."""
    try:
        await sync_devices()   # upsert metadata, catches new tags automatically
        await poll_locations() # insert fresh location row for every device
    except Exception as e:
        log.exception(f"Poll job failed: {e}")


# ── Scheduler startup ─────────────────────────────────────────────────────────

def start_poller():
    """Call this from FastAPI startup event."""
    scheduler = AsyncIOScheduler(timezone="UTC")

    # Run immediately on startup, then every 10 min
    scheduler.add_job(poll_job, "interval", minutes=POLL_INTERVAL_MINUTES, next_run_time=datetime.now(timezone.utc))

    # Sync device metadata once per hour (catches new devices faster)
    scheduler.add_job(sync_devices, "interval", hours=1)

    scheduler.start()
    log.info(f"Tracksolid poller started — polling every {POLL_INTERVAL_MINUTES} minutes.")
