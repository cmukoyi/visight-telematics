#!/usr/bin/env python3
"""
Re-add a device to Hubble Platform after deletion.

Usage:
    python readd_hubble_device.py --name "Device Name" [--tags "tag1,tag2"]

Environment variables required:
    HUBBLE_API_KEY - Your Hubble API token
    HUBBLE_ORG_ID - Your Hubble organization ID
"""

import os
import sys
import json
import argparse
import requests
from typing import Dict, List, Optional


def register_hubble_device(
    name: str,
    tags: Optional[List[str]] = None,
    encryption: str = "AES-256-CTR",
    counter_source: str = "UNIX_TIME"
) -> Dict:
    """
    Register a new device to Hubble Platform.
    
    Args:
        name: Device name
        tags: Optional list of tags
        encryption: Encryption mode (AES-256-CTR, AES-128-CTR, AES-128-EAX)
        counter_source: UNIX_TIME or DEVICE_UPTIME
    
    Returns:
        Dict with device registration response including new device_id and key
    """
    api_key = os.getenv("HUBBLE_API_KEY")
    org_id = os.getenv("HUBBLE_ORG_ID")
    
    if not api_key:
        raise ValueError("HUBBLE_API_KEY environment variable not set")
    if not org_id:
        raise ValueError("HUBBLE_ORG_ID environment variable not set")
    
    url = f"https://api.hubble.com/v2/org/{org_id}/devices"
    
    headers = {
        "Content-Type": "application/json",
        "Accept": "application/json",
        "Authorization": f"Bearer {api_key}"
    }
    
    body = {
        "n_devices": 1,
        "encryption": encryption,
        "counter_source": counter_source,
        "names": [name]
    }
    
    if tags:
        body["tags"] = [tags]
    
    print(f"Registering device '{name}' to Hubble...")
    print(f"Organization: {org_id}")
    print(f"Encryption: {encryption}")
    print(f"Counter Source: {counter_source}")
    if tags:
        print(f"Tags: {tags}")
    
    response = requests.post(url, headers=headers, json=body)
    
    if response.status_code == 200:
        data = response.json()
        device = data.get("devices", [{}])[0]
        
        print("\n✅ Device registered successfully!")
        print(f"Device ID: {device.get('id')}")
        print(f"Device Key: {device.get('key')}")
        print(f"Name: {device.get('name')}")
        
        if device.get('tags'):
            print(f"Tags: {', '.join(device.get('tags', []))}")
        
        print("\n⚠️  IMPORTANT: Save the Device Key securely - it cannot be retrieved later!")
        print("\nNext steps:")
        print("1. Update your device firmware with the new Device Key")
        print("2. The device will appear in PinPlot admin portal after first packet")
        
        return data
    else:
        error_msg = response.text
        try:
            error_data = response.json()
            error_msg = json.dumps(error_data, indent=2)
        except:
            pass
        
        print(f"\n❌ Registration failed (HTTP {response.status_code}):")
        print(error_msg)
        sys.exit(1)


def main():
    parser = argparse.ArgumentParser(
        description="Re-add a device to Hubble Platform after deletion"
    )
    parser.add_argument(
        "--name",
        required=True,
        help="Device name (e.g. 'Warehouse Tag #42')"
    )
    parser.add_argument(
        "--tags",
        help="Comma-separated tags (e.g. 'warehouse,floor2')"
    )
    parser.add_argument(
        "--encryption",
        default="AES-256-CTR",
        choices=["AES-256-CTR", "AES-128-CTR", "AES-128-EAX"],
        help="Encryption mode (default: AES-256-CTR)"
    )
    parser.add_argument(
        "--counter-source",
        default="UNIX_TIME",
        choices=["UNIX_TIME", "DEVICE_UPTIME"],
        help="Counter source for EID rotation (default: UNIX_TIME)"
    )
    
    args = parser.parse_args()
    
    tags = args.tags.split(",") if args.tags else None
    
    register_hubble_device(
        name=args.name,
        tags=tags,
        encryption=args.encryption,
        counter_source=args.counter_source
    )


if __name__ == "__main__":
    main()
