#!/usr/bin/env python3
"""
Test Floor Plan Setup with real authentication
Run this on the pinplot.me server via SSH

Usage:
  python3 test_floor_plan_setup.py

This script will:
1. Create a test user session
2. Test /api/portal/buildings endpoint
3. Verify the response
"""

import requests
import json
import sys
from datetime import datetime, timedelta
import jwt

# Configuration
BASE_URL = "http://localhost:8001"  # Backend API on server
API_URL = f"{BASE_URL}/api"

# JWT secret (MUST match what's in .env JWT_SECRET)
# You'll need to get this from the server's .env file
JWT_SECRET = "YOUR_JWT_SECRET_HERE"

def create_test_token(user_id=1, username="testuser", usergroup_id=1):
    """Create a valid JWT token for testing"""
    payload = {
        "sub": str(user_id),
        "username": username,
        "usergroup_id": usergroup_id,
        "exp": datetime.utcnow() + timedelta(hours=1)
    }
    token = jwt.encode(payload, JWT_SECRET, algorithm="HS256")
    return token

def test_buildings_endpoint(token):
    """Test the buildings endpoint"""
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json"
    }
    
    print("Testing /api/portal/buildings...")
    response = requests.get(f"{API_URL}/portal/buildings", headers=headers)
    
    print(f"Status: {response.status_code}")
    print(f"Response: {response.text[:500]}")
    
    if response.status_code == 200:
        buildings = response.json()
        print(f"✅ SUCCESS! Found {len(buildings)} buildings")
        return True
    else:
        print(f"❌ FAILED: {response.status_code}")
        return False

def test_without_token():
    """Test without authentication (should fail)"""
    print("\nTesting without authentication...")
    response = requests.get(f"{API_URL}/portal/buildings")
    
    print(f"Status: {response.status_code}")
    if response.status_code == 401:
        print("✅ Correctly rejects unauthenticated requests")
        return True
    else:
        print(f"⚠️ Unexpected status: {response.status_code}")
        return False

def main():
    print("=== Floor Plan Setup API Test ===")
    print(f"Testing against: {BASE_URL}")
    print(f"Time: {datetime.now()}\n")
    
    # Test 1: Without auth (should fail)
    test_without_token()
    
    # Test 2: With auth (should succeed)
    print("\n" + "="*50)
    
    if JWT_SECRET == "YOUR_JWT_SECRET_HERE":
        print("❌ ERROR: You need to set JWT_SECRET in this script")
        print("Run on server: grep JWT_SECRET /root/pinplot/.env")
        sys.exit(1)
    
    token = create_test_token()
    print(f"Generated test token (first 30 chars): {token[:30]}...")
    
    success = test_buildings_endpoint(token)
    
    print("\n" + "="*50)
    if success:
        print("✅ ALL TESTS PASSED")
        print("\nThe API works correctly with authentication.")
        print("The issue must be in the frontend JavaScript.")
        print("\nNext steps:")
        print("1. Open browser to https://pinplot.me/customer/")
        print("2. Open DevTools Console")
        print("3. Click Setup button")
        print("4. Check for '[Floor Plan]' log messages")
    else:
        print("❌ TESTS FAILED")
        print("The API endpoint is not working correctly.")
    
    sys.exit(0 if success else 1)

if __name__ == "__main__":
    main()
