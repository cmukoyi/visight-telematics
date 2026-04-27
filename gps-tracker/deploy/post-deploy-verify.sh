#!/bin/bash
# POST-DEPLOYMENT VERIFICATION SCRIPT
# Run this MANUALLY on your production server after deployment
# This script tests that changes are actually running in the deployed app
# Usage: bash post-deploy-verify.sh

set -e

APP_URL="https://beacontelematics.co.uk"

echo "=========================================="
echo "POST-DEPLOYMENT VERIFICATION"
echo "=========================================="
echo ""

# Check 1: Verify containers are running
echo "1️⃣ Checking if containers are running..."
cd ~/beacon-telematics/gps-tracker

if ! docker compose ps | grep -q "beacon_telematics_flutter_web"; then
  echo "   ❌ Flutter web container not found!"
  echo "   Containers running:"
  docker compose ps
  exit 1
fi

if ! docker compose ps | grep beacon_telematics_flutter_web | grep -q "Up"; then
  echo "   ❌ Flutter web container is NOT running (status: $(docker compose ps | grep beacon_telematics_flutter_web | awk '{print $NF}'))"
  echo "   ACTION: Containers need to be restarted!"
  echo "   RUN: docker compose restart beacon_telematics_flutter_web"
  exit 1
fi

echo "   ✅ Flutter web container is running"
echo ""

# Check 2: Verify source code has changes
echo "2️⃣ Checking if source code has expected changes..."
if grep -q "createdAt.isAfter" ./mobile-app/ble_tracker_app/lib/screens/alerts_screen.dart; then
  echo "   ✅ Source code contains: createdAt.isAfter filter"
else
  echo "   ❌ Source code MISSING: createdAt.isAfter filter"
  exit 1
fi

if grep -q "_daysToShow = 7" ./mobile-app/ble_tracker_app/lib/screens/alerts_screen.dart; then
  echo "   ✅ Source code contains: _daysToShow = 7"
else
  echo "   ⚠️  Source code missing _daysToShow (might be hardcoded)"
fi

if grep -q "Last.*days" ./mobile-app/ble_tracker_app/lib/screens/alerts_screen.dart; then
  echo "   ✅ Source code contains: 'Last days' label"
else
  echo "   ❌ Source code MISSING: 'Last days' label text"
fi

echo ""

# Check 3: Verify Docker image has been rebuilt recently
echo "3️⃣ Checking Docker image rebuild time..."
IMAGE_ID=$(docker inspect beacon_telematics_flutter_web:latest --format='{{.ID}}' 2>/dev/null || echo "unknown")
echo "   Flask Web Image ID: $IMAGE_ID"

# Get image creation time
IMAGE_DATE=$(docker inspect beacon_telematics_flutter_web:latest --format='{{.Created}}' 2>/dev/null || echo "unknown")
echo "   Image created: $IMAGE_DATE"
echo ""

# Check 4: Verify Flutter app is served
echo "4️⃣ Testing HTTP request to app..."
RESPONSE=$(curl -s -o /dev/null -w "%{http_code}" "$APP_URL")
if [ "$RESPONSE" = "200" ]; then
  echo "   ✅ App is responding with HTTP 200"
else
  echo "   ❌ App returned HTTP $RESPONSE (expected 200)"
  exit 1
fi

echo ""

# Check 5: Check HTML files exist
echo "5️⃣ Checking if Flutter web files exist in container..."
if docker exec beacon_telematics_flutter_web ls -lh /usr/share/nginx/html/index.html >/dev/null 2>&1; then
  SIZE=$(docker exec beacon_telematics_flutter_web stat -c%s /usr/share/nginx/html/index.html)
  echo "   ✅ index.html exists (size: $SIZE bytes)"
else
  echo "   ❌ index.html NOT FOUND in container"
  exit 1
fi

if docker exec beacon_telematics_flutter_web ls -lh /usr/share/nginx/html/main.dart.js >/dev/null 2>&1; then
  SIZE=$(docker exec beacon_telematics_flutter_web stat -c%s /usr/share/nginx/html/main.dart.js)
  echo "   ✅ main.dart.js exists (size: $SIZE bytes)"
else
  echo "   ⚠️  main.dart.js NOT FOUND (this is normal, might be obfuscated)"
fi

echo ""

# Check 6: Container logs for errors
echo "6️⃣ Checking container logs for startup errors..."
ERROR_COUNT=$(docker logs --tail 50 beacon_telematics_flutter_web 2>&1 | grep -i "error\|failed\|warning" | wc -l)
if [ "$ERROR_COUNT" -gt 0 ]; then
  echo "   ⚠️  Found $ERROR_COUNT error/warning messages:"
  docker logs --tail 50 beacon_telematics_flutter_web 2>&1 | grep -i "error\|failed\|warning" | head -5
else
  echo "   ✅ No startup errors found"
fi

echo ""
echo "=========================================="
echo "✅ POST-DEPLOYMENT VERIFICATION COMPLETE"
echo "=========================================="
echo ""
echo "NEXT STEPS:"
echo "1. Open browser DevTools (F12)"
echo "2. Go to the Alerts screen"
echo "3. Open Console tab and look for:"
echo "   - '🔄 AlertsScreen initialized'"
echo "   - '📋 Loaded X alerts total'"
echo "   - '⏰ Filtering to last 7 days'"
echo "   - '✅ Filtered to X alerts from last 7 days'"
echo ""
echo "If you don't see these logs:"
echo "   → Changes haven't been deployed to container"
echo "   → Container needs to be rebuilt: docker compose build --no-cache"
echo ""
echo "Test the app at: $APP_URL/#/alerts"
echo "Expected: 'Last 7 days' label above alerts, only recent alerts shown"
