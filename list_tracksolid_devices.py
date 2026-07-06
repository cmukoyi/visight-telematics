#!/usr/bin/env python3
"""
Helper script to list all TrackSolid devices and their IMEIs.
Run this first to find the IMEI you want to use for testing track data.
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

TOKEN_TTL = 3600  # 1 hour


# ── Signature Generation ─────────────────────────────────────────────────────
def generate_signature(params: dict, app_secret: str) -> str:
    """Generate MD5 signature for Jimi Open API."""
    sorted_keys = sorted(params.keys())
    concat = ''.join(k + params[k] for k in sorted_keys)
    sign_string = app_secret + concat + app_secret
    return hashlib.md5(sign_string.encode('utf-8')).hexdigest().upper()


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
        print(f"💾 Token cached")
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
    print("🔑 Getting OAuth access token...")
    
    # Try to load from cache first
    cached_token, _ = load_token_cache()
    if cached_token:
        return cached_token
    
    # Cache miss - fetch new token
    print("   Fetching new token from API...")
    
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
    
    response = httpx.post(OPEN_API_URL, data=token_params, timeout=30.0)
    response.raise_for_status()
    data = response.json()
    
    if data.get('code') != 0:
        raise Exception(f"OAuth error code={data.get('code')}: {data.get('message')}")
    
    access_token = data['result']['accessToken']
    expires_in = data['result'].get('expiresIn', TOKEN_TTL)
    expires_at = datetime.now(timezone.utc) + timedelta(seconds=expires_in)
    
    # Cache the token
    save_token_cache(access_token, expires_at)
    
    print(f"✅ Access token obtained\n")
    return access_token


# ── Step 2: List All Devices ─────────────────────────────────────────────────
def list_all_devices(access_token: str):
    """Call jimi.user.device.list to get all devices."""
    print("📋 Fetching device list...")
    
    timestamp = datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S')
    
    params = {
        'access_token': access_token,
        'app_key': TRACKSOLID_APP_KEY,
        'format': 'json',
        'method': 'jimi.user.device.list',
        'sign_method': 'md5',
        'target': TRACKSOLID_ACCOUNT,
        'timestamp': timestamp,
        'v': '0.9',
    }
    params['sign'] = generate_signature(params, TRACKSOLID_APP_SECRET)
    
    response = httpx.post(OPEN_API_URL, data=params, timeout=30.0)
    response.raise_for_status()
    data = response.json()
    
    if data.get('code') != 0:
        print(f"❌ Error code={data.get('code')}: {data.get('message')}")
        return None
    
    devices = data.get('result', [])
    print(f"✅ Found {len(devices)} devices\n")
    
    return devices


# ── Step 3: List Device Locations ────────────────────────────────────────────
def list_device_locations(access_token: str):
    """Call jimi.user.device.location.list to get current locations."""
    print("📍 Fetching device locations...")
    
    timestamp = datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S')
    
    params = {
        'access_token': access_token,
        'app_key': TRACKSOLID_APP_KEY,
        'format': 'json',
        'map_type': 'GOOGLE',
        'method': 'jimi.user.device.location.list',
        'sign_method': 'md5',
        'target': TRACKSOLID_ACCOUNT,
        'timestamp': timestamp,
        'v': '0.9',
    }
    params['sign'] = generate_signature(params, TRACKSOLID_APP_SECRET)
    
    response = httpx.post(OPEN_API_URL, data=params, timeout=30.0)
    response.raise_for_status()
    data = response.json()
    
    if data.get('code') != 0:
        print(f"❌ Error code={data.get('code')}: {data.get('message')}")
        return {}
    
    locations = data.get('result', [])
    print(f"✅ Got {len(locations)} device locations\n")
    
    # Convert to dict keyed by IMEI for easy lookup
    location_map = {str(loc.get('imei')): loc for loc in locations}
    return location_map


# ── Main Script ──────────────────────────────────────────────────────────────
if __name__ == "__main__":
    print("="*80)
    print("TrackSolid Device List - Find Your IMEI")
    print("="*80)
    print()
    
    try:
        # Get access token
        access_token = get_access_token()
        
        # Get device list
        devices = list_all_devices(access_token)
        
        # Get current locations
        locations = list_device_locations(access_token)
        
        if not devices:
            print("⚠️  No devices found")
            exit(1)
        
        # Display devices with their current location
        print("="*80)
        print("TRACKSOLID DEVICES")
        print("="*80)
        print()
        
        for i, device in enumerate(devices, 1):
            imei = device.get('imei')
            device_name = device.get('deviceName', 'N/A')
            vehicle_number = device.get('vehicleNumber', 'N/A')
            mc_type = device.get('mcType', 'N/A')
            enabled = device.get('enabledFlag', 0)
            activation = device.get('activationTime', 'N/A')
            expiration = device.get('expiration', 'N/A')
            
            print(f"Device #{i}")
            print(f"{'─'*80}")
            print(f"📱 IMEI:           {imei}")
            print(f"🏷️  Device Name:    {device_name}")
            print(f"🚗 Vehicle Number: {vehicle_number}")
            print(f"📡 Device Type:    {mc_type}")
            print(f"🟢 Enabled:        {'Yes' if enabled == 1 else 'No'}")
            print(f"📅 Activated:      {activation}")
            print(f"⏰ Expires:        {expiration}")
            
            # Show current location if available
            location = locations.get(str(imei))
            if location:
                lat = location.get('lat', 0)
                lng = location.get('lng', 0)
                gps_time = location.get('gpsTime', 'N/A')
                battery = location.get('batteryPowerVal', 'N/A')
                address = location.get('locDesc', 'N/A')
                
                print(f"\n📍 Current Location:")
                print(f"   Coordinates: {lat}, {lng}")
                print(f"   Last GPS:    {gps_time}")
                print(f"   Battery:     {battery}%")
                print(f"   Address:     {address}")
            else:
                print(f"\n⚠️  No current location data")
            
            print()
        
        # Show example command
        if devices:
            example_imei = devices[0].get('imei')
            print("="*80)
            print("NEXT STEPS")
            print("="*80)
            print()
            print("To test track history, edit test_tracksolid_track_list.py and set:")
            print(f'   TEST_IMEI = "{example_imei}"')
            print()
            print("Then run:")
            print("   python test_tracksolid_track_list.py")
            print()
        
    except Exception as e:
        print(f"❌ Error: {type(e).__name__}: {e}")
        import traceback
        traceback.print_exc()
