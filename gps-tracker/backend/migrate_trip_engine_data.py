"""
One-time migration script to populate trip engine tables from existing tracksolid_locations data.

This script:
1. Migrates positions from tracksolid_locations → device_positions
2. Creates device_state rows with trip_subscribed=true for all devices
3. Initializes tracksolid_sync_state

Run this ONCE before starting the trip engine background tasks.

Usage:
    python migrate_trip_engine_data.py [--imei IMEI] [--all] [--dry-run]
"""

import argparse
import asyncio
from datetime import datetime, timezone
from typing import List, Optional

from sqlalchemy import select, func
from sqlalchemy.dialects.postgresql import insert

from app.database import SessionLocal
from app.models import (
    TrackSolidLocation,
    DevicePosition,
    DeviceState,
    TrackSolidSyncState,
)


def migrate_positions(db, imei: Optional[str] = None, limit: Optional[int] = None, dry_run: bool = False):
    """
    Migrate positions from tracksolid_locations to device_positions.
    
    Args:
        db: Database session
        imei: If provided, only migrate this IMEI. Otherwise migrate all.
        limit: If provided, limit number of positions per device
        dry_run: If True, don't commit changes
    """
    print("\n" + "="*80)
    print("MIGRATING POSITIONS FROM tracksolid_locations → device_positions")
    print("="*80)
    
    # Build query
    query = select(TrackSolidLocation)
    
    if imei:
        query = query.where(TrackSolidLocation.imei == imei)
        print(f"🎯 Target: IMEI {imei}")
    else:
        print(f"🎯 Target: ALL devices")
    
    query = query.order_by(TrackSolidLocation.imei, TrackSolidLocation.timestamp)
    
    if limit:
        # Note: This limits total, not per-device
        query = query.limit(limit)
        print(f"⚠️  Limited to {limit} total positions")
    
    locations = db.execute(query).scalars().all()
    
    print(f"\n📊 Found {len(locations)} positions to migrate")
    
    if dry_run:
        print("🔍 DRY RUN MODE - No changes will be committed")
        # Show sample
        if locations:
            print(f"\nSample positions:")
            for loc in locations[:5]:
                print(f"  IMEI {loc.imei}: {loc.timestamp} @ ({loc.latitude}, {loc.longitude})")
        return 0
    
    # Migrate positions
    inserted_count = 0
    skipped_count = 0
    
    for loc in locations:
        # Prepare position data
        position_data = {
            'device_imei': loc.imei,
            'lat': loc.latitude,
            'lng': loc.longitude,
            'observed_at': loc.timestamp,  # Already UTC
            'direction': loc.direction,
            'gps_speed': loc.speed,
            'pos_type': None,  # Not in tracksolid_locations
            'satellite': None,
            'ignition': None,
            'acc_status': None,
            'gps_mode': None,
            'confidence': None,
            'source': 'migration',
            'created_at': datetime.now(timezone.utc),
        }
        
        # UPSERT with ON CONFLICT DO NOTHING (idempotent)
        stmt = insert(DevicePosition).values(**position_data).on_conflict_do_nothing(
            index_elements=['device_imei', 'observed_at']
        )
        result = db.execute(stmt)
        
        if result.rowcount > 0:
            inserted_count += 1
        else:
            skipped_count += 1
    
    db.commit()
    
    print(f"\n✅ Migration complete:")
    print(f"   Inserted: {inserted_count}")
    print(f"   Skipped (duplicates): {skipped_count}")
    
    return inserted_count


