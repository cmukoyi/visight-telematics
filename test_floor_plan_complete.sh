#!/bin/bash
# Complete Floor Plan diagnostic - run on pinplot.me server via SSH
# Usage: ssh root@pinplot.me 'bash -s' < test_floor_plan_complete.sh

echo "=== Floor Plan Complete Server Diagnostic ==="
echo "Server: $(hostname)"
echo "Time: $(date)"
echo ""

# 1. Check if backend is running
echo "1️⃣ Checking backend service..."
if systemctl is-active --quiet uvicorn-gps; then
    echo "✅ Backend service running"
else
    echo "❌ Backend service NOT running"
    echo "   Run: systemctl status uvicorn-gps"
fi

# 2. Check if backend responds
echo ""
echo "2️⃣ Testing backend health..."
if curl -sf http://localhost:8001/api/health >/dev/null 2>&1; then
    echo "✅ Backend API responding"
else
    echo "❌ Backend API not responding"
fi

# 3. Test buildings endpoint (without auth - should return 401)
echo ""
echo "3️⃣ Testing /api/portal/buildings..."
RESPONSE=$(curl -s -w "\nHTTP:%{http_code}" http://localhost:8001/api/portal/buildings)
STATUS=$(echo "$RESPONSE" | grep "HTTP:" | cut -d: -f2)
BODY=$(echo "$RESPONSE" | grep -v "HTTP:")

if [ "$STATUS" = "401" ]; then
    echo "✅ Endpoint exists and requires auth (correct)"
    echo "   Response: $BODY"
elif [ "$STATUS" = "404" ]; then
    echo "❌ Endpoint NOT FOUND - routing problem"
elif [ "$STATUS" = "200" ]; then
    echo "⚠️ Endpoint returns 200 without auth (unexpected)"
else
    echo "❓ Status: $STATUS"
    echo "   Response: $BODY"
fi

# 4. Check customer-dashboard service
echo ""
echo "4️⃣ Checking customer-dashboard service..."
if netstat -tuln | grep -q ":3011 "; then
    echo "✅ Customer dashboard service on port 3011"
else
    echo "❌ Customer dashboard NOT running on port 3011"
fi

# 5. Test customer dashboard HTML
echo ""
echo "5️⃣ Testing customer dashboard HTML..."
if curl -sf http://localhost:3011/ | grep -q "Floor Plan"; then
    echo "✅ Customer dashboard serving Floor Plan content"
else
    echo "❌ Customer dashboard missing Floor Plan content"
fi

# 6. Check for integration script
echo ""
echo "6️⃣ Checking integration script..."
if curl -sf http://localhost:3011/ | grep -q "Floor Plan Sketch Database Integration"; then
    echo "✅ Integration script present"
    
    # Count log statements
    LOG_COUNT=$(curl -sf http://localhost:3011/ | grep -c "\[Floor Plan\]")
    echo "   Found $LOG_COUNT [Floor Plan] log statements"
    
    # Check specific features
    if curl -sf http://localhost:3011/ | grep -q "apiFetch function not found"; then
        echo "   ✅ apiFetch availability check present"
    fi
    
    if curl -sf http://localhost:3011/ | grep -q "Setup button clicked"; then
        echo "   ✅ Setup button logging present"
    fi
    
    if curl -sf http://localhost:3011/ | grep -q "loadBuildingsAndFloors() called"; then
        echo "   ✅ loadBuildingsAndFloors logging present"
    fi
else
    echo "❌ Integration script NOT found"
fi

# 7. Check for Setup button
echo ""
echo "7️⃣ Checking Setup button..."
if curl -sf http://localhost:3011/ | grep -q 'id="setupBtn"'; then
    echo "✅ Setup button exists in HTML"
else
    echo "❌ Setup button NOT found"
fi

# 8. Check for modals
echo ""
echo "8️⃣ Checking modals..."
if curl -sf http://localhost:3011/ | grep -q 'id="sketchSetupModal"'; then
    echo "✅ Setup modal exists"
else
    echo "❌ Setup modal NOT found"
fi

# 9. Check nginx is routing correctly
echo ""
echo "9️⃣ Checking nginx routing..."
if curl -sf https://pinplot.me/customer/ | grep -q "Floor Plan"; then
    echo "✅ Nginx routing /customer/ correctly"
else
    echo "❌ Nginx routing problem"
fi

echo ""
echo "=== Summary ==="
echo "All services checked. If everything is ✅ above, then:"
echo ""
echo "Next step: Test in browser"
echo "1. Open: https://pinplot.me/customer/"
echo "2. Login as a user"
echo "3. Go to Floor Plan Sketch tab"
echo "4. Open browser console (F12)"
echo "5. Click Setup button"
echo "6. Look for '[Floor Plan]' log messages"
echo ""
echo "If you see 'apiFetch function not found' error:"
echo "  → The script runs BEFORE apiFetch is defined"
echo "  → Need to move integration script to END of HTML"
echo ""
echo "If you see 'Setup button clicked' but no modal:"
echo "  → The loadBuildingsAndFloors() function is failing"
echo "  → Check the specific error message after 'Loading buildings'"
