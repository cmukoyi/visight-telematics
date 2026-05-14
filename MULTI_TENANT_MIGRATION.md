# Multi-Tenant Migration Plan

> **Goal:** consolidate the PinPlot-HPS and beaconTelematics repos into a single
> trunk-based monorepo where tenant branding, infra and assets are isolated
> data — not interleaved code. Enables safe staging-on-pinplot,
> cherry-pick-to-prod-on-beacon workflows.

**Status:** ☐ Not started · 🚧 In progress · ✅ Done · ⏭ Skipped

---

## Why we are doing this

Today PinPlot-HPS and beaconTelematics are two independent repos with overlapping
code. Branding, nginx config and tenant defaults are mixed inside otherwise-shared
files (notably `customer-dashboard/public/index.html` and
`admin-portal/index.html`). Every shared change requires manual file porting,
which:

- causes drift (e.g. role='admin' UI fix had to be made and committed twice)
- risks branding mix-ups
- has no audit trail showing which features made it to prod
- scales badly to a 3rd / 4th tenant

## Target architecture

Single repo, tenants as data, branches per environment.

```
PinPlot-HPS/
├── gps-tracker/                   ← shared code, byte-identical for every tenant
│   ├── backend/
│   ├── customer-dashboard/public/
│   ├── admin-portal/
│   ├── mqtt-bridge/
│   └── mobile-app/
├── tenants/
│   ├── pinplot/                   ← staging tenant
│   │   ├── branding.json          # name, colors, support email, MapTiler key
│   │   ├── customer-logo.png
│   │   ├── admin-logo.png
│   │   ├── favicon.ico
│   │   ├── nginx.conf             # domain, certs, CSP
│   │   ├── docker-compose.override.yml  # container names, volumes, ports
│   │   ├── .env.template
│   │   └── mobile/                # theme.dart, environment.dart, assets/
│   └── beacon/                    ← prod tenant (same shape)
├── scripts/
│   ├── build.sh <tenant>          # assembles a tenant-specific build
│   └── deploy.sh <tenant>
└── .github/workflows/
    ├── deploy-pinplot.yml         # push to main → staging
    └── deploy-beacon.yml          # push to prod/beacon → prod
```

## Workflow once migrated

1. New feature → branch off `main` → PR → merge to `main` → auto-deploys to
   pinplot.me (staging).
2. Test on staging.
3. Promote to prod:
   ```
   git checkout prod/beacon
   git cherry-pick <sha>
   git push
   ```
   → auto-deploys to beacontelematics.co.uk.
4. Beacon-only branding tweak: edit `tenants/beacon/branding.json` on
   `prod/beacon`, push.
5. Hotfix on prod: branch off `prod/beacon`, fix, merge to `prod/beacon`, then
   cherry-pick **back** to `main` so staging stays current.

---

## Phase 0 — Pre-work hygiene

These are independent of the migration but should be done first.

- [ ] Add `.env`, `*.log`, `*.db` to `.gitignore` in both repos
- [ ] `git rm --cached` the tracked `.env` files in beaconTelematics
      (`gps-tracker/.env`, `gps-tracker/backend/.env`)
- [ ] **Rotate** the leaked DB password (was exposed in `gps-tracker/backend/.env`
      → `M8SxcyZctkgyJ8Ns`) — change in DB, env, secrets manager
- [ ] Add Flutter build artefacts to `.gitignore`:
      `.dart_tool/`, `.flutter-plugins-dependencies`, `.idea/`, `build/`,
      `android/.gradle/`, `android/.kotlin/`, `android/build/`,
      `android/app/src/main/java/`, `android/local.properties`,
      `android/gradle/wrapper/gradle-wrapper.jar`, `*.iml`,
      `ios/Flutter/{Generated.xcconfig,ephemeral,flutter_export_environment.sh}`,
      `ios/Runner/GeneratedPluginRegistrant.{h,m}`,
      `linux/flutter/ephemeral`, `macos/Flutter/ephemeral`,
      `windows/flutter/ephemeral`
