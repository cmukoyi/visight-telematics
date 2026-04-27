#!/bin/bash
set -e

# Deployment script for Beacon Telematics
# Usage: ./deploy-to-server.sh

echo "========================================="
echo "🚀 Beacon Telematics Deployment Script"
echo "========================================="
echo ""

# Variables from environment (passed from GitHub Actions)
SSH_USER="${SSH_USER:-root}"
SSH_HOST="${SSH_HOST:?SSH_HOST not set}"
DEPLOY_DIR="~/pinplot/gps-tracker"

echo "📍 Deploying to: $SSH_USER@$SSH_HOST:$DEPLOY_DIR"
echo ""

# Step 1: Test SSH connection
echo "Step 1: Testing SSH connection..."
if ! ssh -o ConnectTimeout=10 -o StrictHostKeyChecking=no "$SSH_USER@$SSH_HOST" true; then
    echo "❌ SSH connection failed"
    exit 1
fi
echo "✅ SSH connection OK"
echo ""

# Step 2: Create environment file on server
echo "Step 2: Creating environment file on server..."
ssh -o StrictHostKeyChecking=no "$SSH_USER@$SSH_HOST" bash << 'ENVEOF'
set -e
mkdir -p ~/pinplot/gps-tracker/backend

# Create .env file with all secrets
cat > ~/pinplot/gps-tracker/backend/.env << 'EOF'
DATABASE_URL=PLACEHOLDER_DATABASE_URL
SECRET_KEY=PLACEHOLDER_SECRET_KEY
POSTGRES_USER=PLACEHOLDER_POSTGRES_USER
POSTGRES_PASSWORD=PLACEHOLDER_POSTGRES_PASSWORD
POSTGRES_DB=PLACEHOLDER_POSTGRES_DB
SENDGRID_API_KEY=PLACEHOLDER_SENDGRID_API_KEY
ALLOWED_ORIGINS=PLACEHOLDER_ALLOWED_ORIGINS
MZONE_CLIENT_ID=PLACEHOLDER_MZONE_CLIENT_ID
MZONE_CLIENT_SECRET=PLACEHOLDER_MZONE_CLIENT_SECRET
MZONE_USERNAME=PLACEHOLDER_MZONE_USERNAME
MZONE_PASSWORD=PLACEHOLDER_MZONE_PASSWORD
FROM_EMAIL=PLACEHOLDER_FROM_EMAIL
DEBUG=False
ENVIRONMENT=production
EOF

chmod 600 ~/pinplot/gps-tracker/backend/.env

# Verify file exists
if [ ! -f ~/pinplot/gps-tracker/backend/.env ]; then
    echo "❌ .env file creation failed"
    exit 1
fi

echo "✅ Environment file created"
ls -lh ~/pinplot/gps-tracker/backend/.env
ENVEOF

echo ""

# Step 3: Sync code to server
echo "Step 3: Syncing code to server..."
rsync -avz --delete \
    --exclude '.git' \
    --exclude '.github' \
    --exclude 'node_modules' \
    --exclude '__pycache__' \
    --exclude '*.pyc' \
    --exclude '.env' \
    --exclude 'backend/.env' \
    --exclude '.dart_tool' \
    --exclude 'pinplot_postgres_data' \
    ./gps-tracker/ "$SSH_USER@$SSH_HOST:$DEPLOY_DIR/" || {
        echo "❌ rsync failed"
        exit 1
    }
echo "✅ Code synced"
echo ""

# Step 4: Deploy containers
echo "Step 4: Deploying containers..."
ssh -o StrictHostKeyChecking=no "$SSH_USER@$SSH_HOST" bash << 'DEPLOYEOF'
set -e
cd ~/pinplot/gps-tracker

# Verify .env exists before any docker commands
if [ ! -f backend/.env ]; then
    echo "❌ .env file not found after rsync!"
    exit 1
fi
echo "✅ .env file confirmed present"

# Stop old containers
echo "Stopping old containers..."
docker compose down --remove-orphans || true

# Remove old images to force rebuild
echo "Removing stale UI images..."
docker images --format '{{.Repository}}:{{.Tag}}' \
    | grep -E 'flutter|admin' \
    | xargs -r docker rmi -f 2>/dev/null || true

# Build containers
echo "Building containers..."
docker compose build --no-cache flutter-web admin-portal || {
    echo "❌ UI build failed"
    exit 1
}
docker compose build backend customer || {
    echo "❌ Backend/Customer build failed"
    exit 1
}

# Start services
echo "Starting services..."
docker compose up -d || {
    echo "❌ Failed to start containers"
    docker compose logs --tail 50
    exit 1
}

# Wait for services
echo "Waiting for services to stabilize..."
sleep 20

# Verify services
echo ""
echo "Container status:"
docker compose ps

# Test health endpoint
echo ""
echo "Testing backend health..."
if docker logs pinplot_backend 2>/dev/null | grep -q "Application startup complete"; then
    echo "✅ Backend is ready"
else
    echo "⚠️  Backend still initializing (check logs)"
fi

echo ""
echo "✅ Deployment complete!"
DEPLOYEOF

echo ""
echo "========================================="
echo "✅ DEPLOYMENT SUCCESSFUL"
echo "========================================="
echo ""
echo "Access points:"
echo "  Backend API:   http://$SSH_HOST:8001/api/health"
echo "  Admin:         http://$SSH_HOST:3010/"
echo "  Customer:      http://$SSH_HOST:3011/"
echo "  Flutter:       http://$SSH_HOST:3012/"
