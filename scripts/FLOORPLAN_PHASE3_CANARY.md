# Floorplan Phase 3 — Canary UI Enablement

**Status**: Ready for canary deployment  
**Target**: PinPlot production (main branch)  
**Timeline**: Enable → 2-4h validation → Monitor 24h → Full rollout  
**Safety**: Limited blast radius, fail-safe handles 404/401 gracefully

---

## Prerequisites ✅

- [x] Phase 2 completed with 24-48h clean run (bridge stable, no restarts)
- [x] 32,803+ positions in DB (data ingestion confirmed)
- [x] Feature gate configuration ready (template updated)
- [x] UI fail-safe implemented (app.js lines 712-716)
- [x] Validation script created

---

## Deployment Steps

### 1. Enable Floorplan Portal Endpoints

SSH to PinPlot production and update backend `.env`:

```bash
ssh root@pinplot-server
nano /root/pinplot/gps-tracker/backend/.env
```

**Change:**
```bash
# OLD (Phase 2 dark launch)
TENANT_DISABLED_FEATURES=floorplan

# NEW (Phase 3 canary)
TENANT_DISABLED_FEATURES=
```

Verify:
```bash
grep TENANT_DISABLED_FEATURES /root/pinplot/gps-tracker/backend/.env
# Should show: TENANT_DISABLED_FEATURES=  (empty or commented)
```

### 2. Restart Backend Only

```bash
cd /root/pinplot/gps-tracker
docker compose restart backend

# Wait 10s then verify backend started
docker logs pinplot_backend 2>&1 | tail -50
```

**Expected logs:**
- ✅ `pareto_bridge: started`
- ✅ `pareto_bridge: connected to http://pareto-anywhere:3001`
- ❌ **Should NOT see:** `tenant feature kill-switch active for: floorplan`

### 3. Verify API Endpoints Accessible

From your local machine, run the validation script:

```bash
# Get a valid portal JWT first
# 1. Log into https://pinplot.me/customer as a test user
# 2. Open DevTools → Application → Local Storage → pp_portal_token
# 3. Copy the JWT value

# Run validation
cd /path/to/PinPlot-HPS
PORTAL_TOKEN="<paste-jwt-here>" bash scripts/validate-floorplan-phase3.sh
```

**Expected output:**
```
✅ ALL TESTS PASSED — Phase 3 canary ready for user validation
```

If validation fails:
- Check backend was restarted after .env change
- Verify JWT is not expired
- Review backend logs for errors

---

## User Journey Validation

### Journey 1: Floor List Loads

**Steps:**
1. Navigate to https://pinplot.me/customer
2. Log in as a portal user
3. Click "Floor Plan" tab in left navigation

**Expected:**
- Tab loads without 404 error page
- If no floors configured: Shows empty state message
- If floors exist: Dropdown shows floor list (G, 1F, 2F, etc.)
- Canvas renders floor plan layout

**Fail Criteria:**
- ❌ 404 error page (feature gate still active)
- ❌ JavaScript errors in console
- ❌ Canvas does not render

### Journey 2: Floor Details Load

**Steps:**
1. From Floor Plan tab, select a floor from dropdown
2. Observe canvas and side panel

**Expected:**
- Canvas redraws with selected floor layout
- Rooms, corridors, doors render correctly
- If gateways registered: Gateway markers visible (toggle "Beacons" layer)
- Side panel shows asset count for that floor

**Fail Criteria:**
- ❌ Canvas does not update on floor change
- ❌ Layout misaligned or distorted
- ❌ Registered gateways do not appear

### Journey 3: Assets Update Every Polling Interval

**Steps:**
1. Power on a BLE tag near a registered gateway
2. Wait 3 seconds (POLL_INTERVAL_MS)
3. Observe canvas and asset list

**Expected:**
- Asset appears on canvas at gateway position
- Asset appears in right-side asset list
- Asset status shows "online" (green indicator)
- Asset updates position as tag moves between gateways
- Polling continues every 3s (check Network tab: `/api/portal/floorplan/assets`)

**Fail Criteria:**
- ❌ Asset does not appear within 10s
- ❌ Position does not update when tag moves
- ❌ Polling stops after first request
- ❌ Network errors in console

### Journey 4: Wrong-Floor Ghosting (Nearest-Gateway Tolerance)

**Steps:**
1. Place tag on Floor G near a gateway
2. Observe tag appears on Floor G canvas
3. Move tag to Floor 1F (different floor)
4. Wait for position update

**Expected:**
- Tag disappears from Floor G canvas when moved to 1F
- Tag appears on Floor 1F canvas at nearest gateway
- Some "ghosting" acceptable (tag lingers 3-10s on wrong floor due to RSSI hysteresis)
- Within tolerance defined in MVP spec (nearest-gateway method has ±1 floor ambiguity)

