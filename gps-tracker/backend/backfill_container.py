#!/usr/bin/env python3
"""
Trip Engine v2.1.6 Backfill Script (Container Version)

Designed to run inside the Docker container with proper Python path setup.

Usage (from host):
    docker compose exec backend python backfill_container.py --device 780901807707363
    docker compose exec backend python backfill_container.py --all-test-devices
    docker compose exec backend python backfill_container.py --test-only --all-test-devices
"""
import argparse
import sys
import os
from datetime import datetime, timezone

# Ensure app module is in path (container-specific)
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker
from app.services.trip_engine import TripEngine

# Device IMEIs from spec
TEST_DEVICES = {
    '907': '780901807707363',
    '767': '780901807707767', 
    '571': '780901807707502',
    '363': '863844069007363',  # Updated correct IMEI
}

def get_db_session():
    """Create database session from environment."""
    db_url = os.getenv('DATABASE_URL')
    if not db_url:
        print("❌ DATABASE_URL not set in environment")
        sys.exit(1)
    
    engine = create_engine(db_url)
    Session = sessionmaker(bind=engine)
    return Session()

def clear_device_data(session, device_imei, start_date=None, end_date=None):
    """Clear engine state and trip data for a device."""
    print(f"\n🗑️  Clearing data for device {device_imei}")
    
    where_parts = ["device_imei = :imei"]
    params = {'imei': device_imei}
    
    if start_date:
        where_parts.append("started_at >= :start_date")
        params['start_date'] = start_date
    if end_date:
        where_parts.append("started_at < :end_date")
        params['end_date'] = end_date
    
    where_clause = " AND ".join(where_parts)
    
    # Delete in dependency order
    tables = [
        ('legs', where_clause),
        ('stationaries', where_clause),
        ('journeys', where_clause),
        ('engine_state', 'device_imei = :imei'),
    ]
    
    for table, where in tables:
        result = session.execute(
            text(f"DELETE FROM {table} WHERE {where}"),
            params
        )
        print(f"   ✓ Deleted {result.rowcount} rows from {table}")
    
    session.commit()
    print("✅ Data cleared")

def verify_migrations(session):
    """Check that v2.1.6 migrations are applied."""
    print("\n🔍 Checking migrations...")
    
    # Check B1 constraint
    result = session.execute(text("""
        SELECT indexname FROM pg_indexes 
        WHERE tablename = 'legs' AND indexname = 'ux_leg_device_start'
    """))
    b1_applied = result.scalar() is not None
    
    # Check B5 migration
    result = session.execute(text("""
        SELECT version_num FROM alembic_version 
        WHERE version_num = 'v216_b5_terminal_stops'
    """))
    b5_applied = result.scalar() is not None
    
    print(f"   {'✅' if b1_applied else '❌'} B1: Unique constraint (ux_leg_device_start)")
    print(f"   {'✅' if b5_applied else '❌'} B5: Terminal stops migration")
    
    if not b1_applied:
        print("\n⚠️  B1 migration not applied! Run: alembic upgrade head")
        return False
    
    return True

def backfill_device(session, device_imei):
    """Run trip engine for a device."""
    print(f"\n🚀 Backfilling device {device_imei}")
    
    engine = TripEngine(db=session, device_imei=device_imei)
    stats = engine.process_positions()
    
    print(f"\n✅ Backfill complete:")
    print(f"   Positions: {stats['positions_processed']}")
    print(f"   Stationaries: {stats['stationaries_created']}")
    print(f"   Legs: {stats['legs_created']}")
    print(f"   Journeys: {stats['journeys_created']}")
    
    return stats

def run_tests(session, device_imei):
    """Run acceptance tests."""
    print(f"\n📊 Testing device {device_imei}")
    
    # B1: Duplicates
    result = session.execute(text("""
        SELECT COUNT(*) FROM (
            SELECT device_imei, started_at
            FROM legs
            WHERE device_imei = :imei
            GROUP BY device_imei, started_at
            HAVING COUNT(*) > 1
        ) dupes
    """), {'imei': device_imei})
    dupes = result.scalar()
    print(f"   {'✅' if dupes == 0 else '❌'} B1: Duplicate legs ({dupes} found)")
    
    # B2: Gaps
    result = session.execute(text("""
        SELECT COUNT(*) FROM (
            SELECT 
                EXTRACT(EPOCH FROM (s.started_at - l.ended_at)) as gap
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
        WHERE gap != 0
    """), {'imei': device_imei})
    gaps = result.scalar()
    print(f"   {'✅' if gaps == 0 else '❌'} B2: Leg→stop gaps ({gaps} non-zero)")
    
    # B3: Air legs (571 only)
    if device_imei == '780901807707502':
        result = session.execute(text("""
            SELECT COUNT(*) FROM legs 
            WHERE device_imei = :imei AND is_air_leg = true
        """), {'imei': device_imei})
        air_legs = result.scalar()
        
        result = session.execute(text("""
            SELECT COUNT(*) FROM journeys 
            WHERE device_imei = :imei AND is_air_journey = true
        """), {'imei': device_imei})
        air_journeys = result.scalar()
        
        print(f"   {'✅' if air_legs == 2 else '❌'} B3: Air legs ({air_legs} found, expected 2)")
        print(f"   {'✅' if air_journeys >= 2 else '❌'} B3: Air journeys ({air_journeys} found)")
    
    # B5: Journey end times
    result = session.execute(text("""
        SELECT COUNT(*) FROM journeys j
        WHERE j.device_imei = :imei
        AND j.ended_at > (
            SELECT MAX(l.ended_at) FROM legs l WHERE l.journey_id = j.id
        )
    """), {'imei': device_imei})
    overshoot = result.scalar()
    print(f"   {'✅' if overshoot == 0 else '❌'} B5: Journey end times ({overshoot} overshoots)")

def main():
    parser = argparse.ArgumentParser(description='Backfill Trip Engine v2.1.6')
    parser.add_argument('--device', help='Device IMEI')
    parser.add_argument('--all-test-devices', action='store_true')
    parser.add_argument('--skip-clear', action='store_true')
    parser.add_argument('--test-only', action='store_true')
    
    args = parser.parse_args()
    
    if args.all_test_devices:
        devices = list(TEST_DEVICES.values())
    elif args.device:
        devices = [args.device]
    else:
        print("Error: Specify --device or --all-test-devices")
        sys.exit(1)
    
    session = get_db_session()
    
    try:
        if not verify_migrations(session):
            sys.exit(1)
        
        for device_imei in devices:
            print(f"\n{'='*60}")
            print(f"Device: {device_imei}")
            print(f"{'='*60}")
            
            if not args.test_only and not args.skip_clear:
                clear_device_data(session, device_imei)
            
            if not args.test_only:
                backfill_device(session, device_imei)
            
            run_tests(session, device_imei)
        
        print("\n✅ Complete!")
        
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
