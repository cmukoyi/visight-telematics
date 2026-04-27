#!/bin/bash

# Geofence Notification Mock Test Script
# This script tests the geofence alert system by simulating tracker locations
# outside and inside POI geofences to trigger notifications.

echo "========================================="
echo "Geofence Notification Mock Test"
echo "========================================="
echo ""

# Configuration
API_URL="http://localhost:8000"
TRACKER_ID="647b512f-92b8-4184-8a82-4321365d6336"

# Get auth token (replace with your actual credentials)
echo "Step 1: Login to get auth token..."
echo "Please enter your email:"
read EMAIL
echo "Please enter your password:"
read -s PASSWORD
echo ""

LOGIN_RESPONSE=$(curl -s -X POST "$API_URL/api/login" \
  -H "Content-Type: application/json" \
  -d "{\"email\":\"$EMAIL\",\"password\":\"$PASSWORD\"}")

TOKEN=$(echo $LOGIN_RESPONSE | grep -o '"access_token":"[^"]*' | cut -d'"' -f4)

if [ -z "$TOKEN" ]; then
  echo "❌ Login failed. Please check your credentials."
  exit 1
fi

echo "✅ Login successful!"
echo ""

# POI Information
echo "========================================="
echo "Test Configuration:"
echo "========================================="
echo "Tracker ID: $TRACKER_ID"
echo "Armed POIs at location: 51.375896, -0.194597 (radius: 150m)"
echo "  - 'Laptop Delivery' (single POI)"
echo "  - 'Test Delivery' (route POI)"
echo ""

# Test 1: Location OUTSIDE geofence (should trigger EXIT event)
echo "========================================="
echo "Test 1: Location OUTSIDE geofence"
echo "========================================="
echo "Testing with coordinates 1km away from POI origin..."
echo "Test coordinates: 51.385, -0.205"
echo ""

OUTSIDE_RESPONSE=$(curl -s -X POST "$API_URL/api/v1/test/mock-location" \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer $TOKEN" \
  -d "{
    \"tracker_id\": \"$TRACKER_ID\",
    \"latitude\": 51.385,
    \"longitude\": -0.205
  }")

echo "Response:"
echo $OUTSIDE_RESPONSE | python3 -m json.tool
echo ""

ALERTS_COUNT=$(echo $OUTSIDE_RESPONSE | grep -o '"alerts_triggered":[0-9]*' | cut -d':' -f2)
echo "✅ Alerts triggered: $ALERTS_COUNT"
echo ""

# Wait a bit before next test (debouncing)
echo "Waiting 3 seconds before next test (debouncing)..."
sleep 3
echo ""

# Test 2: Location INSIDE geofence (should trigger ENTRY event)
echo "========================================="
echo "Test 2: Location INSIDE geofence"
echo "========================================="
echo "Testing with coordinates inside POI radius..."
echo "Test coordinates: 51.375896, -0.194597 (exact POI location)"
echo ""

INSIDE_RESPONSE=$(curl -s -X POST "$API_URL/api/v1/test/mock-location" \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer $TOKEN" \
  -d "{
    \"tracker_id\": \"$TRACKER_ID\",
    \"latitude\": 51.375896,
    \"longitude\": -0.194597
  }")

echo "Response:"
echo $INSIDE_RESPONSE | python3 -m json.tool
echo ""

ALERTS_COUNT=$(echo $INSIDE_RESPONSE | grep -o '"alerts_triggered":[0-9]*' | cut -d':' -f2)
echo "✅ Alerts triggered: $ALERTS_COUNT"
echo ""

# Check MailHog
echo "========================================="
echo "Next Steps:"
echo "========================================="
echo "1. Check MailHog for email notifications:"
echo "   Open browser: http://localhost:8025"
echo ""
echo "2. Check mobile app Alerts screen to see notifications"
echo ""
echo "3. Query database to see alert records:"
echo "   docker exec ble_tracker_db psql -U ble_user -d ble_tracker \\"
echo "     -c \"SELECT id, event_type, latitude, longitude, is_read, created_at \\"
echo "        FROM geofence_alerts ORDER BY created_at DESC LIMIT 5;\""
echo ""
echo "========================================="
echo "Test Complete!"
echo "========================================="
