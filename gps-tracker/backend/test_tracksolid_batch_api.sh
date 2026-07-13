#!/bin/bash
# Test TrackSolid batch location API with curl
# Run this to verify API calls work BEFORE deploying

set -e

echo "🔧 Testing TrackSolid Batch Location API"
echo ""

# Load credentials from .env
if [ -f .env ]; then
    export $(grep -v '^#' .env | xargs)
else
    echo "❌ .env file not found!"
    exit 1
fi

# Check required env vars
if [ -z "$TRACKSOLID_ACCOUNT" ] || [ -z "$TRACKSOLID_PASSWORD" ] || [ -z "$TRACKSOLID_APP_KEY" ] || [ -z "$TRACKSOLID_APP_SECRET" ]; then
    echo "❌ Missing TrackSolid credentials in .env"
    exit 1
fi

echo "📋 Using account: $TRACKSOLID_ACCOUNT"
echo ""

# Step 1: Get OAuth token
echo "Step 1: Getting OAuth token..."
PASSWORD_MD5=$(echo -n "$TRACKSOLID_PASSWORD" | md5sum | awk '{print $1}')
TIMESTAMP=$(date -u +"%Y-%m-%d %H:%M:%S")

# Build token params (alphabetically sorted for signature)
TOKEN_PARAMS="app_key${TRACKSOLID_APP_KEY}expires_in7200formatjsonmethodjimi.oauth.token.getsign_methodmd5timestamp${TIMESTAMP}user_id${TRACKSOLID_ACCOUNT}user_pwd_md5${PASSWORD_MD5}v0.9"
TOKEN_SIGN=$(echo -n "${TRACKSOLID_APP_SECRET}${TOKEN_PARAMS}${TRACKSOLID_APP_SECRET}" | md5sum | awk '{print toupper($1)}')

TOKEN_RESPONSE=$(curl -s -X POST "https://eu-open.tracksolidpro.com/route/rest" \
  -d "app_key=${TRACKSOLID_APP_KEY}" \
  -d "expires_in=7200" \
  -d "format=json" \
  -d "method=jimi.oauth.token.get" \
  -d "sign_method=md5" \
  -d "timestamp=${TIMESTAMP}" \
  -d "user_id=${TRACKSOLID_ACCOUNT}" \
  -d "user_pwd_md5=${PASSWORD_MD5}" \
  -d "v=0.9" \
  -d "sign=${TOKEN_SIGN}")

echo "Token response: $TOKEN_RESPONSE" | jq '.' || echo "$TOKEN_RESPONSE"
echo ""

ACCESS_TOKEN=$(echo "$TOKEN_RESPONSE" | jq -r '.result.accessToken')

if [ -z "$ACCESS_TOKEN" ] || [ "$ACCESS_TOKEN" = "null" ]; then
    echo "❌ Failed to get access token"
    exit 1
fi

echo "✅ Got access token: ${ACCESS_TOKEN:0:20}..."
echo ""

# Step 2: Fetch batch locations
echo "Step 2: Fetching batch locations..."
TIMESTAMP=$(date -u +"%Y-%m-%d %H:%M:%S")

# Build location params (alphabetically sorted for signature)
LOC_PARAMS="access_token${ACCESS_TOKEN}app_key${TRACKSOLID_APP_KEY}formatjsonmap_typeGOOGLEmethodjimi.user.device.location.listsign_methodmd5target${TRACKSOLID_ACCOUNT}timestamp${TIMESTAMP}v0.9"
LOC_SIGN=$(echo -n "${TRACKSOLID_APP_SECRET}${LOC_PARAMS}${TRACKSOLID_APP_SECRET}" | md5sum | awk '{print toupper($1)}')

LOCATION_RESPONSE=$(curl -s -X POST "https://eu-open.tracksolidpro.com/route/rest" \
  -d "access_token=${ACCESS_TOKEN}" \
  -d "app_key=${TRACKSOLID_APP_KEY}" \
  -d "format=json" \
  -d "map_type=GOOGLE" \
  -d "method=jimi.user.device.location.list" \
  -d "sign_method=md5" \
  -d "target=${TRACKSOLID_ACCOUNT}" \
  -d "timestamp=${TIMESTAMP}" \
  -d "v=0.9" \
  -d "sign=${LOC_SIGN}")

echo "Location response:"
echo "$LOCATION_RESPONSE" | jq '.' || echo "$LOCATION_RESPONSE"
echo ""

# Check result
CODE=$(echo "$LOCATION_RESPONSE" | jq -r '.code')
DEVICE_COUNT=$(echo "$LOCATION_RESPONSE" | jq -r '.result | length')

if [ "$CODE" = "0" ]; then
    echo "✅ Success! Received $DEVICE_COUNT device locations"
    
    # Show first device as example
    echo ""
    echo "Example device:"
    echo "$LOCATION_RESPONSE" | jq '.result[0]'
    
    # Check for problematic posType values
    echo ""
    echo "Checking posType values..."
    echo "$LOCATION_RESPONSE" | jq '.result[].posType' | sort | uniq -c
else
    MESSAGE=$(echo "$LOCATION_RESPONSE" | jq -r '.message')
    echo "❌ API error: $MESSAGE"
    exit 1
fi
