# Movement Analytics Promotion Assessment
## From `main` to `prod/beacon`

**Date:** July 25, 2026  
**Assessor:** GitHub Copilot  
**Status:** ⚠️ HIGH COMPLEXITY - Requires Careful Planning

---

## Executive Summary

**Scope:** 276 total commits between prod/beacon and main  
**Primary Feature:** Movement Analytics (formerly Movement History Advanced)  
**Admin Features:** Trip subscription management, backfill tools, reprocessing UI  
**Risk Level:** 🔴 HIGH - Major backend changes, new database tables, worker service required

---

## Core Feature Set

### 1. Movement Analytics (Frontend)
**Commits:** ~40 commits  
**Key Features:**
- ✨ Journey visualization with interactive map
- ✨ 3-panel responsive layout (Assets | Map | Journeys)
- ✨ Date range filtering (Today, Yesterday, 7d, 30d, Custom)
- ✨ Asset status filtering (Total, Active, Idle, Offline)
- ✨ Category filtering (All, NewTags, Parcels, QR)
- ✨ Journey expansion/collapse with path rendering
- ✨ Satellite/Streets map switcher
- ✨ Unit of measurement support
- ✨ Battery icons and timestamp badges
- ✨ Focus ring for selected journeys
- ✨ "Plot All Journeys" feature
- 🐛 Multiple bug fixes for UI oscillation, timestamp sync, filter counts

**Files Changed:**
- `gps-tracker/customer-dashboard/public/index.html` (+3000 lines approx)

### 2. Trip Engine v2.1.6 → v2.2 (Backend)
**Commits:** ~50 commits  
**New Services:**
- `app/services/trip_engine.py` (2312 lines) - Core journey calculation engine
- `app/services/trip_backfill_service.py` (331 lines) - Historical data backfill
- `app/services/trip_reprocess_service.py` (153 lines) - Journey reprocessing
- `app/services/async_job_worker.py` (382 lines) - Background job processor

**Key Features:**
- 🚀 Journey calculation from GPS positions
- 🚀 Stationary period detection
- 🚀 Moving leg segmentation
- 🚀 Air journey rollup for flights
- 🚀 Day boundary auto-close
- 🚀 Re-entrancy guards
- 🚀 Overlap detection
- 🚀 Journey metrics (distance, duration, battery drain)

### 3. Admin Dashboard Enhancements
**Commits:** ~30 commits  
**New Features:**
- ✨ Device subscription management (enable/disable trip calculation per device)
- ✨ Manual backfill UI (reprocess specific date ranges)
- ✨ Batch reprocessing (fix journey data issues)
- ✨ Trip configuration (engine parameters)
- ✨ Async job monitoring
- ✨ Logger download improvements

**Files Changed:**
- `gps-tracker/admin-portal/index.html` (+2121 lines)
- `gps-tracker/admin-portal/trip-config.html` (578 lines NEW)
- `gps-tracker/backend/app/routes_admin.py` (+814 lines)
- `gps-tracker/backend/app/models_admin.py` (+47 lines)

---

## Database Changes

### New Tables (via Alembic migrations):
1. **`journeys`** - Trip data (start/end time, metrics)
2. **`journey_legs`** - Moving segments with positions array
3. **`journey_stationaries`** - Stationary periods
4. **`engine_state`** - Per-device calculation state
5. **`device_positions`** - Deduplicated GPS positions
6. **`async_jobs`** - Background job queue
7. **`tenant_trip_config`** - Per-tenant engine configuration

### Migrations Required:
```bash
# Critical migrations (10 files)
055_trip_engine_schema.py       # Creates core tables
058_add_tenant_trip_config.py   # Config table
059_add_async_jobs.py           # Job queue
v22_refinements.py              # Schema refinements
B1_B2_B3_fixes.py               # Phase 1 constraints
B4_B5_fixes.py                  # Phase 2 fixes
B1_deduplication_*.py           # Data cleanup (3 files)
fix_D1_migration.py             # Table name fixes
```

---

## Infrastructure Changes

### New Docker Service Required:
```yaml
worker:
  build: ./backend/Dockerfile
  container_name: beacon_telematics_worker
  command: python -m app.services.async_job_worker
  # Polls async_jobs table every 5s
  # Processes batch backfill/reprocess jobs
```

**Impact:** New container must be added to `docker-compose.yml`

---

## Dependencies & Prerequisites

### Backend API Changes:
✅ `/api/portal/journeys` - NEW endpoint for Movement Analytics  
✅ `/api/portal/journeys/{journey_id}` - Journey detail endpoint  
✅ `/api/admin/trip-config` - Engine configuration  
✅ `/api/admin/devices/{id}/subscribe` - Subscription management  
✅ `/api/admin/backfill` - Manual backfill  
✅ `/api/admin/reprocess` - Batch reprocessing  

