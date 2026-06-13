#!/bin/bash
# ─────────────────────────────────────────────────────────────────────────────
# Phase 3 Canary Validation Script
# ─────────────────────────────────────────────────────────────────────────────
# Validates floorplan portal endpoints are accessible and functional after
# removing floorplan from TENANT_DISABLED_FEATURES.
#
# Prerequisites:
#   - Phase 2 completed with 24-48h clean run
#   - TENANT_DISABLED_FEATURES updated (empty or without floorplan)
#   - Backend restarted to apply config change
#   - Valid portal JWT token for testing
#
# Usage:
#   1. Set PORTAL_TOKEN env var or pass as first argument
#   2. Run from any directory: bash scripts/validate-floorplan-phase3.sh
#
# Exit codes:
#   0 = all validations passed
#   1 = partial failure (some endpoints/features not working)
#   2 = critical failure (feature gate still active or no connectivity)
# ─────────────────────────────────────────────────────────────────────────────

set -euo pipefail

# ─── Configuration ───────────────────────────────────────────────────────────
API_BASE="${API_BASE:-https://pinplot.me/api/portal/floorplan}"
PORTAL_TOKEN="${1:-${PORTAL_TOKEN:-}}"

if [ -z "$PORTAL_TOKEN" ]; then
    echo "❌ ERROR: Portal JWT token required"
    echo "   Usage: PORTAL_TOKEN=<jwt> $0"
    echo "   Or:    $0 <jwt>"
    exit 2
fi

FAIL_COUNT=0
WARN_COUNT=0

echo "════════════════════════════════════════════════════════════════════════════"
echo "  Floorplan Phase 3 Canary Validation — $(date '+%Y-%m-%d %H:%M:%S %Z')"
echo "════════════════════════════════════════════════════════════════════════════"
echo ""
echo "🎯 Target: $API_BASE"
echo ""

# ─── Helper Functions ────────────────────────────────────────────────────────
call_api() {
    local endpoint="$1"
    local expected_status="${2:-200}"
    
    echo -n "  Testing $endpoint ... "
    
    response=$(curl -s -w "\n%{http_code}" \
        -H "Authorization: Bearer $PORTAL_TOKEN" \
        -H "Content-Type: application/json" \
        "$API_BASE$endpoint" 2>&1)
    
    http_code=$(echo "$response" | tail -n1)
    body=$(echo "$response" | head -n-1)
    
    if [ "$http_code" = "$expected_status" ]; then
        echo "✅ $http_code"
        echo "$body"
        return 0
    else
        echo "❌ Got $http_code, expected $expected_status"
        if [ -n "$body" ]; then
            echo "     Response: $body" | head -c 200
        fi
        return 1
    fi
}

# ─── Test 1: Feature Gate Removed ────────────────────────────────────────────
echo "🚦 Test 1: Feature Gate Status"
echo "────────────────────────────────────────────────────────────────────────────"

if call_api "/health" 200; then
    RESPONSE_BODY="$body"
    echo "  ✅ Health endpoint accessible (feature gate removed)"
    
    # Parse bridge status
    if echo "$RESPONSE_BODY" | grep -q '"connected":true'; then
        echo "  ✅ Bridge connected"
    else
        echo "  ⚠️  Bridge not connected"
        WARN_COUNT=$((WARN_COUNT + 1))
    fi
    
    # Parse raddec count
    RADDEC_COUNT=$(echo "$RESPONSE_BODY" | grep -oP '"raddec_count":\K\d+' || echo "0")
    echo "  📊 Raddec count: $RADDEC_COUNT"
    
    # Parse asset counts
    ASSETS_TOTAL=$(echo "$RESPONSE_BODY" | grep -oP '"assets":.*"total":\K\d+' || echo "0")
    ASSETS_ONLINE=$(echo "$RESPONSE_BODY" | grep -oP '"online":\K\d+' || echo "0")
    echo "  📊 Assets: $ASSETS_TOTAL total, $ASSETS_ONLINE online"
    
else
    echo "  ❌ CRITICAL: Health endpoint returned non-200"
    echo "     Feature gate may still be active or backend not restarted"
    FAIL_COUNT=$((FAIL_COUNT + 1))
fi
echo ""

# ─── Test 2: Floor List Endpoint ─────────────────────────────────────────────
echo "🏢 Test 2: Floor List"
echo "────────────────────────────────────────────────────────────────────────────"

if call_api "/floors" 200; then
    FLOOR_COUNT=$(echo "$body" | grep -o '"id"' | wc -l | tr -d ' ')
    echo "  📊 Floors returned: $FLOOR_COUNT"
    
    if [ "$FLOOR_COUNT" -eq 0 ]; then
        echo "  ⚠️  No floors configured (expected for fresh deployment)"
        WARN_COUNT=$((WARN_COUNT + 1))
    else
        echo "  ✅ Floor data available"
        # Extract first floor ID for next test
        FIRST_FLOOR_ID=$(echo "$body" | grep -oP '"id":"\K[^"]+' | head -1)
        echo "  📝 Sample floor ID: $FIRST_FLOOR_ID"
    fi
else
    echo "  ❌ Floor list endpoint failed"
    FAIL_COUNT=$((FAIL_COUNT + 1))
fi
echo ""

# ─── Test 3: Floor Details (if floors exist) ─────────────────────────────────
if [ -n "${FIRST_FLOOR_ID:-}" ]; then
    echo "🗺️  Test 3: Floor Details"
    echo "────────────────────────────────────────────────────────────────────────────"
    
    if call_api "/floors/$FIRST_FLOOR_ID" 200; then
        echo "  ✅ Floor details loaded"
        
        # Parse gateway count
        GW_COUNT=$(echo "$body" | grep -o '"gateways":\[' | wc -l | tr -d ' ')
        echo "  📊 Gateways on floor: $GW_COUNT"
    else
        echo "  ❌ Floor details endpoint failed"
        FAIL_COUNT=$((FAIL_COUNT + 1))
    fi
    echo ""
