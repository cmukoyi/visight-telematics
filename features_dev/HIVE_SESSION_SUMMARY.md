# HIVE Session Summary — May 28, 2026

## Overview

Completed first round of HIVE v1.1 testing feedback and bug fixes. Session covered:
1. UI polish fixes (5 bugs)
2. Alert improvements  
3. Two critical bugs from production testing

## Commits Shipped to `main` (7 total)

### 1. `3c504f2` — 5 UI bugs (completed earlier)
- Timeline pagination (10 events per page)
- Light-mode map overlay contrast
- Config modal slider thumb visibility  
- Recreate button fix (archive source memberships before creating new)
- Removed recreate button from archive view

### 2. `a28d95c` — HIVE alert improvements
- Friendly labels for all alert types
- Red colour for breach alerts
- Hive name in Asset column
- Breach description in Detail column

### 3. `cec766f` — Migration 039: backfill hive_name
- Retroactively adds `hive_name` to historical alert meta_data
- Fixes "—" in Asset column for old alerts

### 4. `3226de6` — Wizard profile threshold defaults
- Stationary: 150m
- Slow: 450m
- Mobile: 1000m
- Fixed bug where wizard left threshold blank or defaulted all to 1000m

### 5. `7f0fffd` — Human-readable event labels
- Timeline now shows "Motion state changed" instead of "MOTION_STATE_CHANGED"
- Added fallback helper to auto-convert any SNAKE_CASE → Title Case

### 6. `a4edbad` — Timeline date grouping
- Groups events by date with headers (TODAY, YESTERDAY, Mon 27 May)
- Makes 7-day history clear (was showing only times, looked like all today)

### 7. `b357442` — Bug fixes from production testing ⭐
- **BUG #2 (FIXED)**: Outlier algorithm corrected to count breaching pairs per spec
- **BUG #1 (DIAGNOSTIC)**: Added comprehensive structured logging to diagnose motion oscillation

---

## Bug Details

### Bug #2 — Outlier Mis-Attribution (FIXED)

**Test scenario**: 3-tag hive (283/087/342), tag 283 driven 300km away

**Problem**: Different tags identified as outlier when 283 should be consistent

**Root cause**: Algorithm used "max distance" instead of "most breaching pairs"

**Fix**:
- Refactored `pairwise_max_distance()` → `pairwise_max_distance_and_outlier(threshold_m)`
- Now counts breaching pairs per spec §2.4
- Tag with most breaching pairs = outlier
- Alphabetical tiebreaker for determinism

**Expected result**: Tag 283 consistently identified as outlier (has 2 breaching pairs vs. 1 each for 087/342)

### Bug #1 — Motion State Oscillation (DIAGNOSTIC LOGGING ADDED)

**Problem**: System cycles STATIONARY → PRE_TRANSIT → STATIONARY every 6-12 minutes, firing repeated breach alerts

**Hypothesis**: Centroid computed from FRESH tags only. When tag composition changes (283 goes STALE → FRESH as GPS reports arrive), centroid jumps, creating apparent velocity even when all tags are stationary.

**Fix (Phase 1)**: Added comprehensive structured logging capturing:
- Motion state transitions
- Centroid position, speed, bearing, fresh tag composition
- Per-tag velocities + coherence score
- Breaching pair counts
- Alert state transitions

**Next step**: Re-run test scenario, capture logs, analyze to confirm root cause, then apply targeted fix

---

## Testing Required

### Priority 1 — Validate on pinplot.me

1. **Outlier fix verification**:
   - Create 3-tag hive
   - Move one tag far away (300+ km)
   - Keep other two together
   - Confirm breach alert shows same tag as outlier across all events

2. **UI polish**:
   - Recent Activity shows date headers (TODAY, YESTERDAY, etc.)
   - Timeline shows human-readable labels ("Motion state changed")
   - Wizard defaults: Stationary=150m, Slow=450m, Mobile=1000m
   - Light mode: map overlays readable
   - Config modal: slider thumb visible
   - Active hive recreate: works without error

3. **Alerts**:
   - Breach alerts show friendly labels ("Hive Breach" not "hive_breached")
   - Breach colour is red
   - Asset column shows hive name (not "—")
   - Detail column shows breach description

### Priority 2 — Production test for Bug #1

Re-run original test scenario:
- 3-tag hive, one tag driven 300km away
- Monitor for 1-2 hours
- Check backend logs for structured evaluation output
- Confirm no motion state oscillation
- If oscillation persists, analyze logs to identify root cause

### Priority 3 — Beacon promotion

Once pinplot.me validated:
```bash
cd ~/Documents/MobileCode/Pinplot && \
  git checkout main && git pull && \
  git checkout prod/beacon && git merge --ff-only main && \
  git push origin prod/beacon && git checkout main
```

This will ship all 7 commits (UI fixes + alert improvements + bug fixes) to beacon in one promotion.

---

## Documentation Created

1. **`HIVE_BUG_FIX_PLAN.md`** — Detailed analysis of both bugs, fix strategy, success criteria
2. **`HIVE_Implementation_Verification.md`** — Original verification guide from user (comprehensive testing checklist)

---

## Files Modified This Session

### Backend
- `gps-tracker/backend/app/services/hive_service.py` — Outlier algorithm + diagnostic logging
- `gps-tracker/backend/alembic/versions/039_backfill_hive_alert_meta.py` — Migration to backfill hive_name

### Frontend  
- `gps-tracker/customer-dashboard/public/index.html` — 5 UI fixes + alert improvements + timeline date grouping

### Documentation
- `features_dev/HIVE_BUG_FIX_PLAN.md` — New
- `features_dev/HIVE_Implementation_Verification.md` — New (from user)

---

## Next Actions

1. **Monitor pinplot.me deploy** — all 7 commits should autodeploy
2. **Validate UI fixes** — run through testing checklist above
3. **Re-run production test** — capture diagnostic logs for Bug #1
4. **Analyze logs** — if oscillation persists, identify root cause from structured log data
5. **Apply final fix** — once root cause confirmed (likely centroid composition churn)
6. **Promote to beacon** — ff-merge after validation

---

## Session Stats

- **Commits**: 7
- **Files modified**: 3 backend, 1 frontend, 2 documentation
- **Bugs fixed**: 1 (outlier mis-attribution)
- **Bugs diagnosed**: 1 (motion oscillation — logging added, awaiting production test)
- **Lines changed**: ~180 backend, ~800 frontend/docs

All changes deployed to `main` and triggering pinplot.me autodeploy.
