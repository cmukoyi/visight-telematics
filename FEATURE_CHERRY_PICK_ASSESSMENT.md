# Feature Cherry-Pick Assessment for prod/beacon Promotion

**Date:** 2026-07-24  
**Purpose:** Identify features to promote and hide for production beacon deployment

---

## 📋 Features Overview

### ✅ Features to KEEP & Promote

#### 1. Movement Analytics
**Status:** ✅ Production Ready (BETA badge removed in commit `3610cbc`)

**Location:**
- Navigation menu: Line 328-331 in `index.html`
- Tab implementation: Lines 13523-15475 (full IIFE module)
- Data source: Uses Trip Engine (backend `/api/admin/trips/` endpoints)

**Dependencies:**
- ✅ Trip Engine v2.1.11 (backend)
- ✅ Device subscription system
- ✅ Journey/leg/stationary database tables
- ✅ Category filtering system

**Files affected:**
- `gps-tracker/customer-dashboard/public/index.html`

**Backend endpoints required:**
- `/api/portal/trips/journeys` - Journey list
- `/api/portal/trips/legs` - Leg details
- `/api/portal/trips/stationaries` - Stop details
- `/api/portal/categories` - Category filters

**No changes needed** - Already stable, BETA removed.

---

#### 2. Satellite Maps
**Status:** ✅ Fully Implemented & Working

**Location:**
- Live Map: Lines 486-487 (map style button)
- Movement Analytics: Lines 3529-3530 (map style button)
- Style handler: Lines 10376-10377, 13622-13623

**Implementation:**
```javascript
// Satellite style uses MapTiler hybrid-v4 (satellite imagery with labels)
case 'satellite':
    tileStyle = 'hybrid-v4'; // satellite with labels - most useful
```

**Files affected:**
- `gps-tracker/customer-dashboard/public/index.html`

**Dependencies:**
- ✅ MapTiler API (already configured)
- ✅ No backend changes needed

**No changes needed** - Already working perfectly.

---

### ❌ Features to HIDE (Not Production Ready)

#### 3. Floor Plan (Tracking Tab)
**Status:** ⚠️ BETA - Not ready for beacon production

**Location:**
- Navigation: Lines 313-316
- Tab: `data-tab="floorplan"`
- Implementation: Uses uploaded floor plan images with asset overlay

**Why hide:**
- Still in Beta
- Complex feature requiring building/floor database setup
- Not requested by beacon customer
- Would confuse users without proper onboarding

**Action needed:** Hide navigation button

---

#### 4. Floor Plan Sketch (Management Tab)
**Status:** ⚠️ BETA - Not ready for beacon production

**Location:**
- Navigation: Lines 362-365
- Tab: `data-tab="building"`
- Implementation: Lines 12732-13519 (canvas-based floor plan builder)

**Why hide:**
- Still in Beta
- Complex drawing tool with gateway placement
- Integration with backend building/floor system
- Requires training and onboarding
- Not requested by beacon customer

**Action needed:** Hide navigation button

---

## 🎯 Implementation Plan

### Step 1: Hide Floor Plan Features

Hide the navigation buttons using CSS display:none or by commenting out the HTML:

**Option A: CSS-based hiding (recommended for easy toggle)**
```css
/* Hide Floor Plan features for beacon deployment */
.nav-item[data-tab="floorplan"],
.nav-item[data-tab="building"] {
    display: none !important;
}
```

**Option B: Remove from HTML (cleaner but harder to toggle back)**
Comment out lines:
- Lines 313-316 (Floor Plan button)
- Lines 362-365 (Floor Plan Sketch button)

**Recommendation:** Use Option A (CSS) so features can be easily enabled later if beacon requests them.

---

### Step 2: Verify Dependencies

#### Movement Analytics Dependencies:
- ✅ Trip Engine v2.1.11 deployed
- ✅ Migration 20260724_v2111_d1_late_arrivals.py (positions.received_at)
- ✅ Device subscription system
- ✅ Categories table and API

**Check on beacon:**
```bash
# SSH to beacon server
ssh root@beacontelematics.co.uk

# Check migration state
docker exec beacon_backend alembic -c /app/alembic.ini current

# Verify Trip Engine is running
docker exec beacon_backend python -c "from app.services.trip_engine import ENGINE_VERSION; print(ENGINE_VERSION)"

# Check categories exist
docker exec beacon_backend psql -U pinplot_db_user -d pinplot_db -c "SELECT COUNT(*) FROM categories;"
```

#### Satellite Maps Dependencies:
- ✅ MapTiler API key (already in environment)
- ✅ No backend dependencies

