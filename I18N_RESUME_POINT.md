# i18n Implementation - Resume Point

> **LOCAL ONLY** - gitignored, never committed
> Last updated: 2026-06-20

---

## ✅ What's Complete

### Backend (Phase 1)
- ✅ 3 database tables: `languages`, `translation_keys`, `translations`
- ✅ Migration 049: i18n schema + 45 seed keys
- ✅ Migration 050: fix column name bug (`translation_key` → `key`)
- ✅ Migration 051: add 454 customer dashboard keys (total: 499 keys)
- ✅ Public API: `GET /api/languages`, `GET /api/translations/{lang}`
- ✅ Admin API: Full CRUD + translate proxy + bulk operations
- ✅ All 499 keys translated to French (auto-translate via MyMemory)

### Admin Portal (Phase 2)
- ✅ Translation Manager (spreadsheet UI)
- ✅ Language Manager (CRUD languages)
- ✅ Auto-translate feature (🤖 button)
- ✅ Clean failed translations (🗑️ button)
- ✅ Backend proxy for translate API (no CORS issues)
- ✅ Usergroup language selector

### Customer Dashboard (Phase 4 - IN PROGRESS)
- ✅ TranslationService (Singleton, lazy loading, caching)
- ✅ Language selector in Settings tab
- ✅ Global `t()` helper function
- ✅ `translateAll()` observer pattern (auto-updates UI on language change)
- ✅ localStorage persistence (`LANG_KEY`)
- ✅ Support for `data-i18n`, `data-i18n-placeholder`, `data-i18n-title`
- ✅ Demo: 7 strings marked (3 in Settings card + 4 in navigation)
- ⏳ **INCOMPLETE: 484 strings need markup** (see below)

### Flutter App (Phase 5)
- ❌ Not started

---

## 🎯 What's Left: Mark Up 484 Customer Dashboard Strings

### Current Status
- **Total keys in DB:** 499
- **Keys with markup:** 7 (1.4%)
- **Keys needing markup:** 484 (97%)

### Marked Strings (7)
1. `settings.language` - Settings card heading
2. `settings.language_hint` - Settings card description
3. `settings.interface_language` - Settings row label
4. `settings.language_stored_locally` - Settings row hint
5. `assets.asset_management` - Nav: Asset Management
6. `geofences.title` - Nav: Geofences
7. `settings.title` - Nav: Settings

### Where to Resume: Systematic Markup Plan

**File:** `gps-tracker/customer-dashboard/public/index.html` (6000+ lines)

**Approach:** Work through UI sections systematically:

#### 1. Navigation (Remaining)
- [ ] User Accounts nav item
- [ ] QR / NFC Tags nav item
- [ ] Floor Plan Sketch nav item
- [ ] Tag Subscriptions nav item
- [ ] Asset Activity nav item
- [ ] Journey Log nav item
- [ ] Geofence Events nav item
- [ ] Alerts nav item
- [ ] Download nav item

#### 2. Dashboard Tab (Line ~400-800)
- [ ] Welcome message
- [ ] Asset statistics cards
- [ ] Recent alerts
- [ ] Map controls
- [ ] Search/filter labels

#### 3. Asset Management Tab (Line ~800-1200)
- [ ] Table headers (Name, IMEI, Status, Last Seen, etc.)
- [ ] Action buttons (Add, Edit, Delete, Import, Export)
- [ ] Form labels (Asset Name, IMEI, Category, etc.)
- [ ] Status badges
- [ ] Bulk operation labels

#### 4. Geofences Tab (Line ~1200-1600)
- [ ] Table headers
- [ ] Form labels (Name, Radius, Address, etc.)
- [ ] Draw controls
- [ ] Shape type labels

#### 5. Users Tab (Line ~1600-2000)
- [ ] Table headers
- [ ] Form labels (Email, Role, Name, etc.)
- [ ] Role dropdown options
- [ ] Permission labels

#### 6. QR/NFC Tab (Line ~2000-2100)
- [ ] Instructions
- [ ] Form labels
- [ ] Download button

#### 7. Settings Tab (Line ~2100-2400)
- [ ] Account & Security section (partially done)
- [ ] Preferences section (partially done)
- [ ] Appearance section
- [ ] Email Preferences section
- [ ] Data Retention section
- [ ] Categories section

