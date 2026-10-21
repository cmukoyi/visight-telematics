# ViSight Track

Telematics platform for Teltonika devices: device events arrive on the GPRS
listener, are queued, stored and decoded by DataProfiler, and delivered per
Data Exchange to the customer dashboard.

- `gps-tracker/backend` — FastAPI backend, DataProfiler pipeline (`app/dataprofiler`)
- `gps-tracker/admin-portal` — admin portal (`/admin`)
- `gps-tracker/customer-dashboard` — customer dashboard (`/customer`)
- `tenants/visight` — deployment config, branding and nginx for track.visighttelematics.co.za
- `.github/workflows/deploy-production.yml` — deploys `main` to production
