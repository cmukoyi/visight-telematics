#!/bin/bash
# Debug script to check if static files are mounted correctly in backend container

echo "=================================="
echo "Container Static File Debug"
echo "=================================="
echo ""

BACKEND_CONTAINER="beacon_telematics_backend"

# Check if container is running
if ! docker ps --format '{{.Names}}' | grep -q "^${BACKEND_CONTAINER}$"; then
    echo "❌ Backend container is not running!"
    echo ""
    echo "Available containers:"
    docker ps --format 'table {{.Names}}\t{{.Status}}'
    exit 1
fi

echo "✅ Container ${BACKEND_CONTAINER} is running"
echo ""

# Check if /app/static directory exists
echo "Checking /app/static directory in container..."
if docker exec "$BACKEND_CONTAINER" test -d /app/static; then
    echo "✅ /app/static directory exists"
else
    echo "❌ /app/static directory NOT FOUND"
    exit 1
fi
echo ""

# List contents of /app/static
echo "Contents of /app/static:"
docker exec "$BACKEND_CONTAINER" ls -lah /app/static
echo ""

# Check if asset.html exists
echo "Checking for asset.html..."
if docker exec "$BACKEND_CONTAINER" test -f /app/static/asset.html; then
    echo "✅ asset.html exists"
    # Show file size
    docker exec "$BACKEND_CONTAINER" stat -c "Size: %s bytes" /app/static/asset.html 2>/dev/null || \
    docker exec "$BACKEND_CONTAINER" stat -f "Size: %z bytes" /app/static/asset.html
else
    echo "❌ asset.html NOT FOUND"
fi
echo ""

# Check if scanner.html exists
echo "Checking for scanner.html..."
if docker exec "$BACKEND_CONTAINER" test -f /app/static/scanner.html; then
    echo "✅ scanner.html exists"
else
    echo "❌ scanner.html NOT FOUND"
fi
echo ""

# Show docker-compose.yml volumes for backend
echo "Backend volume mounts from docker-compose.yml:"
docker inspect "$BACKEND_CONTAINER" --format '{{range .Mounts}}{{.Source}} -> {{.Destination}} ({{.Mode}}){{"\n"}}{{end}}'
echo ""

echo "=================================="
echo "If asset.html is NOT FOUND, you need to:"
echo "1. Check docker-compose.yml has the volume mount:"
echo "   volumes:"
echo "     - ./customer-dashboard/public:/app/static:ro"
echo "2. Restart the backend container:"
echo "   docker-compose restart backend"
echo "=================================="
