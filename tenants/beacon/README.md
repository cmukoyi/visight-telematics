# tenants/beacon/

Brand and infrastructure files for the **Beacon Telematics** tenant
(beacontelematics.co.uk). Mirrors `tenants/pinplot/` in shape.

**Status:** Phase 3.1 — data captured, not yet wired into a deployment
pipeline. See `MULTI_TENANT_MIGRATION.md` for roadmap.

## Source → destination mapping

`scripts/build.sh beacon` (once Phase 3.2 wires it up) will copy:

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
| `infra/docker-compose.yml` | (Phase 3.2 — special handling, see below) |

## docker-compose.yml special handling

Beacon uses `beacon_telematics_*` for container, volume and network
names (vs pinplot's `pinplot_*`). For Phase 3.1 we keep beacon's
existing compose file as a per-tenant copy. Phase 3.2 will decide
whether to:

1. Keep per-tenant compose files (simple, slight duplication), or
2. Templatise the shared `gps-tracker/docker-compose.yml` with a
   `__TENANT_PREFIX__` placeholder (DRY, slightly more magic).

Either way, beacon's existing volume `beacon_telematics_postgres_data`
**must not be renamed** — it would orphan production data. Any
templating must produce that exact volume name.

## Required env vars (server-side `backend/.env`)

See `.env.template` in this directory for the full list.
