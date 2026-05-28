# HIVE Recreate Button — Troubleshooting ERR_CONNECTION_REFUSED

## Issue

When clicking "Recreate Hive" on an active hive, the browser shows:

```
POST https://pinplot.me/api/portal/hive/{hive_id}/recreate net::ERR_CONNECTION_REFUSED
```

## Analysis

### What's Correct ✅

1. **Frontend code** (index.html line 11077):
   ```javascript
   const r = await apiFetch(`/api/portal/hive/${_hiveCurrentId}/recreate`, { method: 'POST' });
   ```
   URL is correct: `/api/portal/hive/{id}/recreate`

2. **Backend route** (routes_hive.py line 793):
   ```python
   @router.post("/{hive_id}/recreate")
   def recreate_hive(hive_id: str, request: Request, db: Session = Depends(get_db)):
   ```
   Route exists and matches frontend call

3. **Router registration** (routes_hive.py line 41):
   ```python
   router = APIRouter(
       prefix="/api/portal/hive",
       tags=["hive"],
       dependencies=[Depends(require_feature_enabled("hive"))],
   )
   ```
   Prefix is correct, feature flag dependency exists but shouldn't cause CONNECTION_REFUSED

4. **Recent fix** (commit 3c504f2):
   Recreate logic was fixed to properly delete source hive memberships before recreating

### What ERR_CONNECTION_REFUSED Means 🔴

This error is **NOT** a code issue — it means the browser literally cannot connect to the backend server. Possible causes:

1. **Backend container crashed** after recent deployments (b357442, cc07cc0)
2. **Deployment still in progress** — GitHub Actions workflow hasn't completed
3. **Backend failed to start** due to a runtime error (import issue, database migration failure)
4. **Nginx proxy misconfiguration** — routing broken for `/api/portal/hive/*` endpoints
5. **Feature flag disabled** — if `require_feature_enabled("hive")` returns 404, but this would be `Failed to fetch` not `CONNECTION_REFUSED`

## Diagnostic Steps

### 1. Check if backend is running

SSH to pinplot.me:
```bash
ssh pinplot.me
docker ps | grep backend
```

Expected output: Container named `gps-tracker-backend-1` or similar in `Up` status.

If not running, check logs:
```bash
docker logs gps-tracker-backend-1 --tail 100
```

### 2. Check deployment status

Visit GitHub Actions: https://github.com/PinPlot/PinPlot-HPS/actions

Recent workflow for commit `cc07cc0` should show:
- ✅ Green checkmark = deployed successfully
- 🟡 Yellow dot = still deploying
- 🔴 Red X = deployment failed

### 3. Test backend connectivity

```bash
curl -v https://pinplot.me/api/portal/hive
```

Expected: `401 Unauthorized` or `403 Forbidden` (auth required)
Actual if broken: `Connection refused` or timeout

### 4. Check nginx logs

```bash
docker logs nginx --tail 50 | grep "/api/portal/hive"
```

Look for:
- `upstream connect error` = backend container not reachable
- `502 Bad Gateway` = backend crashed during request
- No logs = request not reaching nginx (DNS/firewall issue)

### 5. Check database migrations

If backend crashed on startup, migration 039 (backfill hive_name) might have failed:

```bash
docker logs gps-tracker-backend-1 | grep -A10 "migration"
```

### 6. Check Python imports

The recent changes added structured logging in hive_service.py. If there's an import error:

```bash
docker logs gps-tracker-backend-1 | grep -i "importerror\|modulenotfounderror"
```

### 7. Verify feature flag

In psql or backend shell:
```sql
SELECT disabled_features FROM usergroups WHERE id = '<your_usergroup_id>';
```

If `disabled_features` contains `'hive'`, the feature is disabled for your tenant.

## Quick Fix if Backend Crashed

```bash
ssh pinplot.me
cd /path/to/gps-tracker
docker-compose restart backend
docker-compose logs -f backend  # watch for startup errors
```

## Expected Recreate Flow (when working)

1. User clicks "Recreate Hive" → confirm dialog
2. Frontend POSTs to `/api/portal/hive/{id}/recreate`
3. Backend (routes_hive.py line 794-920):
   - Finds source hive
   - Snapshots tag memberships
   - Deletes source memberships (frees tags)
   - Archives source hive if active
   - Creates new hive with fresh 60-day expiry
   - Copies config from source
   - Re-binds same tags to new hive
   - Returns `{hive_id, name, message}`
4. Frontend refreshes hive list → new hive appears

## Recent Commits That Changed HIVE Backend

- **b357442** (2 hours ago): Added diagnostic logging to hive_service.py
  - Risk: Import error if logger setup broken
  - Check: `import json`, `log.info()` calls
  
- **cec766f** (2 hours ago): Migration 039 backfill hive_name
  - Risk: Migration might fail if old data has FK issues
  - Check: `alembic current` should show revision 039

## Resolution Plan

1. **Immediate**: Check if backend is running (`docker ps`)
2. **If crashed**: Check logs for Python errors, restart backend
3. **If deploying**: Wait 2-3 minutes for GitHub Actions to complete
4. **If nginx issue**: Check proxy config for `/api/portal/hive` location block
5. **If feature disabled**: Remove `'hive'` from usergroup.disabled_features
6. **If persistent**: Roll back to commit `3c504f2` (last known working recreate)

## Expected Timeline

- **Normal deployment**: 2-3 minutes from `git push` to live
- **With backend restart**: Add 10-20 seconds
- **With migration**: Add 5-30 seconds depending on data volume

## Test After Fix

1. Open HIVE tab → select an active hive
2. Click "Recreate Hive"
3. Confirm dialog
4. Should see: Success + hive list refreshes with new hive
5. Check Recent Activity: "Hive created" event

---

**Status**: Issue documented — awaiting deployment completion or backend diagnostic.

**Next action**: Check GitHub Actions workflow status for commit `cc07cc0`.
