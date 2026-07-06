#!/usr/bin/env python3
"""
Test script for TrackSolid Open API - jimi.device.track.list method
Gets historical track data (GPS breadcrumbs) for a device.
"""

import hashlib
import httpx
from datetime import datetime, timedelta, timezone
import json
import os

# ── TrackSolid API Configuration ─────────────────────────────────────────────
OPEN_API_URL = "https://eu-open.tracksolidpro.com/route/rest"
TOKEN_CACHE_FILE = "/tmp/tracksolid_token_cache.json"  # Cache token to avoid rate limits

# Credentials (from TRACKSOLID_ARCHITECTURE.md)
TRACKSOLID_ACCOUNT = "Beacontelematics"
TRACKSOLID_PASSWORD = "Transport01!"
TRACKSOLID_APP_KEY = "8FB345B8693CCD00705B2242580910A0339A22A4105B6558"
TRACKSOLID_APP_SECRET = "860d274a6c50445d86a93ed89de79278"

# Token TTL
TOKEN_TTL = 3600  # 1 hour


# ── Signature Generation ─────────────────────────────────────────────────────
def generate_signature(params: dict, app_secret: str) -> str:
    """
    Generate MD5 signature for Jimi Open API per official algorithm.
    
    Algorithm:
    1. Sort all params (except 'sign') alphabetically by key
    2. Concatenate as: key1value1key2value2...
    3. Wrap with: app_secret + concat + app_secret
    4. MD5 and uppercase
    """
    sorted_keys = sorted(params.keys())
    concat = ''.join(k + params[k] for k in sorted_keys)
    sign_string = app_secret + concat + app_secret
    print(f"\n🔐 Signature calculation:")
    print(f"   Sorted params: {sorted_keys}")
    print(f"   Concatenated: {concat[:80]}..." if len(concat) > 80 else f"   Concatenated: {concat}")
    print(f"   Sign string: {sign_string[:80]}..." if len(sign_string) > 80 else f"   Sign string: {sign_string}")
    signature = hashlib.md5(sign_string.encode('utf-8')).hexdigest().upper()
    print(f"   MD5 signature: {signature}")
    return signature


# ── Token Caching ────────────────────────────────────────────────────────────
def save_token_cache(access_token: str, expires_at: datetime):
    """Save token to cache file with expiry time."""
    try:
        cache_data = {
            'access_token': access_token,
            'expires_at': expires_at.isoformat()
        }
        with open(TOKEN_CACHE_FILE, 'w') as f:
            json.dump(cache_data, f)
        print(f"💾 Token cached to {TOKEN_CACHE_FILE}")
    except Exception as e:
        print(f"⚠️  Failed to cache token: {e}")


def load_token_cache() -> tuple[str | None, datetime | None]:
    """Load token from cache file if it exists and is still valid."""
    if not os.path.exists(TOKEN_CACHE_FILE):
        return None, None
    
    try:
        with open(TOKEN_CACHE_FILE, 'r') as f:
            cache_data = json.load(f)
        
        access_token = cache_data.get('access_token')
        expires_at_str = cache_data.get('expires_at')
        
        if not access_token or not expires_at_str:
            return None, None
        
        expires_at = datetime.fromisoformat(expires_at_str)
        
        # Check if token is still valid (with 60s buffer)
        now = datetime.now(timezone.utc)
        if expires_at > now + timedelta(seconds=60):
            remaining = int((expires_at - now).total_seconds())
            print(f"♻️  Using cached token (valid for {remaining}s)")
            return access_token, expires_at
        else:
            print(f"⏰ Cached token expired, fetching new one...")
            return None, None
            
    except Exception as e:
        print(f"⚠️  Failed to load cached token: {e}")
        return None, None


# ── Step 1: Get OAuth Access Token ───────────────────────────────────────────
def get_access_token() -> str:
    """Fetch OAuth access_token via jimi.oauth.token.get (with file-based cache)"""
    print("\n" + "="*80)
    print("STEP 1: Getting OAuth Access Token")
    print("="*80)
    
    # Try to load from cache first
    cached_token, _ = load_token_cache()
    if cached_token:
        return cached_token
    
    # Cache miss - fetch new token
    print("🔑 Fetching new OAuth token from API...")
    
    password_md5 = hashlib.md5(TRACKSOLID_PASSWORD.encode()).hexdigest().lower()
    timestamp = datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S')
    
    token_params = {
        'app_key': TRACKSOLID_APP_KEY,
        'expires_in': str(TOKEN_TTL),
        'format': 'json',
        'method': 'jimi.oauth.token.get',
        'sign_method': 'md5',
        'timestamp': timestamp,
        'user_id': TRACKSOLID_ACCOUNT,
        'user_pwd_md5': password_md5,
        'v': '0.9',
    }
    token_params['sign'] = generate_signature(token_params, TRACKSOLID_APP_SECRET)
    
    print(f"\n📤 Request URL: {OPEN_API_URL}")
    print(f"📤 Request params: {json.dumps({k: v for k, v in token_params.items() if k != 'sign'}, indent=2)}")
    print(f"📤 Signature: {token_params['sign']}")
    
    response = httpx.post(OPEN_API_URL, data=token_params, timeout=30.0)
    response.raise_for_status()
    data = response.json()
    
    print(f"\n📥 Response: {json.dumps(data, indent=2)}")
    
    if data.get('code') != 0:
        raise Exception(f"OAuth error code={data.get('code')}: {data.get('message')}")
    
    access_token = data['result']['accessToken']
    expires_in = data['result'].get('expiresIn', TOKEN_TTL)
    expires_at = datetime.now(timezone.utc) + timedelta(seconds=expires_in)
    
    # Cache the token
    save_token_cache(access_token, expires_at)
    
    print(f"\n✅ Access token obtained: {access_token[:20]}...{access_token[-20:]}")
    return access_token


