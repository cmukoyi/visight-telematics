# BeaconTelematics Deployment Guide - Critical Rules Edition

**Last Updated:** March 17, 2026  
**Issue:** 8+ hour production outage (March 17, 2026)  
**Root Cause:** Flutter builds in Docker with incompatible Dart version  
**Status:** ✅ FIXED - Site now online  

---

## 🚨 6 CRITICAL RULES (Never Break These)

These rules prevent the 8-hour outage from happening again.

### Rule 1: Flutter Builds in GitHub Actions, NOT Docker
**Outage Cause:** Docker tried `cirrusci/flutter:latest` (Dart 2.19.4 from 2023). Modern flutter_lints require Dart 3.5+. Build failed repeatedly.

**What You Must Do:**
- ✅ GitHub Actions builds Flutter locally with modern environment
- ✅ rsync pre-built artifacts to server (`/build/web/` folder)
- ✅ Dockerfile only serves files via nginx

**What You Must NOT Do:**
- ❌ Add `RUN flutter pub get` in Dockerfile
- ❌ Add `RUN flutter build web` in Dockerfile
- ❌ Use Docker base images with pre-installed Flutter/Dart
- ❌ Rely on Docker to compile Flutter

**Check Your Dockerfile:**
```dockerfile
# ❌ WRONG - Never do this:
FROM cirrusci/flutter:latest as builder
RUN flutter pub get && flutter build web

# ✅ CORRECT - Only serve pre-built:
FROM nginx:alpine
COPY ble_tracker_app/build/web /usr/share/nginx/html
```

---

### Rule 2: No Hardcoded Secrets in docker-compose.yml
**Outage Cause:** Line had `MZONE_CLIENT_SECRET=g_SkQ.B.z3TeBU$$g#hVeP#c2`. Docker saw `$$g` and tried expanding `${g}`, causing warnings and variable injection risks.

**What You Must Do:**
- ✅ Load all secrets from `.env` files via `env_file:`
- ✅ Use only `env_file: ./backend/.env` in docker-compose
- ✅ Store real secrets ONLY in `.env` (add to .gitignore)

**What You Must NOT Do:**
- ❌ Hardcode secrets in docker-compose.yml
- ❌ Use `$$` or `${}` in secret values
- ❌ Put same secret in both `env_file` AND `environment`

**Correct Pattern:**
```yaml
# ✅ CORRECT
backend:
  env_file:
    - ./backend/.env
  # NO environment: section with secrets!

# ❌ WRONG - Never do this:
backend:
  environment:
    - MZONE_CLIENT_SECRET=g_SkQ.B.z3TeBU$$g#hVeP#c2
```

---

### Rule 3: SDK Constraints Must Match Build Environment
**Outage Cause:** `pubspec.yaml` said `sdk: ^3.11.0` but Pub in Docker got Dart 2.19.4. Mismatch = build failure.

**What You Must Do:**
- ✅ Use realistic constraint: `sdk: '^3.5.0'`
- ✅ Match GitHub Actions environment (Flutter 3.41.2+ = Dart 3.5+)
- ✅ Test SDK-related changes locally before committing

**What You Must NOT Do:**
- ❌ Use overly permissive ranges like `>=2.17.0 <4.0.0`
- ❌ Pin to versions you don't understand
- ❌ Ignore dependency resolution warnings

**In pubspec.yaml:**
```yaml
# ✅ CORRECT
environment:
  sdk: '^3.5.0'  # Specific and realistic

dev_dependencies:
  flutter_lints: ^6.0.0  # Also Dart 3.5+ compatible
```

---

### Rule 4: Always Use `--no-cache --pull` in Docker
**Outage Cause:** Server cached old `cirrusci/flutter:latest` image. Running `docker compose build` reused cached layers instead of pulling fresh.

**What You Must Do:**
- ✅ Use `docker compose build --no-cache --pull`
- ✅ Every GitHub Actions deployment forces fresh images
- ✅ Never assume base images are up-to-date

**What You Must NOT Do:**
- ❌ Use `docker compose build` without flags
- ❌ Rely on automatic updates (there are none)
- ❌ Trust image caching for new deployments

**In GitHub Actions Workflow:**
```yaml
- name: Build all containers
  run: |
    cd ~/beacon-telematics/gps-tracker
    docker compose build --no-cache --pull --progress=plain
```

---

### Rule 5: Verify Artifacts Exist Before and After Syncing
**Outage Cause:** Flutter built `/build/web/` locally. rsync excluded it silently. Docker looked for files that weren't there.

