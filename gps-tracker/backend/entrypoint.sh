#!/bin/bash
set -e

# Database migrations (DATABASE_URL passed via docker-compose env_file)
echo "� Running database migrations..."
alembic upgrade head

echo "�🔧 Initializing admin user..."
python init_admin.py || true

echo "🚀 Starting backend server..."
exec "$@"
