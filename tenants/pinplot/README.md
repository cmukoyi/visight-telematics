# tenants/pinplot/

Canonical source of all PinPlot-tenant-specific assets and infra config.
`scripts/build.sh pinplot` copies the contents of this directory into the
matching `gps-tracker/` runtime locations before image build / rsync.

| Source (this dir)                              | Destination (under `gps-tracker/`)                                       |
|------------------------------------------------|--------------------------------------------------------------------------|
| `admin/logo.png`                               | `admin-portal/assets/logo.png`                                           |
| `customer/logo.png`                            | `customer-dashboard/public/assets/logo.png`                              |
| `mobile/assets/MainLogo.png`                   | `mobile-app/ble_tracker_app/assets/MainLogo.png`                         |
| `mobile/assets/FullLogowhite.png`              | `mobile-app/ble_tracker_app/assets/FullLogowhite.png`                    |
| `mobile/web/favicon.ico`                       | `mobile-app/ble_tracker_app/web/favicon.ico`                             |
| `mobile/web/favicon.png`                       | `mobile-app/ble_tracker_app/web/favicon.png`                             |
| `mobile/web/favicon-16x16.png`                 | `mobile-app/ble_tracker_app/web/favicon-16x16.png`                       |
| `mobile/web/favicon-32x32.png`                 | `mobile-app/ble_tracker_app/web/favicon-32x32.png`                       |
| `mobile/web/apple-touch-icon.png`              | `mobile-app/ble_tracker_app/web/apple-touch-icon.png`                    |
| `mobile/web/android-chrome-192x192.png`        | `mobile-app/ble_tracker_app/web/android-chrome-192x192.png`              |
| `mobile/web/android-chrome-512x512.png`        | `mobile-app/ble_tracker_app/web/android-chrome-512x512.png`              |
| `infra/nginx.conf`                             | `nginx/nginx.conf`                                                       |

## Phase 1.1 status

These files are currently **copies** of what already lives under `gps-tracker/`.
That redundancy is intentional during Phase 1.1 — it lets us prove
`scripts/build.sh pinplot` is correct (idempotent: running it must produce
zero `git diff`) before Phase 1.3 deletes the originals.

## Not included here (handled separately)

- **Runtime logo override** — `gps-tracker/customer-dashboard/tenant-assets/`
  remains the per-server drop-in path for live logo swaps. It overrides the
  build-time default shipped by this directory.
- **Docker compose tenant bits** (container names, DB defaults, FROM_EMAIL) —
  will be extracted into `tenants/pinplot/docker-compose.override.yml` in
  Phase 1.2 / 1.3, not yet.
- **Mobile app theme/colors** — Phase "Future" (Flutter brand abstraction).
