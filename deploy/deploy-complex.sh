#!/bin/bash
set -e

################################################################################
# Beacon Telematics Deployment Script
# 
# This script handles all deployment logic for production deployments.
# It's designed to be:
#   - Idempotent (safe to run multiple times)
#   - Debuggable (clear error messages and logging)
#   - Testable (works both locally and in CI/CD)
#   - Secure (handles secrets properly)
#
# Usage (in CI/CD):
#   export SSH_HOST="161.35.38.209"
#   export SSH_USER="root"
#   export DATABASE_URL="postgresql://..."
#   ... (set all other secrets as env vars)
#   ./deploy/deploy.sh
#
# Usage (locally):
#   ./deploy/deploy.sh
#
################################################################################

# Configuration
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"
REMOTE_BASE_DIR="~/pinplot/gps-tracker"

# Required environment variables for deployment
REQUIRED_VARS=(
    "SSH_HOST"
    "SSH_USER"
    "DATABASE_URL"
    "SECRET_KEY"
    "POSTGRES_USER"
    "POSTGRES_PASSWORD"
    "POSTGRES_DB"
    "SENDGRID_API_KEY"
    "ALLOWED_ORIGINS"
    "MZONE_CLIENT_ID"
    "MZONE_CLIENT_SECRET"
    "MZONE_USERNAME"
    "MZONE_PASSWORD"
    "FROM_EMAIL"
)

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

################################################################################
# Functions
################################################################################

log_header() {
    echo -e "${BLUE}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
    echo -e "${BLUE}$1${NC}"
    echo -e "${BLUE}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
}

log_step() {
    echo -e "${YELLOW}→${NC} $1"
}

log_success() {
    echo -e "${GREEN}✓${NC} $1"
}

log_error() {
    echo -e "${RED}✗${NC} $1"
}

die() {
    log_error "$1"
    exit 1
}

################################################################################
# Validation
################################################################################

log_header "Validating Deployment Configuration"

# Check if running in CI or locally
if [ -z "$SSH_HOST" ]; then
    log_error "SSH_HOST not set"
    die "This script requires SSH_HOST environment variable"
fi

log_step "Checking required environment variables..."

missing_vars=0
for var in "${REQUIRED_VARS[@]}"; do
    if [ -z "${!var}" ]; then
        log_error "Missing: $var"
        missing_vars=$((missing_vars + 1))
    else
        # Show first 10 chars of sensitive vars
        if [[ "$var" == *"PASSWORD"* ]] || [[ "$var" == *"SECRET"* ]] || [[ "$var" == *"KEY"* ]]; then
            value="${!var}"
            echo "  ✓ $var: ${value:0:10}... (${#value} chars)"
        else
            echo "  ✓ $var: ${!var}"
        fi
    fi
done

if [ $missing_vars -gt 0 ]; then
    die "$missing_vars environment variables are missing"
fi

log_success "All required variables present"

################################################################################
# SSH Connection Test
################################################################################

log_header "Testing SSH Connection"

log_step "Testing SSH to $SSH_USER@$SSH_HOST..."
if ! ssh -o ConnectTimeout=10 -o StrictHostKeyChecking=no "$SSH_USER@$SSH_HOST" true 2>/dev/null; then
    die "SSH connection to $SSH_USER@$SSH_HOST failed"
fi

log_success "SSH connection successful"

################################################################################
# Create .env File on Server
################################################################################

log_header "Configuring Remote Environment"

log_step "Creating .env file on server..."

ssh -o StrictHostKeyChecking=no "$SSH_USER@$SSH_HOST" bash -s << 'ENVSCRIPT'
set -e

# Create directory
mkdir -p ~/pinplot/gps-tracker/backend

# Create temporary file first (safer)
temp_env=$(mktemp)
trap "rm -f $temp_env" EXIT