**What You Must Do:**
- ✅ Verify build artifacts exist after GitHub Actions build
- ✅ Verify they synced to server before Docker runs
- ✅ Log file counts to catch silent failures

**What You Must NOT Do:**
- ❌ Assume rsync succeeded without checking
- ❌ Skip verification steps in deployment
- ❌ Ignore rsync output/errors

**Verification Script:**
```bash
# After building locally
[ -d "gps-tracker/mobile-app/ble_tracker_app/build/web" ] || {
  echo "ERROR: Build artifacts missing!"; exit 1
}
FILE_COUNT=$(find build/web -type f | wc -l)
[ $FILE_COUNT -gt 0 ] || { echo "ERROR: No files in build/web"; exit 1; }
echo "✅ Found $FILE_COUNT build artifacts"

# After syncing to server
ssh root@server "[ -d ~/beacon-telematics/gps-tracker/mobile-app/ble_tracker_app/build/web ] || { echo 'ERROR: rsync failed'; exit 1; }"
echo "✅ Artifacts synced successfully"
```

---

### Rule 6: rsync Must Explicitly Include Build Artifacts
**Outage Cause:** Default exclude rules were too broad. `build/web/` wasn't in include list, so rsync skipped it.

**What You Must Do:**
- ✅ Explicitly INCLUDE generated artifacts BEFORE general excludes
- ✅ Order matters: includes first, then excludes
- ✅ Test with `--dry-run` before running for real

**What You Must NOT Do:**
- ❌ Use only exclusion rules (too restrictive)
- ❌ Assume generated folders sync automatically
- ❌ Run rsync without dry-run first

**Correct rsync Pattern:**
```bash
rsync -avz --delete \
  --include 'mobile-app/ble_tracker_app/build/web/***' \
  --include 'mobile-app/ble_tracker_app/build/' \
  --exclude '.git' \
  --exclude 'node_modules' \
  --exclude '__pycache__' \
  ./gps-tracker/ root@server:~/beacon-telematics/gps-tracker/

# Test first with --dry-run
rsync --dry-run -avz ... (add all flags from above)
```

---

### Rule 7: Correct Nginx Caching Strategy (CRITICAL for UI updates to appear)
**March 17 P.M. Issue:** "I made changes but can't see them even after deployment!" - Users reporting UI changes not appearing in browser.

**Root Cause:** The nginx config in `mobile-app/Dockerfile` was caching `index.html` for 1 HOUR: `Cache-Control: public, max-age=3600`. Browser served old HTML referencing old JavaScript forever.

**The Solution: Different cache strategies by file type:**

| File Type | max-age | Reason | Header |
|-----------|---------|--------|--------|
| `index.html` | 0 (never) | HTML must always be fresh, it references JS bundles | `no-cache, no-store, must-revalidate` |
| `main.dart.js`, `*.js`, `*.css` | 1 year | Safe because filenames include content hash | `public, immutable, max-age=31536000` |
| `flutter_service_worker.js` | 0 (never) | Service worker must check for updates | `no-cache, no-store, must-revalidate` |
| Fonts, images (`.woff2`, `.png`, etc) | 1 year | Safe - rarely change | `public, max-age=31536000, immutable` |

**What You Must Do:**
- ✅ HTML files: `Cache-Control: no-cache, no-store, must-revalidate`
- ✅ Hashed bundles (`.js`, `.css`): `Cache-Control: public, immutable, max-age=31536000`
- ✅ Service worker: `Cache-Control: no-cache, no-store, must-revalidate`
- ✅ Always set `Pragma: no-cache` and `Expires: 0` for non-cached resources

**What You Must NOT Do:**
- ❌ Use `max-age=3600` on root location (catches HTML!)
- ❌ Cache `index.html` for any duration
- ❌ Use `public, max-age=*` on HTML
- ❌ Skip the service worker no-cache directive

**Correct Dockerfile Config:**
```dockerfile
# HTML: NO CACHE
location ~ ^/.*\.html$ {
    add_header Cache-Control "no-cache, no-store, must-revalidate";
    add_header Pragma "no-cache";
    add_header Expires "0";
}

# Hashed bundles: 1 YEAR CACHE (safe due to hash in filename)
location ~ \.(js|css)$ {
    add_header Cache-Control "public, immutable, max-age=31536000";
}

# Service worker: NO CACHE
location /flutter_service_worker.js {
    add_header Cache-Control "no-cache, no-store, must-revalidate";
    add_header Pragma "no-cache";
    add_header Expires "0";
}

# SPA fallback: NO CACHE (falls back to index.html)
location / {
    try_files $uri $uri/ /index.html;
    add_header Cache-Control "no-cache, no-store, must-revalidate";
}
```

