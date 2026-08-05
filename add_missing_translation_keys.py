#!/usr/bin/env python3
"""
Extract all i18n translation keys from customer-dashboard/public/index.html
and add missing keys to the database.

This script:
1. Parses index.html for data-i18n, data-i18n-title, data-i18n-placeholder attributes
2. Groups keys by category (prefix before the dot)
3. Adds missing keys to translation_keys table
4. Reports what was added

Usage:
  Local:  python3 add_missing_translation_keys.py
  Server: docker exec -i pinplot_backend python3 /tmp/add_missing_translation_keys.py
"""

import re
import psycopg2
import os
from collections import defaultdict

# Database connection - try environment variable first, then defaults
DATABASE_URL = os.getenv('DATABASE_URL')

if DATABASE_URL:
    # Parse postgresql://user:pass@host:port/dbname
    import re as regex_module
    match = regex_module.match(r'postgresql://([^:]+):([^@]+)@([^:]+):(\d+)/(.+)', DATABASE_URL)
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

def extract_keys_from_html(html_file_path):
    """Extract all unique translation keys from HTML file."""
    try:
        with open(html_file_path, 'r', encoding='utf-8') as f:
            html_content = f.read()
    except FileNotFoundError:
        print(f"❌ File not found: {html_file_path}")
        return []
    
    # Regex patterns to match data-i18n attributes
    patterns = [
        r'data-i18n="([^"]+)"',           # data-i18n="key"
        r'data-i18n-title="([^"]+)"',     # data-i18n-title="key"
        r'data-i18n-placeholder="([^"]+)"' # data-i18n-placeholder="key"
    ]
    
    keys = set()
    for pattern in patterns:
        matches = re.findall(pattern, html_content)
        keys.update(matches)
    
    return sorted(keys)

def categorize_keys(keys):
    """Group keys by category (prefix before first dot)."""
    categorized = defaultdict(list)
    
    for key in keys:
        if '.' in key:
            category = key.split('.', 1)[0]
            categorized[category].append(key)
        else:
            categorized['general'].append(key)
    
    return dict(categorized)

def generate_default_text(key):
    """Generate human-readable default text from key."""
    # Take the last part after final dot
    if '.' in key:
        text = key.split('.')[-1]
    else:
        text = key
    
    # Replace underscores with spaces
    text = text.replace('_', ' ')
    
    # Capitalize first letter of each word
    text = ' '.join(word.capitalize() for word in text.split())
    
    return text

def add_keys_to_database(keys):
    """Add missing translation keys to the database."""
    conn = None
    added_count = 0
    skipped_count = 0
    
    try:
        conn = psycopg2.connect(**DB_CONFIG)
        cur = conn.cursor()
        
        for key in keys:
            # Determine category
            if '.' in key:
                category = key.split('.', 1)[0]
            else:
                category = 'general'
            
            # Generate default text
            default_text = generate_default_text(key)
            
            # Check if key already exists
            cur.execute("SELECT id FROM translation_keys WHERE key = %s", (key,))
            existing = cur.fetchone()
            
            if existing:
                print(f"  ⏭️  {key} (already exists)")
                skipped_count += 1
                continue
            
            # Insert new key
            cur.execute("""
                INSERT INTO translation_keys (key, category, default_text, context)
                VALUES (%s, %s, %s, %s)
            """, (key, category, default_text, None))
            
            print(f"  ✅ {key} → {default_text}")
            added_count += 1
        
        conn.commit()
        cur.close()
        
        return added_count, skipped_count
        
    except Exception as e:
        print(f"❌ Database error: {e}")
        if conn:
            conn.rollback()
        return 0, 0
    finally:
        if conn:
            conn.close()

def main():
    print("=" * 80)
    print("Translation Keys Extraction & Database Import")
    print("=" * 80)
    print()
    
    # Try multiple possible paths for the HTML file
    possible_paths = [
        '/tmp/index.html',  # Temporary location when copied into container
        '/root/pinplot/gps-tracker/customer-dashboard/public/index.html',  # Pinplot host
        '/root/beacon-telematics/gps-tracker/customer-dashboard/public/index.html',  # Beacon host
        '/app/customer-dashboard/public/index.html',  # Inside backend container
        'gps-tracker/customer-dashboard/public/index.html',  # Relative path
        'customer-dashboard/public/index.html'  # Relative path fallback
    ]
    
    html_file = None
    for path in possible_paths:
        if os.path.exists(path):
            html_file = path
            break
    
    if not html_file:
        print(f"❌ Could not find index.html in any of these locations:")
        for path in possible_paths:
            print(f"   • {path}")
        return
    
    print(f"📄 Parsing HTML file: {html_file}")
    keys = extract_keys_from_html(html_file)
    print(f"   Found {len(keys)} unique translation keys\n")
    
    # Categorize keys
    categorized = categorize_keys(keys)
    
    print("📊 Keys by category:")
    for category, cat_keys in sorted(categorized.items()):
        print(f"   {category:20s} {len(cat_keys):3d} keys")
    print()
    
    # Show sample keys from each category
    print("📋 Sample keys from each category:")
    for category, cat_keys in sorted(categorized.items()):
        print(f"\n   {category.upper()}:")
        for key in sorted(cat_keys)[:5]:
            print(f"      • {key}")
        if len(cat_keys) > 5:
            print(f"      ... and {len(cat_keys) - 5} more")
    print()
    
    # Add to database
    print("💾 Adding missing keys to database...")
    added, skipped = add_keys_to_database(keys)
    
    print()
    print("=" * 80)
    print(f"✅ Complete! Added {added} new keys, skipped {skipped} existing keys")
    print("=" * 80)
    print()
    print("🌐 Next steps:")
    print("   1. Go to https://pinplot.me/admin/index.html#translations")
    print("   2. Click the refresh icon to see new keys")
    print("   3. Use 'Auto-translate All' to translate missing French keys")
    print("   4. Or manually translate keys one by one")
    print()

if __name__ == '__main__':
    main()
