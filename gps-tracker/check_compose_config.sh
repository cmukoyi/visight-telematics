#!/bin/bash
# Check what docker-compose.yml is actually on the server

echo "=================================="
echo "Docker Compose Configuration Check"
echo "=================================="
echo ""

echo "1. Checking docker-compose.yml on server"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
if [ -f docker-compose.yml ]; then
    echo "✅ docker-compose.yml exists"
    echo ""
    echo "Backend service volumes configuration:"
    grep -A 20 'container_name:.*backend' docker-compose.yml | grep -A 10 'volumes:' | head -15
else
    echo "❌ docker-compose.yml not found!"
fi
echo ""

echo "2. Current running backend container config"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
BACKEND=$(docker ps --format '{{.Names}}' | grep -E '(backend|pinplot_backend)' | head -n1)
if [ -n "$BACKEND" ]; then
    echo "Container: $BACKEND"
    echo ""
    echo "ALL volume mounts:"
    docker inspect "$BACKEND" --format '{{range .Mounts}}{{.Type}}: {{.Source}} → {{.Destination}}{{"\n"}}{{end}}'
else
    echo "❌ Backend container not found"
fi
echo ""

echo "=================================="
echo "SOLUTION:"
echo "=================================="
echo "If docker-compose.yml has the volume mount but container doesn't:"
echo "  → docker compose down && docker compose up -d"
echo ""
echo "If docker-compose.yml is missing the volume mount:"
echo "  → GitHub Actions didn't deploy the latest version"
echo "  → Check: git log -1 docker-compose.yml"
echo "=================================="
