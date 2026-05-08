# tenant-assets/

Per-deployment branding assets that must NEVER be committed to git or
overwritten when this repo is synced into a sister tenant (e.g.
BeaconTelematics).

This directory is mounted as a Docker bind volume into the `customer`
container at `/app/public/tenant-assets/` and is served by nginx at
`/customer/tenant-assets/...`.

## Drop-in files

| Filename             | Used by                                                    |
|----------------------|------------------------------------------------------------|
| `logo.png`           | Customer-portal login & header (falls back to `assets/logo.png`) |
| `favicon.ico`        | Browser tab icon (optional override)                       |

## Workflow

1. SCP your tenant logo onto the production server:
   ```
   scp ./mylogo.png server:~/pinplot/gps-tracker/customer-dashboard/tenant-assets/logo.png
   ```
2. No restart needed — the file is served immediately by nginx.
3. `git pull` will not touch this directory because the contents are
   gitignored (only this README and `.gitkeep` are tracked).

## Why not commit logos?

Two tenants share the same source tree (PinPlot ⇄ BeaconTelematics).
Committed logos would clobber each other on every sync. Keeping them
out of git and inside a volume keeps each tenant's branding stable.