def create_device_states(db, imei: Optional[str] = None, subscribe_all: bool = False, dry_run: bool = False):
    """
    Create device_state rows for all devices in device_positions.
    
    Args:
        db: Database session
        imei: If provided, only create for this IMEI
        subscribe_all: If True, set trip_subscribed=true for all devices
        dry_run: If True, don't commit changes
    """
    print("\n" + "="*80)
    print("CREATING device_state ROWS")
    print("="*80)
    
    # Get unique IMEIs from device_positions
    if imei:
        imeis = [imei]
        print(f"🎯 Target: IMEI {imei}")
    else:
        query = select(DevicePosition.device_imei).distinct()
        imeis = [row[0] for row in db.execute(query).all()]
        print(f"🎯 Target: {len(imeis)} devices from device_positions")
    
    if dry_run:
        print(f"🔍 DRY RUN MODE - Would create {len(imeis)} device_state rows")
        print(f"   trip_subscribed: {subscribe_all}")
        return 0
    
    created_count = 0
    now = datetime.now(timezone.utc)
    
    for device_imei in imeis:
        # Get latest position timestamp for this device
        latest_pos = db.execute(
            select(func.max(DevicePosition.observed_at))
            .where(DevicePosition.device_imei == device_imei)
        ).scalar()
        
        # UPSERT device_state row
        stmt = insert(DeviceState).values(
            device_imei=device_imei,
            last_position_ts=latest_pos,
            last_batch_ts=now,
            trip_subscribed=subscribe_all,
            created_at=now,
            updated_at=now,
        ).on_conflict_do_update(
            index_elements=['device_imei'],
            set_={
                'last_position_ts': latest_pos,
                'last_batch_ts': now,
                'trip_subscribed': subscribe_all,
                'updated_at': now,
            }
        )
        db.execute(stmt)
        created_count += 1
    
    db.commit()
    
    print(f"\n✅ Created/updated {created_count} device_state rows")
    print(f"   trip_subscribed: {subscribe_all}")
    
    return created_count


def initialize_sync_state(db, dry_run: bool = False):
    """Initialize tracksolid_sync_state singleton row."""
    print("\n" + "="*80)
    print("INITIALIZING tracksolid_sync_state")
    print("="*80)
    
    if dry_run:
        print("🔍 DRY RUN MODE - Would create tracksolid_sync_state row")
        return
    
    now = datetime.now(timezone.utc)
    next_reset = now.replace(hour=0, minute=0, second=0, microsecond=0)
    if next_reset <= now:
        from datetime import timedelta
        next_reset += timedelta(days=1)
    
    stmt = insert(TrackSolidSyncState).values(
        id=1,
        last_batch_sweep_at=now,
        api_calls_today=0,
        api_calls_reset_at=next_reset,
        updated_at=now,
    ).on_conflict_do_nothing(
        index_elements=['id']
    )
    
    result = db.execute(stmt)
    db.commit()
    
    if result.rowcount > 0:
        print(f"✅ Created tracksolid_sync_state row")
    else:
        print(f"ℹ️  tracksolid_sync_state already exists")


def main():
    parser = argparse.ArgumentParser(description='Migrate tracksolid_locations to trip engine tables')
    parser.add_argument('--imei', type=str, help='Migrate only this IMEI')
    parser.add_argument('--all', action='store_true', help='Migrate ALL devices (default: single IMEI)')
    parser.add_argument('--limit', type=int, help='Limit number of positions to migrate')
    parser.add_argument('--subscribe-all', action='store_true', help='Set trip_subscribed=true for all devices')
    parser.add_argument('--dry-run', action='store_true', help='Show what would be done without making changes')
    
    args = parser.parse_args()
    
    if not args.imei and not args.all:
        # Default: migrate test device
        args.imei = '781950640095475'
        print(f"⚠️  No --imei or --all specified, defaulting to test device: {args.imei}")
    
    db = SessionLocal()
    
    try:
        # Step 1: Migrate positions
        migrate_positions(db, imei=args.imei, limit=args.limit, dry_run=args.dry_run)
        
        # Step 2: Create device_state rows
        create_device_states(db, imei=args.imei, subscribe_all=args.subscribe_all, dry_run=args.dry_run)
        
        # Step 3: Initialize sync state
        initialize_sync_state(db, dry_run=args.dry_run)
        
        print("\n" + "="*80)
        print("✅ MIGRATION COMPLETE!")
        print("="*80)
        
        if args.dry_run:
            print("\n⚠️  This was a DRY RUN - no changes were made")
            print("   Remove --dry-run flag to actually migrate data")
        else:
            print("\n🚀 Trip engine is now ready to process trips!")
            print("   Restart the backend to start background tasks")
        
    finally:
        db.close()


if __name__ == "__main__":
    main()
