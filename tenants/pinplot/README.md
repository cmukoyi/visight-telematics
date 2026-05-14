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

Plus, from `tenant.env`, the tenant prefix and DB defaults are
substituted into `gps-tracker/docker-compose.template.yml` to render
`gps-tracker/docker-compose.yml`.

## tenant.env

| Variable | PinPlot value | Used for |
|---|---|---|
| `TENANT_PREFIX` | `pinplot` | Container, volume, and network names |
| `TENANT_DB_USER` | `pinplot_db_user` | `POSTGRES_USER` default |
| `TENANT_DB_NAME` | `pinplot_db` | `POSTGRES_DB` default |

**CRITICAL:** PinPlot's existing production volume is
`pinplot_postgres_data`. Renaming `TENANT_PREFIX` orphans production
data. Do NOT change.

## Not included here (handled separately)

- **Runtime logo override** — `gps-tracker/customer-dashboard/tenant-assets/`
  remains the per-server drop-in path for live logo swaps. It overrides the
  build-time default shipped by this directory.
- **Mobile app theme/colors** — Phase "Future" (Flutter brand abstraction).