- [ ] Untrack the build artefacts already committed to beaconTelematics
- [ ] Decide canonical home for `EMAIL_VERIFICATION_README.md` and
      `GEOFENCE_MOCK_TESTING.md` (currently only in beacon)

---

## Phase 1 — Make PinPlot a tenant of itself

Goal: prove the tenant-extraction model works **without changing any runtime
behavior**.

- [ ] Create `tenants/pinplot/` directory
- [ ] Move `gps-tracker/admin-portal/assets/logo.png` → `tenants/pinplot/admin-logo.png`
- [ ] Move `gps-tracker/customer-dashboard/public/assets/logo.png` → `tenants/pinplot/customer-logo.png`
- [ ] Move mobile app brand assets (`MainLogo.png`, `FullLogowhite.png`,
      `web/favicon.ico`, `web/android-chrome-*.png`, `web/apple-touch-icon.png`)
      → `tenants/pinplot/mobile/assets/`
- [ ] Move `gps-tracker/nginx/nginx.conf` → `tenants/pinplot/nginx.conf`
- [ ] Extract pinplot-specific bits of `gps-tracker/docker-compose.yml`
      (container names, DB defaults, volumes, network names, FROM_EMAIL)
      into `tenants/pinplot/docker-compose.override.yml`
- [ ] Write `scripts/build.sh <tenant>` that copies/symlinks the tenant's
      files into the right runtime locations before `docker compose build`
- [ ] Update GitHub deploy workflow to call `scripts/build.sh pinplot`
- [ ] Verify pinplot.me deploy still works **byte-identical** to today
- [ ] Commit + tag as `phase-1-pinplot-self-tenant`

**Exit criteria:** pinplot.me runs from the new tenant layout with zero
visible/functional change.

---

## Phase 2 — Backport beacon's safe additions, eliminate brand strings from shared HTML

Goal: shared HTML files become byte-identical regardless of tenant.

### Shared customer dashboard (`customer-dashboard/public/index.html`)
- [ ] Add favicon `<link>` tags (already in beacon) to PinPlot — harmless,
      pinplot serves its own `/favicon.ico`
- [ ] Add `_ppRefreshAllBasemaps()` invocation inside `_ppApplyBrand`
- [ ] Add `window._ppRefreshAllBasemaps = _ppRefreshAllBasemaps` export

### Shared admin portal (`admin-portal/index.html`)
- [ ] Backport `/api/branding` bootstrap script
- [ ] Wrap default brand strings with `<span data-brand="product">…</span>`
- [ ] Add favicon links + tenant-assets logo fallback

### Branding plumbing
- [ ] Define `tenants/<slug>/branding.json` schema
      (`name`, `product`, `support_email`, `theme_primary`, `maptiler_key`,
      `default_logo_url`, …)
- [ ] Backend `/api/branding` reads from the active tenant's `branding.json`
      (env var `TENANT_SLUG=pinplot|beacon` selects which file)
- [ ] Verify both portals render correctly when `/api/branding` returns the
      pinplot defaults

### Verify shared files now identical between tenants
- [ ] `diff` of customer/admin HTML between tenants returns 0 lines
- [ ] Commit + tag as `phase-2-shared-html-identical`

**Exit criteria:** every file under `gps-tracker/` is byte-identical for any
tenant. All differences live under `tenants/<slug>/`.

---

## Phase 3 — Onboard Beacon as a second tenant

- [ ] Create `tenants/beacon/` directory
- [ ] Copy beacon's brand assets in from beaconTelematics repo
      (logos, favicons, mobile app assets)
- [ ] Copy beacon's `nginx.conf` (domain, certs, CSP)
- [ ] Create `tenants/beacon/docker-compose.override.yml` (container names,
      volumes, network, FROM_EMAIL)
- [ ] Create `tenants/beacon/branding.json` matching current beacon look
- [ ] Create `tenants/beacon/.env.template` (no secrets — secrets stay in
      GitHub Actions / server env)
