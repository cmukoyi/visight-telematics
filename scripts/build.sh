#!/usr/bin/env bash
# scripts/build.sh — assemble a tenant's runtime tree under gps-tracker/
#
# Usage:  bash scripts/build.sh <tenant>
#
# Example: bash scripts/build.sh pinplot
#
# Copies every file under tenants/<tenant>/ into its matching destination
# under gps-tracker/ (see tenants/<tenant>/README.md for the mapping).
# Idempotent: running it twice produces zero diff. Safe to run before any
# `docker compose build` or rsync to the deploy host.
#
# Load-bearing as of Phase 1.3: the destination paths are gitignored under
# gps-tracker/.gitignore, so the assembled files exist ONLY after this
# script runs (locally for dev, on the CI runner for production deploys).

set -euo pipefail

TENANT="${1:-}"
if [[ -z "$TENANT" ]]; then
  echo "usage: $0 <tenant>" >&2
  exit 2
fi

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SRC="$REPO_ROOT/tenants/$TENANT"
DST="$REPO_ROOT/gps-tracker"

if [[ ! -d "$SRC" ]]; then
  echo "❌ tenant directory not found: $SRC" >&2
  exit 1
fi

echo "→ assembling tenant: $TENANT"
echo "  src: $SRC"
echo "  dst: $DST"

# (src_relative_to_$SRC,  dst_relative_to_$DST) pairs
MAP=(
  "admin/logo.png:admin-portal/assets/logo.png"
  "customer/logo.png:customer-dashboard/public/assets/logo.png"
  "customer/help/HIVE_User_Manual.html:customer-dashboard/public/help/HIVE_User_Manual.html"
  "customer/help/QR_NFC_Guide_Pinplot.html:customer-dashboard/public/help/QR_NFC_Guide_Pinplot.html"
  "customer/help/QR_NFC_Guide_Beacon.html:customer-dashboard/public/help/QR_NFC_Guide_Beacon.html"
  "customer/help/Movement_Analytics_User_Manual_v2_1_Pinplot.html:customer-dashboard/public/help/Movement_Analytics_User_Manual_v2_1_Pinplot.html"
  "customer/help/Movement_Analytics_User_Manual_v2_1_Beacon.html:customer-dashboard/public/help/Movement_Analytics_User_Manual_v2_1_Beacon.html"
  "customer/help/Movement_Analytics_Benutzerhandbuch_v2_1_Beacon_DE.html:customer-dashboard/public/help/Movement_Analytics_Benutzerhandbuch_v2_1_Beacon_DE.html"
  "customer/help/Movement_Analytics_Gebruikershandleiding_v2_1_Beacon_NL.html:customer-dashboard/public/help/Movement_Analytics_Gebruikershandleiding_v2_1_Beacon_NL.html"
  "customer/help/Movement_Analytics_Manual_Usuario_v2_1_Beacon_ES.html:customer-dashboard/public/help/Movement_Analytics_Manual_Usuario_v2_1_Beacon_ES.html"
  "customer/help/Movement_Analytics_Manuale_Utente_v2_1_Beacon_IT.html:customer-dashboard/public/help/Movement_Analytics_Manuale_Utente_v2_1_Beacon_IT.html"
  "customer/help/Movement_Analytics_Manuel_Utilisateur_v2_1_Beacon_FR.html:customer-dashboard/public/help/Movement_Analytics_Manuel_Utilisateur_v2_1_Beacon_FR.html"
  "customer/help/Movement_Analytics_User_Manual_v2_1_Beacon_EN.html:customer-dashboard/public/help/Movement_Analytics_User_Manual_v2_1_Beacon_EN.html"
  "mobile/assets/MainLogo.png:mobile-app/ble_tracker_app/assets/MainLogo.png"
  "mobile/assets/FullLogowhite.png:mobile-app/ble_tracker_app/assets/FullLogowhite.png"
  "mobile/web/favicon.ico:mobile-app/ble_tracker_app/web/favicon.ico"
  "mobile/web/favicon.png:mobile-app/ble_tracker_app/web/favicon.png"
  "mobile/web/favicon-16x16.png:mobile-app/ble_tracker_app/web/favicon-16x16.png"
  "mobile/web/favicon-32x32.png:mobile-app/ble_tracker_app/web/favicon-32x32.png"
  "mobile/web/apple-touch-icon.png:mobile-app/ble_tracker_app/web/apple-touch-icon.png"
  "mobile/web/android-chrome-192x192.png:mobile-app/ble_tracker_app/web/android-chrome-192x192.png"
  "mobile/web/android-chrome-512x512.png:mobile-app/ble_tracker_app/web/android-chrome-512x512.png"
  "mobile/web/index.html:mobile-app/ble_tracker_app/web/index.html"
  "mobile/lib/theme/app_theme.dart:mobile-app/ble_tracker_app/lib/theme/app_theme.dart"
  "mobile/lib/config/environment.dart:mobile-app/ble_tracker_app/lib/config/environment.dart"
  "mobile/lib/main.dart:mobile-app/ble_tracker_app/lib/main.dart"
  "mobile/lib/screens/scan_screen.dart:mobile-app/ble_tracker_app/lib/screens/scan_screen.dart"
  "mobile/ios/Runner/Info.plist:mobile-app/ble_tracker_app/ios/Runner/Info.plist"
  "infra/nginx.conf:nginx/nginx.conf"
)

