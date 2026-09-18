#!/usr/bin/env python3
"""
Add missing Settings i18n translation keys and auto-translate to French
Usage: 
  Local: python3 add_settings_translation_keys.py
  Server: docker exec -i pinplot_backend python3 /app/add_settings_translation_keys.py
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

# New Settings translation keys to add
NEW_KEYS = [
    # Account & Security
    ('settings.account_security', 'settings', 'Account & Security'),
    ('settings.account_security_hint', 'settings', 'Change your login password.'),
    ('settings.password', 'settings', 'Password'),
    ('settings.password_hint', 'settings', 'Keep your account secure with a strong password.'),
    ('settings.change_password', 'settings', 'Change Password'),
    ('settings.current_password', 'settings', 'Current password'),
    ('settings.new_password', 'settings', 'New password'),
    ('settings.new_password_min', 'settings', 'min 8 characters'),
    ('settings.confirm_new_password', 'settings', 'Confirm new password'),
    
    # Data Retention
    ('settings.data_retention', 'settings', 'Data Retention'),
    ('settings.data_retention_hint', 'settings', 'How long movement history is stored for your assets. Older data is automatically purged.'),
    ('settings.history_retention', 'settings', 'History Retention'),
    ('settings.history_retention_hint', 'settings', 'Tag location history older than this will be removed.'),
    ('settings.edit', 'settings', 'Edit'),
    ('settings.30_days', 'settings', '30 days'),
    ('settings.60_days', 'settings', '60 days'),
    ('settings.90_days', 'settings', '90 days'),
    ('settings.6_months', 'settings', '6 months'),
    ('settings.1_year', 'settings', '1 year'),
    ('settings.2_years', 'settings', '2 years'),
    ('settings.3_years', 'settings', '3 years'),
    ('settings.retention_auto_delete_hint', 'settings', 'Data beyond this period is automatically deleted to save storage.'),
    
    # Appearance
    ('settings.company_logo_dark', 'settings', 'Company Logo (Dark Mode)'),
    ('settings.dark_mode', 'settings', 'Dark Mode'),
    ('settings.logo_dark_hint', 'settings', 'Optional alternative logo for dark mode. Falls back to the light logo if not set.'),
    ('settings.no_logo', 'settings', 'No logo'),
    ('settings.upload', 'settings', 'Upload'),
    ('settings.remove', 'settings', 'Remove'),
    ('settings.primary_colour', 'settings', 'Primary Colour'),
    ('settings.primary_colour_hint', 'settings', 'Buttons, links, active states.'),
    ('settings.accent_colour', 'settings', 'Accent Colour'),
    ('settings.accent_colour_hint', 'settings', 'Secondary highlights.'),
    ('settings.restore_default', 'settings', 'Restore default'),
    ('settings.save_appearance', 'settings', 'Save Appearance'),
    ('settings.discard', 'settings', 'Discard'),
    
    # Alerts & Notifications
    ('settings.alerts_notifications', 'settings', 'Alerts & Notifications'),
    ('settings.alerts_notifications_hint', 'settings', 'Control when you are notified about your assets.'),
    ('settings.enable_alerts', 'settings', 'Enable Alerts'),
    ('settings.enable_alerts_hint', 'settings', 'Master switch — turns all notifications on or off.'),
    ('settings.notify_when_tag', 'settings', 'Notify me when a tag…'),
    ('settings.geofence_entry_exit', 'settings', 'Geofence entry / exit'),
    ('settings.geofence_entry_exit_hint', 'settings', 'Alert when an asset enters or exits a defined geofence area.'),
    ('settings.battery_low', 'settings', 'Battery is low'),
    ('settings.battery_low_hint', 'settings', 'Alert when a tag\'s battery drops below 20%.'),
    ('settings.offline_7_days', 'settings', 'Alert when a tag hasn\'t been reported a location in last 7 days'),
    ('settings.offline_7_days_hint', 'settings', 'Alert when a tag hasn\'t been detected for an extended period.'),
    ('settings.hive_breach', 'settings', 'Hive breach detected'),
    ('settings.hive_breach_hint', 'settings', 'Alert when a tag separates from its HIVE group beyond the configured threshold.'),
    ('settings.temperature_monitoring', 'settings', 'Temperature threshold'),
    ('settings.temperature_monitoring_hint', 'settings', 'Alert when a monitored tag crosses its configured high or low temperature limit.'),
    ('settings.how_to_notify', 'settings', 'How to notify me'),
    ('settings.email_notifications', 'settings', 'Email notifications'),
    ('settings.email_notifications_hint', 'settings', 'Send alert emails to the addresses listed below.'),
    ('settings.notification_addresses', 'settings', 'Notification addresses — your login email is always included.'),
    ('settings.add_email_placeholder', 'settings', 'Add email address…'),
    ('settings.add', 'settings', 'Add'),
    ('settings.sms_alerts', 'settings', 'SMS Alerts'),
    ('settings.sms_alerts_hint', 'settings', 'Receive text messages for your alerts.'),
    ('settings.mobile_number', 'settings', 'Mobile Number'),
    ('settings.mobile_number_hint', 'settings', 'UK numbers: 07xxx will be converted to +44 automatically.'),
    ('settings.phone_placeholder', 'settings', 'e.g. 07700900123 or +447700900123'),
    ('settings.sms_alert_types', 'settings', 'SMS alert types'),
    ('settings.geofence_sms', 'settings', 'Geofence entry / exit alerts'),
    ('settings.battery_sms', 'settings', 'Battery low alerts'),
    ('settings.offline_sms', 'settings', 'Tag offline alerts'),
    ('settings.hive_sms', 'settings', 'Hive breach alerts'),
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
    print("🌍 Adding Missing Settings Translation Keys\n")
    
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
