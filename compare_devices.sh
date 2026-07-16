#!/bin/bash
# Compare journey data for two devices in same car

echo "=== COMPARING DEVICES IN SAME CAR ==="
echo ""

docker exec pinplot_backend python3 -c "
from app.database import SessionLocal
from app.models import Journey, Leg, Stationary, DevicePosition
from datetime import datetime, timezone
from sqlalchemy import func, and_

db = SessionLocal()
try:
    # Device 1: 781950640095475
    # Device 2: 780901807705907
    
    # Find journeys around 11:00-12:30 today
    today_start = datetime(2026, 7, 16, 11, 0, 0, tzinfo=timezone.utc)
    today_end = datetime(2026, 7, 16, 14, 30, 0, tzinfo=timezone.utc)
    
    devices = ['781950640095475', '780901807705907']
    
    for imei in devices:
        print(f'\n{'='*80}')
        print(f'DEVICE: {imei}')
        print(f'{'='*80}')
        
        # Get journeys
        journeys = db.query(Journey).filter(
            Journey.device_imei == imei,
            Journey.started_at >= today_start,
            Journey.started_at <= today_end
        ).order_by(Journey.started_at).all()
        
        print(f'\nJourneys: {len(journeys)}')
        
        for idx, j in enumerate(journeys, 1):
            print(f'\n  Journey {idx}: {str(j.id)[:8]}...')
            print(f'    Time: {j.started_at.strftime(\"%H:%M:%S\")} – {j.ended_at.strftime(\"%H:%M:%S\")}')
            print(f'    Distance: {j.total_distance_m/1000:.2f} km')
            print(f'    Legs: {j.leg_count}, Stationaries: {j.stationary_count}')
            
            # Get position count for this time window
            pos_count = db.query(func.count(DevicePosition.id)).filter(
                DevicePosition.device_imei == imei,
                DevicePosition.observed_at >= j.started_at,
                DevicePosition.observed_at <= j.ended_at
            ).scalar()
            
            print(f'    Positions received: {pos_count}')
            
            if pos_count > 0:
                # Average reporting interval
                duration_sec = (j.ended_at - j.started_at).total_seconds()
                avg_interval = duration_sec / pos_count if pos_count > 1 else 0
                print(f'    Avg reporting interval: {avg_interval:.0f} seconds')
            
            # Get leg details
            legs = db.query(Leg).filter(
                Leg.journey_id == j.id
            ).order_by(Leg.started_at).all()
            
            if legs:
                print(f'\n    Legs breakdown:')
                for leg_idx, leg in enumerate(legs, 1):
                    duration_min = leg.duration_seconds / 60
                    print(f'      Leg {leg_idx}: {leg.distance_m/1000:.2f} km, {duration_min:.0f} min, {leg.point_count} positions')
            
            # Get stationary details
            stats = db.query(Stationary).filter(
                Stationary.journey_id == j.id
            ).order_by(Stationary.started_at).all()
            
            if stats:
                print(f'\n    Stationaries breakdown:')
                for stat_idx, stat in enumerate(stats, 1):
                    duration_min = stat.duration_seconds / 60
                    print(f'      Stat {stat_idx}: {duration_min:.1f} min, {stat.point_count} positions')

finally:
    db.close()
"
