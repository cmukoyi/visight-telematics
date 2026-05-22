# TrackSolid Open API Migration

## Overview

Migrated from per-IMEI polling (110 parallel API calls) to official Open API (1 bulk call).

**Benefits:**
- ✅ Solves WAF IP ban issue permanently
- ✅ 99% reduction in API calls (110 → 1 per polling cycle)
- ✅ Official integration channel with 86,400 calls/day quota
- ✅ Faster polling (single request vs parallel wait)

---

## Required Environment Variables

Add these to `.env` files on BOTH droplets (pinplot and beacon):

```bash
# TrackSolid Open API Credentials (jimi.user.device.location.list)
TRACKSOLID_APP_KEY=8FB345B8693CCD00705B2242580910A0339A22A4105B6558
TRACKSOLID_APP_SECRET=860d274a6c50445d86a93ed89de79278
```

### Existing Variables (keep as-is)

These are still needed for token authentication:

```bash
TRACKSOLID_ACCOUNT=Beacontelematics
TRACKSOLID_PASSWORD=95d16ce0247f42706fca9eb7691e53d8
TRACKSOLID_USER_ID=<existing_value>
TRACKSOLID_ORG_ID=<existing_value>
```

---

## Server Deployment Steps

### Step 1: Update Pinplot Server

```bash
# SSH to pinplot droplet
ssh root@<pinplot_IP>

# Edit .env file
cd /root/pinplot/gps-tracker/backend
nano .env

# Add these two lines:
TRACKSOLID_APP_KEY=8FB345B8693CCD00705B2242580910A0339A22A4105B6558
TRACKSOLID_APP_SECRET=860d274a6c50445d86a93ed89de79278

# Save and exit (Ctrl+X, Y, Enter)
```

### Step 2: Update Beacon Server

```bash
# SSH to beacon droplet (NEW IP)
ssh root@167.172.49.62

# Edit .env file
cd /root/beacon-telematics/gps-tracker/backend
nano .env

# Add the same two lines:
TRACKSOLID_APP_KEY=8FB345B8693CCD00705B2242580910A0339A22A4105B6558
TRACKSOLID_APP_SECRET=860d274a6c50445d86a93ed89de79278

# Save and exit
```

### Step 3: Deploy Code Changes

Follow the standard deployment runbook:

```bash
# On your laptop
cd ~/Documents/MobileCode/Pinplot

# Create PR for the changes
git checkout -b feat/tracksolid-open-api-migration
git add gps-tracker/backend/app/services/device_providers/tracksolid_provider.py
git add gps-tracker/backend/app/services/location_poller_service.py
git commit -m "feat(tracksolid): migrate to Open API (jimi.user.device.location.list)

- Replaces 110 parallel per-IMEI calls with 1 bulk API call
- Uses official jimi.user.device.location.list endpoint
- Solves WAF IP ban issue by staying within integration quotas
- Adds TRACKSOLID_APP_KEY and TRACKSOLID_APP_SECRET env vars
- 99% reduction in API call volume (110 → 1 per 10-min cycle)"

git push -u origin feat/tracksolid-open-api-migration

# Create PR → merge to main → deploys to pinplot
# After pinplot validated → promote to beacon
```

### Step 4: Verify on Pinplot

After deploy completes:

```bash
# SSH to pinplot
ssh root@<pinplot_IP>
cd /root/pinplot/gps-tracker

# Watch backend logs
docker logs -f --tail 50 pinplot_backend | grep -E "TrackSolid|Series 2"
```

**Expected log output:**
```
📍 TrackSolid Open API: received 110 devices from jimi.user.device.location.list
📍 TrackSolid Open API: 110/110 devices had valid GPS fixes
```

**Old output (now gone):**
```
📍 TrackSolid getMonitorInfo: 110/110 locations fetched  ← parallel calls
```

### Step 5: Promote to Beacon

After pinplot validates successfully:

```bash
cd ~/Documents/MobileCode/Pinplot
git checkout main && git pull
git checkout prod/beacon
git merge --ff-only main
git push origin prod/beacon
```