fi

# ─── Test 4: Assets Endpoint ─────────────────────────────────────────────────
echo "📍 Test 4: Assets Endpoint"
echo "────────────────────────────────────────────────────────────────────────────"

if call_api "/assets" 200; then
    ASSET_COUNT=$(echo "$body" | grep -o '"id"' | wc -l | tr -d ' ')
    echo "  📊 Assets returned: $ASSET_COUNT"
    
    if [ "$ASSET_COUNT" -eq 0 ]; then
        echo "  ℹ️  No assets (no gateways reporting or feature just enabled)"
    else
        echo "  ✅ Asset data flowing"
        # Parse first asset
        FIRST_ASSET=$(echo "$body" | grep -oP '"tag_id":"\K[^"]+' | head -1)
        echo "  📝 Sample asset: $FIRST_ASSET"
    fi
else
    echo "  ❌ Assets endpoint failed"
    FAIL_COUNT=$((FAIL_COUNT + 1))
fi
echo ""

# ─── Test 5: Assets with Floor Filter ────────────────────────────────────────
if [ -n "${FIRST_FLOOR_ID:-}" ]; then
    echo "🔍 Test 5: Assets with Floor Filter"
    echo "────────────────────────────────────────────────────────────────────────────"
    
    if call_api "/assets?floor_key=$FIRST_FLOOR_ID" 200; then
        FILTERED_COUNT=$(echo "$body" | grep -o '"id"' | wc -l | tr -d ' ')
        echo "  ✅ Filtered query works"
        echo "  📊 Assets on floor $FIRST_FLOOR_ID: $FILTERED_COUNT"
    else
        echo "  ❌ Floor-filtered assets endpoint failed"
        FAIL_COUNT=$((FAIL_COUNT + 1))
    fi
    echo ""
fi

# ─── Test 6: Unregistered Gateways Endpoint ──────────────────────────────────
echo "📡 Test 6: Unregistered Gateways"
echo "────────────────────────────────────────────────────────────────────────────"

if call_api "/gateways/unregistered" 200; then
    UNREG_COUNT=$(echo "$body" | grep -o ',' | wc -l | tr -d ' ')
    echo "  📊 Unregistered gateway IDs: $((UNREG_COUNT + 1))"
    
    if [ "$UNREG_COUNT" -gt 0 ]; then
        echo "  ℹ️  Gateways detected but not yet registered in admin UI"
        echo "     Sample: $(echo "$body" | head -c 100)"
    fi
else
    echo "  ❌ Unregistered gateways endpoint failed"
    FAIL_COUNT=$((FAIL_COUNT + 1))
fi
echo ""

# ─── Test 7: Feature Gate Still Active Check ─────────────────────────────────
echo "🔒 Test 7: Verify Feature Gate Inactive"
echo "────────────────────────────────────────────────────────────────────────────"

# This should return 200, not 404. We already tested /health above, 
# but let's explicitly confirm no 404 on any endpoint
echo "  Running spot check on multiple endpoints..."

GATE_ACTIVE=false
for endpoint in "/health" "/floors" "/assets"; do
    response_code=$(curl -s -o /dev/null -w "%{http_code}" \
        -H "Authorization: Bearer $PORTAL_TOKEN" \
        "$API_BASE$endpoint")
    
    if [ "$response_code" = "404" ]; then
        echo "  ❌ $endpoint returned 404 — feature gate still active!"
        GATE_ACTIVE=true
        FAIL_COUNT=$((FAIL_COUNT + 1))
    fi
done

if [ "$GATE_ACTIVE" = false ]; then
    echo "  ✅ No 404 responses — feature gate confirmed inactive"
fi
echo ""

# ─── Summary ─────────────────────────────────────────────────────────────────
echo "════════════════════════════════════════════════════════════════════════════"
echo "  Validation Summary"
echo "════════════════════════════════════════════════════════════════════════════"

if [ $FAIL_COUNT -eq 0 ] && [ $WARN_COUNT -eq 0 ]; then
    echo "  ✅ ALL TESTS PASSED — Phase 3 canary ready for user validation"
    echo ""
    echo "  Next steps:"
    echo "    1. Test customer dashboard UI: https://pinplot.me/customer"
    echo "    2. Navigate to Floor Plan tab (should load, not show 404)"
    echo "    3. Verify floors/assets render correctly"
    echo "    4. Confirm polling updates every 3 seconds"
    echo "    5. Monitor for 2-4 hours, then proceed to full rollout"
    exit 0
elif [ $FAIL_COUNT -eq 0 ]; then
    echo "  ⚠️  $WARN_COUNT WARNING(S) — Non-critical issues detected"
    echo "     Phase 3 functional but needs attention (see warnings above)"
    echo ""
    echo "  Proceed with caution:"
    echo "    - Warnings may indicate missing setup (no floors/gateways)"
    echo "    - Bridge may not be connected (check backend logs)"
    echo "    - Can still proceed to UI validation if endpoints work"
    exit 1
else
    echo "  ❌ $FAIL_COUNT FAILURE(S) — Phase 3 validation failed"
    echo "     Review failures above before proceeding"
    echo ""
    echo "  Troubleshooting:"
    echo "    1. Verify TENANT_DISABLED_FEATURES is empty in backend .env"
    echo "    2. Confirm backend was restarted after config change"
    echo "    3. Check backend logs for feature gate status"
    echo "    4. Ensure portal JWT is valid and not expired"
    exit 2
fi
