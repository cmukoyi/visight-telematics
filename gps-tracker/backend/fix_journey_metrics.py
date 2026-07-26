#!/usr/bin/env python3
"""
Fix journey metrics for journeys with 0 km but existing legs.

BUG: Some journeys have total_distance_m = 0 and ended_at = started_at,
but they have legs in the database with correct distances.

This script:
1. Finds journeys with total_distance_m = 0 but leg_count > 0
2. Recalculates metrics from actual legs and stationaries
3. Updates journey records with correct values

Usage:
    python3 fix_journey_metrics.py                    # Dry run (show what would be fixed)
    python3 fix_journey_metrics.py --apply            # Apply fixes
    python3 fix_journey_metrics.py --journey-id UUID  # Fix specific journey
"""
import argparse
from datetime import datetime, timezone
from sqlalchemy import select, and_, func
from app.database import get_db
from app.models import Journey, Leg, Stationary


def find_broken_journeys(db):
    """Find journeys with 0 distance but existing legs."""
    # Query journeys where total_distance_m = 0 but legs exist
    stmt = select(Journey).where(
        Journey.total_distance_m == 0
    ).order_by(Journey.started_at.desc())
    
    journeys = db.execute(stmt).scalars().all()
    
    broken = []
    for journey in journeys:
        # Check if this journey actually has legs
        leg_count = db.scalar(
            select(func.count())
            .select_from(Leg)
            .where(Leg.journey_id == journey.id)
        )
        
        if leg_count > 0:
            broken.append(journey)
    
    return broken


def recalculate_journey_metrics(db, journey_id):
    """Recalculate and update metrics for a specific journey."""
    from uuid import UUID
    
    # Convert to UUID if needed
    if isinstance(journey_id, str):
        journey_id = UUID(journey_id)
    
    # Get journey
    journey = db.query(Journey).filter(Journey.id == journey_id).first()
    if not journey:
        print(f"❌ Journey {journey_id} not found")
        return False
    
    # Get legs
    legs = db.execute(
        select(Leg).where(Leg.journey_id == journey_id).order_by(Leg.started_at)
    ).scalars().all()
    
    # Get stationaries
    stationaries = db.execute(
        select(Stationary).where(Stationary.journey_id == journey_id).order_by(Stationary.started_at)
    ).scalars().all()
    
    print(f"\n📊 Journey {journey_id}")
    print(f"   Device: {journey.device_imei}")
    print(f"   Current metrics:")
    print(f"     - Distance: {journey.total_distance_m} m ({journey.total_distance_m/1000:.1f} km)")
    print(f"     - Started: {journey.started_at}")
    print(f"     - Ended: {journey.ended_at}")
    print(f"     - Legs: {journey.leg_count}")
    print(f"     - Stationaries: {journey.stationary_count}")
    
    # Calculate new metrics
    total_distance_m = sum(leg.distance_m for leg in legs)
    leg_count = len(legs)
    stationary_count = len(stationaries)
    
    # Calculate time window from all timestamps
    all_timestamps = []
    if legs:
        all_timestamps.extend([leg.started_at, leg.ended_at] for leg in legs)
    if stationaries:
        all_timestamps.extend([s.started_at, s.ended_at] for s in stationaries)
    
    if all_timestamps:
        flat_timestamps = [t for pair in all_timestamps for t in pair]
        new_started_at = min(flat_timestamps)
        new_ended_at = max(flat_timestamps)
        total_duration_seconds = int((new_ended_at - new_started_at).total_seconds())
    else:
        new_started_at = journey.started_at
        new_ended_at = journey.ended_at
        total_duration_seconds = 0
    
    print(f"   Calculated metrics:")
    print(f"     - Distance: {total_distance_m} m ({total_distance_m/1000:.1f} km)")
    print(f"     - Started: {new_started_at}")
    print(f"     - Ended: {new_ended_at}")
    print(f"     - Duration: {total_duration_seconds/60:.0f} min")
    print(f"     - Legs: {leg_count}")
    print(f"     - Stationaries: {stationary_count}")
    
    # Check if update is needed
    needs_update = (
        journey.total_distance_m != total_distance_m or
        journey.leg_count != leg_count or
        journey.stationary_count != stationary_count or
        journey.started_at != new_started_at or
        journey.ended_at != new_ended_at
    )
    
    if not needs_update:
        print("   ✅ Metrics already correct, no update needed")
        return False
    
    # Update journey
    journey.total_distance_m = total_distance_m
    journey.leg_count = leg_count
    journey.stationary_count = stationary_count
    journey.started_at = new_started_at
    journey.ended_at = new_ended_at
    journey.total_duration_seconds = total_duration_seconds
    
    return True


def main():
    parser = argparse.ArgumentParser(description="Fix journey metrics")
    parser.add_argument("--apply", action="store_true", help="Apply fixes (default is dry run)")
    parser.add_argument("--journey-id", type=str, help="Fix specific journey by ID")
    args = parser.parse_args()
    
    db = next(get_db())
    
    try:
        if args.journey_id:
            # Fix specific journey
            print(f"🔧 Fixing journey {args.journey_id}")
            updated = recalculate_journey_metrics(db, args.journey_id)
            
            if updated:
                if args.apply:
                    db.commit()
                    print(f"\n✅ Journey {args.journey_id} updated")
                else:
                    db.rollback()
                    print(f"\n🔍 DRY RUN: Would update journey {args.journey_id}")
                    print("   Run with --apply to apply changes")
            else:
                print(f"\n⏭️  No changes needed for journey {args.journey_id}")
        
        else:
            # Find and fix all broken journeys
            print("🔍 Searching for journeys with broken metrics...")
            broken = find_broken_journeys(db)
            
            if not broken:
                print("✅ No broken journeys found")
                return
            
            print(f"\n📋 Found {len(broken)} journey(s) with 0 km but existing legs:\n")
            
            updated_count = 0
            for journey in broken:
                updated = recalculate_journey_metrics(db, journey.id)
                if updated:
                    updated_count += 1
            
            print(f"\n{'='*80}")
            print(f"📊 Summary: {updated_count} journey(s) need updates")
            
            if updated_count > 0:
                if args.apply:
                    db.commit()
                    print(f"✅ Applied fixes to {updated_count} journey(s)")
                else:
                    db.rollback()
                    print(f"🔍 DRY RUN: Would update {updated_count} journey(s)")
                    print("   Run with --apply to apply changes")
    
    except KeyboardInterrupt:
        print("\n\n⚠️  Interrupted by user")
        db.rollback()
    except Exception as exc:
        print(f"\n❌ Error: {exc}")
        import traceback
        traceback.print_exc()
        db.rollback()
    finally:
        db.close()


if __name__ == "__main__":
    main()
