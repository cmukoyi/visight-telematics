#!/usr/bin/env python3
"""
Register a webhook endpoint with Hubble Network.

This script creates or updates a webhook configuration to receive
real-time packet data from all Hubble devices in the organization.

Usage:
    python3 register_hubble_webhook.py

Environment variables required:
    HUBBLE_API_KEY - Hubble API authentication token
    HUBBLE_ORG_ID - Hubble organization ID
    HUBBLE_WEBHOOK_URL - Public URL for webhook endpoint (e.g., https://pinplot.me/api/webhooks/hubble)
    HUBBLE_WEBHOOK_SECRET - Secret token for validating webhook requests
"""

import httpx
import os
import sys
from datetime import datetime

# Configuration
API_KEY = os.getenv("HUBBLE_API_KEY", "0bff3f034bc9587456587e9385af4fd3afda865fcee150052302183737d43b2aaedaae076075e68d72d428f5242bccb6")
ORG_ID = os.getenv("HUBBLE_ORG_ID", "e1009837-5f8e-461c-b9ca-d99cb42022de")
WEBHOOK_URL = os.getenv("HUBBLE_WEBHOOK_URL", "https://pinplot.me/api/webhooks/hubble")
WEBHOOK_SECRET = os.getenv("HUBBLE_WEBHOOK_SECRET")

API_BASE = "https://api.hubble.com"


def list_webhooks():
    """List existing webhooks."""
    url = f"{API_BASE}/v1/org/{ORG_ID}/webhooks"
    headers = {"Authorization": f"Bearer {API_KEY}"}
    
    print(f"📋 Listing existing webhooks...")
    response = httpx.get(url, headers=headers, timeout=30.0)
    
    if response.status_code == 200:
        data = response.json()
        webhooks = data.get("webhooks", [])
        
        if not webhooks:
            print("   No webhooks configured")
            return []
        
        for i, wh in enumerate(webhooks, 1):
            print(f"   {i}. {wh.get('name', 'Unnamed')}")
            print(f"      ID: {wh.get('id')}")
            print(f"      URL: {wh.get('url')}")
            print(f"      Batch Size: {wh.get('batch_size', 'default')}")
            print(f"      Created: {wh.get('created_at')}")
        
        return webhooks
    else:
        print(f"   ❌ Error: {response.status_code} - {response.text}")
        return []


def create_webhook():
    """Create a new webhook endpoint."""
    url = f"{API_BASE}/v1/org/{ORG_ID}/webhooks"
    headers = {"Authorization": f"Bearer {API_KEY}"}
    
    payload = {
        "name": "PinPlot Production Webhook",
        "url": WEBHOOK_URL,
        "batch_size": 100,  # Send up to 100 packets per batch (max 1000)
    }
    
    print(f"\n📝 Creating webhook...")
    print(f"   URL: {WEBHOOK_URL}")
    print(f"   Batch size: {payload['batch_size']}")
    
    response = httpx.post(url, headers=headers, json=payload, timeout=30.0)
    
    if response.status_code in (200, 201):
        data = response.json()
        webhook = data.get("webhook", {})
        secret = data.get("secret")  # Returned only on creation
        
        print(f"\n✅ Webhook created successfully!")
        print(f"   Webhook ID: {webhook.get('id')}")
        print(f"   Name: {webhook.get('name')}")
        print(f"   URL: {webhook.get('url')}")
        
        if secret:
            print(f"\n🔐 WEBHOOK SECRET (save this in .env as HUBBLE_WEBHOOK_SECRET):")
            print(f"   {secret}")
            print(f"\n   ⚠️  This secret is shown only once - save it now!")
        
        return True
    else:
        print(f"\n❌ Error creating webhook: {response.status_code}")
        print(f"   {response.text}")
        return False


def delete_webhook(webhook_id):
    """Delete a webhook by ID."""
    url = f"{API_BASE}/v1/org/{ORG_ID}/webhooks/{webhook_id}"
    headers = {"Authorization": f"Bearer {API_KEY}"}
    
    print(f"\n🗑️  Deleting webhook {webhook_id}...")
    response = httpx.delete(url, headers=headers, timeout=30.0)
    
    if response.status_code in (200, 204):
        print(f"   ✅ Webhook deleted")
        return True
    else:
        print(f"   ❌ Error: {response.status_code} - {response.text}")
        return False


def main():
    print("=" * 60)
    print("Hubble Webhook Registration")
    print("=" * 60)
    
    if not API_KEY or not ORG_ID:
        print("❌ Error: HUBBLE_API_KEY and HUBBLE_ORG_ID must be set")
        sys.exit(1)
    
    if not WEBHOOK_URL:
        print("❌ Error: HUBBLE_WEBHOOK_URL must be set")
        print("   Example: https://pinplot.me/api/webhooks/hubble")
        sys.exit(1)
    
    # List existing webhooks
    existing = list_webhooks()
    
    # Check if webhook already exists
    existing_pinplot = [wh for wh in existing if WEBHOOK_URL in wh.get("url", "")]
    
    if existing_pinplot:
        print(f"\n⚠️  Webhook for {WEBHOOK_URL} already exists")
        print(f"   Webhook ID: {existing_pinplot[0].get('id')}")
        
        response = input("\n   Delete and recreate? (y/N): ")
        if response.lower() == 'y':
            delete_webhook(existing_pinplot[0].get('id'))
            create_webhook()
        else:
            print("   No changes made")
    else:
        create_webhook()
    
    print("\n" + "=" * 60)
    print("Next Steps:")
    print("=" * 60)
    print("1. Add HUBBLE_WEBHOOK_SECRET to gps-tracker/backend/.env")
    print("2. Restart backend: docker compose restart backend")
    print("3. Monitor logs: docker logs -f pinplot_backend")
    print("4. Test webhook endpoint: curl https://pinplot.me/api/webhooks/hubble")
    print("=" * 60)


if __name__ == "__main__":
    main()
