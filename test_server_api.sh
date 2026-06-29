#!/bin/bash
# Test Floor Plan Setup API on pinplot.me server
# Usage: ./test_server_api.sh

echo "=== Floor Plan Setup Server API Test ==="
echo ""

# 1. Test if buildings endpoint exists
echo "1️⃣ Testing /api/portal/buildings endpoint..."
RESPONSE=$(curl -s -w "\nHTTP_STATUS:%{http_code}" https://pinplot.me/api/portal/buildings)
HTTP_STATUS=$(echo "$RESPONSE" | grep HTTP_STATUS | cut -d: -f2)
BODY=$(echo "$RESPONSE" | grep -v HTTP_STATUS)

echo "Status: $HTTP_STATUS"
echo "Response: $BODY"
echo ""

if [ "$HTTP_STATUS" = "401" ]; then
    echo "✅ Endpoint exists but requires authentication (expected)"
    echo "➡️ Need to test with real user token"
elif [ "$HTTP_STATUS" = "404" ]; then
    echo "❌ Endpoint not found! Backend routing issue"
    exit 1
elif [ "$HTTP_STATUS" = "200" ]; then
    echo "⚠️ Endpoint returns 200 without auth (unexpected)"
else
    echo "❓ Unexpected status: $HTTP_STATUS"
fi

echo ""
echo "2️⃣ Checking if integration script exists in deployed HTML..."
curl -s https://pinplot.me/ | grep -q "Floor Plan Sketch Database Integration"
if [ $? -eq 0 ]; then
    echo "✅ Integration script found in HTML"
else
    echo "❌ Integration script NOT found in HTML"
    exit 1
fi

echo ""
echo "3️⃣ Checking if Setup button exists..."
curl -s https://pinplot.me/ | grep -q 'id="setupBtn"'
if [ $? -eq 0 ]; then
    echo "✅ Setup button found in HTML"
else
    echo "❌ Setup button NOT found in HTML"
    exit 1
fi

echo ""
echo "4️⃣ Checking if new logging code deployed..."
curl -s https://pinplot.me/ | grep -q '\[Floor Plan\]'
if [ $? -eq 0 ]; then
    echo "✅ New logging code deployed"
    
    # Count how many log statements
    LOG_COUNT=$(curl -s https://pinplot.me/ | grep -o '\[Floor Plan\]' | wc -l)
    echo "   Found $LOG_COUNT log statements"
else
    echo "❌ New logging code NOT deployed yet"
    echo "➡️ Wait for GitHub Actions to complete"
fi

echo ""
echo "5️⃣ Checking if loadBuildingsAndFloors has error handling..."
curl -s https://pinplot.me/ | grep -q 'loadBuildingsAndFloors() called'
if [ $? -eq 0 ]; then
    echo "✅ New loadBuildingsAndFloors logging found"
else
    echo "❌ Old loadBuildingsAndFloors (no logging)"
fi

echo ""
echo "6️⃣ Checking if apiFetch availability check exists..."
curl -s https://pinplot.me/ | grep -q 'apiFetch function not found'
if [ $? -eq 0 ]; then
    echo "✅ apiFetch availability check deployed"
else
    echo "❌ apiFetch check not deployed"
fi

echo ""
echo "=== Summary ==="
echo "Run this to test with actual auth token:"
echo ""
echo "TOKEN='your_jwt_token_here'"
echo "curl -H 'Authorization: Bearer \$TOKEN' https://pinplot.me/api/portal/buildings"
