#!/usr/bin/env python3
"""
Test translation APIs locally before deployment.
Tests both LibreTranslate and MyMemory APIs.
"""
import httpx
import asyncio
import sys


async def test_libretranslate():
    """Test LibreTranslate API"""
    print("Testing LibreTranslate...")
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.post(
                'https://libretranslate.com/translate',
                json={
                    'q': 'Hello, world!',
                    'source': 'en',
                    'target': 'fr',
                    'format': 'text'
                },
                headers={'Content-Type': 'application/json'}
            )
            
            print(f"Status: {response.status_code}")
            print(f"Response: {response.text[:200]}")
            
            if response.status_code == 200:
                data = response.json()
                translated = data.get('translatedText', '')
                print(f"✅ LibreTranslate SUCCESS: '{translated}'")
                return True
            else:
                print(f"❌ LibreTranslate FAILED: {response.status_code}")
                return False
    
    except Exception as e:
        print(f"❌ LibreTranslate ERROR: {e}")
        return False


async def test_mymemory():
    """Test MyMemory API"""
    print("\nTesting MyMemory...")
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.get(
                'https://api.mymemory.translated.net/get',
                params={
                    'q': 'Hello, world!',
                    'langpair': 'en|fr'
                }
            )
            
            print(f"Status: {response.status_code}")
            print(f"Response: {response.text[:200]}")
            
            if response.status_code == 200:
                data = response.json()
                translated = data.get('responseData', {}).get('translatedText', '')
                print(f"✅ MyMemory SUCCESS: '{translated}'")
                return True
            else:
                print(f"❌ MyMemory FAILED: {response.status_code}")
                return False
    
    except Exception as e:
        print(f"❌ MyMemory ERROR: {e}")
        return False


async def main():
    print("=" * 60)
    print("Translation API Test Suite")
    print("=" * 60)
    
    results = []
    
    # Test both services
    results.append(await test_libretranslate())
    results.append(await test_mymemory())
    
    print("\n" + "=" * 60)
    print("SUMMARY")
    print("=" * 60)
    print(f"LibreTranslate: {'✅ WORKING' if results[0] else '❌ FAILED'}")
    print(f"MyMemory: {'✅ WORKING' if results[1] else '❌ FAILED'}")
    
    if any(results):
        print("\n✅ At least one service is working - safe to deploy")
        sys.exit(0)
    else:
        print("\n❌ ALL SERVICES FAILED - DO NOT DEPLOY")
        sys.exit(1)


if __name__ == '__main__':
    asyncio.run(main())
