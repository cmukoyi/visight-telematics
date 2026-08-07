# tenants/beacon/

Brand and infrastructure files for the **Beacon Telematics** tenant
(beacontelematics.co.uk). Mirrors `tenants/pinplot/` in shape.

## Source → destination mapping

`scripts/build.sh beacon` copies these files into `gps-tracker/`:

| Tenant source | gps-tracker destination |
|---|---|
| `admin/logo.png` | `admin-portal/assets/logo.png` |
| `customer/logo.png` | `customer-dashboard/public/assets/logo.png` |
| `mobile/assets/MainLogo.png` | `mobile-app/ble_tracker_app/assets/MainLogo.png` |
| `mobile/assets/FullLogowhite.png` | `mobile-app/ble_tracker_app/assets/FullLogowhite.png` |
| `mobile/web/favicon.ico` | `mobile-app/ble_tracker_app/web/favicon.ico` |
| `mobile/web/favicon.png` | `mobile-app/ble_tracker_app/web/favicon.png` |
| `mobile/web/favicon-16x16.png` | `mobile-app/ble_tracker_app/web/favicon-16x16.png` |
| `mobile/web/favicon-32x32.png` | `mobile-app/ble_tracker_app/web/favicon-32x32.png` |
| `mobile/web/apple-touch-icon.png` | `mobile-app/ble_tracker_app/web/apple-touch-icon.png` |
| `mobile/web/android-chrome-192x192.png` | `mobile-app/ble_tracker_app/web/android-chrome-192x192.png` |
| `mobile/web/android-chrome-512x512.png` | `mobile-app/ble_tracker_app/web/android-chrome-512x512.png` |
| `infra/nginx.conf` | `nginx/nginx.conf` |

Plus, from `tenant.env`, the tenant prefix and DB defaults are
substituted into `gps-tracker/docker-compose.template.yml` to render
`gps-tracker/docker-compose.yml`.

## tenant.env

| Variable | Beacon value | Used for |
|---|---|---|
| `TENANT_PREFIX` | `beacon_telematics` | Container, volume, and network names |
| `TENANT_DB_USER` | `beacon_user` | `POSTGRES_USER` default |
| `TENANT_DB_NAME` | `beacon_telematics` | `POSTGRES_DB` default |

**CRITICAL:** beacon's existing production volume is
`beacon_telematics_postgres_data`. Renaming `TENANT_PREFIX` orphans
production data. Do NOT change.

## Required env vars (server-side `backend/.env`)

See `.env.template` in this directory for the full list. Real values
are set manually on beacon's DigitalOcean box and are never written by
the deploy pipeline.