Watch beacon deploy at: https://github.com/PinPlot/PinPlot-HPS/actions/workflows/deploy-production.yml

### Step 6: Verify on Beacon

```bash
# SSH to beacon (new droplet)
ssh root@167.172.49.62
cd /root/beacon-telematics/gps-tracker

# Watch backend logs
docker logs -f --tail 50 beacon_telematics_backend | grep -E "TrackSolid|Series 2"

# Check database — all 110 tags should have fresh timestamps
docker exec beacon_telematics_db psql -U beacon_user -d beacon_telematics -c \
  "SELECT count(*) FILTER (WHERE last_seen > now() - interval '15 minutes') AS updated_15m,
          count(*) AS total
   FROM ble_tags WHERE tag_type='tracksolid';"
```

**Expected:** `updated_15m` close to `total` (110)

---

## Troubleshooting

### Error: `KeyError: 'TRACKSOLID_APP_KEY'`

**Cause:** Environment variables not set on the server.

**Fix:**
1. SSH to the server
2. Add the vars to `backend/.env`
3. Restart backend: `docker compose restart backend`

### Error: `🚫 TrackSolid Open API error code=401`

**Cause:** Invalid app_key, app_secret, or access_token.

**Fix:**
1. Verify credentials in `.env` match those provided by TrackSolid support
2. Check signature generation logic matches Jimi docs
3. Test with curl:
   ```bash
   curl -X POST https://eu-open.tracksolidpro.com/gateway/openapi \
     -H "Content-Type: application/json" \
     -d '{"app_key":"...","timestamp":"...","sign":"...","method":"jimi.user.device.location.list","access_token":"...","target":"Beacontelematics"}'
   ```

### Error: `🚫 TrackSolid Open API HTTP 403`

**Cause:** IP still WAF-banned OR app_key not authorized for this endpoint.

**Fix:**
1. Confirm you're on the NEW droplet (167.172.49.62) not old
2. Contact TrackSolid support to verify app_key has `jimi.user.device.location.list` permissions
3. Wait 24-48h for IP ban to expire if on old droplet

### No GPS updates after deploy

**Cause:** Backend container didn't pick up new code or env vars.

**Fix:**
```bash
cd /root/beacon-telematics/gps-tracker
docker compose down
docker compose up -d --build backend
docker logs -f beacon_telematics_backend
```

---

## Rollback Plan

If the Open API fails and you need to revert:

```bash
cd ~/Documents/MobileCode/Pinplot

# Revert to previous commit
git checkout prod/beacon
git log --oneline -5  # find the commit BEFORE the open-api change
git reset --hard <previous-commit-sha>
git push --force-with-lease origin prod/beacon

# Beacon will auto-deploy the old code
```

The old per-IMEI method is still in `tracksolid_provider.py` as `fetch_all_tracksolid_locations()` — we only changed which one is imported.

---

## Next Steps After Successful Migration

1. **Monitor API quota usage** — Jimi console should show daily call count well under 86,400
2. **Remove old code** (optional cleanup after 1 week stable):
   - Delete `fetch_all_tracksolid_locations()` function
   - Delete `_fetch_monitor_info_single()` helper
   - Delete `_MONITOR_INFO_URL` constant
3. **Document for future onboarding** — this is now the primary integration method

---

## Summary of Code Changes

| File | Change |
|---|---|
| `tracksolid_provider.py` | Added `fetch_all_tracksolid_locations_open_api()` using `jimi.user.device.location.list` |
| `tracksolid_provider.py` | Added `_generate_open_api_signature()` for MD5 auth |
| `tracksolid_provider.py` | Added `_open_api_creds()` to read APP_KEY/APP_SECRET from env |
| `location_poller_service.py` | Changed import from old → new function |
| `location_poller_service.py` | Updated call site (line 142) to use new bulk API |

**Lines of code changed:** ~200 added, 2 modified  
**API calls saved per 10-min cycle:** 109 (110 → 1)  
**Daily API call reduction:** ~15,696 calls/day (109 calls × 6 per hour × 24 hours)