- [ ] Create `prod/beacon` branch from `main`
- [ ] Add `.github/workflows/deploy-beacon.yml` triggered on push to `prod/beacon`
- [ ] **First deploy goes to a staging URL** (e.g. `beacon-staging.pinplot.me`)
      to validate parity with current beacontelematics.co.uk
- [ ] Manual parity check: visual diff of customer + admin portals,
      smoke test login + add tag + add geofence
- [ ] Cut DNS / load-balancer over from old beaconTelematics deploy to new
      pipeline (run both in parallel briefly if possible)
- [ ] Monitor for 48h, confirm no regressions
- [ ] Archive (don't delete) the `beaconTelematics` repo with README pointing
      at PinPlot-HPS / `prod/beacon`
- [ ] Commit + tag as `phase-3-beacon-onboarded`

**Exit criteria:** beacontelematics.co.uk is served from PinPlot-HPS
`prod/beacon` branch.

---

## Phase 4 — Adopt the workflow

- [ ] Document the cherry-pick promotion process in `CONTRIBUTING.md`
- [ ] Add a `git alias` snippet for `promote-to-beacon`:
      ```
      git config --global alias.promote-to-beacon \
        '!f(){ git checkout prod/beacon && git cherry-pick "$1" && git push; }; f'
      ```
- [ ] Branch protection on `prod/beacon`: require linear history,
      no force-push
- [ ] First real feature flow end-to-end:
      branch → PR → merge to main → staging deploy → cherry-pick to prod/beacon
      → prod deploy → ✅
- [ ] Retro: any pain points? adjust scripts before they harden

---

## Future phases (not blocking)

- [ ] Mobile app: introduce `--dart-define=BRAND=pinplot|beacon` and move
      `lib/theme/app_theme.dart`, `lib/config/environment.dart`,
      `lib/main.dart` brand bits behind a `Brand` abstraction reading from
      `tenants/<slug>/mobile/`
- [ ] Add a 3rd tenant as a smoke test of the model
- [ ] Per-tenant feature flags (some tenants might disable e.g. `hive`) —
      already partially supported by `TENANT_DISABLED_FEATURES` env var
- [ ] Extract DB migration safety per tenant (each tenant has its own
      Postgres → migrations run per-tenant on deploy)

---

## Risks & mitigations

| Risk | Mitigation |
|---|---|
| Prod outage during Phase 3 cutover | Run new pipeline to staging URL first, parity-test, then DNS swap with old pipeline still warm |
| Build script bug copies wrong tenant assets | Build script writes a `BUILD_TENANT.txt` marker into the image; deploy workflow asserts it matches expected before promoting |
| Drift between `main` and `prod/beacon` builds up | Weekly reminder to cherry-pick; later, GitHub Action that opens an issue listing un-cherry-picked commits |
| Beacon-only hotfix forgotten on main | Pre-merge check on `prod/beacon` requires a linked main commit; or use `git cherry` to detect orphan commits |
| Existing committed secrets in `.env` | Phase 0 covers rotation — must be done **before** repo consolidation makes them more discoverable |

---

## Decision log

| Date | Decision | Rationale |
|---|---|---|
| 2026-05-14 | Adopt monorepo + tenants/ + branches model | Manual two-repo sync is unsustainable; cherry-pick gives natural staging→prod gate |
| 2026-05-14 | Keep PinPlot-HPS as canonical repo | All active dev happens here; archive beaconTelematics post-cutover |
| 2026-05-14 | `prod/beacon` is a long-lived branch, not a tag | Allows hotfixes; tags can be cut from it for releases |

---

## Quick reference

**Where things live (target state):**

| Need | Location |
|---|---|
| Add a feature | `gps-tracker/**` (any branch), merge to `main` |
| Change beacon's logo | `tenants/beacon/customer-logo.png` on `prod/beacon` |
| Change beacon's domain | `tenants/beacon/nginx.conf` on `prod/beacon` |
| Add a new tenant | New `tenants/<slug>/` + new deploy workflow |
| Rotate beacon DB password | Server env / GitHub Actions secret — **never** in repo |

