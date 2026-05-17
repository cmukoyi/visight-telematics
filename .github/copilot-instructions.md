# Repository conventions for AI assistants

This file is read automatically by Copilot, Claude, Cursor, and other AI
assistants when working in this repo. Follow these rules without exception.

---

## Secrets

- **Never** write a credential literal anywhere in source code, tests, scripts,
  or documentation. Credentials include API keys, passwords, OAuth client
  secrets, JWT signing keys, database URLs, and basic-auth headers.
- **Never** use `os.getenv("X", "fallback-literal")` or
  `os.getenv("X") or "literal"` for any variable whose name contains
  `PASSWORD`, `SECRET`, `TOKEN`, `KEY`, or `AUTH`. The "fallback" pattern
  silently substitutes a literal in production when the env var is missing —
  which both ships the literal as a real credential and hides the missing
  config.
- For required secrets use one of:
  - `os.environ["VAR_NAME"]` — raises `KeyError` at startup if unset
  - `_required_env("VAR_NAME")` — the helper in
    `gps-tracker/backend/app/services/mzone_service.py` that raises a clear
    `RuntimeError` with remediation instructions
- Endpoints, URLs, ports, and other non-secret config MAY use
  `os.getenv("VAR", "default")` — defaults that are not secrets are fine.
- When asked to add an integration, ALWAYS:
  1. Add the variable to the relevant `.env.example` (placeholder value only)
  2. Document the required vars in the PR description
  3. Never echo a real credential value in commits, comments, or logs

The CI lint guard in `.github/workflows/deploy-production.yml`
(`No hardcoded secrets / env-fallback literals in backend code` step) will
block any PR that violates the above. It is intentionally narrow — backend
Python files only, excludes test files — to keep false positives at zero.

## Deployments

- Deployments are triggered by `.github/workflows/deploy-production.yml`
  on push:
  - push to `main` → deploys the **pinplot** tenant
  - push to `prod/beacon` → deploys the **beacon** tenant
- **Never** instruct the user to `git pull` on a server. All updates flow
  through the workflow.
- The two tenants live on **separate DigitalOcean droplets**:
  - Pinplot: `159.89.50.65`, repo at `/root/pinplot/`
  - Beacon: separate host, repo at `/root/beacon-telematics/`
- Tenant `.env` files are protected from rsync overwrites by Phase 4's
  `--exclude` rules — they survive deploys. Edit them directly on the server
  when adding new env vars; never commit a real `.env`.

## Tenant overlay system

- Per-tenant content lives under `tenants/<slug>/`.
- `scripts/build.sh <slug>` copies overlay files to their destinations
  (defined in the `MAP` array). Destinations MUST be gitignored — the CI
  lint guard enforces this.
- The brand-drift ratchet in the deploy workflow caps tenant-specific
  strings ("Beacon Telematics", `beacontelematics.co.uk`, beacon-specific
  hex colors) in shared code at a grandfathered count. New occurrences
  fail CI. To resolve drift, move the value to `tenants/<slug>/` and add
  the destination to `scripts/build.sh MAP`.

## Database conventions (per-tenant Postgres)

- Main tracker/device table is `ble_tags` (NOT `tags` — that table does not
  exist; common mistake).
- `tag_type` actual production values:
  - `'scope'` — MZone-fed (vehicle data from MZone OAuth API).
    `mzone_vehicle_id` is populated.
  - `'tracksolid'` — TrackSolid-fed (BLE tag devices).
  - `'series1'` / `'series2'` are model defaults that may appear in the
    Flutter app but are NOT in current production data. Always start a
    query with `SELECT tag_type, COUNT(*) FROM ble_tags GROUP BY tag_type;`
    before filtering.
- Latest location is denormalised into `ble_tags.latitude`,
  `ble_tags.longitude`, `ble_tags.last_seen`, `ble_tags.battery_level`
  (no separate locations history table is used for "current position").

## Two unrelated "Scope" code paths

This trips up new contributors regularly. They are NOT the same system:

- `app/services/mzone_service.py` — OAuth2 to `login.mzoneweb.net`. Fetches
  vehicle locations for `tag_type='scope'` rows on a 10s poll. The actually-
  important integration. Env vars: `MZONE_*`.
- `app/services/device_providers/scope_provider.py` — HTTP Basic auth to
  `scopemp.net`. Used **only** when a customer adds a new tag via the wizard
  and selects `tag_type=scope`. Env var: `SCOPE_AUTH_HEADER`.

## Feature flags

- `TENANT_DISABLED_FEATURES` env var (comma-separated list) hides features.
  Enforced in three layers in `app/routes_portal.py`: API surface (404 from
  feature-specific routes), `/api/portal/me/effective-features`, and write
  authorisation. Setting this var requires a backend restart.

## When in doubt

- Read existing patterns before inventing new ones — `tracksolid_provider.py`
  is the reference for "how a provider service should handle secrets".
- Prefer editing existing files over creating new ones.
- For multi-step changes, describe the plan in the PR description so it
  survives `git log`.
