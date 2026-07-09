#!/usr/bin/env python3
"""
Backfill addresses for device_positions using reverse geocoding.

This script:
1. Finds all positions with NULL address
2. Reverse geocodes using the real geocode_service (MapTiler API)
3. Updates positions with real location names
4. Respects rate limits and caching (500m threshold)

Usage:
    python backfill_position_addresses.py --limit 100
    python backfill_position_addresses.py --imei 781950640095475
    python backfill_position_addresses.py --all
"""

import sys
import os
import argparse
import time
from datetime import datetime
from typing import Optional

# Add parent directory to path for imports
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.database import get_db
from app.models import DevicePosition
from app.services.geocode_service import GeocodeService
from sqlalchemy import select, and_, func
from sqlalchemy.orm import Session


def backfill_addresses(
    db: Session,
    geocode_service: GeocodeService,
    imei: Optional[str] = None,
    limit: Optional[int] = None,
    batch_size: int = 50,
    delay_seconds: float = 0.5
):
    """
    Backfill addresses for positions without geocoding.
    
    Args:
        db: Database session
        geocode_service: Geocoding service instance
        imei: Filter by specific device IMEI (optional)
        limit: Max positions to process (optional)
        batch_size: Positions to process before committing
        delay_seconds: Delay between geocode API calls
    """
    
    # Build query for positions without addresses
    query = select(DevicePosition).where(
        and_(
            DevicePosition.address.is_(None),
            DevicePosition.lat.isnot(None),
            DevicePosition.lng.isnot(None)
        )
    )
    
    if imei:
        query = query.where(DevicePosition.device_imei == imei)
    
    # Order by observed_at to process chronologically
    query = query.order_by(DevicePosition.observed_at.asc())
    
    if limit:
        query = query.limit(limit)
    
    # Get count first
    count_query = select(func.count()).select_from(DevicePosition).where(
        and_(
            DevicePosition.address.is_(None),
            DevicePosition.lat.isnot(None),
            DevicePosition.lng.isnot(None)
        )
    )
    if imei:
        count_query = count_query.where(DevicePosition.device_imei == imei)
    
    total_count = db.scalar(count_query)
    process_count = min(limit, total_count) if limit else total_count
    
    print(f"📊 Found {total_count:,} positions without addresses")
    print(f"🎯 Processing {process_count:,} positions")
    if imei:
        print(f"📱 Filtering by IMEI: {imei}")
    print("")
    
    # Process positions
    positions = db.execute(query).scalars().all()
    
    processed = 0
    updated = 0
    cached = 0
    errors = 0
    start_time = time.time()
    
    for pos in positions:
        try:
            # Call geocode service (uses smart caching)
            result = geocode_service.reverse_geocode(
                device_imei=pos.device_imei,
                lat=pos.lat,
                lng=pos.lng
            )
            
            # Update position with address
            pos.address = result["address"]
            
            if result.get("cached"):
                cached += 1
                print(f"💾 [{processed+1}/{process_count}] CACHED: {pos.device_imei} @ {pos.observed_at.strftime('%Y-%m-%d %H:%M')} → {result['address'][:50]}...")
            else:
                updated += 1
                print(f"🌍 [{processed+1}/{process_count}] GEOCODED: {pos.device_imei} @ {pos.observed_at.strftime('%Y-%m-%d %H:%M')} → {result['address']}")
                
                # Respect rate limits for API calls
                time.sleep(delay_seconds)
            
            processed += 1
            
            # Commit in batches
            if processed % batch_size == 0:
                db.commit()
                elapsed = time.time() - start_time
                rate = processed / elapsed if elapsed > 0 else 0
                eta = (process_count - processed) / rate if rate > 0 else 0
                print(f"✅ Batch committed: {processed}/{process_count} ({processed/process_count*100:.1f}%) | Rate: {rate:.1f} pos/sec | ETA: {eta/60:.1f} min")
            
        except Exception as exc:
            errors += 1
            print(f"❌ [{processed+1}/{process_count}] ERROR: {pos.device_imei} @ {pos.observed_at} - {exc}")
            # Continue processing despite errors
    
    # Final commit
    db.commit()
    
    elapsed = time.time() - start_time
    print("")
    print("=" * 80)
    print(f"✅ Backfill complete!")
    print(f"📊 Processed: {processed:,} positions")
    print(f"🌍 API calls: {updated:,} (new geocodes)")
    print(f"💾 Cache hits: {cached:,} (within 500m)")
    print(f"❌ Errors: {errors}")
    print(f"⏱️  Duration: {elapsed:.1f} seconds ({processed/elapsed:.1f} pos/sec)")
    print("=" * 80)


def main():
    parser = argparse.ArgumentParser(description="Backfill addresses for device positions")
    parser.add_argument("--imei", type=str, help="Filter by specific device IMEI")
    parser.add_argument("--limit", type=int, help="Max positions to process")
    parser.add_argument("--all", action="store_true", help="Process all positions (no limit)")
    parser.add_argument("--batch-size", type=int, default=50, help="Commit batch size (default: 50)")
    parser.add_argument("--delay", type=float, default=0.5, help="Delay between API calls in seconds (default: 0.5)")
    
    args = parser.parse_args()
    
    # Validate arguments
    if not args.all and not args.limit:
        print("⚠️  WARNING: No --limit specified and --all not set.")
        print("This will process ALL positions without addresses.")
        response = input("Continue? (yes/no): ").strip().lower()
        if response != "yes":
            print("Aborted.")
            return
    
    # Get database session
    db = next(get_db())
    
    # Initialize geocoding service
    geocode_service = GeocodeService(db=db)
    
    try:
        print("")
        print("🚀 Starting address backfill...")
        print("")
        
        backfill_addresses(
            db=db,
            geocode_service=geocode_service,
            imei=args.imei,
            limit=args.limit,
            batch_size=args.batch_size,
            delay_seconds=args.delay
        )
        
    except KeyboardInterrupt:
        print("\n\n⚠️  Interrupted by user. Committing processed positions...")
        db.commit()
        print("✅ Changes committed. Safe to exit.")
    
    except Exception as exc:
        print(f"\n\n❌ Fatal error: {exc}")
        db.rollback()
        raise
    
    finally:
        db.close()


if __name__ == "__main__":
    main()
