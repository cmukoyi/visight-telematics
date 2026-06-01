#!/bin/bash
# Diagnose why /app/static/asset.html is not found in backend container

echo "=================================="
echo "Volume Mount Diagnostics"
echo "=================================="
echo ""

BACKEND_CONTAINER=$(docker ps --format '{{.Names}}' | grep -E '(backend|pinplot_backend|beacon.*backend)' | head -n1)

if [ -z "$BACKEND_CONTAINER" ]; then
    echo "❌ Backend container not found!"
    exit 1
fi

echo "Backend Container: $BACKEND_CONTAINER"
echo ""

# 1. Check if files exist on HOST
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "1. Files on HOST (should exist)"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
if [ -f ./customer-dashboard/public/asset.html ]; then
    echo "✅ ./customer-dashboard/public/asset.html EXISTS on host"
    ls -lh ./customer-dashboard/public/asset.html
else
    echo "❌ ./customer-dashboard/public/asset.html NOT FOUND on host"
    echo ""
    echo "This means GitHub Actions did not sync the file!"
    echo "Check .github/workflows/deploy-production.yml rsync excludes"
    exit 1
fi

if [ -f ./customer-dashboard/public/scanner.html ]; then
    echo "✅ ./customer-dashboard/public/scanner.html EXISTS on host"
    ls -lh ./customer-dashboard/public/scanner.html
else
    echo "⚠️  ./customer-dashboard/public/scanner.html NOT FOUND on host"
fi
echo ""

# 2. Check container volume mounts
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "2. Container Volume Mounts"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
docker inspect "$BACKEND_CONTAINER" --format '{{range .Mounts}}Source: {{.Source}} → Destination: {{.Destination}} ({{.Mode}}){{"\n"}}{{end}}' | grep -E '(static|customer)'
echo ""

# 3. Check if /app/static directory exists in container
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "3. /app/static in Container"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
if docker exec "$BACKEND_CONTAINER" test -d /app/static; then
    echo "✅ /app/static directory EXISTS in container"
    echo ""
    echo "Contents of /app/static:"
    docker exec "$BACKEND_CONTAINER" ls -la /app/static
else
    echo "❌ /app/static directory NOT FOUND in container"
    echo ""
    echo "This means the volume mount is not configured!"
    echo "Check docker-compose.yml for:"
    echo "  volumes:"
    echo "    - ./customer-dashboard/public:/app/static:ro"
    exit 1
fi
echo ""

# 4. Check if asset.html exists in container
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "4. asset.html in Container"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
if docker exec "$BACKEND_CONTAINER" test -f /app/static/asset.html; then
    echo "✅ /app/static/asset.html EXISTS in container"
    docker exec "$BACKEND_CONTAINER" stat /app/static/asset.html 2>/dev/null || \
    docker exec "$BACKEND_CONTAINER" ls -lh /app/static/asset.html
else
    echo "❌ /app/static/asset.html NOT FOUND in container"
    echo ""
    echo "Possible causes:"
    echo "1. Volume mount path mismatch (check docker-compose.yml)"
    echo "2. Container started before files were synced (restart needed)"
    echo "3. File permissions issue"
fi
echo ""

# 5. Check docker-compose.yml volume configuration
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "5. docker-compose.yml Configuration"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
if grep -A5 "container_name:.*backend" docker-compose.yml | grep -q "customer-dashboard/public:/app/static"; then
    echo "✅ Volume mount configured in docker-compose.yml"
    grep -A10 "container_name:.*backend" docker-compose.yml | grep -A5 "volumes:"
else
    echo "❌ Volume mount NOT configured in docker-compose.yml"
    echo ""
    echo "Add to backend service:"
    echo "  volumes:"
    echo "    - ./customer-dashboard/public:/app/static:ro"
fi
echo ""

# 6. Test actual endpoint
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "6. Test /asset/TEST Endpoint"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
RESPONSE=$(curl -s --max-time 5 http://localhost:8001/asset/TEST123)
if echo "$RESPONSE" | grep -q "<!DOCTYPE html>"; then
    echo "✅ Endpoint returns HTML (working correctly)"
    echo "First 200 chars of response:"
    echo "$RESPONSE" | head -c 200
elif echo "$RESPONSE" | jq -e '.error' >/dev/null 2>&1; then
    echo "❌ Endpoint returns JSON error:"
    echo "$RESPONSE" | jq '.'
else
    echo "⚠️  Unexpected response:"
    echo "$RESPONSE" | head -c 500
fi
echo ""

echo "=================================="
echo "Diagnostic Summary"
echo "=================================="
echo "If asset.html exists on host but not in container:"
echo "  → Run: docker compose restart backend"
echo ""
echo "If asset.html does not exist on host:"
echo "  → GitHub Actions did not sync it. Check workflow excludes."
echo ""
echo "If volume mount not configured:"
echo "  → Add volume mount to docker-compose.yml and restart"
echo "=================================="
