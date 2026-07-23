#!/usr/bin/env python3
"""
Trip Engine v2.1.6 Backfill Script

Reprocesses historical data for specified devices to verify all v2.1.6 fixes.
Clears engine state and journeys/legs/stationaries for selected devices,
then runs the Trip Engine to regenerate everything with v2.1.6 logic.

Usage:
    python backfill_v216.py --device 780901807707363  # Device 907
    python backfill_v216.py --device 780901807707767  # Device 767
    python backfill_v216.py --device 780901807707502  # Device 571
    python backfill_v216.py --all-test-devices        # Devices 907, 767, 571, 363
    python backfill_v216.py --date-range 2026-07-01 2026-07-23
"""
import argparse
import sys
from datetime import datetime, timezone
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

# Device IMEIs from spec
TEST_DEVICES = {
    '907': '780901807707363',
    '767': '780901807707767',
    '571': '780901807707502',
    '363': '780901807707363',  # Need to verify this IMEI
}

def get_db_session():
    """Create database session."""
    # Use environment variable or default
    import os
    db_url = os.getenv('DATABASE_URL', 'postgresql://pinplot_db_user:password@localhost:5433/pinplot_db')
    engine = create_engine(db_url)
    Session = sessionmaker(bind=engine)
    return Session()

def clear_device_data(session, device_imei, start_date=None, end_date=None):
    """Clear engine state and trip data for a device."""
    print(f"\n🗑️  Clearing data for device {device_imei}")
    
    # Build WHERE clause
    where_parts = ["device_imei = :imei"]
    params = {'imei': device_imei}
    
    if start_date:
        where_parts.append("started_at >= :start_date")
        params['start_date'] = start_date
    if end_date:
        where_parts.append("started_at < :end_date")
        params['end_date'] = end_date
    
    where_clause = " AND ".join(where_parts)
    
    # Delete in order (foreign keys)
    tables = [
        ('legs', where_clause),
        ('stationaries', where_clause),
        ('journeys', where_clause),
        ('engine_state', 'device_imei = :imei'),  # Always clear full state
    ]
    
    for table, where in tables:
        result = session.execute(
            text(f"DELETE FROM {table} WHERE {where}"),
            params
        )
        print(f"   Deleted {result.rowcount} rows from {table}")
    
    session.commit()
    print("✅ Data cleared")

def verify_prerequisites(session):
    """Check that migrations are applied."""
    print("\n🔍 Checking prerequisites...")
    
    # Check B1 migration (unique constraint)
    result = session.execute(text("""
        SELECT indexname FROM pg_indexes 
        WHERE tablename = 'legs' AND indexname = 'ux_leg_device_start'
    """))
    if not result.scalar():
        print("❌ B1 migration not applied! Run: alembic upgrade head")
        return False
    
    # Check B5 migration (exists in alembic_version?)
    result = session.execute(text("""
        SELECT version_num FROM alembic_version 
        WHERE version_num = 'v216_b5_terminal_stops'
    """))
    has_b5 = result.scalar() is not None
    
    print(f"✅ B1 migration applied (ux_leg_device_start exists)")
    print(f"{'✅' if has_b5 else '⚠️ '} B5 migration {'applied' if has_b5 else 'NOT applied (will run without terminal stop detachment)'}")
    
    return True

def backfill_device(session, device_imei, start_date=None, end_date=None):
    """Run trip engine backfill for a device."""
    print(f"\n🚀 Backfilling device {device_imei}")
    
    # Import here to avoid circular deps
    from app.services.trip_engine import TripEngine
    
    # Create engine instance
    engine = TripEngine(db=session, device_imei=device_imei)
    
    # Process all positions
    stats = engine.process_positions()
    
    print(f"✅ Backfill complete:")
    print(f"   Positions: {stats['positions_processed']}")
    print(f"   Stationaries: {stats['stationaries_created']}")
    print(f"   Legs: {stats['legs_created']}")
    print(f"   Journeys: {stats['journeys_created']}")
    
    return stats