### Environment Variables:
No new env vars required - feature uses existing TENANT_DISABLED_FEATURES

---

## Promotion Strategies

### ❌ Option 1: Full Merge (NOT RECOMMENDED)
**Command:** `git merge main`  
**Result:** Will conflict on 276 commits, guaranteed failure  
**Risk:** 🔴 EXTREME - Same issue as before with syntax errors

### ⚠️ Option 2: Cherry-Pick Feature Branch (MODERATE RISK)
**Steps:**
1. Create temporary branch from prod/beacon
2. Cherry-pick Movement Analytics commits (manual conflict resolution)
3. Cherry-pick admin features  
4. Cherry-pick database migrations
5. Test thoroughly before merge

**Risk:** 🟡 HIGH - Manual conflict resolution, easy to miss dependencies  
**Time:** 3-5 hours minimum

### ✅ Option 3: Fresh Deployment from main (RECOMMENDED)
**Strategy:** Deploy from `main` branch to Beacon with feature flags

**Steps:**
1. Add to Beacon backend/.env:
   ```bash
   TENANT_DISABLED_FEATURES=floorplan,building  # Keep disabled
   # Movement Analytics ENABLED (remove from disabled list)
   ```

2. Update GitHub Actions workflow to deploy main to Beacon:
   ```yaml
   # .github/workflows/deploy-beacon.yml
   branches: [main]  # Change from prod/beacon
   ```

3. Keep prod/beacon for rollback only:
   ```bash
   # Tag current prod/beacon as last stable
   git tag beacon-stable-pre-analytics origin/prod/beacon
   git push origin beacon-stable-pre-analytics
   ```

**Risk:** 🟢 LOW - Clean deployment, all features tested together  
**Time:** 1 hour setup + testing

---

## Testing Checklist

### Before Promotion:
- [ ] Database backup of Beacon production
- [ ] Test migrations on Beacon staging clone
- [ ] Verify worker service starts correctly
- [ ] Test Movement Analytics with real Beacon data
- [ ] Test admin backfill UI
- [ ] Test subscription enable/disable
- [ ] Verify no regressions in existing features

### After Promotion:
- [ ] Movement Analytics tab loads
- [ ] Journey data calculates correctly
- [ ] Map shows journey paths
- [ ] Satellite switcher works
- [ ] Admin dashboard accessible
- [ ] Worker service processing jobs
- [ ] No console errors
- [ ] Performance acceptable

---

## Rollback Plan

### If Deployment Fails:
```bash
# Revert to tagged stable version
git checkout beacon-stable-pre-analytics
git checkout -b prod/beacon-rollback
docker compose down
docker compose up -d --build

# OR restore database backup if migrations applied
pg_restore -d beacon_telematics backup_pre_analytics.sql
```

---

## Estimated Timeline

### Option 3 (Recommended):
- **Day 1:** Database backup, worker service setup (2 hours)
- **Day 2:** Deploy main to Beacon staging, test (4 hours)
- **Day 3:** Production deployment window (2 hours)
- **Total:** 8 hours spread over 3 days

### Option 2 (Cherry-pick):
- **Day 1-2:** Cherry-pick commits, resolve conflicts (8 hours)
- **Day 3:** Testing on staging (4 hours)
- **Day 4:** Production deployment (2 hours)
- **Total:** 14 hours spread over 4 days

---

## Recommendation

**🎯 USE OPTION 3: Fresh Deployment from main**

**Rationale:**
1. ✅ Avoids merge conflict hell (276 commits)
2. ✅ All features tested together on main/PinPlot
3. ✅ Feature flags already implemented
4. ✅ Faster deployment (1 hour vs 14 hours)
5. ✅ Lower risk of syntax errors
6. ✅ Easier rollback (just redeploy old image)

**Next Steps:**
1. Tag current prod/beacon as `beacon-stable-pre-analytics`
2. Update `.github/workflows/deploy-beacon.yml` to deploy from main
3. Test on Beacon staging first
4. Schedule production deployment window

---

## Questions to Answer Before Proceeding:

1. **Does Beacon have a staging environment?**  
   - If not, can we create one by cloning docker-compose.yml?

2. **Current database size?**  
   - Migrations may take time on large datasets

3. **Downtime acceptable?**  
   - Worker service requires restart, migrations need app offline

4. **Monitoring in place?**  
   - Need to watch worker service logs, journey calculation performance

5. **Backup strategy verified?**  
   - Can we restore database if migrations fail?

---

**Assessment Status:** ✅ Complete - Ready for decision on promotion strategy
