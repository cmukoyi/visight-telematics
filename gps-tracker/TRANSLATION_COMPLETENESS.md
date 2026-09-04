# Dashboard Translation Completeness

## Required Completion Rule

For every active non-English language, every translation key discovered from
`customer-dashboard/public/index.html` and `qr-generator.html` must have a
non-empty value that is not an English fallback. Whitespace, HTML entities, and
casing differences do not make an English value a valid translation.

The deployment runs `app.sync_dashboard_translation_keys`. It now fails if this
rule is not true. A successful deployment is therefore the completion signal;
the percentage in the admin portal is informational only.

## Current French Result

The production check on 2026-09-04 failed: `626/899` dashboard keys are valid
French translations and `273` are missing or still English fallbacks. Do not
mark French complete until the verifier returns `899/899` with exit code `0`.

## Reported Dashboard Coverage

| Surface | Covered keys/pattern |
| --- | --- |
| Live Map marker and details | `common.active`, `map.centre_on_map`, `assets.sensor_data`, sensor labels |
| Asset List map control | `tooltips.view_on_map` |
| Movement History | `trips.found_click_route` and `currentLocale()` date formatting |
| Movement Analytics | date-range, journey, leg, stationary, and position keys |
| Hive wizard | `hive.*`, `common.step`, `common.of`, `common.continue` |
| Asset Management | `asset_mgmt.*`, `assets.*`, and `settings.save_changes` |
| Geofences and import | `geofences.*`, `floor_plan.*`, and `locations.*` |
| QR/NFC | `qr.*` and `nfc.*` |
| Settings | `settings.*`, duration options, and category keys |
| Reports and Alerts | `reports.*`, `alerts.*`, and common status keys |

Dynamic content must call `t(key, fallback)`. Inserted HTML must use
`data-i18n`, `data-i18n-placeholder`, or `data-i18n-title`; the dashboard
observer translates those markers after rendering. Dates use
`toLocaleString(currentLocale())` or `toLocaleDateString(currentLocale())`.

## Production Verification

Run the verifier after every deployment:

```sh
cd gps-tracker/backend
python scripts/verify_dashboard_translations.py --base-url https://pinplot.me --language fr
```

It exits non-zero for any missing key or English fallback. The Hive keys below
are the minimum smoke check and must have French text, not English:

For a deterministic check using a downloaded response:

```sh
curl -fsS https://pinplot.me/api/translations/fr > /tmp/pinplot-fr.json
python scripts/verify_dashboard_translations.py --language fr --translations-file /tmp/pinplot-fr.json
```

- `hive.create_new_hive`
- `hive.select_tags`
- `hive.which_tags_question`
- `hive.select_assets_help`
- `common.step`
- `common.of`
- `common.continue`

The deployment workflow additionally checks these keys directly against the
production database after the synchronizer runs.