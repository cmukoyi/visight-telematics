#!/bin/bash
#
# Deploy Trip Engine Worker Pool v2.4.0
# 
# This script deploys the worker pool architecture to the production server.
# Run from your local machine.
#

set -e  # Exit on error

DEPLOY_HOST="root@159.89.50.65"
DEPLOY_KEY="~/.ssh/pinplot-deploy"
PROJECT_DIR="/root/pinplot/gps-tracker"

echo "=========================================="
echo "Trip Engine Worker Pool v2.4.0 Deployment"
echo "=========================================="
echo ""

# Function to run SSH command
ssh_exec() {
    ssh -i $DEPLOY_KEY $DEPLOY_HOST "$1"
}

# Step 1: Verify connection
echo "Step 1: Verifying connection..."
ssh_exec "echo '✅ Connected to production server'" || {
    echo "❌ Failed to connect to server"
    exit 1
}

# Step 2: Pull latest code
echo ""
echo "Step 2: Pulling latest code from GitHub..."
ssh_exec "cd $PROJECT_DIR && git fetch && git log -1 --oneline"

read -p "Current commit shown above. Continue with deployment? (y/n) " -n 1 -r
echo ""
if [[ ! $REPLY =~ ^[Yy]$ ]]; then
    echo "Deployment cancelled"
    exit 0
fi

ssh_exec "cd $PROJECT_DIR && git pull origin main"

# Step 3: Add environment variables
echo ""
echo "Step 3: Adding worker pool environment variables..."
ssh_exec "cd $PROJECT_DIR/backend && \
    if ! grep -q 'TRIP_ENGINE_WORKER_POOL' .env; then \
        echo '' >> .env && \
        echo '# Trip Engine Worker Pool (v2.4.0)' >> .env && \
        echo 'TRIP_ENGINE_WORKER_POOL=true' >> .env && \
        echo 'TRIP_ENGINE_NUM_WORKERS=5' >> .env && \
        echo '✅ Added worker pool config to .env'; \
    else \
        echo '✅ Worker pool config already exists in .env'; \
    fi"

# Step 4: Rebuild backend
echo ""
echo "Step 4: Rebuilding backend image..."
ssh_exec "cd $PROJECT_DIR && docker compose build backend"

# Step 5: Restart backend (minimal downtime)
echo ""
echo "Step 5: Restarting backend service..."
ssh_exec "cd $PROJECT_DIR && docker compose up -d backend"

# Wait for backend to be healthy
echo ""
echo "Waiting for backend to be healthy (30 seconds)..."
sleep 30

# Step 6: Verify deployment
echo ""
echo "Step 6: Verifying deployment..."

# Check if worker pool started
ssh_exec "docker logs beacon_telematics_backend --tail 100 | grep -i 'worker pool' || echo '⚠️  No worker pool logs found'"

# Check metrics endpoint
echo ""
echo "Fetching worker pool metrics..."
ssh_exec "curl -s http://localhost:8001/api/trip-engine/metrics | python3 -m json.tool || echo '⚠️  Failed to fetch metrics'"

# Step 7: Final status
echo ""
echo "=========================================="
echo "Deployment Complete!"
echo "=========================================="
echo ""
echo "Next steps:"
echo "1. Monitor logs: ssh -i $DEPLOY_KEY $DEPLOY_HOST 'docker logs beacon_telematics_backend -f --tail 100'"
echo "2. Check metrics: curl https://beacontelematics.co.uk/api/trip-engine/metrics | jq"
echo "3. Verify journeys: Check Movement Analytics dashboard"
echo ""
echo "To adjust worker count later:"
echo "  1. Edit backend/.env on server: TRIP_ENGINE_NUM_WORKERS=10"
echo "  2. Restart: docker compose up -d backend"
echo ""
echo "To rollback to legacy mode:"
echo "  1. Edit backend/.env on server: TRIP_ENGINE_WORKER_POOL=false"
echo "  2. Restart: docker compose up -d backend"
echo ""
