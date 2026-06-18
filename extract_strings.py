#!/usr/bin/env python3
"""
Extract hardcoded strings from Customer Dashboard HTML/JS files.
Generates a comprehensive list of translation keys with context.
"""
import re
import json
from pathlib import Path
from collections import defaultdict
import sys


def extract_html_strings(file_path):
    """Extract strings from HTML elements"""
    strings = []
    
    with open(file_path, 'r', encoding='utf-8') as f:
        content = f.read()
    
    # Extract from element text content
    # Matches: <button>Text</button>, <h1>Title</h1>, etc.
    pattern = r'<(?:button|h[1-6]|label|span|p|a|title|option|th|td)[^>]*>([^<]+)</(?:button|h[1-6]|label|span|p|a|title|option|th|td)>'
    matches = re.findall(pattern, content, re.MULTILINE)
    
    for match in matches:
        text = match.strip()
        # Skip empty, numbers, variables, HTML entities
        if text and not text.startswith('${') and not text.startswith('{{') and len(text) > 1 and not text.isdigit():
            strings.append(('html_content', text, extract_context(content, text)))
    
    # Extract from placeholder attributes
    placeholder_pattern = r'placeholder=["\']([^"\']+)["\']'
    matches = re.findall(placeholder_pattern, content)
    for match in matches:
        if match and len(match) > 1:
            strings.append(('placeholder', match, 'Input placeholder'))
    
    # Extract from title attributes
    title_pattern = r'title=["\']([^"\']+)["\']'
    matches = re.findall(title_pattern, content)
    for match in matches:
        if match and len(match) > 1:
            strings.append(('title', match, 'Tooltip'))
    
    # Extract from alert/confirm messages
    alert_pattern = r'(?:alert|confirm)\(["\']([^"\']+)["\']\)'
    matches = re.findall(alert_pattern, content)
    for match in matches:
        if match and len(match) > 5:
            strings.append(('alert', match, 'Alert/Confirm message'))
    
    return strings


def extract_context(content, text):
    """Try to determine context from surrounding code"""
    # Find the line with this text
    for line in content.split('\n'):
        if text in line:
            # Check for common patterns
            if 'button' in line.lower():
                return 'Button text'
            elif 'label' in line.lower():
                return 'Form label'
            elif '<h1' in line or '<h2' in line or '<h3' in line:
                return 'Page heading'
            elif 'nav' in line.lower():
                return 'Navigation item'
            elif 'modal' in line.lower():
                return 'Modal dialog'
            elif 'error' in line.lower():
                return 'Error message'
            elif 'success' in line.lower():
                return 'Success message'
    return 'General UI text'


def generate_key(text, category_prefix=''):
    """Generate a translation key from text"""
    # Remove special characters, convert to snake_case
    key = re.sub(r'[^a-zA-Z0-9\s]', '', text.lower())
    key = re.sub(r'\s+', '_', key)
    key = key[:50]  # Max 50 chars
    
    if category_prefix:
        return f"{category_prefix}.{key}"
    return key


def categorize_strings(strings):
    """Organize strings by category"""
    categories = defaultdict(list)
    
    for source_type, text, context in strings:
        # Determine category based on context and content
        text_lower = text.lower()
        
        if any(word in text_lower for word in ['login', 'password', 'email', 'sign in', 'sign out', 'logout', 'forgot']):
            category = 'auth'
        elif any(word in text_lower for word in ['dashboard', 'overview', 'welcome']):
            category = 'dashboard'
        elif any(word in text_lower for word in ['live map', 'map', 'location', 'track']):
            category = 'map'
        elif any(word in text_lower for word in ['asset', 'device', 'tag', 'beacon']):
            category = 'assets'
        elif any(word in text_lower for word in ['trip', 'history', 'movement', 'route']):
            category = 'trips'
        elif any(word in text_lower for word in ['geofence', 'fence', 'zone']):
            category = 'geofences'
        elif any(word in text_lower for word in ['alert', 'notification', 'inbox']):
            category = 'alerts'
        elif any(word in text_lower for word in ['report', 'analytics']):
            category = 'reports'
        elif any(word in text_lower for word in ['setting', 'profile', 'preference', 'language']):
            category = 'settings'
        elif any(word in text_lower for word in ['save', 'cancel', 'delete', 'edit', 'add', 'remove', 'close', 'confirm', 'back', 'next', 'search', 'filter', 'sort']):
            category = 'common'
        elif any(word in text_lower for word in ['error', 'failed', 'invalid']):
            category = 'errors'
        elif any(word in text_lower for word in ['success', 'saved', 'updated', 'created']):
            category = 'success'
        else:
            category = 'general'
        
        categories[category].append({
            'text': text,
            'context': context,
            'source_type': source_type
        })
    
    return categories


def main():
    dashboard_path = Path('gps-tracker/customer-dashboard/public/index.html')
    
    if not dashboard_path.exists():
        print(f"❌ Error: {dashboard_path} not found")
        sys.exit(1)
    
    print("=" * 80)
    print("🔍 Customer Dashboard String Extraction")
    print("=" * 80)
    print()
    
    # Extract strings
    print(f"📄 Extracting from: {dashboard_path}")
    strings = extract_html_strings(dashboard_path)
    
    # Remove duplicates
    unique_strings = list(set(strings))
    print(f"✅ Found {len(unique_strings)} unique strings")
    print()
    
    # Categorize
    categories = categorize_strings(unique_strings)
    
    # Generate translation keys
    translation_keys = []
    seen_keys = set()
    
    for category, items in sorted(categories.items()):
        print(f"\n📦 Category: {category.upper()} ({len(items)} strings)")
        print("-" * 80)
        
        for item in items:
            key = generate_key(item['text'], category)
            
            # Ensure unique keys
            counter = 1
            original_key = key
            while key in seen_keys:
                key = f"{original_key}_{counter}"
                counter += 1
            
            seen_keys.add(key)
            
            translation_keys.append({
                'key': key,
                'category': category,
                'context': item['context'],
                'default_text': item['text']
            })
            
            print(f"  • {key}: \"{item['text']}\" ({item['context']})")
    
    # Save to JSON
    output_file = 'extracted_translation_keys.json'
    with open(output_file, 'w', encoding='utf-8') as f:
        json.dump(translation_keys, f, indent=2, ensure_ascii=False)
    
    print()
    print("=" * 80)
    print(f"✅ Extraction complete!")
    print(f"📊 Total keys: {len(translation_keys)}")
    print(f"📁 Output: {output_file}")
    print()
    print("📋 Summary by category:")
    for category, items in sorted(categories.items()):
        print(f"  • {category}: {len(items)} keys")
    print()
    print("🎯 Next steps:")
    print("  1. Review extracted_translation_keys.json")
    print("  2. Refine categories and contexts")
    print("  3. Generate migration 051 from this data")
    print("  4. Run auto-translate for French")
    print("=" * 80)


if __name__ == '__main__':
    main()
