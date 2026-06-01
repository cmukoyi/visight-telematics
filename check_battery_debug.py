#!/usr/bin/env python3
"""
Quick diagnostic script to check battery data for IMEI 780901807707342
"""
import os
import sys
from pathlib import Path

# Add backend to path
sys.path.insert(0, str(Path(__file__).parent / "gps-tracker" / "backend"))

from app.database import SessionLocal
from app.models import BLETag, TrackSolidLocation
from sqlalchemy import desc

def main():
    db = SessionLocal()
    try:
        imei = "780901807707342"
        
        print(f"\n{'='*80}")
        print(f"BATTERY DIAGNOSTIC FOR IMEI: {imei}")
        print(f"{'='*80}\n")
        
        # Check BLETag table
        tag = db.query(BLETag).filter(BLETag.imei == imei).first()
        if tag:
            print("📱 BLETag Table:")
            print(f"   IMEI: {tag.imei}")
            print(f"   Device Name: {tag.device_name}")
            print(f"   Tag Type: {tag.tag_type}")
            print(f"   Battery Level: {tag.battery_level}%")
            print(f"   Is Active: {tag.is_active}")
        else:
            print(f"❌ No tag found with IMEI {imei}")
            return
        
        print()
        
        # Check TrackSolidLocation table (last 5 records)
        locations = (
            db.query(TrackSolidLocation)
            .filter(TrackSolidLocation.imei == imei)
            .order_by(desc(TrackSolidLocation.recorded_at))
            .limit(5)
            .all()
        )
        
        if locations:
            print(f"📍 TrackSolidLocation Table (last 5 records):")
            print(f"{'Recorded At':<25} {'Battery (raw)':<15} {'Lat':<12} {'Lng':<12}")
            print("-" * 80)
            for loc in locations:
                print(f"{str(loc.recorded_at):<25} {str(loc.battery):<15} {loc.lat:<12.6f} {loc.lng:<12.6f}")
        else:
            print(f"❌ No location history found for IMEI {imei}")
        
        print()
        
        # Calculate what the current formula would produce
        if locations and locations[0].battery:
            raw_battery = locations[0].battery
            print(f"🔍 Current Formula Analysis:")
            print(f"   Raw value from API: {raw_battery}")
            
            try:
                voltage = float(raw_battery)
                print(f"   Interpreted as voltage: {voltage}V")
                
                if voltage > 2.5:
                    calculated = min(100, max(0, int((voltage - 3.0) / 1.2 * 100)))
                    print(f"   Formula: (voltage - 3.0) / 1.2 * 100")
                    print(f"   Calculated percentage: {calculated}%")
                    print(f"   Stored in BLETag: {tag.battery_level}%")
                    
                    if calculated == 100 and calculated != tag.battery_level:
                        print(f"\n   ⚠️  ISSUE: Formula maxes out at 100% when voltage >= 4.2V")
                        print(f"   ⚠️  The raw value might already be a percentage, not voltage!")
                else:
                    print(f"   Voltage < 2.5V, battery_level set to None")
                    
                # Try interpreting as percentage
                print(f"\n   Alternative interpretation:")
                print(f"   If raw value is already a percentage: {raw_battery}%")
                    
            except (ValueError, TypeError) as e:
                print(f"   ❌ Could not parse as voltage: {e}")
        
        print("\n" + "="*80 + "\n")
        
    finally:
        db.close()

if __name__ == "__main__":
    main()
