# Floorplan Phase 2 Deployment — Dark Launch

**Status**: Ready for production deployment  
**Target**: PinPlot staging (main branch)  
**Timeline**: Deploy → 24-48h observation → Phase 3 enablement  
**Safety**: Bridge runs silently, portal users see HTTP 404 on floorplan endpoints

---

## Prerequisites ✅

- [x] Phase 0 committed (fb28729): Bridge kill-switch and fail-safe startup
- [x] Phase 1 committed (cb22a62, ee4499c): Pareto container + ID normalization
- [x] DB migrations deployed: 
  - Migration 015: `buildings`, `floors`, `indoor_gateways`, `rooms`
  - Migration 036: `tag_indoor_positions`
- [x] Admin UI: Buildings tab operational for gateway registration
- [x] Feature flag documented in `.env.example` and tenant templates

---

## Deployment Steps

### 1. Update Production `.env` on Server

SSH to PinPlot staging server and add feature flags to backend `.env`:

```bash
ssh root@pinplot-staging.example.com
cd /root/pinplot/gps-tracker/backend
nano .env
```

Add these lines at the end:

```bash
# ── Feature Flags (Phase 2 dark launch) ──────────────────────────────
# Comma-separated list. Portal returns 404 for listed features.
# Phase 2: Bridge runs, portal hidden. Phase 3: Remove floorplan from list.
TENANT_DISABLED_FEATURES=floorplan

# Floorplan bridge safety switch (1=enabled, 0=disabled).
# Bridge attempts connection even if floorplan is in disabled features.
FLOORPLAN_BRIDGE_ENABLED=1
```

Save and verify:

```bash
grep -E 'TENANT_DISABLED|FLOORPLAN_BRIDGE' .env
```

### 2. Deploy Latest Main to Staging

```bash
# Pull latest code (includes cb22a62 + ee4499c)
cd /root/pinplot
git pull origin main

# Rebuild and restart containers
cd gps-tracker
docker compose down
docker compose build --no-cache backend
docker compose up -d
```

### 3. Verify Pareto Container Health

```bash
# Check all containers running
docker compose ps

# Expected output includes:
#   pinplot_pareto_anywhere    Up (healthy)

# Check Pareto logs
docker logs pinplot_pareto_anywhere --tail=50

# Expected: "raddec stream listening on port 3001"
```

### 4. Verify Bridge Connection

```bash
# Watch backend logs for bridge startup
docker logs pinplot_backend -f | grep pareto_bridge

# Expected within 60s:
#   pareto_bridge: connected to http://pareto-anywhere:3001
#   pareto_bridge: started
```

If connection fails, check:
- Pareto container health: `docker inspect pinplot_pareto_anywhere | grep Health`
- Network connectivity: `docker exec pinplot_backend curl http://pareto-anywhere:3001`
- Bridge is not disabled: `docker exec pinplot_backend printenv FLOORPLAN_BRIDGE_ENABLED` (should be 1)

### 5. Verify Feature Gate Active

```bash
# Backend logs should show kill-switch on startup
docker logs pinplot_backend 2>&1 | grep "tenant feature kill-switch"

# Expected:
#   portal: tenant feature kill-switch active for: floorplan
```

Test from portal (requires valid portal JWT):

```bash
# Should return 404 Not Found
curl -H "Authorization: Bearer YOUR_PORTAL_JWT" \
  https://pinplot.me/api/portal/floorplan/health
```

---

## Monitoring (24-48h Observation Period)

### Bridge Health Checks

**Check every 4-6 hours during first 24h:**

```bash
# Connection stability — reconnect count should stay low
docker logs pinplot_backend 2>&1 | grep -c "pareto_bridge: reconnecting"

# Raddec ingestion count (increases as gateways send adverts)
docker exec pinplot_postgres psql -U pinplot_db_user pinplot_db \
  -c "SELECT COUNT(*), MAX(last_seen) FROM tag_indoor_positions;"

# Bridge status snapshot
docker logs pinplot_backend 2>&1 | grep "pareto_bridge: status" | tail -1
```

### Container Stability

```bash
# Backend restarts (should be 0)
docker inspect pinplot_backend --format='{{.RestartCount}}'

# Pareto uptime
docker ps --filter name=pinplot_pareto_anywhere --format '{{.Status}}'
```

### Database Performance

```bash
# Check for lock contention on tag_indoor_positions
docker exec pinplot_postgres psql -U pinplot_db_user pinplot_db \
  -c "SELECT relname, n_tup_upd, n_tup_ins 
      FROM pg_stat_user_tables 
      WHERE relname = 'tag_indoor_positions';"

# Row count growth over time
docker exec pinplot_postgres psql -U pinplot_db_user pinplot_db \
  -c "SELECT COUNT(*), 
             COUNT(CASE WHEN status='online' THEN 1 END) as online,
             COUNT(CASE WHEN last_seen > NOW() - INTERVAL '5 minutes' THEN 1 END) as recent
      FROM tag_indoor_positions;"
```

### Error Log Sweep

