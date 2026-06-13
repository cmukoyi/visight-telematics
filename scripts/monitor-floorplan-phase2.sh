#!/bin/bash
# ─────────────────────────────────────────────────────────────────────────────
# Phase 2 Dark Launch Monitoring Script
# ─────────────────────────────────────────────────────────────────────────────
# Run this every 4-6 hours during the 24-48h observation period.
# Usage: ssh root@pinplot-server 'bash -s' < scripts/monitor-floorplan-phase2.sh
#
# Exit codes:
#   0 = all checks passed
#   1 = warning detected (investigate but not critical)
#   2 = critical issue (immediate rollback recommended)
# ─────────────────────────────────────────────────────────────────────────────

set -euo pipefail

COMPOSE_DIR="/root/pinplot/gps-tracker"
DB_USER="pinplot_db_user"
DB_NAME="pinplot_db"

WARN_EXIT=0
CRIT_EXIT=0

echo "════════════════════════════════════════════════════════════════════════════"
echo "  Floorplan Phase 2 Monitoring — $(date '+%Y-%m-%d %H:%M:%S %Z')"
echo "════════════════════════════════════════════════════════════════════════════"
echo ""

# ─── Bridge Connection ───────────────────────────────────────────────────────
echo "🔌 Bridge Connection Status"
echo "────────────────────────────────────────────────────────────────────────────"

if docker logs pinplot_backend 2>&1 | tail -100 | grep -q "pareto_bridge: connected"; then
    echo "  ✅ Bridge connected to Pareto"
    LAST_CONN=$(docker logs pinplot_backend 2>&1 | grep "pareto_bridge: connected" | tail -1)
    echo "     Last: $LAST_CONN"
else
    echo "  ❌ Bridge NOT connected (check logs)"
    CRIT_EXIT=2
fi

RECONNECT_COUNT=$(docker logs pinplot_backend 2>&1 | grep -c "pareto_bridge: reconnecting" || echo "0")
echo "  📊 Reconnect count: $RECONNECT_COUNT"
if [ "$RECONNECT_COUNT" -gt 10 ]; then
    echo "     ⚠️  High reconnect count (>10) — investigate network stability"
    WARN_EXIT=1
fi
echo ""

# ─── Container Health ────────────────────────────────────────────────────────
echo "📦 Container Stability"
echo "────────────────────────────────────────────────────────────────────────────"

BACKEND_RESTARTS=$(docker inspect pinplot_backend --format='{{.RestartCount}}' 2>/dev/null || echo "N/A")
PARETO_RESTARTS=$(docker inspect pinplot_pareto_anywhere --format='{{.RestartCount}}' 2>/dev/null || echo "N/A")

echo "  Backend restarts:  $BACKEND_RESTARTS"
echo "  Pareto restarts:   $PARETO_RESTARTS"

if [ "$BACKEND_RESTARTS" != "0" ] && [ "$BACKEND_RESTARTS" != "N/A" ]; then
    echo "     ⚠️  Backend has restarted — check logs for crashes"
    WARN_EXIT=1
fi

if [ "$PARETO_RESTARTS" != "0" ] && [ "$PARETO_RESTARTS" != "N/A" ]; then
    echo "     ⚠️  Pareto has restarted — check logs"
    WARN_EXIT=1
fi

PARETO_STATUS=$(docker ps --filter name=pinplot_pareto_anywhere --format '{{.Status}}')
echo "  Pareto status:     $PARETO_STATUS"
if echo "$PARETO_STATUS" | grep -q "unhealthy"; then
    echo "     ℹ️  Healthcheck failing but bridge functional (known issue)"
fi
echo ""

# ─── Data Ingestion ──────────────────────────────────────────────────────────
echo "💾 Data Ingestion"
echo "────────────────────────────────────────────────────────────────────────────"

