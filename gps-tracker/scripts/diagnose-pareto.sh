#!/bin/bash
#
# Pareto Anywhere diagnostic - check if ESP32 gateways are sending data
#

set -euo pipefail

echo "📊 Pareto Anywhere Diagnostic Report"
echo "===================================="
echo ""

echo "1️⃣  Container Status"
echo "-------------------"
docker ps --filter 'name=pareto' --format 'table {{.Names}}\t{{.Status}}\t{{.Ports}}'
echo ""

echo "2️⃣  Listening Ports"
echo "------------------"
docker logs pinplot_pareto_anywhere 2>&1 | grep -i 'listening\|running' | head -10
echo ""

echo "3️⃣  Recent Activity (last 50 log lines)"
echo "---------------------------------------"
ACTIVITY=$(docker logs pinplot_pareto_anywhere --tail 50 2>&1 | grep -iE 'raddec|receiver|transmitter|device')
if [ -z "$ACTIVITY" ]; then
    echo "⚠️  NO ACTIVITY DETECTED"
    echo "   Pareto is running but has not received any raddec events."
    echo ""
    echo "   Possible causes:"
    echo "   - ESP32 gateways are not configured to send to this server"
    echo "   - ESP32 gateways are powered off or not detecting any BLE tags"
    echo "   - Network firewall blocking UDP ports 50000-50010"
    echo "   - Wrong IP address configured in ESP32 firmware"
else
    echo "$ACTIVITY"
fi
echo ""

echo "4️⃣  Backend Bridge Status"
echo "------------------------"
docker logs pinplot_backend --tail 30 2>&1 | grep -i 'pareto' | tail -5
echo ""

echo "5️⃣  Database - Indoor Positions"
echo "-------------------------------"
docker exec pinplot_backend python -c "
from app.database import SessionLocal
from app.models import TagIndoorPosition
db = SessionLocal()
try:
    count = db.query(TagIndoorPosition).count()
    print(f'Total indoor positions in DB: {count}')
    if count > 0:
        latest = db.query(TagIndoorPosition).order_by(TagIndoorPosition.timestamp.desc()).first()
        print(f'Latest position: tag_id={latest.tag_id}, floor_key={latest.floor_key}, timestamp={latest.timestamp}')
finally:
    db.close()
"
echo ""

echo "6️⃣  Web Interface Test"
echo "----------------------"
HTTP_STATUS=$(curl -s -o /dev/null -w "%{http_code}" http://localhost:3001/ || echo "FAILED")
if [ "$HTTP_STATUS" = "200" ]; then
    echo "✅ Web interface responding (HTTP $HTTP_STATUS)"
else
    echo "❌ Web interface not responding (HTTP $HTTP_STATUS)"
fi
echo ""

echo "===================================="
echo "Next Steps:"
echo ""
echo "To monitor live:"
echo "  ./scripts/monitor-pareto-realtime.sh"
echo ""
echo "To test ESP32 connectivity:"
echo "  1. Check ESP32 firmware configuration:"
echo "     - Server IP should be: $(hostname -I | awk '{print $1}')"
echo "     - Server Port should be: 50001 (for barnowl)"
echo "  2. Verify ESP32 is powered on and detecting BLE tags"
echo "  3. Check firewall allows UDP 50000-50010 inbound"
echo ""
