#!/bin/bash
# fix_migration_state.sh - Detect and stamp database to correct migration state
# This fixes the worker crashloop issue caused by migration state mismatch

set -e

echo "🔍 Detecting current database state..."

# Check if webhook_logs table exists
WEBHOOK_TABLE_EXISTS=$(docker exec pinplot_db psql -U pinplot_db_user -d pinplot_db -t -c \
  "SELECT EXISTS (SELECT 1 FROM information_schema.tables WHERE table_name = 'webhook_logs');" | tr -d ' ')

# Check if tracksolid composite index exists
TRACKSOLID_INDEX_EXISTS=$(docker exec pinplot_db psql -U pinplot_db_user -d pinplot_db -t -c \
  "SELECT EXISTS (SELECT 1 FROM pg_indexes WHERE indexname = 'idx_tracksolid_imei_recorded');" | tr -d ' ')

# Check if sensor data columns exist
SENSOR_COLUMNS_EXIST=$(docker exec pinplot_db psql -U pinplot_db_user -d pinplot_db -t -c \
  "SELECT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name = 'device_positions' AND column_name = 'temperature');" | tr -d ' ')

# Determine correct revision
if [ "$SENSOR_COLUMNS_EXIST" = "t" ]; then
  CORRECT_REVISION="add_sensor_data"
  echo "✅ Database has sensor data columns - revision should be: add_sensor_data"
elif [ "$TRACKSOLID_INDEX_EXISTS" = "t" ]; then
  CORRECT_REVISION="tracksolid_composite_idx"
  echo "✅ Database has tracksolid index - revision should be: tracksolid_composite_idx"
elif [ "$WEBHOOK_TABLE_EXISTS" = "t" ]; then
  CORRECT_REVISION="add_webhook_logs"
  echo "✅ Database has webhook_logs table - revision should be: add_webhook_logs"
else
  CORRECT_REVISION="tenant_feature_control"
  echo "⚠️  Database missing recent tables - revision should be: tenant_feature_control"
fi

# Get current revision
CURRENT_REVISION=$(docker exec pinplot_db psql -U pinplot_db_user -d pinplot_db -t -c \
  "SELECT version_num FROM alembic_version;" | tr -d ' ')

echo "📌 Current alembic_version: $CURRENT_REVISION"
echo "📌 Correct alembic_version: $CORRECT_REVISION"

if [ "$CURRENT_REVISION" = "$CORRECT_REVISION" ]; then
  echo "✅ Migration state is correct! No action needed."
  exit 0
fi

echo ""
echo "🔧 Fixing migration state..."
docker exec pinplot_db psql -U pinplot_db_user -d pinplot_db -c \
  "UPDATE alembic_version SET version_num = '$CORRECT_REVISION';"

echo "✅ Migration state fixed!"
echo ""
echo "🔄 Restarting worker container..."
cd /root/pinplot/gps-tracker
docker compose up -d worker

echo ""
echo "✅ Done! Worker should now start successfully."
echo ""
echo "Verify with: docker compose ps"