# ── Step 2: Get Device Track List ────────────────────────────────────────────
def get_device_track_list(access_token: str, imei: str, begin_time: str, end_time: str, map_type: str = "GOOGLE"):
    """
    Call jimi.device.track.list to get historical GPS track data.
    
    Args:
        access_token: OAuth token from step 1
        imei: Device IMEI to query
        begin_time: Start time in format "YYYY-MM-DD HH:MM:SS"
        end_time: End time in format "YYYY-MM-DD HH:MM:SS"
        map_type: "GOOGLE" for calibrated coordinates, or omit for raw
    """
    print("\n" + "="*80)
    print("STEP 2: Getting Device Track List")
    print("="*80)
    
    timestamp = datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S')
    
    params = {
        'access_token': access_token,
        'app_key': TRACKSOLID_APP_KEY,
        'begin_time': begin_time,
        'end_time': end_time,
        'format': 'json',
        'imei': imei,
        'map_type': map_type,
        'method': 'jimi.device.track.list',
        'sign_method': 'md5',
        'timestamp': timestamp,
        'v': '0.9',
    }
    params['sign'] = generate_signature(params, TRACKSOLID_APP_SECRET)
    
    print(f"\n📤 Request URL: {OPEN_API_URL}")
    print(f"📤 Request params:")
    print(f"   IMEI: {imei}")
    print(f"   Begin time: {begin_time}")
    print(f"   End time: {end_time}")
    print(f"   Map type: {map_type}")
    print(f"   Method: jimi.device.track.list")
    print(f"   Signature: {params['sign']}")
    
    response = httpx.post(OPEN_API_URL, data=params, timeout=30.0)
    response.raise_for_status()
    data = response.json()
    
    print(f"\n📥 Response Code: {data.get('code')}")
    print(f"📥 Response Message: {data.get('message')}")
    
    if data.get('code') != 0:
        print(f"\n❌ ERROR: {data.get('message')}")
        print(f"Full response: {json.dumps(data, indent=2)}")
        return None
    
    # Pretty print the results
    result = data.get('result', [])
    track_data = data.get('data', {})
    
    print(f"\n✅ SUCCESS! Received {len(result)} GPS points")
    print(f"📊 Total Mileage: {track_data.get('mileage', 0)} km")
    
    if result:
        print(f"\n📍 Track Points:")
        for i, point in enumerate(result[:10], 1):  # Show first 10 points
            print(f"\n   Point {i}:")
            print(f"      Time: {point.get('gpsTime')}")
            print(f"      Location: {point.get('lat')}, {point.get('lng')}")
            print(f"      Speed: {point.get('gpsSpeed')} km/h")
            print(f"      Direction: {point.get('direction')}°")
            print(f"      Position Type: {point.get('posType')} (1=GPS, 2=LBS, 3=WIFI)")
            print(f"      Ignition: {point.get('ignition')}")
            print(f"      ACC Status: {point.get('accStatus')}")
            print(f"      GPS Mode: {point.get('gpsMode')} (0=Real-time, 1=Retransmitted)")
        
        if len(result) > 10:
            print(f"\n   ... and {len(result) - 10} more points")
    else:
        print(f"\n⚠️  No track data found for this time range")
    
    print(f"\n📄 Full Response:")
    print(json.dumps(data, indent=2))
    
    return data


# ── Main Test Script ─────────────────────────────────────────────────────────
if __name__ == "__main__":
    print("="*80)
    print("TrackSolid Open API - jimi.device.track.list Test Script")
    print("="*80)
    
    # ── Configuration ────────────────────────────────────────────────────────
    # Using device #1319 (PB708-76441) which has recent GPS data in Sheffield, UK
    TEST_IMEI = "780901807676441"  # Last GPS: 2026-07-05 16:37:58
    
    # Time range: Last 24 hours
    end_time = datetime.now(timezone.utc)
    begin_time = end_time - timedelta(hours=24)
    
    BEGIN_TIME_STR = begin_time.strftime('%Y-%m-%d %H:%M:%S')
    END_TIME_STR = end_time.strftime('%Y-%m-%d %H:%M:%S')
    
    print(f"\n🔍 Test Configuration:")
    print(f"   IMEI: {TEST_IMEI}")
    print(f"   Time Range: {BEGIN_TIME_STR} to {END_TIME_STR}")
    print(f"   Account: {TRACKSOLID_ACCOUNT}")
    print(f"   APP_KEY: {TRACKSOLID_APP_KEY[:20]}...{TRACKSOLID_APP_KEY[-10:]}")
    
    # Check if IMEI is set
    if TEST_IMEI == "YOUR_IMEI_HERE":
        print("\n" + "!"*80)
        print("⚠️  WARNING: Please set TEST_IMEI variable to your actual device IMEI!")
        print("!"*80)
        print("\nYou can find IMEIs by first calling jimi.user.device.list")
        print("Edit this script and replace 'YOUR_IMEI_HERE' with your IMEI.")
        exit(1)
    
    try:
        # Step 1: Get access token
        access_token = get_access_token()
        
        # Step 2: Get track data
        track_data = get_device_track_list(
            access_token=access_token,
            imei=TEST_IMEI,
            begin_time=BEGIN_TIME_STR,
            end_time=END_TIME_STR,
            map_type="GOOGLE"  # Use Google-calibrated coordinates
        )
        
        print("\n" + "="*80)
        print("✅ Test Complete!")
        print("="*80)
        
    except Exception as e:
        print("\n" + "="*80)
        print(f"❌ Error: {type(e).__name__}: {e}")
        print("="*80)
        import traceback
        traceback.print_exc()