# Write all environment variables to temp file
cat > "$temp_env" << 'EOF'
DATABASE_URL=PLACEHOLDER_DB_URL
SECRET_KEY=PLACEHOLDER_SECRET
POSTGRES_USER=PLACEHOLDER_PG_USER
POSTGRES_PASSWORD=PLACEHOLDER_PG_PASS
POSTGRES_DB=PLACEHOLDER_PG_DB
SENDGRID_API_KEY=PLACEHOLDER_SENDGRID
ALLOWED_ORIGINS=PLACEHOLDER_ORIGINS
MZONE_CLIENT_ID=PLACEHOLDER_MZ_ID
MZONE_CLIENT_SECRET=PLACEHOLDER_MZ_SECRET
MZONE_USERNAME=PLACEHOLDER_MZ_USER
MZONE_PASSWORD=PLACEHOLDER_MZ_PASS
FROM_EMAIL=PLACEHOLDER_EMAIL
DEBUG=False
ENVIRONMENT=production
EOF

# Move to final location atomically (avoids partial writes)
mv "$temp_env" ~/pinplot/gps-tracker/backend/.env
chmod 600 ~/pinplot/gps-tracker/backend/.env

# Verify
if [ ! -f ~/pinplot/gps-tracker/backend/.env ]; then
    echo "Error: .env creation failed" >&2
    exit 1
fi

echo "✓ .env created ($(wc -c < ~/pinplot/gps-tracker/backend/.env) bytes)"
ENVSCRIPT

log_success ".env file created on server"

# Now substitute actual secrets
log_step "Injecting secrets into .env..."

# Escape special characters for sed
escape_sed() {
    sed 's/[&/\]/\\&/g'
}

# Create a script that substitutes all placeholders
substitute_script=$(cat <<'SUBSTITUTION'
set -e
ENV_FILE=~/pinplot/gps-tracker/backend/.env

# Function to safely substitute a variable
substitute() {
    local placeholder="$1"
    local value="$2"
    # Escape the value for sed
    local escaped=$(printf '%s\n' "$value" | sed -e 's/[\/&]/\\&/g')
    sed -i "s/PLACEHOLDER_${placeholder}/${escaped}/g" "$ENV_FILE"
}

substitute "DB_URL" "$DATABASE_URL"
substitute "SECRET" "$SECRET_KEY"
substitute "PG_USER" "$POSTGRES_USER"
substitute "PG_PASS" "$POSTGRES_PASSWORD"
substitute "PG_DB" "$POSTGRES_DB"
substitute "SENDGRID" "$SENDGRID_API_KEY"
substitute "ORIGINS" "$ALLOWED_ORIGINS"
substitute "MZ_ID" "$MZONE_CLIENT_ID"
substitute "MZ_SECRET" "$MZONE_CLIENT_SECRET"
substitute "MZ_USER" "$MZONE_USERNAME"
substitute "MZ_PASS" "$MZONE_PASSWORD"
substitute "EMAIL" "$FROM_EMAIL"

echo "✓ Secrets injected"
SUBSTITUTION
)

ssh -o StrictHostKeyChecking=no "$SSH_USER@$SSH_HOST" bash -s \
    "$DATABASE_URL" \
    "$SECRET_KEY" \
    "$POSTGRES_USER" \
    "$POSTGRES_PASSWORD" \
    "$POSTGRES_DB" \
    "$SENDGRID_API_KEY" \
    "$ALLOWED_ORIGINS" \
    "$MZONE_CLIENT_ID" \
    "$MZONE_CLIENT_SECRET" \
    "$MZONE_USERNAME" \
    "$MZONE_PASSWORD" \
    "$FROM_EMAIL" << 'SUBSTITUTION'
set -e
export DATABASE_URL="$1"
export SECRET_KEY="$2"
export POSTGRES_USER="$3"
export POSTGRES_PASSWORD="$4"
export POSTGRES_DB="$5"
export SENDGRID_API_KEY="$6"
export ALLOWED_ORIGINS="$7"
export MZONE_CLIENT_ID="$8"
export MZONE_CLIENT_SECRET="$9"
export MZONE_USERNAME="${10}"
export MZONE_PASSWORD="${11}"
export FROM_EMAIL="${12}"

ENV_FILE=~/pinplot/gps-tracker/backend/.env

