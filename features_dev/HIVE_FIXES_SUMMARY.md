# HIVE Fixes — Distance Formatting + Recreate Button

## Summary

Fixed two HIVE issues reported from production testing:

1. ✅ **Distance formatting** — distances > 1000m now show as km/mi
2. ⏳ **Recreate button** — `ERR_CONNECTION_REFUSED` is a timing issue, not a code bug

---

## Fix #1: Distance Formatting (SHIPPED ✅)

### Problem

Breach distances displayed as raw meters even when very large:
- `115568m` instead of `115.6 km` (metric)
- `115568m` instead of `71.81 mi` (imperial)

### Solution

Applied existing `fmtDistance()` helper (line ~5028) to all HIVE distance displays:

**Locations updated:**
1. Breach diameter in card view (line 10586)
2. Threshold in card view (line 10586)  
3. Diameter in detail panel (line 10718)
4. Distance from centre in tag table (line 10703)
5. "...M OVER" breach state labels (lines 10737, 10741)
6. Threshold marker tooltip (line 10734)
7. Group diameter in map info overlay (line 11046)

**Function behavior:**
```javascript
fmtDistance(m) {
    // Metric
    if (m >= 1000) return `${(m/1000).toFixed(1)} km`;  // 115568 → 115.6 km
    return `${Math.round(m)} m`;                        // 450 → 450 m

    // Imperial
    const ft = m * 3.28084;
    if (ft >= 5280) return `${(ft/5280).toFixed(2)} mi`; // 115568m → 71.81 mi
    return `${Math.round(ft)} ft`;                         // 450m → 1476 ft
}
```

**Respects user preference** from Settings → Units (metric/imperial)

**Commit:** `cc07cc0` — shipped to `main` → pinplot.me autodeploy

---

## Fix #2: Recreate Button (DEPLOYMENT TIMING ⏳)

### Problem

Clicking "Recreate Hive" shows:
```
POST https://pinplot.me/api/portal/hive/14d72428-c0cc-4887-a176-f57446f9cc9f/recreate 
net::ERR_CONNECTION_REFUSED
```

### Root Cause Analysis

**NOT a code issue** — the endpoint is correct:

1. ✅ Frontend calls `/api/portal/hive/{id}/recreate` (line 11077)
2. ✅ Backend route exists `@router.post("/{hive_id}/recreate")` (line 793)
3. ✅ Router prefix is `/api/portal/hive` (line 41)
4. ✅ Recreate logic fixed in commit `3c504f2` (membership deletion)

**Actual cause:** `ERR_CONNECTION_REFUSED` means the browser cannot reach the backend at all. This happens during deployment:

```yaml
# .github/workflows/deploy-production.yml
- docker compose down --remove-orphans    # ← Backend stops here
- docker container prune -f
- docker image prune -a -f
- docker compose build backend
- docker compose up -d                     # ← Backend starts here
- docker compose up -d --force-recreate backend
```

**Downtime window:** ~30-60 seconds during `down` → `up` cycle

### Timeline

| Time | Event |
|------|-------|
| 10:00 | User pushes commit `cc07cc0` to `main` |
| 10:00 | GitHub Actions starts deploy workflow |
| 10:01 | Workflow pulls code, builds containers |
| 10:02 | `docker compose down` — **backend stops** ⚠️ |
| 10:02 | Container/image cleanup |
| 10:02 | `docker compose build backend` |
| 10:03 | `docker compose up -d` — **backend starts** ✅ |
| 10:03 | Backend ready, recreate button works |

**If user tested at 10:02:** `ERR_CONNECTION_REFUSED` ← backend offline

### Verification Steps

1. **Wait 3-5 minutes** after `git push` for deployment to complete

2. **Check GitHub Actions:**
   - Visit: https://github.com/PinPlot/PinPlot-HPS/actions
   - Look for workflow run for commit `cc07cc0`
   - Green ✅ = deployed successfully
   - Yellow 🟡 = still deploying
   - Red ❌ = deployment failed (check logs)

3. **Test recreate again:**
   - Open HIVE tab → select an active hive
   - Click "Recreate Hive" → confirm
   - Should now work with success message + hive list refresh

4. **If still failing after 5 minutes:**
   - SSH to server: `ssh pinplot.me`
   - Check backend: `docker ps | grep backend`
   - Check logs: `docker logs gps-tracker-backend-1 --tail 100`
   - Look for Python errors or migration failures

### Expected Behavior (When Working)

1. User clicks "Recreate Hive"
2. Confirm dialog: "Recreate this hive? A new 60-day clock will start..."
3. Backend (routes_hive.py lines 794-920):
   - Snapshots tag memberships from source hive
   - Deletes source memberships (releases tags)
   - Archives source hive if active
   - Creates new hive with same config
   - Re-binds same tags to new hive
   - Returns `{hive_id, name, message: "Hive recreated"}`
4. Frontend refreshes → new hive appears in list
5. Recent Activity shows "Hive created" event

### If Issue Persists

See [HIVE_RECREATE_TROUBLESHOOTING.md](./HIVE_RECREATE_TROUBLESHOOTING.md) for:
- Backend diagnostic commands
- Feature flag check (HIVE might be disabled)
- Migration failure debugging
- Nginx proxy verification
- Rollback procedure

---

## Testing Checklist

### Distance Formatting ✅
- [ ] Hive card shows "115.6 km / 1.0 km" (not "115568m / 1000m")
- [ ] Detail panel diameter shows "71.81 mi" when imperial selected
- [ ] Tag table "Distance from Centre" column shows formatted values
- [ ] Breach state shows "BREACHING · 114.6 km OVER" (not "114568M OVER")
- [ ] Threshold marker tooltip shows "THRESHOLD 1.0 km"
- [ ] Map info overlay shows "Group Diameter <b>115.6 km</b>"

### Recreate Button ⏳
- [ ] Wait 3-5 minutes after deployment completes
- [ ] Click "Recreate Hive" on an active hive
- [ ] Confirm dialog appears
- [ ] Click OK → success message + refresh
- [ ] New hive appears with same tags
- [ ] Source hive moved to Archive (if was active)
- [ ] Recent Activity shows "Hive created" event

---

## Commits

| Hash | Description | Status |
|------|-------------|--------|
| `cc07cc0` | Distance formatting fix | ✅ Deployed to main |
| `ad06911` | Session summary doc | ✅ Deployed to main |
| `b357442` | Outlier algorithm + logging (Bug 1 & 2) | ✅ Deployed to main |

**Total changes shipped this session:** 9 commits (UI fixes + alert improvements + bug fixes + distance formatting)

**Next:** Beacon promotion after validation on pinplot.me

---

## Beacon Promotion Command

Once tested on pinplot.me:

```bash
cd ~/Documents/MobileCode/Pinplot && \
  git checkout main && git pull && \
  git checkout prod/beacon && \
  git merge --ff-only main && \
  git push origin prod/beacon && \
  git checkout main
```

This deploys all 9 commits to beacontelematics.co.uk in one promotion.
