#!/bin/bash
# Force rebuild of BeaconTelematics containers
# This script performs a complete clean rebuild of all containers
# Run this on the production server to force updates

set -e

cd ~/beacon-telematics/gps-tracker

echo "🧹 COMPLETE CLEANUP AND REBUILD"
echo "======================================="
echo ""

# Step 1: Stop all containers
echo "1️⃣ Stopping all containers..."
docker compose down --remove-orphans

# Step 2: Remove any dangling volumes or images
echo "2️⃣ Cleaning up unused Docker resources..."
docker system prune -f --volumes

# Step 3: Remove old images to ensure fresh build
echo "3️⃣ Removing old BeaconTelematics images..."
docker rmi -f $(docker images --format '{{.Repository}}:{{.Tag}}' | grep beacon_telematics) 2>/dev/null || echo "   No old images found (OK)"

# Step 4: Verify source has latest code
echo "4️⃣ Verifying source code changes..."
if grep -q "createdAt.isAfter" ./mobile-app/ble_tracker_app/lib/screens/alerts_screen.dart; then
  echo "   ✅ alerts_screen.dart has correct createdAt filter"
else
  echo "   ❌ FAIL: Source code missing expected changes"
  echo "   Run: git pull origin main"
  exit 1
fi

# Step 5: Full rebuild without any caching
echo "5️⃣ Building all containers (this takes 2-3 minutes)..."
docker compose build --no-cache --pull

# Step 6: Start containers
echo "6️⃣ Starting containers..."
docker compose up -d

# Step 7: Wait for services
echo "7️⃣ Waiting for services to start (30 seconds)..."
sleep 30

# Step 8: Verify containers are healthy
echo "8️⃣ Verifying container status..."
docker compose ps

# Step 9: Check logs for errors
echo ""
echo "9️⃣ Checking for startup errors..."

echo ""
echo "Backend logs (last 15 lines):"
docker logs --tail 15 beacon_telematics_backend 2>/dev/null || echo "❌ Backend not ready yet"

echo ""
echo "Flutter web logs (last 15 lines):"
docker logs --tail 15 beacon_telematics_flutter_web 2>/dev/null || echo "❌ Flutter web not ready yet"

# Step 10: Verify the Flutter app contains changes
echo ""
echo "🔟 Verifying alerts changes are deployed..."
sleep 10
if docker exec beacon_telematics_flutter_web grep -r "Last.*days\|_filteredAlerts" /usr/share/nginx/html 2>/dev/null | head -3; then
  echo "   ✅ Changes detected in deployed app"
else
  echo "   ⚠️  Could not verify changes - checking nginx..."
  docker exec beacon_telematics_nginx ls -lh /usr/share/nginx/html/
fi

echo ""
echo "✅ REBUILD COMPLETE!"
echo ""
echo "Test the app:"
echo "  - Alerts screen: https://beacontelematics.co.uk/#/alerts"
echo "  - Should show 'Last 7 days' label and filter alerts"
echo ""
echo "If changes still not visible:"
echo "  1. Hard refresh browser: Ctrl+Shift+R (Windows) or Cmd+Shift+R (Mac)"
echo "  2. Clear browser cache"
echo "  3. Check container is running: docker ps"
echo "  4. View nginx logs: docker logs beacon_telematics_nginx"
