#!/usr/bin/env python3
"""
Manual 60-day backfill script for specific IMEI.

Usage on server:
    cd /root/pinplot/gps-tracker
    docker compose exec backend python manual_backfill_60_days.py 780901807707571
"""
import asyncio
import sys
import os
from datetime import datetime, timedelta, timezone

# Add app to path
sys.path.insert(0, '/app')

from sqlalchemy.orm import Session
from app.database import SessionLocal
from app.services.device_providers.tracksolid_provider import fetch_tracksolid_journey_points
from app.services.trip_reprocess_service import replay_device_trips
from app.models import DeviceState, DevicePosition, BLETag
from sqlalchemy.dialects.postgresql import insert


async def backfill_60_days(device_imei: str):
    """
    Backfill 60 days of GPS data for a specific device.
    
    Args:
        device_imei: Device IMEI to backfill
    """
    print(f"\n{'='*60}")
    print(f"60-DAY BACKFILL FOR IMEI: {device_imei}")
    print(f"{'='*60}\n")
    
    db = SessionLocal()
    
    try:
        # Verify device exists
        tag = db.query(BLETag).filter(BLETag.imei == device_imei).first()
        if not tag:
            print(f"❌ ERROR: Device {device_imei} not found in database")
            return
        
        print(f"✅ Device found: {tag.device_name or device_imei}")
        
        # Calculate 60-day window
        now = datetime.now(timezone.utc)
        window_start = now - timedelta(days=60)
        window_end = now
        
        # Check for clamping (last_position_ts)
        device_state = db.query(DeviceState).filter(
            DeviceState.device_imei == device_imei
        ).first()
        
        clamped = False
        if device_state and device_state.last_position_ts:
            if window_end > device_state.last_position_ts:
                window_end = device_state.last_position_ts
                clamped = True
                print(f"🔒 Clamped end time to forward pipeline boundary: {window_end.isoformat()}")
        
        print(f"\n📅 Time Window:")
        print(f"   Start: {window_start.strftime('%Y-%m-%d %H:%M:%S')} UTC")
        print(f"   End:   {window_end.strftime('%Y-%m-%d %H:%M:%S')} UTC")
        print(f"   Duration: 60 days")
        print(f"   Clamped: {clamped}\n")
        
        # Format times for TrackSolid API
        start_time_str = window_start.strftime("%Y-%m-%d %H:%M:%S")
        end_time_str = window_end.strftime("%Y-%m-%d %H:%M:%S")
        
        # Call TrackSolid API
        print("📡 Calling TrackSolid API...")
        track_data = await fetch_tracksolid_journey_points(
            imei=device_imei,
            start_time=start_time_str,
            end_time=end_time_str,
        )
        
        if not track_data:
            print("⚠️  No track data returned from TrackSolid")
            track_points = []
        else:
            # Parse pipe-delimited GPS points
            gps_point_strs = track_data.get('gpsPointStrList') or []
            track_points = []
            
            print(f"📦 Parsing {len(gps_point_strs)} GPS points...")
            
            for point_str in gps_point_strs:
                try:
                    parts = point_str.split('|')
                    if len(parts) < 10:
                        continue
                    
                    lat = float(parts[8])
                    lng = float(parts[9])
                    if lat == 0.0 and lng == 0.0:
                        continue
                    
                    gps_time_str = parts[7]
                    
                    track_points.append({
                        'lat': lat,
                        'lng': lng,
                        'gpsTime': gps_time_str,
                        'direction': int(float(parts[1])) if parts[1] else None,
                        'gpsSpeed': float(parts[0]) if parts[0] else None,
                    })
                except (ValueError, IndexError) as e:
                    continue
        
        positions_fetched = len(track_points)
        print(f"✅ Fetched {positions_fetched} positions from TrackSolid\n")
        
        # Upsert positions
        print("💾 Upserting positions to database...")
        created_at = datetime.now(timezone.utc)
        inserted_count = 0
        
        for point in track_points:
            gps_time_str = point.get('gpsTime')
            if not gps_time_str:
                continue
            
            try:
                observed_at = datetime.strptime(str(gps_time_str), "%Y-%m-%d %H:%M:%S")
                observed_at = observed_at.replace(tzinfo=timezone.utc)
            except (ValueError, TypeError):
                continue
            
            lat = point.get('lat')
            lng = point.get('lng')
            if lat is None or lng is None:
                continue
            
            position_data = {
                'device_imei': device_imei,
                'lat': lat,
                'lng': lng,
                'observed_at': observed_at,
                'direction': point.get('direction'),
                'gps_speed': point.get('gpsSpeed'),
                'source': 'manual_backfill_60d',
                'created_at': created_at,
            }
            
            stmt = insert(DevicePosition).values(position_data)
            stmt = stmt.on_conflict_do_nothing(
                index_elements=['device_imei', 'observed_at']
            )
            
            result = db.execute(stmt)
            if result.rowcount > 0:
                inserted_count += 1
        
        db.commit()
        
        print(f"✅ Upserted {inserted_count} new positions ({positions_fetched - inserted_count} duplicates skipped)\n")
        
        # Reprocess trips
        print("🔄 Reprocessing trips...")
        reprocess_result = replay_device_trips(
            db=db,
            device_imei=device_imei,
            start_date=None,
            end_date=None,
            tenant_id=None
        )
        
        db.commit()
        
        print(f"\n{'='*60}")
        print("✅ BACKFILL COMPLETE")
        print(f"{'='*60}")
        print(f"Positions Fetched:    {positions_fetched}")
        print(f"Positions Inserted:   {inserted_count}")
        print(f"Positions Processed:  {reprocess_result['positions_processed']}")
        print(f"Journeys Created:     {reprocess_result['journeys_created']}")
        print(f"Legs Created:         {reprocess_result['legs_created']}")
        print(f"Stationaries Created: {reprocess_result['stationaries_created']}")
        print(f"Engine Version:       {reprocess_result['engine_version']}")
        print(f"{'='*60}\n")
        
    except Exception as e:
        print(f"\n❌ ERROR: {e}")
        import traceback
        traceback.print_exc()
        db.rollback()
    finally:
        db.close()


def main():
    if len(sys.argv) != 2:
        print("Usage: python manual_backfill_60_days.py <IMEI>")
        print("Example: python manual_backfill_60_days.py 780901807707571")
        sys.exit(1)
    
    device_imei = sys.argv[1]
    asyncio.run(backfill_60_days(device_imei))


if __name__ == "__main__":
    main()