copied=0
skipped_missing=0
for entry in "${MAP[@]}"; do
  rel_src="${entry%%:*}"
  rel_dst="${entry#*:}"
  src_file="$SRC/$rel_src"
  dst_file="$DST/$rel_dst"

  # Hard guard: NEVER copy .env files via the overlay. Server .env files are
  # managed manually and must not be touched by build/deploy. If a future
  # contributor adds an .env entry to MAP, fail loud here instead of shipping
  # secrets or overwriting a hand-tuned production .env.
  case "$rel_dst" in
    *.env|.env|.env.*|*/.env|*/.env.*|*/*.env)
      echo "❌ refusing to copy .env via overlay: $rel_dst" >&2
      echo "   .env files must be managed manually on the server." >&2
      exit 1
      ;;
  esac

  if [[ ! -f "$src_file" ]]; then
    echo "  ⚠ skip (not in tenant): $rel_src"
    skipped_missing=$((skipped_missing + 1))
    continue
  fi

  mkdir -p "$(dirname "$dst_file")"
  if ! cmp -s "$src_file" "$dst_file" 2>/dev/null; then
    cp "$src_file" "$dst_file"
    echo "  ✓ copied: $rel_dst"
    copied=$((copied + 1))
  fi
done

echo
echo "✅ tenant '$TENANT' assembled — $copied changed, $skipped_missing missing in tenant tree"

# ─── Render docker-compose.yml from template ──────────────────────────────────
# Substitutes __TENANT_PREFIX__, __TENANT_DB_USER__, __TENANT_DB_NAME__ from
# tenants/<tenant>/tenant.env into gps-tracker/docker-compose.template.yml and
# writes gps-tracker/docker-compose.yml (gitignored, build output).
TENANT_ENV="$SRC/tenant.env"
TEMPLATE="$DST/docker-compose.template.yml"
COMPOSE_OUT="$DST/docker-compose.yml"

if [[ ! -f "$TENANT_ENV" ]]; then
  echo "❌ missing $TENANT_ENV — required for compose templating" >&2
  exit 1
fi
if [[ ! -f "$TEMPLATE" ]]; then
  echo "❌ missing $TEMPLATE — required for compose templating" >&2
  exit 1
fi

# Source tenant.env in a subshell to avoid leaking vars
set -a
# shellcheck disable=SC1090
. "$TENANT_ENV"
set +a

: "${TENANT_PREFIX:?tenant.env must define TENANT_PREFIX}"
: "${TENANT_DB_USER:?tenant.env must define TENANT_DB_USER}"
: "${TENANT_DB_NAME:?tenant.env must define TENANT_DB_NAME}"

# Reject placeholder values that look like template noise
for v in TENANT_PREFIX TENANT_DB_USER TENANT_DB_NAME; do
  val="${!v}"
  if [[ "$val" == *"__"* || -z "$val" ]]; then
    echo "❌ $v in tenant.env has invalid value: '$val'" >&2
    exit 1
  fi
done

tmp_out="$(mktemp)"
sed \
  -e "s|__TENANT_PREFIX__|${TENANT_PREFIX}|g" \
  -e "s|__TENANT_DB_USER__|${TENANT_DB_USER}|g" \
  -e "s|__TENANT_DB_NAME__|${TENANT_DB_NAME}|g" \
  "$TEMPLATE" > "$tmp_out"

# Fail loudly if any placeholder leaked through
if grep -q "__TENANT_" "$tmp_out"; then
  echo "❌ unsubstituted placeholders remain in compose output:" >&2
  grep -n "__TENANT_" "$tmp_out" >&2
  rm -f "$tmp_out"
  exit 1
fi

if ! cmp -s "$tmp_out" "$COMPOSE_OUT" 2>/dev/null; then
  mv "$tmp_out" "$COMPOSE_OUT"
  echo "  ✓ rendered: docker-compose.yml (TENANT_PREFIX=$TENANT_PREFIX)"
else
  rm -f "$tmp_out"
fi

# Stamp the build so deploy can verify what was shipped
echo "$TENANT" > "$DST/.tenant"