def run_acceptance_tests(session, device_imei):
    """Run acceptance tests from spec."""
    print(f"\n📊 Running acceptance tests for {device_imei}")
    
    # B1: Check for duplicates
    result = session.execute(text("""
        SELECT COUNT(*) FROM (
            SELECT device_imei, started_at, COUNT(*) as cnt
            FROM legs
            WHERE device_imei = :imei
            GROUP BY device_imei, started_at
            HAVING COUNT(*) > 1
        ) dupes
    """), {'imei': device_imei})
    duplicate_count = result.scalar()
    
    if duplicate_count == 0:
        print("✅ B1: No duplicate legs")
    else:
        print(f"❌ B1: {duplicate_count} duplicate leg groups found")
    
    # B2: Check leg→stationary gaps
    result = session.execute(text("""
        SELECT COUNT(*) FROM (
            SELECT l.device_imei, l.ended_at, s.started_at,
                   EXTRACT(EPOCH FROM (s.started_at - l.ended_at)) as gap_seconds
            FROM legs l
            JOIN stationaries s ON s.journey_id = l.journey_id 
                AND s.started_at > l.ended_at
                AND s.device_imei = l.device_imei
            WHERE l.device_imei = :imei
                AND NOT EXISTS (
                    SELECT 1 FROM legs l2 
                    WHERE l2.journey_id = l.journey_id 
                    AND l2.started_at > l.ended_at 
                    AND l2.started_at < s.started_at
                )
        ) gaps
        WHERE gap_seconds != 0
    """), {'imei': device_imei})
    gap_count = result.scalar()
    
    if gap_count == 0:
        print("✅ B2: All leg→stationary gaps are 0 seconds")
    else:
        print(f"❌ B2: {gap_count} non-zero gaps found")
    
    # B3: Check air legs (device 571 only)
    if device_imei == '780901807707502':
        result = session.execute(text("""
            SELECT COUNT(*) FROM legs 
            WHERE device_imei = :imei AND is_air_leg = true
        """), {'imei': device_imei})
        air_count = result.scalar()
        
        if air_count == 2:
            print("✅ B3: Exactly 2 air legs found")
        else:
            print(f"❌ B3: Expected 2 air legs, found {air_count}")
        
        # Check air journey flag
        result = session.execute(text("""
            SELECT COUNT(*) FROM journeys 
            WHERE device_imei = :imei AND is_air_journey = true
        """), {'imei': device_imei})
        air_journey_count = result.scalar()
        
        if air_journey_count >= 2:
            print(f"✅ B3: {air_journey_count} air journeys found")
        else:
            print(f"❌ B3: Expected >=2 air journeys, found {air_journey_count}")
    
    # B5: Check journey end times
    result = session.execute(text("""
        SELECT COUNT(*) FROM journeys j
        WHERE j.device_imei = :imei
        AND j.ended_at > (
            SELECT MAX(l.ended_at) FROM legs l WHERE l.journey_id = j.id
        )
    """), {'imei': device_imei})
    overshoot_count = result.scalar()
    
    if overshoot_count == 0:
        print("✅ B5: No journeys extend past last leg")
    else:
        print(f"❌ B5: {overshoot_count} journeys extend past last leg")
    
    print()

def main():
    parser = argparse.ArgumentParser(description='Backfill Trip Engine v2.1.6')
    parser.add_argument('--device', help='Single device IMEI to backfill')
    parser.add_argument('--all-test-devices', action='store_true', help='Backfill all test devices (907, 767, 571, 363)')
    parser.add_argument('--date-range', nargs=2, metavar=('START', 'END'), help='Date range (YYYY-MM-DD)')
    parser.add_argument('--skip-clear', action='store_true', help='Skip clearing existing data')
    parser.add_argument('--test-only', action='store_true', help='Run acceptance tests only (no backfill)')
    
    args = parser.parse_args()
    
    # Determine devices to process
    if args.all_test_devices:
        devices = list(TEST_DEVICES.values())
    elif args.device:
        devices = [args.device]
    else:
        print("Error: Specify --device IMEI or --all-test-devices")
        sys.exit(1)
    
    # Parse date range
    start_date = None
    end_date = None
    if args.date_range:
        start_date = datetime.strptime(args.date_range[0], '%Y-%m-%d').replace(tzinfo=timezone.utc)
        end_date = datetime.strptime(args.date_range[1], '%Y-%m-%d').replace(tzinfo=timezone.utc)
    
    # Create session
    session = get_db_session()
    
    try:
        # Check prerequisites
        if not verify_prerequisites(session):
            sys.exit(1)
        
        # Process each device
        for device_imei in devices:
            print(f"\n{'='*60}")
            print(f"Device: {device_imei}")
            print(f"{'='*60}")
            
            if not args.test_only:
                # Clear existing data
                if not args.skip_clear:
                    clear_device_data(session, device_imei, start_date, end_date)
                
                # Backfill
                backfill_device(session, device_imei, start_date, end_date)
            
            # Run tests
            run_acceptance_tests(session, device_imei)
        
        print("\n✅ All done!")
        
    except Exception as e:
        print(f"\n❌ Error: {e}")
        import traceback
        traceback.print_exc()
        session.rollback()
        sys.exit(1)
    finally:
        session.close()

if __name__ == '__main__':
    main()
