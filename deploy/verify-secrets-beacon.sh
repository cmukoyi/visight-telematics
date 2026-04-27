#!/bin/bash
# Verify Secrets Script for Beacon Telematics
# Ensures all required secrets are present after deployment

set -e

echo "🔍 Verifying Beacon Telematics Secrets..."

BACKEND_ENV=~/beacon-telematics/gps-tracker/backend/.env
ROOT_ENV=~/beacon-telematics/gps-tracker/.env
LAST_BACKUP=$(cat ~/beacon-telematics-backups/LAST_BACKUP 2>/dev/null || echo "")

ERRORS=0

# Check backend .env exists
if [ ! -f "$BACKEND_ENV" ]; then
    echo "❌ Backend .env not found!"
    ERRORS=$((ERRORS + 1))
    
    # Restore from backup
    if [ -n "$LAST_BACKUP" ] && [ -f "$LAST_BACKUP/backend.env" ]; then
        echo "🔄 Restoring backend .env from backup..."
        cp "$LAST_BACKUP/backend.env" "$BACKEND_ENV"
        echo "✅ Backend .env restored"
    fi
fi

# Check root .env exists
if [ ! -f "$ROOT_ENV" ]; then
    echo "❌ Root .env not found!"
    ERRORS=$((ERRORS + 1))
    
    # Restore from backup
    if [ -n "$LAST_BACKUP" ] && [ -f "$LAST_BACKUP/root.env" ]; then
        echo "🔄 Restoring root .env from backup..."
        cp "$LAST_BACKUP/root.env" "$ROOT_ENV"
        echo "✅ Root .env restored"
    fi
fi

# Verify critical backend environment variables
if [ -f "$BACKEND_ENV" ]; then
    echo "📋 Checking critical environment variables..."
    
    # Check DATABASE_URL
    if ! grep -q "^DATABASE_URL=" "$BACKEND_ENV"; then
        echo "❌ DATABASE_URL missing in backend .env"
        ERRORS=$((ERRORS + 1))
    fi
    
    # Check SECRET_KEY
    if ! grep -q "^SECRET_KEY=" "$BACKEND_ENV"; then
        echo "❌ SECRET_KEY missing in backend .env"
        ERRORS=$((ERRORS + 1))
    fi
    
    # Check SENDGRID_API_KEY
    if ! grep -q "^SENDGRID_API_KEY=" "$BACKEND_ENV"; then
        echo "⚠️  SENDGRID_API_KEY missing (emails won't work)"
    fi
    
    # Check MZONE credentials
    if ! grep -q "^MZONE_CLIENT_SECRET=" "$BACKEND_ENV"; then
        echo "⚠️  MZONE_CLIENT_SECRET missing (GPS tracking won't work)"
    fi
    
    if [ $ERRORS -eq 0 ]; then
        echo "✅ All critical secrets present"
    fi
fi

# Verify database connection
echo "🗄️  Verifying database connection..."
if docker exec beacon_telematics_backend python -c "from app.database import engine; engine.connect()" 2>/dev/null; then
    echo "✅ Database connection successful"
else
    echo "❌ Database connection failed"
    ERRORS=$((ERRORS + 1))
fi

# Check container health
echo "🏥 Checking container health..."
UNHEALTHY=$(docker ps --filter "name=beacon_telematics" --filter "health=unhealthy" -q)
if [ -n "$UNHEALTHY" ]; then
    echo "❌ Unhealthy containers detected:"
    docker ps --filter "name=beacon_telematics" --filter "health=unhealthy"
    ERRORS=$((ERRORS + 1))
fi

if [ $ERRORS -gt 0 ]; then
    echo ""
    echo "❌ Verification failed with $ERRORS error(s)"
    exit 1
fi

echo ""
echo "✅ All verifications passed!"
exit 0
