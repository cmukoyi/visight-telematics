# 🌍 Internationalization (i18n) Implementation Plan
**Platform: Pinplot/BeaconTelematics**  
**Primary Language: French (Français)**  
**Test Environment: Pinplot (pinplot.me)**  
**Started: 2026-06-18**

---

## 📋 Overview

Implement database-driven multi-language support across:
- Admin Portal (translation management)
- Customer Dashboard (React/JS)
- Flutter Mobile App

**Key Requirement:** New customer needs platform in French.

---

## 🏗️ Architecture

### Database Schema

```sql
-- Languages table
CREATE TABLE languages (
    id SERIAL PRIMARY KEY,
    code VARCHAR(5) UNIQUE NOT NULL,  -- 'en', 'fr', 'es'
    name VARCHAR(50) NOT NULL,         -- 'English', 'Français'
    is_active BOOLEAN DEFAULT true,
    created_at TIMESTAMP DEFAULT NOW()
);

-- Translation keys (namespace.key format)
CREATE TABLE translation_keys (
    id SERIAL PRIMARY KEY,
    key VARCHAR(255) UNIQUE NOT NULL,  -- 'dashboard.welcome', 'fleet.add_vehicle'
    category VARCHAR(50),               -- 'dashboard', 'fleet', 'common'
    context TEXT,                       -- Help text for translators
    default_text TEXT NOT NULL,         -- Fallback English text
    created_at TIMESTAMP DEFAULT NOW()
);

-- Actual translations
CREATE TABLE translations (
    id SERIAL PRIMARY KEY,
    language_code VARCHAR(5) REFERENCES languages(code),
    translation_key VARCHAR(255) REFERENCES translation_keys(key),
    translated_text TEXT NOT NULL,
    last_updated TIMESTAMP DEFAULT NOW(),
    UNIQUE(language_code, translation_key)
);

-- Add to existing tables
ALTER TABLE usergroups ADD COLUMN default_language VARCHAR(5) DEFAULT 'en';
ALTER TABLE users ADD COLUMN preferred_language VARCHAR(5) NULL;  -- User override
```

### Language Resolution Logic
```
1. Check user.preferred_language (highest priority)
2. Fall back to usergroup.default_language
3. Fall back to 'en' (system default)
```

---

## 🚀 Implementation Phases

### ✅ Phase 1: Backend API (FastAPI)

**Migration File:** `049_add_i18n_tables.py` ✅ COMPLETE

**API Endpoints:** ✅ ALL IMPLEMENTED

```python
# Public API - get translations
GET /api/translations/{lang_code}           # Returns {key: translation}
GET /api/languages                          # List active languages

# Admin API - manage translations
GET /api/admin/translation-keys             # List all keys with translations
POST /api/admin/translation-keys            # Create new key
PUT /api/admin/translations                 # Update translation for key+lang
POST /api/admin/languages                   # Add new language
DELETE /api/admin/languages/{code}          # Deactivate language

# Bulk operations
POST /api/admin/translations/import         # CSV/JSON import
GET /api/admin/translations/export/{lang}   # Export for translators
```

**Files to Create:**
- `gps-tracker/backend/alembic/versions/049_add_i18n_tables.py` ✅
- `gps-tracker/backend/app/models_i18n.py` ✅
- `gps-tracker/backend/app/routes_i18n.py` ✅
- `gps-tracker/backend/app/routes_admin_i18n.py` ✅

**Status:** ✅ COMPLETE - Deployed to main (commit a0f5080)

---

### ✅ Phase 2: Admin Portal UI

**New Pages:**

1. **Translation Manager** (`admin-portal/translations.html`) ✅
   - View all translation keys ✅
   - Filter by category (dashboard, fleet, common, etc.) ✅
   - Search functionality ✅
   - Inline editing for translations ✅
   - Add new keys ✅
   - Show completion % per language ✅
   
2. **Language Manager** (`admin-portal/languages.html`) ✅
   - Add/activate languages ✅
   - View translation progress ✅
   - Export untranslated keys ✅
   - Import translated files ✅

3. **Usergroup Editor Enhancement** ✅ COMPLETE
   - Add "Default Language" dropdown
   - Shows active languages from database

**Files to Create/Modify:**
- `gps-tracker/admin-portal/translations.html` ✅ (embedded in index.html)
- `gps-tracker/admin-portal/languages.html` ✅ (embedded in index.html)
- `gps-tracker/admin-portal/usergroups.html` (modify) ✅
- `gps-tracker/admin-portal/index.html` (add nav links) ✅

**Status:** ✅ COMPLETE - Deployed to main (commit 35ad83e)
- Translation Manager: ✅ Complete
- Language Manager: ✅ Complete
- Usergroup Editor: ✅ Complete with language selector

