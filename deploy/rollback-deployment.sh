#!/bin/bash
# Deployment rollback script
# Quickly restore to last working state

set -e

BACKUP_DIR="$HOME/gps-tracker-backups"
APP_DIR="$HOME/gps-tracker"
TIMESTAMP=$(date +%Y%m%d_%H%M%S)

# Color codes
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

echo "=================================================="
echo "🔄 DEPLOYMENT ROLLBACK"
echo "=================================================="
echo "Timestamp: $(date)"
echo ""

# Check if backup directory exists
if [[ ! -d "$BACKUP_DIR" ]]; then
    echo -e "${RED}❌ Backup directory not found: $BACKUP_DIR${NC}"
    echo "Cannot rollback without backups!"
    exit 1
fi

# Show available backups
echo -e "${BLUE}Available backups:${NC}"
echo "-----------------------------------"
ls -lh "$BACKUP_DIR/" | tail -n +2
echo ""

# Find most recent backups
LATEST_ROOT_ENV=$(ls -t "$BACKUP_DIR"/.env.working.* 2>/dev/null | head -1)
LATEST_BACKEND_ENV=$(ls -t "$BACKUP_DIR"/backend.env.working.* 2>/dev/null | head -1)

if [[ -z "$LATEST_ROOT_ENV" ]] || [[ -z "$LATEST_BACKEND_ENV" ]]; then
    echo -e "${RED}❌ Missing required backups for rollback${NC}"
    exit 1
fi

echo -e "${YELLOW}Will restore from:${NC}"
echo "  Root .env: $LATEST_ROOT_ENV"
echo "  Backend .env: $LATEST_BACKEND_ENV"
echo ""

# Confirm rollback
read -p "⚠️  Continue with rollback? (yes/no): " confirm
if [[ "$confirm" != "yes" ]]; then
    echo "Rollback cancelled."
    exit 0
fi

echo ""
echo "Step 1: Backing up current (broken) state..."
echo "-----------------------------------"
if [[ -f "$APP_DIR/.env" ]]; then
    cp "$APP_DIR/.env" "$BACKUP_DIR/.env.broken.$TIMESTAMP"
    echo -e "${GREEN}✅ Saved current .env as .env.broken.$TIMESTAMP${NC}"
fi

if [[ -f "$APP_DIR/backend/.env" ]]; then
    cp "$APP_DIR/backend/.env" "$BACKUP_DIR/backend.env.broken.$TIMESTAMP"
    echo -e "${GREEN}✅ Saved current backend/.env as backend.env.broken.$TIMESTAMP${NC}"
fi

echo ""
echo "Step 2: Stopping containers..."
echo "-----------------------------------"
cd "$APP_DIR"
docker-compose down
echo -e "${GREEN}✅ Containers stopped${NC}"

echo ""
echo "Step 3: Restoring configuration files..."
echo "-----------------------------------"
cp "$LATEST_ROOT_ENV" "$APP_DIR/.env"
echo -e "${GREEN}✅ Restored .env${NC}"

cp "$LATEST_BACKEND_ENV" "$APP_DIR/backend/.env"
echo -e "${GREEN}✅ Restored backend/.env${NC}"

echo ""
echo "Step 4: Restarting containers..."
echo "-----------------------------------"
docker-compose up -d
sleep 10
echo -e "${GREEN}✅ Containers started${NC}"

echo ""
echo "Step 5: Verifying services..."
echo "-----------------------------------"

# Check container status
if docker-compose ps | grep -q "Up"; then
    echo -e "${GREEN}✅ Containers are running${NC}"
else
    echo -e "${RED}❌ Some containers failed to start${NC}"
    docker-compose ps
fi

# Check backend logs
if docker logs ble_tracker_backend --tail 10 2>&1 | grep -q "Application startup complete"; then
    echo -e "${GREEN}✅ Backend is healthy${NC}"
else
    echo -e "${YELLOW}⚠️  Backend may have issues. Recent logs:${NC}"
    docker logs ble_tracker_backend --tail 20
fi

echo ""
echo "=================================================="
echo -e "${GREEN}✅ ROLLBACK COMPLETE!${NC}"
echo "=================================================="
echo ""
echo "Next steps:"
echo "  1. Test the application: https://pinplot.me"
echo "  2. Check admin panel: https://pinplot.me/admin/"
echo "  3. Review broken configs in: $BACKUP_DIR/*.broken.$TIMESTAMP"
echo ""
