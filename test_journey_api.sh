#!/bin/bash

# Test Journey API Endpoints
# This script tests the endpoints used by Plot All Journeys feature

echo "================================================"
echo "Journey API Endpoint Test"
echo "================================================"
echo ""

# Configuration
BASE_URL="https://portal.pinplot.co"
# You'll need to get these from browser cookies after logging in
SESSION_COOKIE="your-session-cookie-here"
IMEI="781950640095475"  # Example IMEI

echo "1. Testing GET /api/portal/journeys (list journeys for asset)"
echo "   URL: ${BASE_URL}/api/portal/journeys?imei=${IMEI}&start_date=2026-07-06&end_date=2026-07-13&limit=50&offset=0"
echo ""

curl -s -X GET \
  "${BASE_URL}/api/portal/journeys?imei=${IMEI}&start_date=2026-07-06&end_date=2026-07-13&limit=50&offset=0" \
  -H "Cookie: session=${SESSION_COOKIE}" \
  -H "Accept: application/json" | jq -r '.journeys | length' 2>/dev/null || echo "Failed to fetch journeys"

JOURNEY_COUNT=$(curl -s -X GET \
  "${BASE_URL}/api/portal/journeys?imei=${IMEI}&start_date=2026-07-06&end_date=2026-07-13&limit=50&offset=0" \
  -H "Cookie: session=${SESSION_COOKIE}" \
  -H "Accept: application/json" | jq -r '.journeys | length' 2>/dev/null)

echo "   Result: Found ${JOURNEY_COUNT} journeys"
echo ""

# Get first journey ID
JOURNEY_ID=$(curl -s -X GET \
  "${BASE_URL}/api/portal/journeys?imei=${IMEI}&start_date=2026-07-06&end_date=2026-07-13&limit=50&offset=0" \
  -H "Cookie: session=${SESSION_COOKIE}" \
  -H "Accept: application/json" | jq -r '.journeys[0].id' 2>/dev/null)

if [ "$JOURNEY_ID" != "null" ] && [ -n "$JOURNEY_ID" ]; then
  echo "2. Testing GET /api/portal/journeys/{id} (get journey details)"
  echo "   Journey ID: ${JOURNEY_ID}"
  echo "   URL: ${BASE_URL}/api/portal/journeys/${JOURNEY_ID}"
  echo ""
  
  curl -s -X GET \
    "${BASE_URL}/api/portal/journeys/${JOURNEY_ID}" \
    -H "Cookie: session=${SESSION_COOKIE}" \
    -H "Accept: application/json" | jq -r '.legs | length, .stationaries | length' 2>/dev/null || echo "Failed to fetch journey details"
  
  LEG_COUNT=$(curl -s -X GET \
    "${BASE_URL}/api/portal/journeys/${JOURNEY_ID}" \
    -H "Cookie: session=${SESSION_COOKIE}" \
    -H "Accept: application/json" | jq -r '.legs | length' 2>/dev/null)
  
  echo "   Result: Journey has ${LEG_COUNT} legs"
  echo ""
  
  echo "3. Testing GET /api/portal/journeys/{id}/path (get path geometry)"
  echo "   URL: ${BASE_URL}/api/portal/journeys/${JOURNEY_ID}/path"
  echo ""
  
  curl -s -X GET \
    "${BASE_URL}/api/portal/journeys/${JOURNEY_ID}/path" \
    -H "Cookie: session=${SESSION_COOKIE}" \
    -H "Accept: application/json" | jq -r '.features | length' 2>/dev/null || echo "Failed to fetch path"
  
  FEATURE_COUNT=$(curl -s -X GET \
    "${BASE_URL}/api/portal/journeys/${JOURNEY_ID}/path" \
    -H "Cookie: session=${SESSION_COOKIE}" \
    -H "Accept: application/json" | jq -r '.features | length' 2>/dev/null)
  
  echo "   Result: Found ${FEATURE_COUNT} path features (legs)"
  echo ""
else
  echo "   ERROR: No journeys found to test"
fi

echo "================================================"
echo "Test Complete"
echo "================================================"
echo ""
echo "INSTRUCTIONS TO RUN THIS TEST:"
echo "1. Log in to https://portal.pinplot.co"
echo "2. Open browser DevTools (F12)"
echo "3. Go to Application > Cookies"
echo "4. Copy the 'session' cookie value"
echo "5. Replace 'your-session-cookie-here' in this script"
echo "6. Run: chmod +x test_journey_api.sh && ./test_journey_api.sh"