**User Workaround (if they still see old version after deployment):**
1. Hard refresh: `Ctrl + Shift + R` (Windows) or `Cmd + Shift + R` (Mac)
2. Or DevTools → Network tab → right-click refresh → check "Disable cache" → reload

---

## ✅ Pre-Deployment Checklist

**Run these before pushing to main:**

```bash
# 1. Check Dockerfile has NO Flutter build commands
grep -r "flutter pub get\|flutter build" gps-tracker/mobile-app/Dockerfile
# ^ Should output NOTHING

# 2. Check docker-compose has NO hardcoded secrets
grep "MZONE_CLIENT_SECRET=" gps-tracker/docker-compose.yml
# ^ Should output NOTHING (only env_file:)

# 3. Check SDK constraints are realistic
grep "sdk:" gps-tracker/mobile-app/ble_tracker_app/pubspec.yaml
# ^ Should show: sdk: '^3.5.0' (not ^3.11.0 or >=2.17.0)

# 4. Check backend section uses env_file
grep -A 3 "backend:" gps-tracker/docker-compose.yml | grep -E "env_file|environment"
# ^ Should show "env_file:" NOT hardcoded secrets

# 5. Run backend tests locally
cd gps-tracker/backend && pytest tests/ -v
# ^ All tests must PASS
```

---

## 🚀 Deployment Flow (What Actually Happens)

```
┌─────────────────────────────────────────┐
│ Developer: git push to main             │
└────────────────┬────────────────────────┘
                 ↓
┌──────────────────────────────────────────┐
│ GitHub Actions Triggered:                │
│ .github/workflows/deploy-production.yml  │
├──────────────────────────────────────────┤
│ 1. Checkout code                         │
│ 2. Run backend tests (pytest)            │
│ 3. Build Flutter locally                 │
│    ├─ flutter pub get                    │
│    └─ flutter build web --release        │
│ 4. VERIFY: Find /build/web files ✅     │
│ 5. Rsync to server with includes:        │
│    ├─ Include mobile-app/...build/web/  │
│    └─ Include mobile-app/...build/      │
│ 6. VERIFY: Check on server files ✅     │
└────────────────┬────────────────────────┘
                 ↓
┌──────────────────────────────────────────┐
│ ON SERVER (161.35.38.209):               │
│ gps-tracker/docker-compose.yml executes: │
├──────────────────────────────────────────┤
│ 1. docker compose build --no-cache       │
│    ├─ Backend: python app                │
│    ├─ Flutter: serves /build/web         │
│    ├─ Database: postgres                 │
│    └─ Nginx: proxies requests            │
│                                          │
│ 2. docker compose up -d                  │
│                                          │
│ 3. Wait for database health (30s)        │
│                                          │
│ 4. Run database migrations               │
│                                          │
│ 5. Start nginx (reverse proxy)           │
└────────────────┬────────────────────────┘
                 ↓
         ✅ SITE ONLINE
      https://beacontelematics.co.uk
```

---

## 🔧 Emergency Troubleshooting

### Symptom: "Failed to load resource: net::ERR_CONNECTION_TIMED_OUT"

```bash
# 1. SSH to server
ssh root@161.35.38.209

# 2. Check all containers running
cd beacon-telematics/gps-tracker
docker compose ps
# Should show: backend, db, nginx, flutter-web all "Up"

# 3. Check backend is responding
docker compose logs --tail=50 backend | grep -i "error\|failed"

# 4. Check nginx is proxying
docker compose logs --tail=20 nginx | grep -i "error\|upstream"

# 5. Verify database is healthy
docker compose exec db pg_isready -U beacon_user
# Should output: accepting connections

# If database is not ready:
docker compose logs --tail=30 db
```

### Symptom: "Flutter page loads but login still fails"

```bash
# 1. Verify Flutter artifacts exist
ls -lh ~/beacon-telematics/gps-tracker/mobile-app/ble_tracker_app/build/web/main.dart.js
# Should show a file with size > 1MB

# 2. Check nginx is serving them
docker compose exec flutter-web ls /usr/share/nginx/html/ | head

# 3. Test backend API directly
curl -s http://backend:8000/health
# Should return JSON response

# 4. Check backend logs for auth errors
docker compose logs --tail=50 backend | grep -i "auth\|login"
```

