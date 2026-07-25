#!/bin/bash
set -e  # Exit on any error

# ============================================================================
# BEACON TELEMATICS - PRE-MIGRATION BACKUP SCRIPT
# ============================================================================
# Purpose: Complete backup before deploying Movement Analytics from main
# Run this on: root@beacontelematics.co.uk
# Date: 2026-07-25
# ============================================================================

BACKUP_DIR="/root/beacon-backups/pre-analytics-$(date +%Y%m%d_%H%M%S)"
APP_DIR="/root/beacon-telematics/gps-tracker"
COMPOSE_PROJECT="beacon_telematics"

echo "════════════════════════════════════════════════════════════════"
echo "🔒 BEACON TELEMATICS PRE-MIGRATION BACKUP"
echo "════════════════════════════════════════════════════════════════"
echo "📁 Backup Location: $BACKUP_DIR"
echo "⏰ Started: $(date)"
echo ""

# Create backup directory
mkdir -p "$BACKUP_DIR"
cd "$BACKUP_DIR"

# ============================================================================
# 1. DATABASE BACKUP
# ============================================================================
echo "📊 [1/6] Backing up PostgreSQL database..."

DB_CONTAINER="${COMPOSE_PROJECT}_db_1"
DB_NAME="beacon_telematics"
DB_USER="beacon_user"

# Check if database container exists
if docker ps -a --format '{{.Names}}' | grep -q "^${DB_CONTAINER}$"; then
    DB_CONTAINER_FOUND="${DB_CONTAINER}"
elif docker ps -a --format '{{.Names}}' | grep -q "${COMPOSE_PROJECT}-db-1"; then
    DB_CONTAINER_FOUND="${COMPOSE_PROJECT}-db-1"
elif docker ps -a --format '{{.Names}}' | grep -q "${COMPOSE_PROJECT}_db"; then
    DB_CONTAINER_FOUND="${COMPOSE_PROJECT}_db"
else
    echo "⚠️  Warning: Could not find database container, trying common names..."
    DB_CONTAINER_FOUND=$(docker ps --format '{{.Names}}' | grep -i 'db' | head -1)
fi

if [ -n "$DB_CONTAINER_FOUND" ]; then
    echo "   Container: $DB_CONTAINER_FOUND"
    
    # Dump database (no password needed - using peer auth inside container)
    docker exec "$DB_CONTAINER_FOUND" pg_dump -U "$DB_USER" -d "$DB_NAME" > database_backup.sql
    
    # Verify dump is not empty
    if [ -s database_backup.sql ]; then
        DB_SIZE=$(du -h database_backup.sql | cut -f1)
        echo "   ✅ Database backed up: $DB_SIZE"
        
        # Also create compressed version
        gzip -c database_backup.sql > database_backup.sql.gz
        COMPRESSED_SIZE=$(du -h database_backup.sql.gz | cut -f1)
        echo "   ✅ Compressed backup: $COMPRESSED_SIZE"
    else
        echo "   ❌ ERROR: Database dump is empty!"
        exit 1
    fi
else
    echo "   ❌ ERROR: Could not find database container!"
    exit 1
fi

# ============================================================================
# 2. DOCKER IMAGES BACKUP
# ============================================================================
echo ""
echo "🐳 [2/6] Saving current Docker images..."

# Get list of running containers
CONTAINERS=$(docker ps --filter "name=${COMPOSE_PROJECT}" --format "{{.Names}}")

if [ -z "$CONTAINERS" ]; then
    echo "   ⚠️  No running containers found with prefix: ${COMPOSE_PROJECT}"
else
    mkdir -p docker_images
    
    for CONTAINER in $CONTAINERS; do
        IMAGE=$(docker inspect --format='{{.Config.Image}}' "$CONTAINER")
        IMAGE_NAME=$(echo "$IMAGE" | tr '/:' '_')
        echo "   Saving: $CONTAINER ($IMAGE)"
        docker save "$IMAGE" | gzip > "docker_images/${IMAGE_NAME}.tar.gz"
    done
    
    IMAGES_SIZE=$(du -sh docker_images | cut -f1)
    echo "   ✅ Docker images saved: $IMAGES_SIZE"
fi

# ============================================================================
# 3. APPLICATION FILES BACKUP
# ============================================================================
echo ""
echo "📦 [3/6] Backing up application files..."

if [ -d "$APP_DIR" ]; then
    # Exclude node_modules, __pycache__, .git to save space
    tar -czf app_files.tar.gz \
        --exclude='node_modules' \
        --exclude='__pycache__' \
        --exclude='.git' \
        --exclude='*.log' \
        -C "$(dirname $APP_DIR)" \
        "$(basename $APP_DIR)"
    
    APP_SIZE=$(du -h app_files.tar.gz | cut -f1)
    echo "   ✅ Application files backed up: $APP_SIZE"
else
    echo "   ❌ ERROR: Application directory not found: $APP_DIR"
    exit 1
fi

# ============================================================================
# 4. DOCKER COMPOSE CONFIGURATION
# ============================================================================
echo ""
echo "⚙️  [4/6] Backing up docker-compose.yml..."

if [ -f "$APP_DIR/docker-compose.yml" ]; then
    cp "$APP_DIR/docker-compose.yml" docker-compose.yml.backup
    echo "   ✅ docker-compose.yml backed up"
else
    echo "   ⚠️  Warning: docker-compose.yml not found"
fi

