#!/usr/bin/env python3
"""
Cleanup script for TagIndoorPosition table - removes unregistered BLE devices.

This script removes TagIndoorPosition records where the tag_id does not match
any active BLETag record with tag_type='ble'. This fixes the 38k unregistered
device problem caused by tracking all ambient BLE devices before the tag_type
filter was added to pareto_bridge.py.

Usage:
    # Dry-run (preview what would be deleted):
    python cleanup_unregistered_indoor_positions.py --dry-run

    # Actually delete:
    python cleanup_unregistered_indoor_positions.py

    # Backup first, then delete:
    python cleanup_unregistered_indoor_positions.py --backup

Environment:
    - Run from gps-tracker/backend/ directory so app.database can be imported
    - Requires DATABASE_URL in .env or environment
"""
import argparse
import sys
import os
from datetime import datetime
from pathlib import Path

# Add parent directory to path so we can import app modules
sys.path.insert(0, str(Path(__file__).parent.parent))

from app.database import SessionLocal, engine
from app.models import TagIndoorPosition, BLETag
from sqlalchemy import text


def backup_table(db):
    """Create a backup of tag_indoor_positions table."""
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup_table_name = f"tag_indoor_positions_backup_{timestamp}"
    
    print(f"📦 Creating backup: {backup_table_name}")
    db.execute(text(f"""
        CREATE TABLE {backup_table_name} AS 
        SELECT * FROM tag_indoor_positions;
    """))
    db.commit()
    
    count = db.execute(text(f"SELECT COUNT(*) FROM {backup_table_name}")).scalar()
    print(f"✅ Backed up {count:,} records to {backup_table_name}")
    return backup_table_name


def get_unregistered_positions(db):
    """Query for TagIndoorPosition records without matching active BLETag (tag_type='ble')."""
    return db.query(TagIndoorPosition).filter(
        ~db.query(BLETag).filter(
            BLETag.mac_address == TagIndoorPosition.tag_id,
            BLETag.tag_type == "ble",
            BLETag.is_active == True
        ).exists()
    ).all()


def get_stats(db):
    """Get current statistics."""
    total_positions = db.query(TagIndoorPosition).count()
    registered_ble_tags = db.query(BLETag).filter(
        BLETag.tag_type == "ble",
        BLETag.is_active == True
    ).count()
    unregistered_positions = len(get_unregistered_positions(db))
    
    return {
        "total_positions": total_positions,
        "registered_ble_tags": registered_ble_tags,
        "unregistered_positions": unregistered_positions
    }


def main():
    parser = argparse.ArgumentParser(
        description="Clean up unregistered BLE devices from TagIndoorPosition table"
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Preview what would be deleted without actually deleting"
    )
    parser.add_argument(
        "--backup",
        action="store_true",
        help="Create a backup table before deleting"
    )
    args = parser.parse_args()

    db = SessionLocal()
    
    try:
        print("🔍 Analyzing tag_indoor_positions table...")
        print()
        
        stats = get_stats(db)
        
        print("📊 Current Statistics:")
        print(f"   Total indoor positions: {stats['total_positions']:,}")
        print(f"   Registered BLE tags (type='ble', active): {stats['registered_ble_tags']:,}")
        print(f"   Unregistered positions to clean: {stats['unregistered_positions']:,}")
        print()
        
        if stats['unregistered_positions'] == 0:
            print("✨ No cleanup needed - all positions are registered!")
            return 0
        
        percentage = (stats['unregistered_positions'] / stats['total_positions'] * 100) if stats['total_positions'] > 0 else 0
        print(f"⚠️  {percentage:.1f}% of positions are unregistered")
        print()
        
        if args.dry_run:
            print("🔬 DRY-RUN MODE - No records will be deleted")
            print()
            print("Sample of unregistered tag_ids (first 20):")
            unregistered = get_unregistered_positions(db)
            for i, pos in enumerate(unregistered[:20], 1):
                print(f"   {i}. {pos.tag_id} (floor_id={pos.floor_id}, last_seen={pos.last_seen})")
            if len(unregistered) > 20:
                print(f"   ... and {len(unregistered) - 20:,} more")
            print()
            print("Run without --dry-run to actually delete these records")
            return 0
        
        # Backup if requested
        backup_name = None
        if args.backup:
            backup_name = backup_table(db)
            print()
        
        # Confirm deletion
        print("⚠️  WARNING: About to delete unregistered indoor positions!")
        if backup_name:
            print(f"   Backup created: {backup_name}")
        print(f"   Records to delete: {stats['unregistered_positions']:,}")
        print()
        response = input("Type 'DELETE' to confirm: ")
        
        if response != "DELETE":
            print("❌ Cancelled - no records deleted")
            return 1
        
        # Perform deletion
        print()
        print("🗑️  Deleting unregistered positions...")
        
        deleted_count = db.query(TagIndoorPosition).filter(
            ~db.query(BLETag).filter(
                BLETag.mac_address == TagIndoorPosition.tag_id,
                BLETag.tag_type == "ble",
                BLETag.is_active == True
            ).exists()
        ).delete(synchronize_session=False)
        
        db.commit()
        
        print(f"✅ Deleted {deleted_count:,} unregistered indoor positions")
        print()
        
        # Show final stats
        final_stats = get_stats(db)
        print("📊 Final Statistics:")
        print(f"   Total indoor positions: {final_stats['total_positions']:,}")
        print(f"   Registered BLE tags: {final_stats['registered_ble_tags']:,}")
        print(f"   Unregistered positions remaining: {final_stats['unregistered_positions']:,}")
        print()
        
        if backup_name:
            print(f"💡 Tip: To restore from backup if needed:")
            print(f"   DROP TABLE tag_indoor_positions;")
            print(f"   ALTER TABLE {backup_name} RENAME TO tag_indoor_positions;")
        
        print()
        print("✅ Cleanup complete!")
        
        return 0
        
    except Exception as e:
        db.rollback()
        print(f"❌ Error: {e}", file=sys.stderr)
        import traceback
        traceback.print_exc()
        return 1
    finally:
        db.close()


if __name__ == "__main__":
    sys.exit(main())
