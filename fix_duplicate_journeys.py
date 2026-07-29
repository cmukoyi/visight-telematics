#!/usr/bin/env python3
"""
Fix duplicate journeys causing UniqueViolation on ux_journey_device_start.

Finds and removes duplicate (device_imei, started_at) pairs, keeping only the oldest journey.
"""

import psycopg2
from psycopg2.extras import RealDictCursor
import sys

# Database connection config
DB_CONFIG = {
    'dbname': 'beacon_db',
    'user': 'beacon_user',
    'password': 'beacon_pw_2024',
    'host': 'localhost',
    'port': 5432
}

def find_duplicates(cursor):
    """Find duplicate journeys."""
    cursor.execute("""
        SELECT 
            device_imei,
            started_at,
            COUNT(*) as duplicate_count,
            MIN(created_at) as oldest_created,
            MAX(created_at) as newest_created,
            ARRAY_AGG(id ORDER BY created_at) as journey_ids
        FROM journeys
        GROUP BY device_imei, started_at
        HAVING COUNT(*) > 1
        ORDER BY device_imei, started_at;
    """)
    return cursor.fetchall()

def delete_duplicates(cursor, dry_run=True):
    """Delete duplicate journeys, keeping the oldest."""
    if dry_run:
        print("🔍 DRY RUN - No changes will be made")
    
    duplicates = find_duplicates(cursor)
    
    if not duplicates:
        print("✅ No duplicate journeys found!")
        return 0
    
    print(f"⚠️  Found {len(duplicates)} duplicate journey sets:\n")
    
    total_to_delete = 0
    for dup in duplicates:
        keep_id = dup['journey_ids'][0]  # Oldest
        delete_ids = dup['journey_ids'][1:]  # All others
        total_to_delete += len(delete_ids)
        
        print(f"Device {dup['device_imei']} @ {dup['started_at']}:")
        print(f"  - {len(dup['journey_ids'])} duplicates (keeping {keep_id})")
        print(f"  - Will delete: {delete_ids}")
    
    print(f"\n📊 Summary: {total_to_delete} duplicate journeys to delete\n")
    
    if dry_run:
        print("✋ Dry run complete. Run with --fix to apply changes.")
        return total_to_delete
    
    # Perform deletion
    cursor.execute("""
        WITH duplicates AS (
            SELECT 
                device_imei,
                started_at,
                id,
                created_at,
                ROW_NUMBER() OVER (PARTITION BY device_imei, started_at ORDER BY created_at ASC) as rn
            FROM journeys
            WHERE (device_imei, started_at) IN (
                SELECT device_imei, started_at
                FROM journeys
                GROUP BY device_imei, started_at
                HAVING COUNT(*) > 1
            )
        )
        DELETE FROM journeys
        WHERE id IN (
            SELECT id FROM duplicates WHERE rn > 1
        );
    """)
    
    deleted_count = cursor.rowcount
    print(f"✅ Deleted {deleted_count} duplicate journeys")
    
    # Verify
    remaining = find_duplicates(cursor)
    if remaining:
        print(f"⚠️  WARNING: {len(remaining)} duplicate sets still remain!")
        return deleted_count
    
    print("✅ All duplicates removed!")
    return deleted_count

def main():
    dry_run = '--fix' not in sys.argv
    
    try:
        conn = psycopg2.connect(**DB_CONFIG)
        cursor = conn.cursor(cursor_factory=RealDictCursor)
        
        deleted = delete_duplicates(cursor, dry_run=dry_run)
        
        if not dry_run and deleted > 0:
            conn.commit()
            print("✅ Changes committed")
        
        cursor.close()
        conn.close()
        
    except Exception as e:
        print(f"❌ Error: {e}")
        if not dry_run:
            conn.rollback()
        sys.exit(1)

if __name__ == '__main__':
    main()
