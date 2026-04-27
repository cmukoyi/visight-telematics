"""
Direct test of the TrackSolid V3 API — bypasses the Pinplot backend entirely.

Steps:
  1. Login to eu.tracksolidpro.com → get JWT
  2. Call queryEquipmentList with the IMEI filter
  3. Print the raw response and show whether the IMEI is found

Usage:
    python test_validate_tag.py [--imei IMEI]

Default IMEI: 780901807425212
"""

import argparse
import hashlib
import json
import sys
import requests

# ── credentials (same as backend .env) ────────────────────────────────────
ACCOUNT  = "Beacontelematics"
PASSWORD = "Transport01!"
USER_ID  = 14566550
ORG_ID   = "984a068e027c453081e81c457c115a91"

LOGIN_URL     = "https://eu.tracksolidpro.com/v3/new/homepage/login"
EQUIPMENT_URL = "https://eu.tracksolidpro.com/v3/new/newEquipment/queryEquipmentList"

# ── arg parsing ─────────────────────────────────────────────────────────────
parser = argparse.ArgumentParser(description="Test TrackSolid IMEI lookup directly")
parser.add_argument("--imei", default="780901807425212", help="IMEI to look up")
args = parser.parse_args()
IMEI = args.imei.strip()

print(f"\n{'='*60}")
print(f"  IMEI to find : {IMEI}")
print(f"{'='*60}\n")

# ── Step 1 — TrackSolid login ───────────────────────────────────────────────
password_md5 = hashlib.md5(PASSWORD.encode()).hexdigest().lower()
print(f"[1/2] Logging in to TrackSolid as '{ACCOUNT}' ...")
print(f"      MD5 password: {password_md5}")

try:
    r = requests.post(
        LOGIN_URL,
        json={
            "account":   ACCOUNT,
            "password":  password_md5,
            "language":  "en",
            "validCode": "",
            "nodeId":    "",
        },
        headers={"Content-Type": "application/json", "Accept": "application/json"},
        timeout=15,
    )
    r.raise_for_status()
except Exception as e:
    print(f"  ❌  Login request failed: {e}")
    sys.exit(1)

login_data = r.json()
print(f"  HTTP {r.status_code}  |  keys: {list(login_data.keys())}")

# Extract token — try common field paths
data_block = login_data.get("data") or {}
token = (
    data_block.get("authorization")
    or data_block.get("token")
    or login_data.get("authorization")
    or login_data.get("token")
    or login_data.get("accessToken")
)

if not token:
    print(f"\n  ❌  No token found in login response:")
    print(json.dumps(login_data, indent=4))
    sys.exit(1)

print(f"  ✅  Token: {token[:40]}...\n")

# ── Step 2 — queryEquipmentList ─────────────────────────────────────────────
print(f"[2/2] Calling queryEquipmentList  (imei='{IMEI}') ...")

# Try with IMEI filter first
payload = {
    "imei":        IMEI,
    "startRow":    "0",
    "userType":    8,
    "userId":      USER_ID,
    "orgId":       ORG_ID,
    "siftType":    "",
    "sortType":    "",
    "sortRule":    "",
    "isNewMcType": "0",
    "videoEntry":  "",
    "type":        "NORMAL",
    "searchStatus": "ALL",
}

try:
    r = requests.post(
        EQUIPMENT_URL,
        json=payload,
        headers={"Authorization": token, "Content-Type": "application/json"},
        timeout=20,
    )
    r.raise_for_status()
except Exception as e:
    print(f"  ❌  Equipment list request failed: {e}")
    sys.exit(1)

eq_data = r.json()
print(f"  HTTP {r.status_code}  |  top-level keys: {list(eq_data.keys())}")

# Decode device list from any known response shape
result_block = eq_data.get("data") or eq_data.get("result") or {}
if isinstance(result_block, list):
    devices = result_block
elif isinstance(result_block, dict):
    devices = (
        result_block.get("list")
        or result_block.get("data")
        or result_block.get("records")
        or []
    )
else:
    devices = []

print(f"  Devices returned: {len(devices)}\n")

# Print first 3 raw device objects so we can see the shape
if devices:
    print("  --- First device (raw) ---")
    print(json.dumps(devices[0], indent=4))
    print()

# Search for IMEI
found = None
for d in devices:
    if str(d.get("imei", "")).strip() == IMEI:
        found = d
        break

print("=" * 60)
if found:
    elec = found.get("elecQuantity", "N/A")
    print(f"  ✅  IMEI {IMEI} FOUND")
    print(f"  Device name  : {found.get('deviceName')}")
    print(f"  elecQuantity : {elec}")
    print(f"  status       : {found.get('status')}")
else:
    print(f"  ❌  IMEI {IMEI} NOT FOUND in {len(devices)} device(s)")
    if devices:
        imeis = [str(d.get("imei", "")) for d in devices[:10]]
        print(f"  First IMEIs returned: {imeis}")
    else:
        print("  Raw response:")
        print(json.dumps(eq_data, indent=4))
print("=" * 60 + "\n")
