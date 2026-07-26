#!/bin/bash
#
# Real-time Pareto Anywhere monitoring
# Shows raddec events as ESP32 gateways send them
#

set -euo pipefail

echo "🔍 Monitoring Pareto Anywhere for BLE asset detections..."
echo "📡 Pareto is listening on UDP ports: 50000 (reel), 50001 (barnowl), 50010 (huawei)"
echo ""
echo "=== Pareto Container Status ==="
docker ps --filter 'name=pareto' --format 'table {{.Names}}\t{{.Status}}'
echo ""

echo "=== Live Log Stream (Ctrl+C to stop) ==="
echo "Looking for: raddec events, device IDs, receiver IDs..."
echo ""

# Follow logs and highlight key events
docker logs pinplot_pareto_anywhere --follow --tail 50 2>&1 | \
  grep --line-buffered -E 'raddec|receiver|transmitter|device|event|connection|websocket|client' || \
  docker logs pinplot_pareto_anywhere --follow --tail 50
