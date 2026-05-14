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
# Phase 1.1: originals still exist in gps-tracker/ and are byte-identical to
# the tenant copies, so this script is currently a no-op verifier. From
# Phase 1.3 onward the originals are removed and this script becomes
# load-bearing.

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
  "mobile/assets/MainLogo.png:mobile-app/ble_tracker_app/assets/MainLogo.png"
  "mobile/assets/FullLogowhite.png:mobile-app/ble_tracker_app/assets/FullLogowhite.png"
  "mobile/web/favicon.ico:mobile-app/ble_tracker_app/web/favicon.ico"
  "mobile/web/favicon.png:mobile-app/ble_tracker_app/web/favicon.png"
  "mobile/web/favicon-16x16.png:mobile-app/ble_tracker_app/web/favicon-16x16.png"
  "mobile/web/favicon-32x32.png:mobile-app/ble_tracker_app/web/favicon-32x32.png"
  "mobile/web/apple-touch-icon.png:mobile-app/ble_tracker_app/web/apple-touch-icon.png"
  "mobile/web/android-chrome-192x192.png:mobile-app/ble_tracker_app/web/android-chrome-192x192.png"
  "mobile/web/android-chrome-512x512.png:mobile-app/ble_tracker_app/web/android-chrome-512x512.png"
  "infra/nginx.conf:nginx/nginx.conf"
)

copied=0
skipped_missing=0
for entry in "${MAP[@]}"; do
  rel_src="${entry%%:*}"
  rel_dst="${entry#*:}"
  src_file="$SRC/$rel_src"
  dst_file="$DST/$rel_dst"

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

# Stamp the build so deploy can verify what was shipped
echo "$TENANT" > "$DST/.tenant"
