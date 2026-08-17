# Customer Dashboard i18n Implementation Status

## ✅ COMPLETED: Movement Analytics Section

### Changes Made (Commits `3476d2e` + `d0bcb9f`)

**HTML Updates:**
- Added `data-i18n` attributes to 27 hardcoded English strings in Movement Analytics
- All text now loads dynamically from translations API

**Translation Keys Script:**
- Created `add_movement_analytics_translation_keys.py`
- Adds 18 new translation keys with EN/FR/NL/IT/ZH translations
- Run on server: `docker exec pinplot_backend python app/add_movement_analytics_translation_keys.py`

### Strings Now Translatable

**Asset Panel:**
- "All" → `common.all`
- "Assets" → `assets.title`
- "last reported" → `general.last_reported`
- "Loading assets..." → `assets.loading_assets`
- "SHOW ASSETS" → `general.show_assets`

**Map Panel:**
- "Journey Map" → `general.journey_map`
- "Select an asset to view journeys" → `trips.select_asset_date`
- "How To" → `general.how_to`
- "Streets" → `map.streets`
- "Satellite" → `map.satellite`
- "Reset view" → `map.reset_view`
- "Show geofences" → `geofence.show_geofences`
- "Clear markers" → `map.clear_markers`

**Legend:**
- "Start" → `trips.start`
- "Leg" → `general.leg`
- "Position" → `general.position`
- "Stationary" → `general.stationary`
- "End" → `trips.end`

**Journeys/Positions Panel:**
- "Journeys" → `trips.journeys`
- "Positions" → `general.positions`
- "SHOW JOURNEYS" → `general.show_journeys`
- "Select an asset to view positions" → `general.select_asset_positions`

---

## 🚧 TODO: Remaining Customer Dashboard Sections

### High Priority (Main Content Areas)

#### 1. **Live Map Tab**
Hardcoded strings to translate:
- Map controls and tooltips
- Asset list headers
- Status filters
- Category filters
- Time badges

Estimated: ~30 strings

#### 2. **Asset List Tab**
Hardcoded strings to translate:
- Table headers ("Name", "Status", "Last Seen", "Battery")
- Filter options
- Action buttons
- Empty states

Estimated: ~25 strings

#### 3. **Movement History Tab**
Hardcoded strings to translate:
- Date range labels
- Journey table headers
- Distance/duration labels
- Empty states
- Load buttons

Estimated: ~35 strings

#### 4. **Floor Plan Tab**
Hardcoded strings to translate:
- Building/floor selectors
- Upload instructions
- Position labels
- Help text

Estimated: ~40 strings

#### 5. **Hive Tracking Tab**
Hardcoded strings to translate:
- Status cards
- Action buttons
- Form labels
- Wizard steps
- Archive labels

Estimated: ~60 strings

### Medium Priority (Management Sections)

#### 6. **Asset Management Tab**
Hardcoded strings:
- Form labels
- Status options
- Action buttons
- Category selectors

Estimated: ~50 strings

#### 7. **Geofences Tab**
Hardcoded strings:
- Form labels
- Shape type options
- Alert settings
- Action buttons

Estimated: ~45 strings

#### 8. **User Accounts Tab**
Hardcoded strings:
- Form labels
- Role options
- Permission toggles
- Action buttons

Estimated: ~40 strings

#### 9. **QR/NFC Tags Tab**
Hardcoded strings:
- Form labels
- Type selectors
- Action buttons
- Bulk operations

Estimated: ~30 strings

#### 10. **Floor Plan Setup Tab**
Hardcoded strings:
- Upload instructions
- Calibration steps
- Action buttons
- Validation messages

Estimated: ~35 strings

### Low Priority (Reports & Settings)

#### 11. **Reports Tabs** (6 tabs)
- Tag Subscriptions
- Item User Activity
- Journey Log
- GeoFence Events
- Battery Offline
- Alerts Inbox

Estimated: ~80 strings total

#### 12. **Settings Modal**
Hardcoded strings:
- Form labels
- Save/cancel buttons
- Validation messages

Estimated: ~20 strings

---

## 📊 Overall Progress

