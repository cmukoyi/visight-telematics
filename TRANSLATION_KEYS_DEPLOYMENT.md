# Translation Keys Deployment Guide

## Summary
We've added **348 translation keys** to the customer dashboard HTML across **12 categories**:

| Category    | Keys | Description |
|-------------|------|-------------|
| settings    | 77   | Settings page (passwords, appearance, alerts, email, SMS) |
| floor_plan  | 65   | Floor plan builder (toolbar, tools, properties) |
| geofences   | 46   | Geofences management (editor, bulk upload, tags) |
| auth        | 39   | Authentication (login, password reset, user management) |
| common      | 37   | Shared elements (buttons, labels, status) |
| assets      | 22   | Asset management |
| trips       | 14   | Movement history & journeys |
| general     | 15   | Miscellaneous features |
| map         | 13   | Map controls & styles |
| nav         | 11   | Navigation sidebar |
| alerts      | 7    | Alerts & notifications |
| reports     | 2    | Reports sections |

**Total: 348 keys**

---

## Deployment Steps

### Option 1: Deploy via SSH (Recommended)

```bash
# 1. Copy script to server
scp add_missing_translation_keys.py root@pinplot.me:/tmp/

# 2. SSH to server
ssh root@pinplot.me

# 3. Run script inside Docker container
docker exec -i pinplot_backend python3 /tmp/add_missing_translation_keys.py
```

### Option 2: Deploy to Beacon Server

```bash
# 1. Copy script to Beacon server
scp add_missing_translation_keys.py root@beacontelematics.co.uk:/tmp/

# 2. SSH to server
ssh root@beacontelematics.co.uk

# 3. Run script inside Docker container
docker exec -i beacon_telematics_backend python3 /tmp/add_missing_translation_keys.py
```

---

## Expected Output

```
================================================================================
Translation Keys Extraction & Database Import
================================================================================

📄 Parsing HTML file: /root/beacon-telematics/gps-tracker/customer-dashboard/public/index.html
   Found 348 unique translation keys

📊 Keys by category:
   settings          77 keys
   floor_plan        65 keys
   geofences         46 keys
   ...

💾 Adding missing keys to database...
  ✅ floor_plan.undo → Undo
  ✅ floor_plan.redo → Redo
  ✅ floor_plan.import_image → Import Image
  ...
  ⏭️  common.save (already exists)
  ⏭️  common.cancel (already exists)

================================================================================
✅ Complete! Added 273 new keys, skipped 75 existing keys
================================================================================

🌐 Next steps:
   1. Go to https://pinplot.me/admin/index.html#translations
   2. Click the refresh icon to see new keys
   3. Use 'Auto-translate All' to translate missing French keys
   4. Or manually translate keys one by one
```

---

## Using the Admin Portal for Translation

### Step 1: Access Translation Manager
1. Go to **https://pinplot.me/admin/index.html**
2. Sign in with admin credentials
3. Click **Translations** tab in the sidebar

### Step 2: Refresh to See New Keys
1. Click the **refresh icon** (🔄) in the top right
2. You should see ~273 new keys with **No translations** status

### Step 3: Auto-Translate Missing Keys (Recommended)
1. Click **Auto-translate All** button
2. System will use LibreTranslate (free) to auto-translate all missing French keys
3. Wait for completion (~2-3 minutes for 273 keys)
4. Review and refine translations as needed

### Step 4: Manual Translation (Alternative)
1. Filter by language: **French**
2. Filter by status: **No translations**
3. Click **Edit** on any key
4. Enter French translation
5. Click **Save**
6. Repeat for each key

### Step 5: Verify on Customer Portal
1. Go to **https://pinplot.me/customer/index.html**
2. Sign in
3. Click **account menu** → **Light maps** to switch language to **Français**
4. Navigate through:
   - Settings (all sections should be French)
   - Geofences (title, editor, bulk upload modal)
   - Floor Plans (toolbar, tools, properties)
   - Navigation sidebar
   - Map controls

---

## Key Translation Examples

### High Priority Keys (Verify These First)

```
floor_plan.floor_plan_builder  → "Constructeur de Plan d'Étage"
floor_plan.undo                → "Annuler"
floor_plan.redo                → "Rétablir"
floor_plan.publish             → "Publier"

geofences.new_geofence         → "Nouvelle Géozone"
geofences.bulk_upload_locations → "Téléchargement en masse"
geofences.drag_drop_csv        → "Glisser-déposer fichier CSV ou Excel"

settings.sms_alerts            → "Alertes SMS"
settings.mobile_number         → "Numéro de mobile"
settings.appearance            → "Apparence"
settings.data_retention        → "Conservation des données"

common.save                    → "Enregistrer"
common.cancel                  → "Annuler"
common.import                  → "Importer"
common.export                  → "Exporter"
```

---

## Troubleshooting

### Script fails with "File not found"
- The script tries multiple paths automatically
- Ensure you're running inside the Docker container:
  ```bash
  docker exec -i pinplot_backend python3 /tmp/add_missing_translation_keys.py
  ```

### Database connection error
- Script uses environment variable `DATABASE_URL` from Docker container
- No manual configuration needed when run inside container

### Keys already exist
- Script will skip existing keys with `⏭️` marker
- Only new keys are added
- Safe to run multiple times

### Auto-translate button missing
- Ensure you're on the **Translations** tab in admin portal
- Button appears at top right: **Auto-translate All**
- If missing, check `/api/admin/i18n/translate` endpoint exists

---

## Rollback (If Needed)

If you need to remove the newly added keys:

```sql
-- Connect to database
docker exec -i pinplot_backend psql -U pinplot_user -d pinplot_db

-- Delete keys added after a certain date (adjust date as needed)
DELETE FROM translation_keys 
WHERE created_at > '2026-08-05 00:00:00';

-- Verify deletion
SELECT category, COUNT(*) 
FROM translation_keys 
GROUP BY category 
ORDER BY category;
```

---

## Next Steps After Translation

Once French translations are complete:

1. **Test thoroughly** on customer portal with French language
2. **Push to production** (both pinplot.me and beacontelematics.co.uk)
3. **Add Dutch translations** using the same Admin Portal workflow
4. **Continue adding i18n markup** to remaining sections:
   - Tables & Data Display (~40 elements)
   - Asset Management (~30 elements)
   - Reports (~25 elements)
   - Modals & Forms (~80 elements)
