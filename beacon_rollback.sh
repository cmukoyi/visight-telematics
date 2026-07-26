#!/bin/bash
set -e  # Exit on any error

# ============================================================================
# BEACON TELEMATICS - ROLLBACK SCRIPT
# ============================================================================
# Purpose: Restore Beacon Telematics from backup if migration fails
# Run this on: root@beacontelematics.co.uk
# Usage: bash beacon_rollback.sh /path/to/backup/directory [--dry-run]
# ============================================================================

DRY_RUN=false
if [ "$2" = "--dry-run" ]; then
    DRY_RUN=true
    echo "🔍 DRY RUN MODE - No changes will be made"
    echo ""
fi

if [ -z "$1" ]; then
    echo "❌ ERROR: Backup directory not specified!"
    echo ""
    echo "Usage: bash beacon_rollback.sh /path/to/backup/directory [--dry-run]"
    echo ""
    echo "Options:"
    echo "  --dry-run    Show what would be restored without making changes"
    echo ""
    echo "Available backups:"
    ls -lt /root/beacon-backups/ 2>/dev/null || echo "   No backups found in /root/beacon-backups/"
    exit 1
fi

BACKUP_DIR="$1"
APP_DIR="/root/beacon-telematics/gps-tracker"
COMPOSE_PROJECT="beacon_telematics"

# Verify backup directory exists
if [ ! -d "$BACKUP_DIR" ]; then
    echo "❌ ERROR: Backup directory does not exist: $BACKUP_DIR"
    exit 1
fi

echo "════════════════════════════════════════════════════════════════"
echo "🔄 BEACON TELEMATICS ROLLBACK"
echo "════════════════════════════════════════════════════════════════"
echo "📁 Restore From: $BACKUP_DIR"
echo "⏰ Started: $(date)"
echo ""

# Show backup info
if [ -f "$BACKUP_DIR/BACKUP_INFO.txt" ]; then
    echo "📋 Backup Information:"
    cat "$BACKUP_DIR/BACKUP_INFO.txt"
    echo ""
fi

# Verify backup completeness
BACKUP_VALID=true
MISSING_COMPONENTS=""

if [ ! -f "$BACKUP_DIR/database_backup.sql" ]; then
    BACKUP_VALID=false
    MISSING_COMPONENTS="${MISSING_COMPONENTS}\n  ❌ database_backup.sql"
fi

if [ ! -f "$BACKUP_DIR/app_files.tar.gz" ]; then
    BACKUP_VALID=false
    MISSING_COMPONENTS="${MISSING_COMPONENTS}\n  ❌ app_files.tar.gz"
fi

if [ ! -d "$BACKUP_DIR/docker_images" ]; then
    BACKUP_VALID=false
    MISSING_COMPONENTS="${MISSING_COMPONENTS}\n  ❌ docker_images directory"
fi

if [ "$BACKUP_VALID" = false ]; then
    echo "⚠️  WARNING: Backup is incomplete! Missing components:"
    echo -e "$MISSING_COMPONENTS"
    echo ""
    echo "❌ This backup cannot be used for restoration."
    echo "   Please use a complete backup or create a new one."
    exit 1
fi

echo "✅ Backup validation passed - all components present"
echo ""

if [ "$DRY_RUN" = true ]; then
    echo "📋 DRY RUN - Would restore:"
    echo "   Database: $(du -h $BACKUP_DIR/database_backup.sql | cut -f1)"
    echo "   Application files: $(du -h $BACKUP_DIR/app_files.tar.gz | cut -f1)"
    echo "   Docker images: $(ls -1 $BACKUP_DIR/docker_images/*.tar.gz 2>/dev/null | wc -l) images"
    echo ""
    echo "✅ Dry run complete - backup is valid and ready for restoration"
    exit 0
fi

# Confirmation prompt
read -p "⚠️  Are you SURE you want to rollback? This will stop services and restore from backup. (yes/no): " CONFIRM

if [ "$CONFIRM" != "yes" ]; then
    echo "❌ Rollback cancelled."
    exit 0
fi

echo ""
echo "🔄 Starting rollback process..."

# ============================================================================
# 1. STOP CURRENT SERVICES
# ============================================================================
echo ""
echo "🛑 [1/5] Stopping current Docker services..."

cd "$APP_DIR"
docker compose down

echo "   ✅ Services stopped"

# ============================================================================
# 2. RESTORE APPLICATION FILES
# ============================================================================
echo ""
echo "📦 [2/5] Restoring application files..."

if [ -f "$BACKUP_DIR/app_files.tar.gz" ]; then
    # Backup current state before overwriting
    CURRENT_BACKUP="/root/beacon-backups/pre-rollback-$(date +%Y%m%d_%H%M%S)"
    mkdir -p "$CURRENT_BACKUP"
    echo "   Creating safety backup in: $CURRENT_BACKUP"
    tar -czf "$CURRENT_BACKUP/app_files.tar.gz" -C "$(dirname $APP_DIR)" "$(basename $APP_DIR)"
    
    # Restore from backup
    echo "   Extracting backup files..."
    tar -xzf "$BACKUP_DIR/app_files.tar.gz" -C "$(dirname $APP_DIR)"
    
    echo "   ✅ Application files restored"
else
    echo "   ❌ ERROR: app_files.tar.gz not found in backup!"
    exit 1