DB_STATS=$(docker exec pinplot_db psql -U "$DB_USER" "$DB_NAME" -t -c \
  "SELECT 
     COUNT(*) as total,
     COUNT(CASE WHEN status='online' THEN 1 END) as online,
     COUNT(CASE WHEN last_seen > NOW() - INTERVAL '5 minutes' THEN 1 END) as recent,
     MAX(last_seen) as last_update
   FROM tag_indoor_positions;" | tr -s ' ')

TOTAL=$(echo "$DB_STATS" | awk '{print $1}')
ONLINE=$(echo "$DB_STATS" | awk '{print $2}')
RECENT=$(echo "$DB_STATS" | awk '{print $3}')
LAST_UPDATE=$(echo "$DB_STATS" | awk '{print $4, $5}')

echo "  Total positions:   $TOTAL"
echo "  Online tags:       $ONLINE"
echo "  Recent (5m):       $RECENT"
echo "  Last update:       $LAST_UPDATE"

if [ "$TOTAL" = "0" ]; then
    echo "     ℹ️  No data yet (no gateways powered on or bridge just started)"
else
    # Check if data is stale (no updates in last hour)
    LAST_TS=$(docker exec pinplot_db psql -U "$DB_USER" "$DB_NAME" -t -c \
      "SELECT EXTRACT(EPOCH FROM (NOW() - MAX(last_seen))) FROM tag_indoor_positions;")
    STALE_SEC=$(echo "$LAST_TS" | tr -d ' ' | cut -d. -f1)
    
    if [ "$STALE_SEC" -gt 3600 ]; then
        STALE_HOURS=$((STALE_SEC / 3600))
        echo "     ⚠️  No new data for ${STALE_HOURS}h — are gateways online?"
        WARN_EXIT=1
    fi
fi
echo ""

# ─── Database Performance ────────────────────────────────────────────────────
echo "⚡ Database Performance"
echo "────────────────────────────────────────────────────────────────────────────"

DB_PERF=$(docker exec pinplot_db psql -U "$DB_USER" "$DB_NAME" -t -c \
  "SELECT n_tup_ins, n_tup_upd, n_tup_del 
   FROM pg_stat_user_tables 
   WHERE relname = 'tag_indoor_positions';" | tr -s ' ')

INSERTS=$(echo "$DB_PERF" | awk '{print $1}')
UPDATES=$(echo "$DB_PERF" | awk '{print $2}')
DELETES=$(echo "$DB_PERF" | awk '{print $3}')

echo "  Inserts:  $INSERTS"
echo "  Updates:  $UPDATES"
echo "  Deletes:  $DELETES"
echo ""

# ─── Error Log Sweep ─────────────────────────────────────────────────────────
echo "🔍 Error Log Sweep (last 100 lines)"
echo "────────────────────────────────────────────────────────────────────────────"

ERROR_COUNT=$(docker logs pinplot_backend 2>&1 | tail -100 | grep -iE "error|exception|traceback" | grep -v "error_code\":0" | wc -l | tr -d ' ')
echo "  Backend errors:    $ERROR_COUNT"

if [ "$ERROR_COUNT" -gt 0 ]; then
    echo "     ⚠️  Errors detected in backend logs:"
    docker logs pinplot_backend 2>&1 | tail -100 | grep -iE "error|exception" | head -5 | sed 's/^/       /'
    WARN_EXIT=1
fi

PARETO_ERROR_COUNT=$(docker logs pinplot_pareto_anywhere 2>&1 | tail -50 | grep -iE "error|exception" | wc -l | tr -d ' ')
echo "  Pareto errors:     $PARETO_ERROR_COUNT"

if [ "$PARETO_ERROR_COUNT" -gt 0 ]; then
    echo "     ⚠️  Errors in Pareto logs:"
    docker logs pinplot_pareto_anywhere 2>&1 | tail -50 | grep -iE "error" | head -3 | sed 's/^/       /'
    WARN_EXIT=1
fi
echo ""

# ─── Feature Gate Status ─────────────────────────────────────────────────────
echo "🚦 Feature Gate Status"
echo "────────────────────────────────────────────────────────────────────────────"

if docker logs pinplot_backend 2>&1 | grep -q "tenant feature kill-switch active for: floorplan"; then
    echo "  ✅ Feature gate active (floorplan disabled for portal)"
else
    echo "  ⚠️  Feature gate NOT active — portal endpoints are live!"
    WARN_EXIT=1
fi

ENV_DISABLED=$(grep TENANT_DISABLED_FEATURES /root/pinplot/gps-tracker/backend/.env | cut -d= -f2)
ENV_BRIDGE=$(grep FLOORPLAN_BRIDGE_ENABLED /root/pinplot/gps-tracker/backend/.env | cut -d= -f2)

echo "  .env config:"
echo "     TENANT_DISABLED_FEATURES=$ENV_DISABLED"
echo "     FLOORPLAN_BRIDGE_ENABLED=$ENV_BRIDGE"
echo ""

# ─── Summary ─────────────────────────────────────────────────────────────────
echo "════════════════════════════════════════════════════════════════════════════"
if [ $CRIT_EXIT -eq 2 ]; then
    echo "  ❌ CRITICAL ISSUE DETECTED — Immediate action required"
    echo "     Review errors above and consider rollback:"
    echo "     cd /root/pinplot/gps-tracker && docker compose restart backend"
    exit 2
elif [ $WARN_EXIT -eq 1 ]; then
    echo "  ⚠️  WARNING — Non-critical issues detected"
    echo "     Review warnings above. System operational but needs attention."
    exit 1
else
    echo "  ✅ ALL CHECKS PASSED — Phase 2 running smoothly"
    echo "     Continue monitoring every 4-6 hours for 24-48h."
    exit 0
fi
