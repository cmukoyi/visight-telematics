#!/bin/bash
# Pinplot Backup & Rollback Script
# Backs up only RUNTIME DATA, not code (code comes from git)
# Usage: ./backup.sh backup    (saves timestamped backup)
#        ./backup.sh list      (shows available backups)
#        ./backup.sh rollback <backup_name>  (restores backup)

set -e

BACKUP_DIR="/root/pinplot-backups"
APP_DIR="/root/pinplot"
TIMESTAMP=$(date +%Y%m%d_%H%M%S)
BACKUP_NAME="pinplot_backup_${TIMESTAMP}"

mkdir -p "$BACKUP_DIR"

# ============ BACKUP FUNCTION ============
backup() {
    echo "📦 Starting backup: $BACKUP_NAME"
    
    BACKUP_PATH="$BACKUP_DIR/$BACKUP_NAME"
    mkdir -p "$BACKUP_PATH"
    
    echo "  1️⃣  Backing up .env files (secrets)..."
    cp "$APP_DIR/gps-tracker/.env" "$BACKUP_PATH/" 2>/dev/null || echo "     (No root .env found)"
    cp "$APP_DIR/gps-tracker/backend/.env" "$BACKUP_PATH/backend.env" 2>/dev/null || echo "     (No backend .env found)"
    
    echo "  2️⃣  Backing up nginx certificates..."
    mkdir -p "$BACKUP_PATH/letsencrypt"
    [ -d "/etc/letsencrypt" ] && cp -r /etc/letsencrypt/* "$BACKUP_PATH/letsencrypt/" 2>/dev/null || echo "     (No certs found)"
    
    echo "  3️⃣  Exporting Docker volumes state..."
    docker volume ls --format "{{.Name}}" > "$BACKUP_PATH/volumes.txt"
    
    echo "  4️⃣  Backing up database..."
    docker exec pinplot_db pg_dump -U pinplot_db_user -d pinplot_db > "$BACKUP_PATH/database.sql" 2>/dev/null || echo "     (Could not dump database)"
    
    echo "  5️⃣  Git commit info..."
    cd "$APP_DIR"
    git log --oneline -5 > "$BACKUP_PATH/git-log.txt" 2>/dev/null || echo "     (Not a git repo)"
    
    echo "  6️⃣  Creating compressed archive (env + db + certs only)..."
    tar -czf "$BACKUP_PATH.tar.gz" -C "$BACKUP_DIR" "$BACKUP_NAME" 2>/dev/null
    rm -rf "$BACKUP_PATH"
    
    echo "✅ Backup complete: $BACKUP_PATH.tar.gz"
    echo "   Size: $(du -h "$BACKUP_PATH.tar.gz" | cut -f1)"
}

# ============ LIST BACKUPS FUNCTION ============
list_backups() {
    echo "📋 Available backups:"
    ls -lhS "$BACKUP_DIR"/*.tar.gz 2>/dev/null | awk '{print $9, "(" $5 ")"}' | sed 's|.*/||' || echo "   No backups found"
}

# ============ ROLLBACK FUNCTION ============
rollback() {
    BACKUP_FILE="$BACKUP_DIR/$1.tar.gz"
    
    if [ ! -f "$BACKUP_FILE" ]; then
        echo "❌ Backup not found: $BACKUP_FILE"
        list_backups
        exit 1
    fi
    
    echo "⚠️  ROLLBACK WARNING: This will restore .env, database, and certificates"
    echo "   Backup: $1"
    echo "   ⚠️  Code stays on current git branch (only runtime data restored)"
    read -p "   Continue? (yes/no): " -r
    if [[ ! $REPLY =~ ^yes$ ]]; then
        echo "   Cancelled."
        exit 1
    fi
    
    cd "$BACKUP_DIR"
    echo "📦 Extracting backup..."
    tar -xzf "$BACKUP_FILE"
    EXTRACTED_DIR=$(basename "$BACKUP_FILE" .tar.gz)
    
    echo "🛑 Stopping backend container..."
    cd "$APP_DIR/gps-tracker"
    docker compose stop backend || true
    
    echo "📂 Restoring .env files..."
    cp "$BACKUP_DIR/$EXTRACTED_DIR/backend.env" "$APP_DIR/gps-tracker/backend/.env" 2>/dev/null || true
    cp "$BACKUP_DIR/$EXTRACTED_DIR/.env" "$APP_DIR/gps-tracker/" 2>/dev/null || true
    chmod 600 "$APP_DIR/gps-tracker/backend/.env" 2>/dev/null || true
    chmod 600 "$APP_DIR/gps-tracker/.env" 2>/dev/null || true
    
    echo "🗄️  Restoring database..."
    docker compose up -d db
    sleep 5
    docker exec pinplot_db psql -U pinplot_db_user -d pinplot_db < "$BACKUP_DIR/$EXTRACTED_DIR/database.sql" 2>/dev/null || echo "   (Database restore skipped)"
    
    echo "🔐 Restoring SSL certificates..."
    [ -d "$BACKUP_DIR/$EXTRACTED_DIR/letsencrypt" ] && \
        sudo cp -r "$BACKUP_DIR/$EXTRACTED_DIR/letsencrypt/"* /etc/letsencrypt/ 2>/dev/null || echo "   (No certs to restore)"
    
    echo "🚀 Restarting backend..."
    docker compose up -d backend
    sleep 5
    
    echo "✅ Rollback complete!"
    echo "   Code: from current git branch"
    echo "   Data: from backup"
    docker compose logs --tail=20 backend
    
    # Cleanup
    rm -rf "$BACKUP_DIR/$EXTRACTED_DIR"
}

# ============ MAIN ============
case "${1:-backup}" in
    backup)
        backup
        ;;
    list)
        list_backups
        ;;
    rollback)
        if [ -z "$2" ]; then
            echo "Usage: $0 rollback <backup_name>"
            list_backups
            exit 1
        fi
        rollback "$2"
        ;;
    *)
        echo "Usage:"
        echo "  $0 backup              # Create timestamped backup (env + db + certs)"
        echo "  $0 list                # List all backups"
        echo "  $0 rollback <name>     # Restore data from backup (code stays from git)"
        exit 1
        ;;
esac
