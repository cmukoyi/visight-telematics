# TrackSolid Open API Integration Architecture

## Overview

This implementation uses the official TrackSolid Open API to poll device locations and metadata efficiently. It replaces the old per-IMEI polling approach (110 parallel requests every 10 min) with a bulk API that returns all devices in **two API calls**.

## Two-Table Design

### 1. `tracksolid_devices` (Static Metadata)
Stores rarely-changing device information. Uses **ON CONFLICT DO UPDATE** (PostgreSQL UPSERT) so new devices are auto-added and existing devices get metadata updates.

**Columns:**
- `imei` (unique key)
- `device_name`, `mc_type`, `sim`
- `vehicle_number`, `driver_name`, `driver_phone`
- `activation_time`, `expiration`, `enabled_flag`
- `created_at`, `updated_at`

### 2. `tracksolid_locations` (Location History)
Stores telemetry snapshots every poll. **Always INSERT** (no updates) to maintain full location history.

**Columns:**
- `imei` (indexed, not unique)
- `lat`, `lng`, `speed`, `acc_status`
- `gps_time`, `hb_time`, `pos_type`
- `battery`, `gps_signal`, `status`
- `recorded_at` (auto-generated, indexed)

### 3. `api_tokens` (OAuth Token Cache)
Caches the OAuth `access_token` to avoid re-authenticating every 10 minutes.

**Columns:**
- `provider` ('tracksolid_open_api', unique key)
- `access_token`, `refresh_token`, `expires_at`
- `updated_at`

## API Calls

### Step 1: OAuth Token (cached for 2 hours)
```python
jimi.oauth.token.get
  - Cached in `api_tokens` table
  - Refreshed 5 min before expiry
  - No password in cleartext (uses MD5 hash)
```

### Step 2: Device Metadata (polled every 10 min)
```python
jimi.user.device.list
  → Returns: IMEI, name, model, SIM, vehicle info
  → Saved to: tracksolid_devices (UPSERT on IMEI)
```

### Step 3: Device Locations (polled every 10 min)
```python
jimi.user.device.location.list
  → Returns: lat/lng, battery, speed, signal, status
  → Saved to: tracksolid_locations (always INSERT)
```

## Automatic New Device Detection

**No manual checking needed!** The PostgreSQL UPSERT pattern handles it:

```sql
INSERT INTO tracksolid_devices (imei, device_name, ...)
VALUES (...)
ON CONFLICT (imei) DO UPDATE
SET device_name = EXCLUDED.device_name,
    updated_at = CURRENT_TIMESTAMP;
```

- **New device added to account** → Inserted on first poll
- **Existing device** → Metadata quietly updated

## Backwards Compatibility

The `ble_tags` table is still updated for existing app functionality (maps, alerts, geofences). This maintains compatibility while the new tables provide:

1. Full location history for analytics
2. Rich metadata for device management
3. Separation of concerns (metadata vs telemetry)

## Polling Schedule

- **Series 1** (MZone/Scope): Every 10 seconds
- **Series 2** (TrackSolid): Every 600 seconds (10 minutes)
  - Token check → fetch if expired
  - Call `device.list` → UPSERT to `tracksolid_devices`
  - Call `location.list` → INSERT to `tracksolid_locations`
  - Update `ble_tags` for backwards compatibility

## Performance Benefits

**Before:**
- 110 parallel API calls every 10 min
- Triggered WAF rate limits
- IP bans from "scraping" behavior

**After:**
- 2 API calls every 10 min (+ 1 token call every 2 hours)
- Within official quota limits (86,400 calls/day)
- No WAF blocks
- Full location history for analytics

## Deployment Checklist

### 1. Run Migration
```bash
cd gps-tracker/backend
alembic upgrade head  # Creates tracksolid_devices, tracksolid_locations, api_tokens
```

### 2. Environment Variables
Add to `backend/.env`:
```bash
TRACKSOLID_ACCOUNT=Beacontelematics
TRACKSOLID_PASSWORD=Transport01!
TRACKSOLID_APP_KEY=8FB345B8693CCD00705B2242580910A0339A22A4105B6558
TRACKSOLID_APP_SECRET=860d274a6c50445d86a93ed89de79278
```

### 3. Restart Backend
```bash
docker compose down
docker compose up -d
```

### 4. Verify Logs
```bash
docker logs -f pinplot_backend | grep "TrackSolid"

# Expected output every 10 min:
♻️  TrackSolid Open API: using cached access_token
📋 TrackSolid device.list: received 351 devices
📍 TrackSolid location.list: received 351 devices
💾 Saved 351 device metadata rows
💾 Saved 351 location history rows
📍 TrackSolid Open API: 6/351 devices had valid GPS fixes
```

### 5. Check Database
```sql
-- Verify devices were added
SELECT count(*) FROM tracksolid_devices;
-- Should show 351 (or actual device count)

-- Verify location history is growing
SELECT count(*) FROM tracksolid_locations;
-- Should increase by ~351 every 10 minutes

-- Check recent locations
SELECT imei, lat, lng, battery, recorded_at 
FROM tracksolid_locations 
ORDER BY recorded_at DESC 
LIMIT 20;

-- Verify token caching
SELECT provider, expires_at FROM api_tokens;
-- Should show: tracksolid_open_api with expires_at ~2 hours in future
```

## Monitoring Queries

### Location History Audit
```sql
-- Count locations per device in last 24 hours
SELECT imei, count(*) as location_count
FROM tracksolid_locations
WHERE recorded_at > now() - interval '24 hours'
GROUP BY imei
ORDER BY location_count DESC;
```

### Device Activity Status
```sql
-- Find devices that haven't reported in 1 hour
SELECT d.imei, d.device_name, max(l.recorded_at) as last_seen
FROM tracksolid_devices d
LEFT JOIN tracksolid_locations l ON d.imei = l.imei
GROUP BY d.imei, d.device_name
HAVING max(l.recorded_at) < now() - interval '1 hour'
   OR max(l.recorded_at) IS NULL;
```

### Battery Health
```sql
-- Average battery per device (last 24h)
SELECT imei, 
       avg(CAST(battery AS FLOAT)) as avg_voltage,
       count(*) as readings
FROM tracksolid_locations
WHERE recorded_at > now() - interval '24 hours'
  AND battery IS NOT NULL
GROUP BY imei
ORDER BY avg_voltage ASC;
```

## Troubleshooting

### Token Issues
```sql
-- Check token expiry
SELECT provider, expires_at, 
       (expires_at - now()) as time_remaining 
FROM api_tokens;

-- Force token refresh (delete cached token)
DELETE FROM api_tokens WHERE provider = 'tracksolid_open_api';
```

### No Location Updates
```bash
# Check if Series 2 poll is firing
docker logs pinplot_backend | grep "Series 2"

# Check for API errors
docker logs pinplot_backend | grep "TrackSolid.*error"

# Verify env vars loaded
docker exec pinplot_backend printenv | grep TRACKSOLID
```

### DB Migration Issues
```bash
# Check migration status
docker exec pinplot_backend alembic current

# Rollback if needed
docker exec pinplot_backend alembic downgrade -1

# Re-run
docker exec pinplot_backend alembic upgrade head
```

## Future Enhancements

1. **Analytics Dashboard**: Use location history for distance/speed reports
2. **Battery Alerts**: Trigger alerts when voltage drops below threshold
3. **Trip Reconstruction**: Build trip summaries from location history
4. **Device Health Monitoring**: Track devices that stop reporting
5. **Cost Optimization**: Adjust poll frequency per device activity level
