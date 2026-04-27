#!/bin/bash
################################################################################
# BEACON TELEMATICS - ROLLBACK SCRIPT
#
# Rolls back to the previous git tag WITHOUT touching .env (secrets stay intact).
# Must be run directly on the production server.
#
# Usage:
#   bash rollback.sh               # rollback to previous git tag
#   bash rollback.sh v1.2.3        # rollback to specific tag/commit
################################################################################

set -e

TARGET="${1:-}"

cd ~/beacon-telematics/gps-tracker || { echo "❌ Directory not found"; exit 1; }

echo ""
echo "🚨 ROLLBACK INITIATED"
echo ""

# Determine rollback target
if [ -z "$TARGET" ]; then
    TARGET=$(git describe --tags --abbrev=0 HEAD^ 2>/dev/null || git rev-parse HEAD~1)
fi

echo "  Target: $TARGET"
echo "  Current: $(git describe --tags --abbrev=0 2>/dev/null || git rev-parse --short HEAD)"
echo ""

# Confirm
printf "⚠️  Roll back to %s? (yes/no): " "$TARGET"
read -r response
if [ "$response" != "yes" ] && [ "$response" != "y" ]; then
    echo "Rollback cancelled"
    exit 0
fi

echo ""
echo "Step 1: Reverting code to $TARGET (secrets untouched)..."
git fetch --tags
git checkout "$TARGET" -- .
echo "✅ Code reverted (backend/.env NOT changed)"

echo ""
echo "Step 2: Stopping containers..."
docker compose down --remove-orphans

echo ""
echo "Step 3: Rebuilding and starting services..."
docker compose build --no-cache flutter-web admin-portal
docker compose build backend customer
docker compose up -d

echo ""
echo "Step 4: Waiting for services..."
sleep 20
docker compose ps

echo ""
echo "================================"
echo "✅ ROLLBACK COMPLETE — $TARGET"
echo "================================"
echo ""
echo "Verify: curl http://localhost:8001/api/health"
echo "Logs:   docker compose logs -f backend"
echo ""