# ============================================================================
# 5. ENVIRONMENT VARIABLES
# ============================================================================
echo ""
echo "🔐 [5/6] Backing up environment files..."

# Backend .env
if [ -f "$APP_DIR/backend/.env" ]; then
    cp "$APP_DIR/backend/.env" backend.env.backup
    echo "   ✅ backend/.env backed up"
else
    echo "   ⚠️  Warning: backend/.env not found"
fi

# Customer .env (if exists)
if [ -f "$APP_DIR/customer-dashboard/.env" ]; then
    cp "$APP_DIR/customer-dashboard/.env" customer.env.backup
    echo "   ✅ customer-dashboard/.env backed up"
fi

# ============================================================================
# 6. GIT STATE
# ============================================================================
echo ""
echo "📋 [6/6] Recording git state..."

if [ -d "$APP_DIR/.git" ]; then
    cd "$APP_DIR"
    git branch > "$BACKUP_DIR/git_branch.txt" 2>/dev/null || echo "unknown" > "$BACKUP_DIR/git_branch.txt"
    git log -1 --oneline > "$BACKUP_DIR/git_commit.txt" 2>/dev/null || echo "unknown" > "$BACKUP_DIR/git_commit.txt"
    git status > "$BACKUP_DIR/git_status.txt" 2>/dev/null || echo "Not a git repo" > "$BACKUP_DIR/git_status.txt"
    git diff > "$BACKUP_DIR/git_diff.txt" 2>/dev/null || true

    CURRENT_BRANCH=$(git branch --show-current 2>/dev/null || echo "unknown")
    CURRENT_COMMIT=$(git log -1 --oneline 2>/dev/null | cut -d' ' -f1 || echo "unknown")
else
    echo "   ⚠️  Not a git repository, skipping git state"
    CURRENT_BRANCH="unknown (deployed from Docker images)"
    CURRENT_COMMIT="unknown"
    echo "$CURRENT_BRANCH" > "$BACKUP_DIR/git_branch.txt"
    echo "$CURRENT_COMMIT" > "$BACKUP_DIR/git_commit.txt"
fi

echo "   ✅ Current branch: $CURRENT_BRANCH"
echo "   ✅ Current commit: $CURRENT_COMMIT"

# ============================================================================
# BACKUP SUMMARY
# ============================================================================
cd "$BACKUP_DIR"

# Verify critical files exist
BACKUP_VALID=true
MISSING_FILES=""

if [ ! -f "database_backup.sql" ] || [ ! -s "database_backup.sql" ]; then
    BACKUP_VALID=false
    MISSING_FILES="${MISSING_FILES}\n  ❌ database_backup.sql is missing or empty"
fi

if [ ! -f "app_files.tar.gz" ] || [ ! -s "app_files.tar.gz" ]; then
    BACKUP_VALID=false
    MISSING_FILES="${MISSING_FILES}\n  ❌ app_files.tar.gz is missing or empty"
fi

if [ ! -d "docker_images" ] || [ -z "$(ls -A docker_images/*.tar.gz 2>/dev/null)" ]; then
    BACKUP_VALID=false
    MISSING_FILES="${MISSING_FILES}\n  ❌ docker_images directory is missing or empty"
fi

cat > BACKUP_INFO.txt <<EOF
════════════════════════════════════════════════════════════════
BEACON TELEMATICS BACKUP INFORMATION
════════════════════════════════════════════════════════════════

Backup Date: $(date)
Backup Location: $BACKUP_DIR
Backup Status: $(if [ "$BACKUP_VALID" = true ]; then echo "✅ VALID"; else echo "❌ INCOMPLETE"; fi)

Git State:
  Branch: $CURRENT_BRANCH
  Commit: $CURRENT_COMMIT

Files Backed Up:
$(ls -lh | tail -n +2)

Docker Images Backed Up:
$(ls -lh docker_images/ 2>/dev/null | tail -n +2 | wc -l) images

Total Backup Size: $(du -sh . | cut -f1)

Restore Command:
  bash beacon_rollback.sh $BACKUP_DIR

════════════════════════════════════════════════════════════════
EOF

echo ""
echo "════════════════════════════════════════════════════════════════"

if [ "$BACKUP_VALID" = true ]; then
    echo "✅ BACKUP COMPLETE AND VERIFIED!"
    echo "════════════════════════════════════════════════════════════════"
    echo "📁 Location: $BACKUP_DIR"
    echo "📊 Total Size: $(du -sh $BACKUP_DIR | cut -f1)"
    echo ""
    echo "📋 Backup Contents:"
    echo "   Database: $(du -h database_backup.sql | cut -f1)"
    echo "   Database (compressed): $(du -h database_backup.sql.gz | cut -f1)"
    echo "   Application files: $(du -h app_files.tar.gz | cut -f1)"
    echo "   Docker images: $(du -sh docker_images | cut -f1) ($(ls -1 docker_images/*.tar.gz | wc -l) images)"
    echo ""
    echo "⏰ Completed: $(date)"
    echo ""
    echo "🔄 To restore from this backup:"
    echo "   bash beacon_rollback.sh $BACKUP_DIR"
else
    echo "⚠️  BACKUP INCOMPLETE - SOME FILES MISSING!"
    echo "════════════════════════════════════════════════════════════════"
    echo -e "$MISSING_FILES"
    echo ""
    echo "❌ This backup may not restore properly!"
    echo "   Please review and re-run the backup script."
    exit 1
fi
echo "════════════════════════════════════════════════════════════════"