---

### ✅ Phase 3: Customer Dashboard (React/JS)

**Implementation:**
- Use **i18next** library (industry standard)
- Load translations from API on startup
- Add language selector to settings
- Replace hardcoded strings with `t('key')`

**Files to Modify:**
- `gps-tracker/customer-dashboard/src/App.js` (init i18next)
- `gps-tracker/customer-dashboard/src/Settings.js` (add language picker)
- `gps-tracker/customer-dashboard/src/**/*.js` (replace strings)

**Code Example:**
```javascript
// On app startup
const userLanguage = await fetchUserLanguage();  // From backend
const translations = await fetch(`/api/translations/${userLanguage}`);

i18next.init({
  lng: userLanguage,
  resources: { [userLanguage]: { translation: translations } }
});

// In components
import { useTranslation } from 'react-i18next';
const { t } = useTranslation();
<h1>{t('dashboard.welcome_message')}</h1>
```

**Status:** 🔲 Not Started

---

### ✅ Phase 4: Flutter Mobile App

**Implementation:**
- Use **flutter_localizations** + API-loaded translations
- Load translations from API on app startup
- Add language picker to settings
- Replace hardcoded strings with translate() calls

**Files to Modify:**
- `gps-tracker/mobile-app/lib/main.dart`
- `gps-tracker/mobile-app/lib/services/api_localizations.dart` (create)
- `gps-tracker/mobile-app/lib/screens/settings_screen.dart`
- `gps-tracker/mobile-app/lib/**/*.dart` (replace strings)

**Code Example:**
```dart
// Load translations from API on startup
class ApiLocalizations {
  final Map<String, String> _translations;
  
  static Future<ApiLocalizations> load(String langCode) async {
    final response = await http.get('/api/translations/$langCode');
    return ApiLocalizations(jsonDecode(response.body));
  }
  
  String translate(String key) => _translations[key] ?? key;
}

// Usage in widgets
Text(AppLocalizations.of(context).translate('fleet.add_vehicle'))
```

**Status:** 🔲 Not Started

---

## 📝 Translation Key Categories

```
common.*          # Buttons, labels used everywhere (Save, Cancel, Delete, etc.)
dashboard.*       # Dashboard-specific text
fleet.*           # Fleet management
geofences.*       # Geofence features
trips.*           # Trip history
alerts.*          # Alert notifications
admin.*           # Admin portal
settings.*        # Settings screens
errors.*          # Error messages
notifications.*   # Push notifications
auth.*            # Login, registration
reports.*         # Reporting features
```

---

## 🎯 Translation Key Extraction

### Step 1: Audit & Extract Hardcoded Strings

**Flutter App:**
```bash
cd gps-tracker/mobile-app
grep -r "Text('" lib/ | grep -v "translate" > hardcoded_flutter.txt
```

**Customer Dashboard:**
```bash
cd gps-tracker/customer-dashboard
grep -r ">\s*[A-Z]" src/ | grep -v "{t(" > hardcoded_dashboard.txt
```

### Step 2: Create Initial English Keys

Estimate: 500-1000 translation keys across all platforms

### Step 3: Seed Database

Include in migration 049 with initial English text

---

## 📅 Timeline

| Week | Focus | Deliverables |
|------|-------|-------------|
| **Week 1** | Backend + Database | Migration, API routes, seed data |
| **Week 2** | Admin Portal | Translation Manager, Language Manager UI |
| **Week 3** | Customer Dashboard | i18next integration, settings UI |
| **Week 4** | Flutter App | API localization, settings UI |
| **Week 5** | Translation Work | Professional French translation, QA |

---

## ✅ Testing Checklist

### Backend Testing
- [ ] Migration 049 runs successfully on Pinplot dev
- [ ] Can create new language via API
- [ ] Can add translation keys via API
- [ ] Can add translations via API
- [ ] Public API returns correct language for user
- [ ] Language resolution follows priority order

### Admin Portal Testing
- [ ] Translation Manager loads all keys
- [ ] Can filter keys by category
- [ ] Can search keys
- [ ] Can edit translations inline
- [ ] Can add new translation keys
- [ ] Can add new language
- [ ] Export CSV works
- [ ] Import CSV works
- [ ] Usergroup editor shows language dropdown
- [ ] Can assign default language to usergroup

### Customer Dashboard Testing
- [ ] Dashboard loads in English (default)
- [ ] Dashboard loads in French when usergroup set to French
- [ ] User can override language in settings
- [ ] Language persists after logout/login
- [ ] All strings are translated (no English leaking through)

