#!/bin/bash
set -e
# Source .env file to ensure all variables are available
if [ -f /app/.env ]; then
    set -a
    source /app/.env
    set +a
fi

# Wait for DATABASE_URL to be set (with timeout)
echo "⏳ Waiting for environment variables..."
MAX_WAIT=30
ELAPSED=0
while [ -z "$DATABASE_URL" ] && [ $ELAPSED -lt $MAX_WAIT ]; do
    sleep 1
    ELAPSED=$((ELAPSED + 1))
    if [ $((ELAPSED % 5)) -eq 0 ]; then
        echo "   Still waiting... ($ELAPSED/$MAX_WAIT seconds)"
    fi
done

if [ -z "$DATABASE_URL" ]; then
    echo "❌ ERROR: DATABASE_URL not set after $MAX_WAIT seconds"
    exit 1
fi

echo "✅ DATABASE_URL is set"echo "� Running database migrations..."
alembic upgrade head

echo "�🔧 Initializing admin user..."
python init_admin.py || true

echo "🚀 Starting backend server..."
exec "$@"
