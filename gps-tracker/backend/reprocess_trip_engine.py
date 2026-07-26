#!/usr/bin/env python3
"""
Clear and re-run trip engine for a device to populate leg_id/stationary_id associations.

This script:
1. Clears existing journeys/legs/stationaries/engine_state for device
2. Clears leg_id/stationary_id from device_positions
3. Re-runs trip engine to recreate everything with associations

Usage:
    python reprocess_trip_engine.py --imei 781950640095475
    python reprocess_trip_engine.py --imei 781950640095475 --dry-run
"""

import sys
import os
import argparse
from datetime import datetime

# Add parent directory to path for imports
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.database import get_db
from app.models import DevicePosition, Journey, Leg, Stationary, EngineState
from app.services.trip_engine import TripEngine, EngineConfig
from sqlalchemy import select, delete, update, func
from sqlalchemy.orm import Session


def clear_trip_data(db: Session, imei: str, dry_run: bool = False):
    """Clear all trip engine data for a device."""
    
    print(f"🧹 Clearing trip data for IMEI {imei}...")
    
    # Count records before deletion
    journey_count = db.scalar(select(func.count()).select_from(Journey).where(Journey.device_imei == imei))
    leg_count = db.scalar(select(func.count()).select_from(Leg).where(Leg.device_imei == imei))
    stat_count = db.scalar(select(func.count()).select_from(Stationary).where(Stationary.device_imei == imei))
    pos_with_assoc = db.scalar(
        select(func.count())
        .select_from(DevicePosition)
        .where(
            DevicePosition.device_imei == imei,
            (DevicePosition.leg_id.isnot(None) | DevicePosition.stationary_id.isnot(None))
        )
    )
    
    print(f"   📊 Found:")
    print(f"      - {journey_count} journeys")
    print(f"      - {leg_count} legs")
    print(f"      - {stat_count} stationaries")
    print(f"      - {pos_with_assoc} positions with associations")
    
    if dry_run:
        print("   🔍 DRY RUN: Would delete these records")
        return
    
    # Delete in order: stationaries → legs → journeys (respects foreign keys)
    db.execute(delete(Stationary).where(Stationary.device_imei == imei))
    db.execute(delete(Leg).where(Leg.device_imei == imei))
    db.execute(delete(Journey).where(Journey.device_imei == imei))
    
    # Clear engine state
    db.execute(delete(EngineState).where(EngineState.device_imei == imei))
    
    # Clear associations from positions
    db.execute(
        update(DevicePosition)
        .where(DevicePosition.device_imei == imei)
        .values(leg_id=None, stationary_id=None)
    )
    
    db.commit()
    print(f"   ✅ Cleared all trip data")


def reprocess_trip_engine(db: Session, imei: str, dry_run: bool = False):
    """Re-run trip engine for a device."""
    
    print("")
    print(f"🔄 Re-processing trip engine for IMEI {imei}...")
    
    # Count positions to process
    pos_count = db.scalar(
        select(func.count())
        .select_from(DevicePosition)
        .where(DevicePosition.device_imei == imei)
    )
    
    print(f"   📊 Found {pos_count} positions to process")
    
    if dry_run:
        print("   🔍 DRY RUN: Would process these positions")
        return {}
    
    # Initialize trip engine with default config
    # Note: TripEngine loads config from database via _load_config()
    engine = TripEngine(db=db, device_imei=imei)
    
    print(f"   ⚙️  Starting trip engine...")
    print("")
    
    # Process all positions
    result = engine.process_positions(limit=None)
    
    db.commit()
    
    return result


def main():
    parser = argparse.ArgumentParser(description="Clear and re-run trip engine for a device")
    parser.add_argument("--imei", type=str, required=True, help="Device IMEI to reprocess")
    parser.add_argument("--dry-run", action="store_true", help="Show what would be done without making changes")
    
    args = parser.parse_args()
    
    # Get database session
    db = next(get_db())
    
    try:
        print("")
        print("=" * 80)
        print(f"🚀 Trip Engine Reprocessing")
        print(f"📱 IMEI: {args.imei}")
        if args.dry_run:
            print("🔍 MODE: DRY RUN (no changes will be made)")
        print("=" * 80)
        print("")
        
        # Step 1: Clear existing data
        clear_trip_data(db, args.imei, dry_run=args.dry_run)
        
        if args.dry_run:
            print("")
            print("=" * 80)
            print("✅ Dry run complete. No changes made.")
            print("=" * 80)
            return
        
        # Step 2: Re-run trip engine
        result = reprocess_trip_engine(db, args.imei, dry_run=args.dry_run)
        
        # Display results
        print("")
        print("=" * 80)
        print("✅ Trip engine reprocessing complete!")
        print("")
        print(f"📊 Results:")
        print(f"   - Positions processed: {result.get('positions_processed', 0)}")
        print(f"   - Journeys created: {result.get('journeys_created', 0)}")
        print(f"   - Legs created: {result.get('legs_created', 0)}")
        print(f"   - Stationaries created: {result.get('stationaries_created', 0)}")
        print(f"   - Final state: {result.get('current_state', 'UNKNOWN')}")
        
        # Verify associations were written
        pos_with_leg = db.scalar(
            select(func.count())
            .select_from(DevicePosition)
            .where(
                DevicePosition.device_imei == args.imei,
                DevicePosition.leg_id.isnot(None)
            )
        )
        pos_with_stat = db.scalar(
            select(func.count())
            .select_from(DevicePosition)
            .where(
                DevicePosition.device_imei == args.imei,
                DevicePosition.stationary_id.isnot(None)
            )
        )
        
        print("")
        print(f"🔗 Position Associations:")
        print(f"   - {pos_with_leg} positions linked to legs")
        print(f"   - {pos_with_stat} positions linked to stationaries")
        print("")
        print("🎯 UI will now show:")
        print("   - Journey visualization on map (start → legs → stops → end)")
        print("   - Blue [Leg N] badges for movement positions")
        print("   - Amber [Stationary N] badges for dwell positions")
        print("=" * 80)
        
    except KeyboardInterrupt:
        print("\n\n⚠️  Interrupted by user.")
        db.rollback()
        print("❌ Changes rolled back.")
    
    except Exception as exc:
        print(f"\n\n❌ Fatal error: {exc}")
        db.rollback()
        raise
    
    finally:
        db.close()


if __name__ == "__main__":
    main()
