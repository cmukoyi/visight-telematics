#!/bin/bash
# Pre-deployment backup script
# Run this BEFORE every deployment to ensure we can rollback

set -e

BACKUP_DIR="$HOME/gps-tracker-backups"
APP_DIR="$HOME/gps-tracker"
TIMESTAMP=$(date +%Y%m%d_%H%M%S)

# Color codes
GREEN='\033[0;32m'
BLUE='\033[0;34m'
NC='\033[0m'

echo "=================================================="
echo "💾 Pre-Deployment Backup"
echo "=================================================="
echo "Timestamp: $(date)"
echo ""

# Create backup directory if it doesn't exist
mkdir -p "$BACKUP_DIR"

# Backup configuration files
echo -e "${BLUE}Backing up configuration files...${NC}"

if [[ -f "$APP_DIR/.env" ]]; then
    cp "$APP_DIR/.env" "$BACKUP_DIR/.env.pre-deploy.$TIMESTAMP"
    echo -e "${GREEN}✅ Backed up .env${NC}"
fi

if [[ -f "$APP_DIR/backend/.env" ]]; then
    cp "$APP_DIR/backend/.env" "$BACKUP_DIR/backend.env.pre-deploy.$TIMESTAMP"
    echo -e "${GREEN}✅ Backed up backend/.env${NC}"
fi

if [[ -f "$APP_DIR/docker-compose.yml" ]]; then
    cp "$APP_DIR/docker-compose.yml" "$BACKUP_DIR/docker-compose.yml.pre-deploy.$TIMESTAMP"
    echo -e "${GREEN}✅ Backed up docker-compose.yml${NC}"
fi

# Backup database
echo ""
echo -e "${BLUE}Backing up database...${NC}"
docker exec ble_tracker_db pg_dump -U ble_user ble_tracker > "$BACKUP_DIR/database.pre-deploy.$TIMESTAMP.sql"
echo -e "${GREEN}✅ Backed up database${NC}"

# Show backup summary
echo ""
echo "=================================================="
echo -e "${GREEN}✅ Pre-deployment backup complete!${NC}"
echo "=================================================="
echo ""
echo "Backups saved to: $BACKUP_DIR"
ls -lh "$BACKUP_DIR" | grep "pre-deploy.$TIMESTAMP"
echo ""
echo "Total backup size:"
du -sh "$BACKUP_DIR"
echo ""

# Clean up old backups (keep last 10)
echo "Cleaning up old backups (keeping last 10)..."
cd "$BACKUP_DIR"
ls -t .env.pre-deploy.* 2>/dev/null | tail -n +11 | xargs -r rm
ls -t backend.env.pre-deploy.* 2>/dev/null | tail -n +11 | xargs -r rm
ls -t database.pre-deploy.*.sql 2>/dev/null | tail -n +11 | xargs -r rm
echo -e "${GREEN}✅ Cleanup complete${NC}"