substitute() {
    local placeholder="$1"
    local value="$2"
    local escaped=$(printf '%s\n' "$value" | sed -e 's/[\/&]/\\&/g')
    sed -i "s/PLACEHOLDER_${placeholder}/${escaped}/g" "$ENV_FILE"
}

substitute "DB_URL" "$DATABASE_URL"
substitute "SECRET" "$SECRET_KEY"
substitute "PG_USER" "$POSTGRES_USER"
substitute "PG_PASS" "$POSTGRES_PASSWORD"
substitute "PG_DB" "$POSTGRES_DB"
substitute "SENDGRID" "$SENDGRID_API_KEY"
substitute "ORIGINS" "$ALLOWED_ORIGINS"
substitute "MZ_ID" "$MZONE_CLIENT_ID"
substitute "MZ_SECRET" "$MZONE_CLIENT_SECRET"
substitute "MZ_USER" "$MZONE_USERNAME"
substitute "MZ_PASS" "$MZONE_PASSWORD"
substitute "EMAIL" "$FROM_EMAIL"

echo "✓ Secrets injected"
SUBSTITUTION

log_success "Secrets injected successfully"

################################################################################
# Sync Code
################################################################################

log_header "Syncing Code to Server"

log_step "Syncing gps-tracker/ to $SSH_USER@$SSH_HOST:$REMOTE_BASE_DIR/..."

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
    "$PROJECT_ROOT/gps-tracker/" \
    "$SSH_USER@$SSH_HOST:$REMOTE_BASE_DIR/" || die "rsync failed"

log_success "Code synced successfully"

################################################################################
# Deploy Containers
################################################################################

log_header "Deploying Containers"

log_step "Deploying to server..."

ssh -o StrictHostKeyChecking=no "$SSH_USER@$SSH_HOST" bash << 'DEPLOYEOF'
set -e

cd ~/pinplot/gps-tracker

# Verify .env exists
if [ ! -f backend/.env ]; then
    echo "✗ .env file not found!" >&2
    exit 1
fi
echo "✓ .env file verified"

# Verify .env has content
if [ ! -s backend/.env ]; then
    echo "✗ .env file is empty!" >&2
    exit 1
fi
echo "✓ .env file has content"

# Stop old containers
echo "Stopping old containers..."
docker compose down --remove-orphans || true

# Remove old UI images to force rebuild
echo "Removing stale UI images..."
docker images --format '{{.Repository}}:{{.Tag}}' \
    | grep -E 'flutter|admin' \
    | xargs -r docker rmi -f 2>/dev/null || true

# Build containers
echo "Building containers (no cache for UI updates)..."
docker compose build --no-cache flutter-web || exit 1
docker compose build --no-cache admin-portal || exit 1
echo "✓ UI containers built"

echo "Building application containers..."
docker compose build backend customer || exit 1
echo "✓ App containers built"

# Start services
echo "Starting all services..."
docker compose up -d || {
    echo "✗ Failed to start containers" >&2
    docker compose logs --tail 50
    exit 1
}
echo "✓ Containers started"

# Wait for stabilization
echo "Waiting for services to stabilize..."
sleep 20

# Show status
echo ""
echo "Container Status:"
docker compose ps

# Test backend health
echo ""
echo "Testing backend health..."
health_check(){
    for i in {1..30}; do
        if docker exec pinplot_backend curl -s http://localhost:8000/api/health >/dev/null 2>&1; then
            echo "✓ Backend is healthy"
            return 0
        fi
        echo "  Checking... ($i/30)"
        sleep 1
    done
    echo "⚠ Backend still initializing (check logs)"
    return 0
}
health_check
DEPLOYEOF

log_success "Deployment completed successfully"

################################################################################
# Summary
################################################################################

log_header "Deployment Summary"

echo ""
echo "✓ All services deployed to production"
echo ""
echo "Access points:"
echo "  Backend API:    http://$SSH_HOST:8001/api/health"
echo "  Admin Portal:   http://$SSH_HOST:3010/"
echo "  Customer UI:    http://$SSH_HOST:3011/"
echo "  Flutter Web:    http://$SSH_HOST:3012/"
echo ""
