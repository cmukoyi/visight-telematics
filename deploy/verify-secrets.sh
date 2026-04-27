#!/bin/bash
# Post-deployment secret verification and repair script
# This ensures production secrets are never corrupted or overwritten

set -e

BACKUP_DIR="$HOME/gps-tracker-backups"
APP_DIR="$HOME/gps-tracker"
TIMESTAMP=$(date +%Y%m%d_%H%M%S)

echo "=================================================="
echo "🔐 Post-Deployment Secret Verification"
echo "=================================================="
echo "Timestamp: $(date)"
echo ""

# Color codes for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# Function to check if DATABASE_URL has password
check_database_url() {
    local file=$1
    local db_url=$(grep "^DATABASE_URL=" "$file" 2>/dev/null || echo "")
    
    if [[ -z "$db_url" ]]; then
        echo -e "${RED}❌ DATABASE_URL not found in $file${NC}"
        return 1
    fi
    
    # Check if password is present between : and @
    if [[ $db_url =~ postgresql://[^:]+:([^@]+)@.* ]]; then
        local password="${BASH_REMATCH[1]}"
        if [[ -z "$password" ]]; then
            echo -e "${RED}❌ DATABASE_URL has EMPTY password in $file${NC}"
            return 1
        else
            echo -e "${GREEN}✅ DATABASE_URL has password in $file${NC}"
            return 0
        fi
    else
        echo -e "${RED}❌ DATABASE_URL format invalid in $file${NC}"
        return 1
    fi
}

# Function to check if MZone credentials exist
check_mzone_config() {
    local file=$1
    local missing=0
    
    for var in MZONE_CLIENT_ID MZONE_CLIENT_SECRET MZONE_USERNAME MZONE_PASSWORD; do
        if ! grep -q "^${var}=" "$file" 2>/dev/null; then
            echo -e "${RED}❌ $var missing in $file${NC}"
            missing=1
        fi
    done
    
    if [[ $missing -eq 0 ]]; then
        echo -e "${GREEN}✅ MZone credentials present in $file${NC}"
        return 0
    else
        return 1
    fi
}

# Function to restore from backup
restore_from_backup() {
    local file=$1
    local backup_pattern=$2
    
    echo -e "${YELLOW}🔄 Attempting to restore $file from backup...${NC}"
    
    # Find most recent working backup
    local latest_backup=$(ls -t "$BACKUP_DIR"/$backup_pattern 2>/dev/null | head -1)
    
    if [[ -n "$latest_backup" ]]; then
        cp "$latest_backup" "$file"
        echo -e "${GREEN}✅ Restored from: $latest_backup${NC}"
        return 0
    else
        echo -e "${RED}❌ No backup found matching: $backup_pattern${NC}"
        return 1
    fi
}

# Main verification
echo "Step 1: Checking backend/.env..."
echo "-----------------------------------"
if ! check_database_url "$APP_DIR/backend/.env"; then
    echo -e "${YELLOW}⚠️  backend/.env has issues. Restoring from backup...${NC}"
    if restore_from_backup "$APP_DIR/backend/.env" "backend.env.working.*"; then
        check_database_url "$APP_DIR/backend/.env" || echo -e "${RED}❌ Restore failed to fix DATABASE_URL${NC}"
    fi
fi

if ! check_mzone_config "$APP_DIR/backend/.env"; then
    echo -e "${YELLOW}⚠️  MZone config incomplete. Restoring from backup...${NC}"
    if restore_from_backup "$APP_DIR/backend/.env" "backend.env.working.*"; then
        check_mzone_config "$APP_DIR/backend/.env" || echo -e "${RED}❌ Restore failed to fix MZone config${NC}"
    fi
fi

echo ""
echo "Step 2: Checking root .env..."
echo "-----------------------------------"
if ! grep -q "^POSTGRES_PASSWORD=" "$APP_DIR/.env" 2>/dev/null; then
    echo -e "${RED}❌ POSTGRES_PASSWORD missing in .env${NC}"
    restore_from_backup "$APP_DIR/.env" ".env.working.*"
else
    echo -e "${GREEN}✅ POSTGRES_PASSWORD present in .env${NC}"
fi

echo ""
echo "Step 3: Testing backend container..."
echo "-----------------------------------"
cd "$APP_DIR"

# Restart backend to apply any fixes
docker-compose restart backend
sleep 5

# Check if backend is healthy
if docker logs ble_tracker_backend --tail 20 2>&1 | grep -q "Application startup complete"; then
    echo -e "${GREEN}✅ Backend started successfully${NC}"
else
    echo -e "${RED}❌ Backend failed to start. Check logs:${NC}"
    docker logs ble_tracker_backend --tail 30
    exit 1
fi

echo ""
echo "=================================================="
echo -e "${GREEN}✅ Secret verification complete!${NC}"
echo "=================================================="
