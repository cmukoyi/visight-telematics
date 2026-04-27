#!/bin/bash
# Verification script to check if alerts screen changes are deployed
# Run this on the production server to verify changes

set -e

echo "🔍 Verifying Alerts Screen 7-day filter deployment..."
echo ""

# Check 1: Source code
echo "1️⃣ Checking source code in repository..."
if grep -q "_filteredAlerts" ./mobile-app/ble_tracker_app/lib/screens/alerts_screen.dart; then
  if grep -q "createdAt.isAfter" ./mobile-app/ble_tracker_app/lib/screens/alerts_screen.dart; then
    echo "   ✅ alerts_screen.dart has correct _filteredAlerts getter with createdAt"
  else
    echo "   ❌ FAIL: createdAt.isAfter not found in _filteredAlerts"
    exit 1
  fi
else
  echo "   ❌ FAIL: _filteredAlerts getter not found"
  exit 1
fi

echo ""
echo "2️⃣ Checking deployed Flutter web app..."

# Check if the built web app contains the changes
if docker exec beacon_telematics_flutter_web cat /usr/share/nginx/html/main.dart.js 2>/dev/null | grep -q "_filteredAlerts\|Last.*days" ; then
  echo "   ✅ Flutter web container has alerts changes compiled in"
else
  echo "   ⚠️  WARNING: Changes might not be in compiled Flutter web"
  echo "   ACTION REQUIRED: Rebuild containers with:"
  echo "   cd ~/beacon-telematics/gps-tracker"
  echo "   docker compose down"
  echo "   docker compose build --no-cache --pull"
  echo "   docker compose up -d"
  exit 1
fi

echo ""
echo "3️⃣ Checking container status..."
docker ps --filter "name=beacon_telematics" --format "table {{.Names}}\t{{.Status}}"

echo ""
echo "✅ All verification checks passed!"
echo "Run this command to force rebuild if verification fails:"
echo "cd ~/beacon-telematics/gps-tracker && docker compose down && docker compose build --no-cache --pull && docker compose up -d"
