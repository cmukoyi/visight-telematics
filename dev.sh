#!/bin/bash
# Local Development Helper Script
# Quick commands for running the app locally

set -e

cd "$(dirname "$0")/gps-tracker"

case "$1" in
  start)
    echo "🚀 Starting local development environment..."
    docker compose -f docker-compose.local.yml up -d
    echo "✅ Services started!"
    echo ""
    echo "Access points:"
    echo "  - Backend API: http://localhost:8000"
    echo "  - API Docs: http://localhost:8000/docs"
    echo "  - Admin: http://localhost:3000"
    echo "  - Customer: http://localhost:3001"
    echo "  - Mobile Web: http://localhost:3002"
    echo ""
    echo "View logs: ./dev.sh logs"
    ;;
    
  stop)
    echo "🛑 Stopping services..."
    docker compose -f docker-compose.local.yml down
    echo "✅ Services stopped!"
    ;;
    
  restart)
    echo "🔄 Restarting services..."
    docker compose -f docker-compose.local.yml restart
    echo "✅ Services restarted!"
    ;;
    
  logs)
    docker compose -f docker-compose.local.yml logs -f ${2:-backend}
    ;;
    
  backend-logs)
    docker compose -f docker-compose.local.yml logs -f backend
    ;;
    
  test)
    echo "🧪 Testing backend..."
    sleep 2
    curl -s http://localhost:8000/ || echo "❌ Backend not responding"
    curl -s http://localhost:8000/docs > /dev/null && echo "✅ API docs accessible" || echo "❌ API docs not accessible"
    ;;
    
  db)
    echo "🗄️  Connecting to database..."
    docker compose -f docker-compose.local.yml exec db psql -U ble_user -d ble_tracker
    ;;
    
  reset)
    echo "⚠️  Resetting database (all data will be lost)..."
    read -p "Are you sure? (yes/no): " confirm
    if [ "$confirm" = "yes" ]; then
      docker compose -f docker-compose.local.yml down -v
      docker compose -f docker-compose.local.yml up -d
      echo "✅ Database reset complete!"
    else
      echo "❌ Reset cancelled"
    fi
    ;;
    
  build)
    echo "🔨 Rebuilding containers..."
    docker compose -f docker-compose.local.yml up --build -d
    echo "✅ Build complete!"
    ;;
    
  status)
    docker compose -f docker-compose.local.yml ps
    ;;
    
  clean)
    echo "🧹 Cleaning up..."
    docker compose -f docker-compose.local.yml down -v
    docker system prune -f
    echo "✅ Cleanup complete!"
    ;;
    
  *)
    echo "Local Development Helper Script"
    echo ""
    echo "Usage: ./dev.sh [command]"
    echo ""
    echo "Commands:"
    echo "  start          - Start all services"
    echo "  stop           - Stop all services"
    echo "  restart        - Restart all services"
    echo "  logs [service] - View logs (default: backend)"
    echo "  backend-logs   - View backend logs"
    echo "  test           - Test if backend is working"
    echo "  db             - Connect to database (psql)"
    echo "  reset          - Reset database (WARNING: deletes data)"
    echo "  build          - Rebuild containers"
    echo "  status         - Show service status"
    echo "  clean          - Stop and remove everything"
    echo ""
    echo "Examples:"
    echo "  ./dev.sh start"
    echo "  ./dev.sh logs backend"
    echo "  ./dev.sh test"
    ;;
esac
