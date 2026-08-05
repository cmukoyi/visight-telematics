#!/usr/bin/env python3
"""
Add missing i18n translation keys and auto-translate to French
Usage: 
  Local: python3 add_missing_translation_keys.py
  Server: docker exec -i pinplot_backend python3 /app/add_missing_translation_keys.py
"""

import psycopg2
import requests
import time
import os
from urllib.parse import quote

# Database connection - try environment variable first, then defaults
DATABASE_URL = os.getenv('DATABASE_URL')

if DATABASE_URL:
    # Parse postgresql://user:pass@host:port/dbname
    import re
    match = re.match(r'postgresql://([^:]+):([^@]+)@([^:]+):(\d+)/(.+)', DATABASE_URL)
    if match:
        DB_CONFIG = {
            'user': match.group(1),
            'password': match.group(2),
            'host': match.group(3),
            'port': int(match.group(4)),
            'database': match.group(5)
        }
    else:
        print("❌ Failed to parse DATABASE_URL")
        exit(1)
else:
    # Local development defaults
    DB_CONFIG = {
        'host': 'localhost',
        'port': 5432,
        'database': 'pinplot_db',
        'user': 'pinplot_db_user',
        'password': 'pinplot_db_password'
    }

# MyMemory API for translations
MYMEMORY_API = "https://api.mymemory.translated.net/get"

# New translation keys to add
NEW_KEYS = [
    # Assets
    ('assets.asset_tag', 'assets', 'Asset / Tag'),
    ('assets.description', 'assets', 'Description'),
    ('assets.type', 'assets', 'Type'),
    ('assets.category', 'assets', 'Category'),
    ('assets.status', 'assets', 'Status'),
    ('assets.package', 'assets', 'Package'),
    ('assets.battery', 'assets', 'Battery'),
    ('assets.last_location', 'assets', 'Last Location'),
    ('assets.last_update', 'assets', 'Last Update'),
    ('assets.expires', 'assets', 'Expires'),
    
    # Geofences
    ('geofences.name_required', 'geofences', 'Name *'),
    ('geofences.address_latlng', 'geofences', 'Address / Lat,Lng'),
    ('geofences.radius', 'geofences', 'Radius'),
    ('geofences.save_location', 'geofences', 'Save location'),
    
    # Common
    ('common.id', 'common', 'ID'),
    ('common.tag', 'common', 'Tag'),
    ('common.last_seen', 'common', 'Last Seen'),
    ('common.distance', 'common', 'Distance'),
    ('common.role', 'common', 'Role'),
    
    # Floor Plan
    ('floor_plan.room_name', 'floor_plan', 'Room name…'),
    ('floor_plan.mac_address', 'floor_plan', 'A4:CF:12:45:AB:CD'),
    
    # Settings/Auth
    ('settings.save_password', 'settings', 'Save Password'),
    ('auth.save_role', 'auth', 'Save Role'),
    
    # Trips (from earlier code additions)
    ('trips.start', 'trips', 'Start'),
    ('trips.end', 'trips', 'End'),
    ('trips.duration', 'trips', 'Duration'),
    ('trips.distance_mi', 'trips', 'Distance (mi)'),
    ('trips.from', 'trips', 'From'),
    ('trips.to', 'trips', 'To'),
    
    # Alerts (from earlier code additions)
    ('alerts.type', 'alerts', 'Type'),
    ('alerts.detail', 'alerts', 'Detail'),
    ('alerts.time', 'alerts', 'Time'),
]


def translate_text(text, source_lang='en', target_lang='fr'):
    """Translate text using MyMemory API"""
    try:
        url = f"{MYMEMORY_API}?q={quote(text)}&langpair={source_lang}|{target_lang}"
        response = requests.get(url, timeout=10)
        
        if response.status_code == 200:
            data = response.json()
            if data.get('responseStatus') == 200:
                return data['responseData']['translatedText']
        
        print(f"  ⚠️  Translation failed for '{text}', using original")
        return text
    except Exception as e:
        print(f"  ⚠️  Translation error for '{text}': {e}")
        return text


def main():
    print("🌍 Adding Missing Translation Keys\n")
    
    # Connect to database
    try:
        conn = psycopg2.connect(**DB_CONFIG)
        cur = conn.cursor()
        print("✅ Connected to database\n")
    except Exception as e:
        print(f"❌ Database connection failed: {e}")
        return
    
    added_count = 0
    skipped_count = 0
    translated_count = 0
    
    try:
        for key, category, default_text in NEW_KEYS:
            # Check if key already exists
            cur.execute("SELECT id FROM translation_keys WHERE key = %s", (key,))
            if cur.fetchone():
                print(f"⏭️  Skipped {key} (already exists)")
                skipped_count += 1
                continue
            
            # Insert translation key
            cur.execute(
                """
                INSERT INTO translation_keys (key, category, default_text, created_at)
                VALUES (%s, %s, %s, NOW())
                RETURNING id
                """,
                (key, category, default_text)
            )
            key_id = cur.fetchone()[0]
            conn.commit()
            
            print(f"✅ Added key: {key}")
            added_count += 1
            
            # Auto-translate to French
            french_text = translate_text(default_text, 'en', 'fr')
            time.sleep(0.5)  # Rate limit: 2 requests/second
            
            # Insert French translation
            try:
                cur.execute(
                    """
                    INSERT INTO translations (language_code, key, translated_text, last_updated)
                    VALUES ('fr', %s, %s, NOW())
                    ON CONFLICT (language_code, key) DO UPDATE
                    SET translated_text = EXCLUDED.translated_text, last_updated = NOW()
                    """,
                    (key, french_text)
                )
                conn.commit()
                print(f"   🇫🇷 '{default_text}' → '{french_text}'")
                translated_count += 1
            except Exception as e:
                print(f"   ⚠️  French translation insert failed: {e}")
                conn.rollback()
        
        print(f"\n📊 Summary:")
        print(f"   ✅ Added: {added_count} keys")
        print(f"   ⏭️  Skipped: {skipped_count} keys (already existed)")
        print(f"   🇫🇷 Translated: {translated_count} to French")
        
    except Exception as e:
        print(f"❌ Error: {e}")
        conn.rollback()
    finally:
        cur.close()
        conn.close()
        print("\n✅ Done!")


if __name__ == "__main__":
    main()