| Section | Status | Strings | Priority |
|---------|--------|---------|----------|
| Movement Analytics | ✅ Complete | 27 | High |
| Live Map | ⏳ Pending | ~30 | High |
| Asset List | ⏳ Pending | ~25 | High |
| Movement History | ⏳ Pending | ~35 | High |
| Floor Plan | ⏳ Pending | ~40 | High |
| Hive Tracking | ⏳ Pending | ~60 | High |
| Asset Management | ⏳ Pending | ~50 | Medium |
| Geofences | ⏳ Pending | ~45 | Medium |
| User Accounts | ⏳ Pending | ~40 | Medium |
| QR/NFC Tags | ⏳ Pending | ~30 | Medium |
| Floor Plan Setup | ⏳ Pending | ~35 | Medium |
| Reports | ⏳ Pending | ~80 | Low |
| Settings | ⏳ Pending | ~20 | Low |
| **TOTAL** | **8% Done** | **~517** | |

---

## 🚀 Deployment Instructions

### For PinPlot Production (159.89.50.65)

1. **Push changes** (when network allows):
   ```bash
   cd /Users/carl/Documents/MobileCode/Pinplot
   git push origin main
   ```

2. **After deployment succeeds**, run translation keys script:
   ```bash
   ssh -i ~/.ssh/pinplot-deploy root@159.89.50.65 \
     "docker exec pinplot_backend python app/add_movement_analytics_translation_keys.py"
   ```

3. **Verify translations work:**
   - Open https://pinplot.me/
   - Switch language to French
   - Go to Movement Analytics tab
   - Verify all text is translated (no English)

### For Beacon Production (prod/beacon branch)

1. **Merge to prod/beacon** (after PinPlot verification):
   ```bash
   git checkout prod/beacon
   git merge main
   git push origin prod/beacon
   ```

2. **After deployment**, run same script on Beacon server

---

## 📝 Implementation Strategy

### Recommended Approach: Iterative Sections

**Phase 1 (Current): Movement Analytics** ✅
- 27 strings translatable
- Script to add missing keys

**Phase 2: High-Priority Tabs** (Next)
- Live Map, Asset List, Movement History, Floor Plan, Hive Tracking
- ~220 strings total
- Estimated: 2-3 hours work

**Phase 3: Management Tabs**
- Asset Management, Geofences, User Accounts, QR/NFC, Floor Plan Setup
- ~200 strings total
- Estimated: 2-3 hours work

**Phase 4: Reports & Settings**
- All report tabs, Settings modal
- ~100 strings total
- Estimated: 1-2 hours work

### Tools Needed

**Option A: Manual (Current Method)**
- Continue adding `data-i18n` attributes manually
- Create scripts for each section's translation keys
- Pro: Full control, easy to review
- Con: Time-consuming, repetitive

**Option B: Semi-Automated**
- Create a Python script to scan HTML for hardcoded English
- Generate translation key mappings automatically
- Bulk update HTML with data-i18n attributes
- Pro: Faster for large sections
- Con: Requires careful validation

---

## ✅ Success Criteria

**For each section to be considered "complete":**
1. ✅ All hardcoded English text has `data-i18n` attributes
2. ✅ Translation keys exist in database (all 5 languages)
3. ✅ Tested in browser with language switcher
4. ✅ No English text visible when viewing in other languages
5. ✅ All tooltips (`title` attributes) also translated

---

## 📚 Reference

**Translation Key Naming Conventions:**
- `common.*` - Shared across entire app (OK, Cancel, Save, etc.)
- `general.*` - General UI elements (buttons, labels)
- `assets.*` - Asset-specific text
- `trips.*` - Journey/trip-related text
- `geofence.*` - Geofence-related text
- `map.*` - Map controls and features
- `auth.*` - Authentication/login text
- `nav.*` - Navigation menu items
- `alerts.*` - Alert/notification text
- `settings.*` - Settings UI text
- `reports.*` - Report-specific text
- `hive.*` - Hive tracking specific text

**Example Translation Key Structure:**
```
nav.live_map          → "Live Map" (menu item)
general.live_map      → "Live Map" (page title)
map.live_map_help     → "Live Map help text" (tooltip)
```