#### 8. Reports Tabs (Line ~2400-3200)
- [ ] Subscriptions report headers/labels
- [ ] Activity report headers/labels
- [ ] Journey log headers/labels
- [ ] Geofence events headers/labels
- [ ] Date filters
- [ ] Export buttons

#### 9. Alerts Tab (Line ~3200-3400)
- [ ] Alert types
- [ ] Alert messages
- [ ] Filter labels
- [ ] Action buttons

#### 10. Download Tab (Line ~3400-3600)
- [ ] App store badges
- [ ] Instructions
- [ ] Feature descriptions

#### 11. Modals & Dialogs (Scattered throughout)
- [ ] Confirmation dialogs
- [ ] Error messages
- [ ] Success messages
- [ ] Loading states

---

## 📋 Translation Key Reference

All 499 keys are in the database. Use these categories:

| Category | Count | Examples |
|----------|-------|----------|
| general | 310 | `general.loading`, `general.save`, `general.cancel` |
| assets | 46 | `assets.asset_name`, `assets.last_seen`, `assets.status` |
| common | 34 | `common.save`, `common.cancel`, `common.delete` |
| auth | 21 | `auth.login`, `auth.logout`, `auth.email` |
| map | 22 | `map.center`, `map.zoom`, `map.layer` |
| alerts | 14 | `alerts.title`, `alerts.no_alerts`, `alerts.mark_read` |
| geofences | 13 | `geofences.title`, `geofences.name`, `geofences.radius` |
| settings | 10 | `settings.title`, `settings.profile`, `settings.language` |
| trips | 9 | `trips.title`, `trips.start_time`, `trips.end_time` |
| errors | 7 | `errors.network`, `errors.invalid_input` |
| fleet | 5 | `fleet.title`, `fleet.vehicles` |
| reports | 4 | `reports.reports`, `reports.reporter_reports_only` |
| dashboard | 3 | `dashboard.title`, `dashboard.welcome` |
| success | 1 | `success.operation_successful` |

---

## 🔧 How to Resume

### Quick Command Reference

**Test translation in browser console:**
```javascript
t('assets.asset_name')  // Should return "Nom de l'actif"
t('common.save')        // Should return "Sauvegarder"
```

**Check database for a key:**
```bash
ssh root@pinplot.me "docker exec pinplot_db psql -U pinplot_db_user -d pinplot_db -c \"SELECT tk.key, t.translated_text FROM translations t JOIN translation_keys tk ON t.key = tk.key WHERE t.language_code='fr' AND tk.key LIKE '%asset%' LIMIT 10;\""
```

**Find strings in HTML to mark up:**
```bash
cd /Users/carl/Documents/MobileCode/Pinplot
grep -n "Asset Name" gps-tracker/customer-dashboard/public/index.html
```

### Markup Pattern

**Before:**
```html
<button>Save</button>
<input placeholder="Enter name">
<span title="Click to edit">Name</span>
```

**After:**
```html
<button data-i18n="common.save">Save</button>
<input data-i18n-placeholder="assets.enter_name" placeholder="Enter name">
<span data-i18n-title="common.click_to_edit" title="Click to edit" data-i18n="assets.name">Name</span>
```

### Batch Editing Approach

1. **Identify section** (e.g., Asset Management table)
2. **List all visible strings** in that section
3. **Map to translation keys** from the 499 in DB
4. **Add data-i18n attributes** in one commit per section
5. **Test** by switching language in Settings

---

## 📊 Estimated Work

- **Time per section:** 15-30 minutes
- **Total sections:** ~11
- **Total time:** 3-5 hours of careful markup
- **Complexity:** Low (mechanical work, pattern-based)
- **Risk:** Low (fallbacks preserve English text)

---

## 🚀 Deployment Status

**Latest commits on main:**
- `29a745a` - Migration 051 (454 keys) ✅ Deployed
- `80ba9a4` - TranslationService wiring ✅ Deployed
- `f125b52` - Navigation i18n demo ✅ Deployed

**Production state:**
- Backend: All migrations applied (051 at head)
- Admin Portal: Translation Manager working
- Customer Dashboard: 7 strings translating, 484 to go
- Database: 499 English keys + 499 French translations

---

## 🎯 When You Return

Say: **"Continue i18n markup"** and I'll:
1. Start with Navigation (finish the 9 remaining items)
2. Move through Dashboard tab
3. Work section by section until all 484 strings are marked
4. Test after each major section
5. Commit in logical batches

OR specify a section: **"Mark up Asset Management tab"**