fi

# ============================================================================
# 3. RESTORE DOCKER COMPOSE CONFIG
# ============================================================================
echo ""
echo "⚙️  [3/5] Restoring docker-compose.yml..."

if [ -f "$BACKUP_DIR/docker-compose.yml.backup" ]; then
    cp "$BACKUP_DIR/docker-compose.yml.backup" "$APP_DIR/docker-compose.yml"
    echo "   ✅ docker-compose.yml restored"
else
    echo "   ⚠️  Warning: docker-compose.yml.backup not found, skipping"
fi

# ============================================================================
# 4. RESTORE ENVIRONMENT FILES
# ============================================================================
echo ""
echo "🔐 [4/5] Restoring environment files..."

if [ -f "$BACKUP_DIR/backend.env.backup" ]; then
    cp "$BACKUP_DIR/backend.env.backup" "$APP_DIR/backend/.env"
    echo "   ✅ backend/.env restored"
else
    echo "   ⚠️  Warning: backend.env.backup not found"
fi

if [ -f "$BACKUP_DIR/customer.env.backup" ]; then
    cp "$BACKUP_DIR/customer.env.backup" "$APP_DIR/customer-dashboard/.env"
    echo "   ✅ customer-dashboard/.env restored"
fi

# ============================================================================
# 5. RESTORE DOCKER IMAGES
# ============================================================================
echo ""
echo "🐳 [5/7] Restoring Docker images..."

if [ -d "$BACKUP_DIR/docker_images" ]; then
    IMAGE_COUNT=$(ls -1 "$BACKUP_DIR/docker_images"/*.tar.gz 2>/dev/null | wc -l)
    
    if [ "$IMAGE_COUNT" -gt 0 ]; then
        echo "   Restoring $IMAGE_COUNT Docker images..."
        
        for IMAGE_FILE in "$BACKUP_DIR/docker_images"/*.tar.gz; do
            IMAGE_NAME=$(basename "$IMAGE_FILE" .tar.gz)
            echo "   Loading: $IMAGE_NAME"
            gunzip -c "$IMAGE_FILE" | docker load
        done
        
        echo "   ✅ Docker images restored"
    else
        echo "   ⚠️  Warning: No Docker images found in backup"
    fi
else
    echo "   ⚠️  Warning: docker_images directory not found in backup"
fi

# ============================================================================
# 6. RESTORE DATABASE
# ============================================================================
echo ""
echo "📊 [6/7] Restoring PostgreSQL database..."

if [ -f "$BACKUP_DIR/database_backup.sql" ]; then
    echo "   Starting database container..."
    cd "$APP_DIR"
    docker compose up -d db
    
    # Wait for database to be ready
    echo "   Waiting for database to be ready..."
    sleep 10
    
    # Find database container
    DB_CONTAINER=$(docker ps --filter "name=${COMPOSE_PROJECT}" --filter "name=db" --format "{{.Names}}" | head -1)
    
    if [ -z "$DB_CONTAINER" ]; then
        echo "   ❌ ERROR: Database container not found!"
        exit 1
    fi
    
    echo "   Container: $DB_CONTAINER"
    
    # Drop and recreate database (connect to postgres database first)
    echo "   Dropping existing database..."
    docker exec "$DB_CONTAINER" psql -U beacon_user -d postgres -c "DROP DATABASE IF EXISTS beacon_telematics;"
    docker exec "$DB_CONTAINER" psql -U beacon_user -d postgres -c "CREATE DATABASE beacon_telematics;"
    
    # Restore backup
    echo "   Restoring database from backup..."
    cat "$BACKUP_DIR/database_backup.sql" | docker exec -i "$DB_CONTAINER" psql -U beacon_user -d beacon_telematics
    
    echo "   ✅ Database restored"
else
    echo "   ❌ ERROR: database_backup.sql not found in backup!"
    exit 1
fi

# ============================================================================
# 7. START SERVICES
# ============================================================================
echo ""
echo "🚀 [7/7] Starting restored services..."

cd "$APP_DIR"
docker compose up -d

echo "   Waiting for services to start..."
sleep 15

# ============================================================================
# VERIFICATION
# ============================================================================
echo ""
echo "🔍 Verifying services..."

RUNNING=$(docker ps --filter "name=${COMPOSE_PROJECT}" --format "{{.Names}}" | wc -l)
echo "   Running containers: $RUNNING"

docker ps --filter "name=${COMPOSE_PROJECT}" --format "table {{.Names}}\t{{.Status}}\t{{.Ports}}"

# ============================================================================
# ROLLBACK SUMMARY
# ============================================================================
echo ""
echo "════════════════════════════════════════════════════════════════"
echo "✅ ROLLBACK COMPLETE!"
echo "════════════════════════════════════════════════════════════════"
echo "📁 Restored From: $BACKUP_DIR"
echo "⏰ Completed: $(date)"
echo ""
echo "🔍 Verification Steps:"
echo "   1. Check website: https://beacontelematics.co.uk"
echo "   2. Test login and basic features"
echo "   3. Check logs: docker compose logs -f"
echo ""
echo "📋 Current Git State:"
cd "$APP_DIR"
echo "   Branch: $(git branch --show-current)"
echo "   Commit: $(git log -1 --oneline)"
echo ""
echo "════════════════════════════════════════════════════════════════"
