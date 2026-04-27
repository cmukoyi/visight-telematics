"""
Device types are now generic for Pinplot:
    - series1 (was Scope/MZone)
    - series2 (was Tracksolid)

Update all code to use only 'series1' and 'series2' for device type logic.
"""
# TrackSolidBLEScope1 => scope1
# TrackSolidBLENeoTrak => NEOTRAK
# TrackSolidBLEScopeT => ScopeTesting
import time
import hashlib
import requests


# TrackSolidBLEScope1 => scope1
# TrackSolidBLENeoTrak => NEOTRAK
# TrackSolidBLEScopeT => ScopeTesting
 

# TrackSolidBLEScopeT => ScopeTesting
# ---------- YOUR CREDENTIALS ----------
account = "Beacontelematics"
user_id = "Beacontelematics"  # Your tracksolid account username
user_pwd = "Transport01!"  # Replace with your actual password
appKey = "8FB345B8693CCD00705B2242580910A0339A22A4105B6558"
appSecret = "860d274a6c50445d86a93ed89de79278"
# --------------------------------------

url = "https://eu-open.tracksolidpro.com/route/rest"


def calculate_signature(params_dict, secret):
    """Calculate MD5 signature for API request"""
    sorted_keys = sorted(params_dict.keys())
    sign_string = secret
    for key in sorted_keys:
        sign_string += key + params_dict[key]
    sign_string += secret
    return hashlib.md5(sign_string.encode('utf-8')).hexdigest().upper()

def get_access_token():
    """Step 1: Get access token"""
    print("=" * 60)
    print("STEP 1: Getting Access Token")
    print("=" * 60)
    
    # Calculate password MD5 (lowercase)
    user_pwd_md5 = hashlib.md5(user_pwd.encode('utf-8')).hexdigest().lower()
    
    # Build parameters for token request
    timestamp = time.strftime("%Y-%m-%d %H:%M:%S", time.gmtime())
    
    params = {
        "app_key": appKey,
        "expires_in": "7200",
        "format": "json",
        "method": "jimi.oauth.token.get",
        "sign_method": "md5",
        "timestamp": timestamp,
        "user_id": user_id,
        "user_pwd_md5": user_pwd_md5,
        "v": "1.0"
    }
    
    # Calculate signature
    signature = calculate_signature(params, appSecret)
    params["sign"] = signature
    
    print(f"Timestamp: {timestamp}")
    print(f"User ID: {user_id}")
    print(f"Password MD5: {user_pwd_md5}")
    print(f"Signature: {signature}\n")
    
    try:
        response = requests.post(url, data=params, timeout=10)
        result = response.json()
        
        print(f"Status code: {response.status_code}")
        print(f"Response: {result}\n")
        
        if result.get("code") == 0:
            access_token = result["result"]["accessToken"]
            print(f"✅ Access Token obtained: {access_token}\n")
            return access_token
        else:
            print(f"❌ Failed to get access token: {result.get('message')}")
            return None
            
    except Exception as e:
        print(f"❌ Error getting access token: {e}")
        return None

def get_device_locations(access_token):
    """Step 2: Get device locations using access token"""
    print("=" * 60)
    print("STEP 2: Getting Device Locations")
    print("=" * 60)
    
    timestamp = time.strftime("%Y-%m-%d %H:%M:%S", time.gmtime())
    
    params = {
        "access_token": access_token,
        "app_key": appKey,
        "format": "json",
        "method": "jimi.user.device.location.list",
        "sign_method": "md5",
        "target": account,
        "timestamp": timestamp,
        "v": "1.0"
    }
    
    # Calculate signature
    signature = calculate_signature(params, appSecret)
    params["sign"] = signature
    
    print(f"Timestamp: {timestamp}")
    print(f"Target account: {account}")
    print(f"Signature: {signature}\n")
    
    try:
        response = requests.post(url, data=params, timeout=10)
        result = response.json()
        
        print(f"Status code: {response.status_code}")
        print(f"Response:\n{result}\n")
        
        if result.get("code") == 0:
            devices = result.get("result", [])
            print(f"✅ Successfully retrieved {len(devices)} device(s)\n")
            
            for device in devices:
                print(f"Device: {device.get('deviceName')}")
                print(f"  IMEI: {device.get('imei')}")
                print(f"  Status: {'Online' if device.get('status') == '1' else 'Offline'}")
                print(f"  Latitude: {device.get('lat')}")
                print(f"  Longitude: {device.get('lng')}")
                print(f"  GPS Time: {device.get('gpsTime')}")
                print()
        else:
            print(f"❌ Error: {result.get('message')}")
            
    except Exception as e:
        print(f"❌ Error getting device locations: {e}")

# Main execution
if __name__ == "__main__":
    # Step 1: Get access token
    access_token = get_access_token()
    
    if access_token:
        # Step 2: Get device locations
        get_device_locations(access_token)
    else:
        print("❌ Cannot proceed without access token")

