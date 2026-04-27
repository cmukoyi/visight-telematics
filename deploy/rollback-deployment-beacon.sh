#!/bin/bash
# Rollback Deployment Script for Beacon Telematics
# Restores the last backup in case of deployment issues

set -e

LAST_BACKUP=$(cat ~/beacon-telematics-backups/LAST_BACKUP 2>/dev/null || echo "")

if [ -z "$LAST_BACKUP" ] || [ ! -d "$LAST_BACKUP" ]; then
    echo "❌ No backup found to rollback to!"
    echo "Available backups:"
    ls -lt ~/beacon-telematics-backups/ 2>/dev/null || echo "None"
    exit 1
fi

echo "🔄 Rolling back Beacon Telematics to backup: $LAST_BACKUP"
echo "⚠️  This will:"
echo "   - Restore .env files"
echo "   - Restore database"
echo "   - Restart containers"
echo ""
read -p "Continue? (yes/no): " CONFIRM

if [ "$CONFIRM" != "yes" ]; then
    echo "❌ Rollback cancelled"
    exit 1
fi

# Stop containers
echo "⏸️  Stopping containers..."
cd ~/beacon-telematics/gps-tracker
docker-compose down

# Restore environment files
echo "📝 Restoring environment files..."
if [ -f "$LAST_BACKUP/backend.env" ]; then
    cp "$LAST_BACKUP/backend.env" ~/beacon-telematics/gps-tracker/backend/.env
    echo "✅ Backend .env restored"
fi

if [ -f "$LAST_BACKUP/root.env" ]; then
    cp "$LAST_BACKUP/root.env" ~/beacon-telematics/gps-tracker/.env
    echo "✅ Root .env restored"
fi

if [ -f "$LAST_BACKUP/docker-compose.yml" ]; then
    cp "$LAST_BACKUP/docker-compose.yml" ~/beacon-telematics/gps-tracker/docker-compose.yml
    echo "✅ docker-compose.yml restored"
fi

# Restore database
echo "💾 Restoring database..."
if [ -f "$LAST_BACKUP/database.sql" ]; then
    # Start only the database container
    docker-compose up -d db
    sleep 10
    
    # Restore database
    docker exec -i beacon_telematics_db psql -U beacon_user beacon_telematics < "$LAST_BACKUP/database.sql"
    echo "✅ Database restored ($(du -h $LAST_BACKUP/database.sql | cut -f1))"
else
    echo "⚠️  No database backup found, skipping"
fi

# Start all containers
echo "🚀 Starting containers..."
docker-compose up -d

# Wait for health check
echo "⏳ Waiting for containers to be healthy..."
sleep 20

# Show container status
docker-compose ps

echo ""
echo "✅ Rollback complete!"
echo "📊 Container status:"
docker ps --filter "name=beacon_telematics"
echo ""
echo "🔍 Check logs with: cd ~/beacon-telematics/gps-tracker && docker-compose logs -f"
