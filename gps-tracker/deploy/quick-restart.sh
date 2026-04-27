#!/bin/bash
# QUICK RESTART SCRIPT - Use this to restart containers with latest code
# Run: bash quick-restart.sh
# This is the FASTEST way to make code changes take effect

set -e

cd ~/beacon-telematics/gps-tracker

echo "🚀 QUICK CONTAINER RESTART"
echo "================================"
echo ""

# Stop old containers
echo "⏹️  Stopping containers..."
docker compose down

# Clear cache
echo "🧹 Clearing Docker cache..."
docker system prune -f --volumes 2>/dev/null || true

# Rebuild without cache
echo "🔨 Rebuilding containers (no cache)..."
docker compose build --no-cache --pull

# Start new containers
echo "▶️  Starting containers..."
docker compose up -d

# Wait for services
echo "⏳ Waiting for services (20 seconds)..."
sleep 20

# Show status
echo ""
echo "📊 Container Status:"
docker compose ps

echo ""
echo "✅ RESTART COMPLETE!"
echo ""
echo "NEXT: Check DevTools Console"
echo "1. Open: https://beacontelematics.co.uk"
echo "2. Press F12 → Console tab"
echo "3. Navigate to: /#/alerts"
echo "4. Look for: 🔄 AlertsScreen initialized"
echo ""
echo "If you see the 🔄 log, changes are deployed!"
echo "If you DON'T see it, run: docker compose logs flutter_web"