**Check on beacon:**
```bash
# Verify MapTiler key exists
docker exec beacon_backend env | grep MAPTILER
```

---

### Step 3: Testing Checklist

After promotion to prod/beacon:

**Movement Analytics:**
- [ ] Navigation shows "Movement Analytics" without BETA badge
- [ ] Tab loads without errors
- [ ] Journey tiles display correctly
- [ ] Category filters work (All, Personal, Work, Other)
- [ ] Status filters work (All, Subscribed, Unsubscribed)
- [ ] Asset selection updates journey view
- [ ] Leg details panel opens on click
- [ ] Stop details panel opens on click
- [ ] Map markers render correctly
- [ ] Polylines connect legs to stops with zero gap (C1 fix)
- [ ] Timeline shows correct journey structure

**Satellite Maps:**
- [ ] "Satellite" button appears on Live Map
- [ ] "Satellite" button appears on Movement Analytics
- [ ] Clicking switches to satellite imagery with labels
- [ ] Switching between Street/Satellite/Terrain works smoothly
- [ ] Active button highlights correctly

**Hidden Features:**
- [ ] Floor Plan button NOT visible in navigation
- [ ] Floor Plan Sketch button NOT visible in navigation
- [ ] No console errors related to missing tabs
- [ ] TAB_TITLES mapping still works for other tabs

---

## 📦 Commits to Cherry-Pick

### Movement Analytics (Already in main)
All Movement Analytics features are already complete and deployed. No specific cherry-picking needed.

Key commits history:
- Multiple commits from PHASE_5.2_COMPLETE.md (journeys, legs, stationaries UI)
- Recent: `3610cbc` - Remove BETA badge

### Satellite Maps (Already in main)
Satellite maps have been implemented for months. Already in main.

### Trip Engine v2.1.11 (Required for Movement Analytics)
**Critical recent commits:**
- `512ae83` - v2.1.11 D1: Fix 50% data loss from late-arriving positions
- `47c2253` - Fix D1 migration table names
- `8381e39` - v2.1.11 C1: Fix leg terminus alignment (zero gap to markers)
- `3610cbc` - Remove BETA badge from Movement Analytics

**Must be promoted together** - these are production fixes that improve data accuracy.

---

## 🚨 Known Issues to Address Before Promotion

### Issue 1: Categories Not Loading
**Symptom:** User reported "categories on live map are gone and on movement analytics"

**Root Cause:** Need to verify categories table exists and is populated on beacon

**Fix:**
```sql
-- Check if categories table exists
SELECT * FROM categories;

-- If empty, seed default categories
INSERT INTO categories (name, color, icon) VALUES
('Personal', '#3b82f6', 'user'),
('Work', '#10b981', 'briefcase'),
('Other', '#6b7280', 'tag')
ON CONFLICT DO NOTHING;
```

### Issue 2: Migration State
**Critical:** Beacon must have all migrations including D1 (received_at column)

**Verify:**
```bash
docker exec beacon_backend alembic -c /app/alembic.ini current
# Should show: v2111_d1_late_arrivals (head)
```

---

## 📝 Deployment Script for Beacon

```bash
#!/bin/bash
# Deploy Movement Analytics + Satellite Maps to prod/beacon
# Hide Floor Plan features

cd /Users/carl/Documents/MobileCode/Pinplot

# 1. Checkout prod/beacon
git checkout prod/beacon

# 2. Merge main (includes all Movement Analytics + Trip Engine fixes)
git merge main

# 3. Add CSS to hide Floor Plan features
# (This can be done manually or via a targeted commit)

# 4. Push to trigger deployment
git push origin prod/beacon

echo "✅ Deployment triggered to beacontelematics.co.uk"
echo ""
echo "📋 Post-deployment checklist:"
echo "  - SSH to beacon and verify migrations"
echo "  - Check categories table is populated"
echo "  - Test Movement Analytics loads"
echo "  - Test Satellite maps work"
echo "  - Verify Floor Plan tabs are hidden"
```

---

## ✅ Summary

**Ready to promote:**
- ✅ Movement Analytics (full feature, BETA removed)
- ✅ Satellite Maps (working perfectly)
- ✅ Trip Engine v2.1.11 (D1 + C1 fixes)

**Must hide:**
- ❌ Floor Plan (Tracking)
- ❌ Floor Plan Sketch (Management)

**Action items:**
1. Add CSS to hide Floor Plan navigation buttons
2. Cherry-pick Trip Engine commits (D1, C1)
3. Verify beacon database has categories table
4. Run migrations on beacon
5. Test Movement Analytics and Satellite maps
6. Monitor for any console errors

**Estimated effort:** 30-45 minutes (mostly verification and testing)