### Flutter App Testing
- [ ] App loads in English (default)
- [ ] App loads in French when usergroup set to French
- [ ] User can select language in settings
- [ ] Language persists after app restart
- [ ] All screens are fully translated

---

## 🐛 Known Issues / Notes

### Phase 1 Deployment Notes:
- **Commit:** a0f5080 (initial), bfec39d (bug fix #1), 93716a6 (bug fix #2), 4b7f9a1 (bug fix #3)
- **Deployed:** 2026-06-18
- **Bug #1 Fixed:** Table name was `usergroups` but should be `user_groups` (with underscore) - Fixed in bfec39d
- **Bug #2 Fixed:** Column name conflict - `Translation.translation_key` (column) conflicted with `translation_key` (relationship). Renamed column to `key` - Fixed in 93716a6
- **Bug #3 Fixed:** Missing `get_current_admin_user` dependency function in admin_auth.py - Added FastAPI dependency for admin authentication - Fixed in 4b7f9a1
- **Migration needed:** Run `docker compose exec backend alembic upgrade head` on pinplot.me server
- **Test endpoints:** After migration, test with Postman:
  - GET https://pinplot.me/api/languages (should return en, fr)
  - GET https://pinplot.me/api/translations/en (should return 50+ keys)
  - GET https://pinplot.me/api/translations/fr (should return 50 keys with empty translations)
  - Admin endpoints require auth token in header

### Phase 2 Deployment Notes:
- **Commit:** 35cd7c2 pushed to main
- **Deployed:** 2026-06-18
- **Access:** Log in to https://pinplot.me/admin/index.html
- **New Menu Items:** 
  - 🌍 Translations (translation key management)
  - 🗣️ Languages (language management)
- **Test workflow:**
  1. Click Translations → Click Refresh
  2. Should see 50+ translation keys
  3. Filter by language (fr) and enable "Missing only"
  4. Click Edit on any key, select French, add translation, Save
  5. Go to Languages tab → Click Refresh
  6. Should see English and French with completion %
  7. Test Export CSV for French
  8. Edit CSV, test Import CSV
- **Still TODO:** Add language selector to Usergroup editor

---

## 📦 Deployment Steps

### For Pinplot Testing:
1. Run migration on dev: `docker compose exec backend alembic upgrade head`
2. Deploy backend API changes
3. Deploy Admin Portal changes
4. Test translation management
5. Deploy Customer Dashboard changes
6. Deploy Flutter app changes

### For Production (BeaconTelematics):
1. Test thoroughly on Pinplot first
2. Merge to `prod/beacon` branch
3. GitHub Actions auto-deploys
4. SSH and run migrations
5. Verify translations work

---

## 🎨 UI Design Notes

### Translation Manager Table Layout:
```
┌─────────────────────────────────────────────────────────────┐
│  Admin Portal > Translations                                │
├─────────────────────────────────────────────────────────────┤
│  [Filter: All Categories ▾] [Search keys...] [+ Add Key]   │
│  [Export to CSV] [Import from CSV]                          │
├──────────┬─────────────┬──────────────────┬─────────────────┤
│ Key      │ Category    │ English          │ French          │
├──────────┼─────────────┼──────────────────┼─────────────────┤
│ common.  │ common      │ Save             │ Enregistrer ✓   │
│ save     │             │                  │ [Edit]          │
├──────────┼─────────────┼──────────────────┼─────────────────┤
│ dashboard│ dashboard   │ Welcome to your  │ ⚠️ Missing      │
│ .welcome │             │ dashboard        │ [Add Translation│
├──────────┼─────────────┼──────────────────┼─────────────────┤
│ fleet.   │ fleet       │ Add Vehicle      │ Ajouter un      │
│ add_veh  │             │                  │ véhicule ✓      │
└──────────┴─────────────┴──────────────────┴─────────────────┘
Progress: French 68% complete (340/500 keys translated)
```

---

## 💡 Advantages of This Approach

1. **No redeployment needed** - Edit translations in Admin Portal, changes are live immediately
2. **Consistent** - Single source of truth for all platforms
3. **Scalable** - Easy to add Spanish, German, etc. in the future
4. **Flexible** - User preference overrides usergroup default
5. **Professional** - Proper i18n standards (i18next, flutter_localizations)
6. **Auditable** - Track who changed translations and when

---

## 📚 Resources

- i18next docs: https://www.i18next.com/
- Flutter localization: https://docs.flutter.dev/development/accessibility-and-localization/internationalization
- FastAPI i18n patterns: (custom implementation)

---

## 🎯 Next Action

**START HERE:** Create database migration 049 with i18n tables and seed English data.

```bash
cd gps-tracker/backend
# Create migration file
# Run migration on dev
# Test API endpoints with Postman
```