### Symptom: "Docker build fails with Dart/SDK error"

```bash
# 1. Check Dockerfile is correct
cat gps-tracker/mobile-app/Dockerfile | head -10
# Should show: FROM nginx:alpine
# Should NOT show: FROM cirrusci/flutter or FROM ghcr.io/cirruslabs

# 2. Verify /build/web synced correctly
find ~/beacon-telematics/gps-tracker/mobile-app/ble_tracker_app/build/web -type f | wc -l
# Should be > 100

# 3. Check GitHub Actions deployment log
# Visit: https://github.com/cmukoyi/beaconTelematics/actions
# Look for "✅ Found X files in build/web"
# Look for "Artifacts synced" message
```

---

## 📊 What Files Changed (Breaking Down the Fix)

### Fixed Files:

1. **`.github/workflows/deploy-production.yml`**
   - Added verification: check build artifacts exist after Flutter build
   - Added verification: check artifacts synced to server
   - Updated rsync to explicitly include `/build/web/` directory

2. **`gps-tracker/mobile-app/Dockerfile`**
   - REMOVED: Multi-stage build with Flutter compilation
   - CHANGED: Now simple nginx serving pre-built artifacts
   - REMOVED: All flutter/dart SDK references

3. **`gps-tracker/docker-compose.yml`**
   - REMOVED: Hardcoded `MZONE_CLIENT_SECRET` from backend environment
   - VERIFIED: Uses only `env_file: ./backend/.env` for secrets

4. **`gps-tracker/mobile-app/ble_tracker_app/pubspec.yaml`**
   - UPDATED: `sdk: '^3.5.0'` (from broken constraints)
   - VERIFIED: `flutter_lints: ^6.0.0` compatible with Dart 3.5+

---

## 🎯 Success Criteria

After deployment, verify ALL of these:

- ✅ Site loads at https://beacontelematics.co.uk
- ✅ Login page appears (no 404 or timeout)
- ✅ Can login with valid credentials
- ✅ No "ERR_CONNECTION_TIMED_OUT" errors
- ✅ No console errors in browser (F12)
- ✅ All containers running: `docker compose ps`
- ✅ Database is healthy: `pg_isready` works
- ✅ Backend responding: `curl http://backend:8000/health`

---

## 📝 Timeline of the Outage (What Happened)

| Time | Event |
|------|-------|
| T+0 | Code deployed, site goes down |
| T+1h | Found hardcoded secret with `$$g` causing variable expansion |
| T+2h | Removed hardcoded secret, but Flutter build still fails |
| T+3h | Reverted to "working" commit, but it also fails |
| T+4h | Discovered: commit had `sdk: ^3.11.0` but Docker has Dart 2.19.4 |
| T+5h | Changed SDK to `>=2.17.0 <4.0.0`, downgraded flutter_lints to ^5.0.0 |
| T+6h | STILL FAILED: flutter_lints ^5.0.0 requires Dart ^3.5.0 |
| T+7h | Downgraded flutter_lints to ^4.0.0, same problem persists |
| T+8h | **BREAKTHROUGH**: Docker was building Flutter! Moved builds to GitHub Actions |
|  | Changed Dockerfile to just serve pre-built artifacts |
|  | ✅ **Site came back online** |

**Root Cause:** Dark 2.19.4 in old Docker image is incompatible with modern Flutter. Building should happen in CI/CD with proper tools, not in Docker.

---

## 🗝️ Key Learnings

1. **Don't build in Docker what should be built in CI/CD**
   - Flutter/Dart builds are complex and environment-sensitive
   - GitHub Actions has proper tooling, Docker doesn't
   - Always move builds out of Docker to CI/CD when possible

2. **Never hardcode secrets, period**
   - Use `.env` files and `env_file:` in docker-compose
   - Never use `${}` or `$$` in secret values
   - Secrets = `.env` (gitignored), not docker-compose.yml

3. **Pre-built artifacts need explicit rsync rules**
   - Generated files won't sync without explicit includes
   - Order matters: includes BEFORE excludes
   - Always verify artifacts before and after sync

4. **Force fresh Docker builds**
   - `docker compose build --no-cache --pull` every deployment
   - Don't trust cached base images
   - Images can get stale without notice

5. **Verify at every step**
   - After building = check artifacts exist
   - After syncing = check artifacts on server
   - After deploying = test the site works
   - Silent failures are the worst

---

**Cost of This Outage:** 8 hours of downtime  
**Cost to Prevent:** Following 6 rules  
**Worth It:** Absolutely  

Never again. ✅
