#!/bin/bash
cd /Users/carl/Documents/MobileCode/mobileGPS

echo "🧪 Running Environment Tests..."
echo "================================"

# Test 1: Check for localhost URLs
echo ""
echo "1️⃣  Checking for hardcoded localhost URLs..."
if grep -rn "localhost\|192\.168\|127\.0\.0\.1" gps-tracker/mobile-app/ble_tracker_app/lib/services/*.dart 2>/dev/null | grep -v environment.dart; then
  echo "   ❌ FAIL: Found hardcoded localhost URLs"
else
  echo "   ✅ PASS: No hardcoded localhost URLs"
fi

# Test 2: Verify environment.dart exists
echo ""
echo "2️⃣  Checking environment.dart configuration..."
if [ -f "gps-tracker/mobile-app/ble_tracker_app/lib/config/environment.dart" ]; then
  echo "   ✅ PASS: environment.dart exists"
  
  # Check for kDebugMode usage
  if grep -q "kDebugMode" gps-tracker/mobile-app/ble_tracker_app/lib/config/environment.dart; then
    echo "   ✅ PASS: Uses automatic build mode detection"
  else
    echo "   ⚠️  WARNING: Not using kDebugMode detection"
  fi
else
  echo "   ❌ FAIL: environment.dart missing"
fi

# Test 3: Check services use Environment
echo ""
echo "3️⃣  Checking services use Environment..."
SERVICES="auth_service.dart api_service.dart location_service.dart poi_service.dart"
for service in $SERVICES; do
  if grep -q "Environment.apiBaseUrl" gps-tracker/mobile-app/ble_tracker_app/lib/services/$service 2>/dev/null; then
    echo "   ✅ $service"
  else
    echo "   ❌ $service (not using Environment)"
  fi
done

# Test 4: Check git hooks installed
echo ""
echo "4️⃣  Checking git hooks..."
if [ "$(git config core.hooksPath)" = ".githooks" ]; then
  echo "   ✅ PASS: Git hooks configured"
  
  if [ -x ".githooks/pre-commit" ]; then
    echo "   ✅ PASS: Pre-commit hook executable"
  else
    echo "   ⚠️  WARNING: Pre-commit hook not executable"
  fi
else
  echo "   ❌ FAIL: Git hooks not configured"
fi

# Test 5: Check backend health
echo ""
echo "5️⃣  Checking backend health..."
if curl -s -f http://localhost:8000/health > /dev/null 2>&1; then
  echo "   ✅ PASS: Backend responding"
else
  echo "   ❌ FAIL: Backend not responding (is Docker running?)"
fi

# Test 6: Check Docker services
echo ""
echo "6️⃣  Checking Docker services..."
cd gps-tracker
RUNNING=$(docker compose ps 2>/dev/null | grep -c "Up")
if [ "$RUNNING" -ge 4 ]; then
  echo "   ✅ PASS: $RUNNING services running"
else
  echo "   ⚠️  WARNING: Only $RUNNING services running"
fi

echo ""
echo "================================"
echo "🏁 Tests Complete!"
echo ""
echo "Next steps:"
echo "  1. Run: cd gps-tracker/mobile-app/ble_tracker_app && flutter run -d chrome"
echo "  2. Check console for: 🛠️  DEBUG MODE: Using development server"
echo "  3. Test login and map loading"
echo "  4. Run: flutter build web --release"
echo "  5. Verify no localhost in build/web/"