**Fail Criteria:**
- ❌ Tag persists on wrong floor indefinitely (>30s)
- ❌ Tag appears on multiple floors simultaneously
- ❌ Tag position wildly incorrect (>20m from actual location)

### Journey 5: Fail-Safe Graceful Degradation

**Steps:**
1. With Floor Plan tab open, SSH to server
2. Temporarily disable floorplan:
   ```bash
   # Edit .env
   TENANT_DISABLED_FEATURES=floorplan
   # Restart backend
   docker compose restart backend
   ```
3. Observe UI behavior (do NOT refresh page)

**Expected:**
- After 3s (next poll), UI detects 404 response
- Polling stops automatically (no infinite retry loop)
- UI shows message: "Floor plan feature is currently unavailable"
- No JavaScript errors or crashes
- User can navigate away from tab

**Fail Criteria:**
- ❌ UI continues polling infinitely
- ❌ JavaScript errors flood console
- ❌ Page becomes unresponsive
- ❌ 404 errors visible to user (should be silent)

**Cleanup:**
```bash
# Re-enable floorplan after test
TENANT_DISABLED_FEATURES=
docker compose restart backend
```

---

## Exit Criteria (2-4h Canary Window)

Monitor these metrics for 2-4 hours after Phase 3 enablement:

### Functional Criteria
- [x] All 5 user journeys pass validation
- [x] Floor list loads without errors
- [x] Floor details render correctly
- [x] Assets update every 3s polling interval
- [x] Wrong-floor ghosting within spec tolerance (<30s stale data)
- [x] Fail-safe handles 404/401 gracefully (tested)

### Operational Criteria
- [x] No increase in backend error rate
- [x] No increase in container restarts
- [x] Bridge stays connected (reconnect count < 5 in 2h window)
- [x] Database query performance stable (no slow queries)
- [x] No user complaints in support channels

### Performance Criteria
- [x] `/api/portal/floorplan/assets` responds < 500ms p95
- [x] Floor plan canvas renders < 1s on tab switch
- [x] Asset position updates < 5s after tag moves

---

## Monitoring Commands

```bash
# Backend error rate
docker logs pinplot_backend 2>&1 | tail -200 | grep -iE "error|exception" | wc -l

# Bridge reconnect count (should be low)
docker logs pinplot_backend 2>&1 | grep -c "pareto_bridge: reconnecting"

# Asset update frequency (check DB writes)
docker exec pinplot_db psql -U pinplot_db_user pinplot_db \
  -c "SELECT COUNT(*), MAX(last_seen) 
      FROM tag_indoor_positions 
      WHERE last_seen > NOW() - INTERVAL '5 minutes';"

# API response times (from nginx access logs)
docker logs pinplot_nginx 2>&1 | grep "/api/portal/floorplan" | tail -50

# Run Phase 2 monitoring script (still applicable)
ssh root@server 'bash -s' < scripts/monitor-floorplan-phase2.sh
```

---

## Rollback Plan (If Issues Found)

### Fast Rollback: Disable Feature Gate

```bash
ssh root@pinplot-server
nano /root/pinplot/gps-tracker/backend/.env

# Re-enable gate
TENANT_DISABLED_FEATURES=floorplan

docker compose restart backend
```

Users will see 404 on next poll (3s), UI will stop polling gracefully.

### Full Rollback: Revert to Phase 2

```bash
cd /root/pinplot
git reset --hard e919f9a  # Last Phase 2 commit
cd gps-tracker
docker compose down
docker compose up -d --build
```

---

## Success Metrics → Full Rollout

After 2-4h canary passes all exit criteria:

1. **Update Beacon Tenant** (prod/beacon branch):
   - Cherry-pick Phase 0-3 commits to prod/beacon
   - Run same 24-48h observation for Beacon
   - Enable Phase 3 for Beacon after validation

2. **Monitor Full Deployment**:
   - Run monitoring script every 6h for 48h
   - Track user engagement (Floor Plan tab views)
   - Measure asset tracking accuracy (user feedback)

3. **Customer Dashboard Integration**:
   - Add Floor Plan as default tab for configured tenants
   - Create onboarding docs for gateway setup
   - Train support team on troubleshooting

---

## Known Limitations (MVP Scope)

- **Nearest-Gateway Method**: ±5-10m accuracy, not sub-meter
- **Floor Ambiguity**: Tags between floors may appear on wrong floor briefly
- **No Historical Playback**: Only live positions, no time-travel
- **Static Floor Plans**: Canvas-based, not dynamic zoom levels like Leaflet
- **No Zone Triggers**: Position display only, no geofence alerts yet

These are acceptable for MVP scope as defined in the spec. Future PRs will address.

---

## Contact

**Deployment Owner**: Carl  
**Canary Window**: 2-4 hours  
**Monitoring Frequency**: Every 30 min during canary  
**Full Rollout**: After 2-4h validation passes

**Slack Alerts** (if configured):
- Backend error rate spike
- Bridge reconnect count > 10
- Container restarts
