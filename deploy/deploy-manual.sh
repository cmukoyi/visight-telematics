#!/bin/bash

# Manual deployment script for Digital Ocean
# Usage: ./deploy-manual.sh <server-ip> <username>

set -e

if [ "$#" -ne 2 ]; then
    echo "Usage: $0 <server-ip> <username>"
    echo "Example: $0 165.232.123.45 root"
    exit 1
fi

SERVER_IP=$1
USERNAME=$2
REMOTE_DIR="~/gps-tracker"

echo "🚀 Deploying GPS Tracker to $SERVER_IP..."

# Check if we can connect to server
echo "🔐 Testing SSH connection..."
ssh -o ConnectTimeout=5 $USERNAME@$SERVER_IP "echo '✅ SSH connection successful'"

# Create remote directory
echo "📁 Creating remote directory..."
ssh $USERNAME@$SERVER_IP "mkdir -p $REMOTE_DIR"

# Sync files to server (excluding unnecessary files)
echo "📤 Syncing files to server..."
rsync -avz --delete \
    --exclude '.git' \
    --exclude 'node_modules' \
    --exclude '__pycache__' \
    --exclude '*.pyc' \
    --exclude '.env' \
    --exclude 'build' \
    --exclude '.dart_tool' \
    --exclude '.DS_Store' \
    --exclude '*.log' \
    --exclude 'venv' \
    --exclude '.pytest_cache' \
    --exclude 'htmlcov' \
    --exclude 'coverage' \
    ../ $USERNAME@$SERVER_IP:$REMOTE_DIR/

# Deploy on server
echo "🐳 Starting Docker containers on server..."
ssh $USERNAME@$SERVER_IP << 'ENDSSH'
    cd ~/gps-tracker
    
    # Check if .env exists
    if [ ! -f backend/.env ]; then
        echo "❌ Error: backend/.env file not found!"
        echo "Please create backend/.env file with required environment variables"
        echo "You can copy from .env.example and fill in your values"
        exit 1
    fi
    
    # Pull latest images and rebuild
    docker-compose pull
    docker-compose down
    docker-compose up -d --build
    
    # Wait for containers to start
    echo "⏳ Waiting for containers to be ready..."
    sleep 10
    
    # Show container status
    echo ""
    echo "📊 Container Status:"
    docker-compose ps
    
    # Show recent logs
    echo ""
    echo "📝 Recent Logs:"
    docker-compose logs --tail=30
ENDSSH

# Verify deployment
echo ""
echo "🔍 Verifying deployment..."
sleep 3

if curl -f -s http://$SERVER_IP:5001/health > /dev/null; then
    echo "✅ Backend API is responding"
else
    echo "⚠️  Backend API health check failed"
fi

if curl -f -s http://$SERVER_IP:3000 > /dev/null; then
    echo "✅ Admin Dashboard is responding"
else
    echo "⚠️  Admin Dashboard health check failed"
fi

if curl -f -s http://$SERVER_IP:3001 > /dev/null; then
    echo "✅ Customer Dashboard is responding"
else
    echo "⚠️  Customer Dashboard health check failed"
fi

echo ""
echo "✅ Deployment complete!"
echo ""
echo "🌐 Service URLs:"
echo "   Backend API:        http://$SERVER_IP:5001"
echo "   Admin Dashboard:    http://$SERVER_IP:3000"
echo "   Customer Dashboard: http://$SERVER_IP:3001"
echo ""
echo "📝 View logs:"
echo "   ssh $USERNAME@$SERVER_IP 'cd ~/gps-tracker && docker-compose logs -f'"
echo ""
echo "🔄 Restart services:"
echo "   ssh $USERNAME@$SERVER_IP 'cd ~/gps-tracker && docker-compose restart'"