```bash
# Check for bridge exceptions
docker logs pinplot_backend 2>&1 | grep -i "pareto.*error\|pareto.*exception" | tail -20

# Check for gateway ID mismatches
docker logs pinplot_backend 2>&1 | grep "unknown receiver" | tail -10
```

---

## Admin UI Validation (After 12h Stability)

### Test Gateway Registration Workflow

1. **Admin Portal → Buildings Tab**
   - URL: `https://pinplot.me/admin`
   - Login with admin credentials

2. **Create Test Building**
   - Click "+ Add Building"
   - Name: "Test Building - Phase 2"
   - Assign to: PinPlot tenant
   - MQTT Topic: `position/#` (default)
   - Save

3. **Add Test Floor**
   - Select building → "+ Add Floor"
   - Label: "Ground Floor"
   - Map: 800x500 (default)
   - Save

4. **Upload Floor Plan**
   - Click floor → Floor Editor
   - "📁 Upload Plan" → select PNG/JPG
   - Verify image renders on canvas

5. **Check Unregistered Gateways**
   - Power on test XIAO gateway (flashed with target receiver ID)
   - Wait 30-60s for Pareto to receive first raddec
   - Check bridge status for unregistered list:

```bash
docker logs pinplot_backend 2>&1 | grep "unregistered_gateways" | tail -1
```

6. **Register Gateway**
   - Floor Editor → Mode: "Place Gateway"
   - Click on floor plan to set x/y position
   - Modal appears:
     - Receiver ID: Copy from unregistered list (lowercase, no colons)
     - Label: "GW-Test-01"
   - Save
   - Verify gateway marker appears at clicked location

7. **Verify Database Record**

```bash
docker exec pinplot_postgres psql -U pinplot_db_user pinplot_db \
  -c "SELECT receiver_id, label, x, y, created_at 
      FROM indoor_gateways 
      ORDER BY created_at DESC LIMIT 1;"
```

8. **Monitor Tag Position Ingestion**

Power on BLE tag near the registered gateway. Wait 60s then check:

```bash
docker exec pinplot_postgres psql -U pinplot_db_user pinplot_db \
  -c "SELECT tag_id, x, y, zone, rssi, status, last_seen 
      FROM tag_indoor_positions 
      WHERE last_seen > NOW() - INTERVAL '2 minutes';"
```

---

## Success Criteria (24-48h)

- [ ] **Bridge Stability**: Reconnect count < 5 over 24h period
- [ ] **No Container Restarts**: Backend and Pareto `RestartCount` = 0
- [ ] **Data Ingestion**: `tag_indoor_positions` row count increases (confirms raddec processing)
- [ ] **Feature Gate Works**: Portal endpoints return 404, admin endpoints return 200
- [ ] **Gateway Registration**: Admin UI workflow completes without errors
- [ ] **ID Normalization**: Registered gateway receiver_id matches raddec payloads (case-insensitive)
- [ ] **No DB Locks**: No slow queries or lock timeouts in Postgres logs
- [ ] **Clean Logs**: No exceptions in backend logs related to pareto_bridge or indoor tracking

---

## Rollback Plan (If Issues Found)

### Fast Rollback: Disable Bridge

```bash
# Edit .env and set FLOORPLAN_BRIDGE_ENABLED=0
ssh root@pinplot-staging.example.com
nano /root/pinplot/gps-tracker/backend/.env

# Change:
FLOORPLAN_BRIDGE_ENABLED=0

# Restart backend only (keeps DB data)
docker compose restart backend
```

### Full Rollback: Revert to Pre-Phase-1

```bash
cd /root/pinplot
git reset --hard fb28729  # Revert to Phase 0 (before Pareto service added)
cd gps-tracker
docker compose down
docker compose up -d --build
```

---

## Next Steps → Phase 3 Enablement

**After 48h+ clean run**, proceed to Phase 3:

1. **Remove Feature Gate** (enable portal endpoints):
   ```bash
   # Edit .env and remove floorplan from TENANT_DISABLED_FEATURES
   TENANT_DISABLED_FEATURES=
   ```

2. **Update Tenant Template** for future deployments:
   ```bash
   # tenants/pinplot/.env.template
   TENANT_DISABLED_FEATURES=  # Empty = fully enabled
   ```

3. **Test Portal Endpoints**:
   - GET `/api/portal/floorplan/health` → Returns bridge status (200 OK)
   - GET `/api/portal/floorplan/floors` → Returns buildings/floors for tenant
   - GET `/api/portal/floorplan/assets?floor_key=<uuid>` → Returns tag positions

4. **Customer Dashboard Integration**:
   - Add Floorplan tab/iframe to customer-dashboard
   - Wire real-time asset position updates
   - Test with production BLE tags

5. **Beacon Promotion** (only after PinPlot Phase 3 validates):
   - Deploy Phase 0-2 to prod/beacon
   - Run same 24-48h observation
   - Enable Phase 3 for Beacon tenant

---

## Contact

**Deployment Owner**: Carl  
**Rollback Authority**: Carl (can execute without approval if critical)  
**Monitoring Schedule**: Every 4-6h first 24h, then daily checks  

**Slack Alerts** (if configured):
- Container restarts
- Bridge reconnect count > 10
- Backend error rate spike
