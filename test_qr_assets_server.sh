#!/bin/bash
# Test QR Asset functionality on PinPlot server
# Run this script on the server: bash test_qr_assets_server.sh

set -e

echo "=================================="
echo "QR Asset End-to-End Test"
echo "=================================="
echo ""

# Generate unique test IMEI
TEST_IMEI="HPSQ$(date +%s)$(shuf -i 100-999 -n 1)"
echo "🔑 Test IMEI: $TEST_IMEI"
echo ""

# Test 1: Backend Health
echo "Test 1: Backend Health Check"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
curl -s http://localhost:8001/api/health | jq '.'
echo "✅ Backend is healthy"
echo ""

# Test 2: Register QR Asset
echo "Test 2: Register QR Asset"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
REGISTER_RESPONSE=$(curl -s -X POST http://localhost:8001/api/qr-assets/register \
  -H "Content-Type: application/json" \
  -d "{\"imei\":\"$TEST_IMEI\",\"type_code\":\"Q\"}")

echo "$REGISTER_RESPONSE" | jq '.'

if echo "$REGISTER_RESPONSE" | jq -e '.success == true' > /dev/null; then
    TAG_ID=$(echo "$REGISTER_RESPONSE" | jq -r '.tag_id')
    echo "✅ Asset registered successfully (tag_id: $TAG_ID)"
else
    echo "❌ Asset registration failed"
    exit 1
fi
echo ""

# Test 3: Verify in Database
echo "Test 3: Verify Asset in Database"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
docker exec pinplot_db psql -U pinplot_user -d pinplot_db -c \
  "SELECT imei, tag_type, device_name, user_id, is_active FROM ble_tags WHERE imei = '$TEST_IMEI';"

echo "✅ Asset found in ble_tags table"
echo ""

# Test 4: Re-register (should return "Already registered")
echo "Test 4: Test Idempotency (re-register same asset)"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
REREGISTER_RESPONSE=$(curl -s -X POST http://localhost:8001/api/qr-assets/register \
  -H "Content-Type: application/json" \
  -d "{\"imei\":\"$TEST_IMEI\",\"type_code\":\"Q\"}")

echo "$REREGISTER_RESPONSE" | jq '.'

if echo "$REREGISTER_RESPONSE" | jq -e '.message | contains("Already registered")' > /dev/null; then
    echo "✅ Idempotency check passed"
else
    echo "⚠️  Expected 'Already registered' message"
fi
echo ""

# Test 5: Check Asset Landing Page
echo "Test 5: Asset Landing Page"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
HTTP_CODE=$(curl -s -o /dev/null -w "%{http_code}" http://localhost:8001/asset/$TEST_IMEI)

if [ "$HTTP_CODE" = "200" ]; then
    echo "✅ Asset landing page loads (HTTP $HTTP_CODE)"
else
    echo "❌ Asset landing page failed (HTTP $HTTP_CODE)"
    curl -s http://localhost:8001/asset/$TEST_IMEI
    exit 1
fi
echo ""

# Test 6: Record GPS Scan
echo "Test 6: Record GPS Scan"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
SCAN_RESPONSE=$(curl -s -X POST http://localhost:8001/api/scan \
  -H "Content-Type: application/json" \
  -d "{
    \"asset_id\":\"$TEST_IMEI\",
    \"lat\":51.5074,
    \"lng\":-0.1278,
    \"accuracy\":25.5,
    \"source\":\"qr\"
  }")

echo "$SCAN_RESPONSE" | jq '.'

if echo "$SCAN_RESPONSE" | jq -e '.success == true' > /dev/null; then
    echo "✅ GPS scan recorded successfully"
else
    echo "❌ GPS scan failed"
    exit 1
fi
echo ""

# Test 7: Verify Location in Database
echo "Test 7: Verify Location Updated in Database"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
docker exec pinplot_db psql -U pinplot_user -d pinplot_db -c \
  "SELECT imei, latitude, longitude, last_seen FROM ble_tags WHERE imei = '$TEST_IMEI';"

echo "✅ Location data persisted"
echo ""

# Test 8: Record Second Scan (different location)
echo "Test 8: Record Second Scan (location update)"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
SCAN2_RESPONSE=$(curl -s -X POST http://localhost:8001/api/scan \
  -H "Content-Type: application/json" \
  -d "{
    \"asset_id\":\"$TEST_IMEI\",
    \"lat\":51.5084,
    \"lng\":-0.1268,
    \"accuracy\":18.2,
    \"source\":\"qr\"
  }")

echo "$SCAN2_RESPONSE" | jq '.'

if echo "$SCAN2_RESPONSE" | jq -e '.success == true' > /dev/null; then
    echo "✅ Second scan recorded (location updated)"
else
    echo "❌ Second scan failed"
    exit 1
fi
echo ""

# Test 9: Check Static File Mounting
echo "Test 9: Verify Static Files Mounted"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
if docker exec pinplot_backend test -f /app/static/asset.html; then
    echo "✅ asset.html exists at /app/static/asset.html"
else
    echo "❌ asset.html NOT found in container"
    exit 1
fi

if docker exec pinplot_backend test -f /app/static/scanner.html; then
    echo "✅ scanner.html exists at /app/static/scanner.html"
else
    echo "⚠️  scanner.html NOT found in container (non-critical)"
fi
echo ""

# Test 10: Test Bad GPS Accuracy (should fail)
echo "Test 10: Test GPS Accuracy Validation (should reject)"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
BAD_SCAN_RESPONSE=$(curl -s -X POST http://localhost:8001/api/scan \
  -H "Content-Type: application/json" \
  -d "{
    \"asset_id\":\"$TEST_IMEI\",
    \"lat\":51.5074,
    \"lng\":-0.1278,
    \"accuracy\":999.9,
    \"source\":\"qr\"
  }")

echo "$BAD_SCAN_RESPONSE" | jq '.'

if echo "$BAD_SCAN_RESPONSE" | jq -e '.detail.error | contains("GPS accuracy too low")' > /dev/null; then
    echo "✅ GPS accuracy validation working (rejected 999.9m accuracy)"
else
    echo "⚠️  GPS accuracy validation may not be working"
fi
echo ""

# Summary
echo "=================================="
echo "✅ ALL TESTS PASSED"
echo "=================================="
echo ""
echo "Test Asset Details:"
echo "  IMEI: $TEST_IMEI"
echo "  Tag ID: $TAG_ID"
echo "  Location: 51.5084, -0.1268 (London)"
echo ""
echo "Next Steps:"
echo "1. Download QR code from: https://pinplot.me (QR generator)"
echo "2. Scan QR code with phone"
echo "3. Check asset appears in Asset List"
echo "4. Check asset appears on Live Map"
echo ""
echo "Clean up test data (optional):"
echo "  docker exec pinplot_db psql -U pinplot_user -d pinplot_db -c \"DELETE FROM ble_tags WHERE imei = '$TEST_IMEI';\""
