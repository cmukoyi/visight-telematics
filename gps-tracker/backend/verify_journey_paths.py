#!/usr/bin/env python3
"""
Verify that journey paths have proper geometry and can be rendered correctly.

This script checks:
1. Do legs have path geometry (not just start/end points)?
2. Does the /api/portal/journeys/{id}/path endpoint return proper GeoJSON?
3. How many coordinates are in each leg path?

Usage:
    python verify_journey_paths.py
    python verify_journey_paths.py --imei 781950640095475
    python verify_journey_paths.py --journey-id abc-123-def
"""

import sys
import os
import argparse
from datetime import datetime
import json

# Add parent directory to path for imports
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.database import get_db
from app.models import Journey, Leg, Stationary
from sqlalchemy import select, func, text
from sqlalchemy.orm import Session


def verify_journey_paths(db: Session, imei: str = None, journey_id: str = None):
    """Verify journey path geometry."""
    
    print("=" * 80)
    print("🔍 Journey Path Verification")
    print("=" * 80)
    print("")
    
    # Get journeys to check
    if journey_id:
        journeys = db.execute(
            select(Journey).where(Journey.id == journey_id)
        ).scalars().all()
        print(f"📊 Checking specific journey: {journey_id}")
    elif imei:
        journeys = db.execute(
            select(Journey)
            .where(Journey.device_imei == imei)
            .order_by(Journey.started_at.desc())
            .limit(5)
        ).scalars().all()
        print(f"📊 Checking latest 5 journeys for IMEI: {imei}")
    else:
        journeys = db.execute(
            select(Journey)
            .order_by(Journey.started_at.desc())
            .limit(5)
        ).scalars().all()
        print(f"📊 Checking latest 5 journeys (all devices)")
    
    if not journeys:
        print("❌ No journeys found!")
        return
    
    print(f"   Found {len(journeys)} journey(s)")
    print("")
    
    for journey in journeys:
        print("-" * 80)
        print(f"Journey: {journey.id}")
        print(f"Device: {journey.device_imei}")
        print(f"Started: {journey.started_at}")
        print(f"Ended: {journey.ended_at}")
        print(f"Distance: {journey.total_distance_m / 1000:.2f} km")
        print(f"Legs: {journey.leg_count}")
        print("")
        
        # Get legs for this journey
        legs = db.execute(
            select(Leg)
            .where(Leg.journey_id == journey.id)
            .order_by(Leg.started_at)
        ).scalars().all()
        
        if not legs:
            print("   ⚠️  No legs found for journey!")
            continue
        
        print(f"   Checking {len(legs)} leg(s):")
        print("")
        
        total_coords = 0
        legs_with_geometry = 0
        legs_without_geometry = 0
        
        for i, leg in enumerate(legs, 1):
            # Query path geometry
            result = db.execute(text("""
                SELECT 
                    ST_AsGeoJSON(path)::json as path_geojson,
                    ST_NumPoints(path) as num_points,
                    ST_Length(path::geography) as length_m
                FROM legs
                WHERE id = :leg_id
            """), {"leg_id": str(leg.id)}).fetchone()
            
            if result and result.path_geojson:
                geojson = result.path_geojson
                num_points = result.num_points or 0
                length_m = result.length_m or 0
                
                coords = []
                if geojson.get('coordinates'):
                    coords = geojson['coordinates']
                
                total_coords += len(coords)
                legs_with_geometry += 1
                
                status = "✅" if len(coords) > 2 else "⚠️ "
                print(f"      Leg {i}: {status} {len(coords)} coordinates, {length_m:.0f}m")
                
                if len(coords) == 2:
                    print(f"           ⚠️  Only 2 points - this is a straight line!")
                    print(f"           Start: {coords[0]}")
                    print(f"           End:   {coords[1]}")
            else:
                legs_without_geometry += 1
                print(f"      Leg {i}: ❌ NO GEOMETRY")
        
        print("")
        print(f"   Summary:")
        print(f"      - Legs with geometry: {legs_with_geometry}/{len(legs)}")
        print(f"      - Legs without geometry: {legs_without_geometry}/{len(legs)}")
        print(f"      - Total coordinates: {total_coords}")
        print(f"      - Avg coordinates per leg: {total_coords / len(legs) if legs else 0:.1f}")
        print("")
        
        # Test GeoJSON endpoint format
        print("   Testing GeoJSON endpoint format:")
        result = db.execute(text("""
            SELECT 
                id,
                started_at,
                ended_at,
                distance_m,
                duration_seconds,
                is_air_leg,
                ST_AsGeoJSON(path)::json as geometry
            FROM legs
            WHERE journey_id = :journey_id
            ORDER BY started_at
        """), {"journey_id": str(journey.id)}).fetchall()
        
        features = []
        for leg in result:
            features.append({
                "type": "Feature",
                "geometry": leg.geometry if leg.geometry else {
                    "type": "LineString",
                    "coordinates": []
                },
                "properties": {
                    "id": str(leg.id),
                    "type": "leg",
                    "started_at": leg.started_at.isoformat(),
                    "ended_at": leg.ended_at.isoformat(),
                    "distance_m": float(leg.distance_m),
                    "duration_seconds": leg.duration_seconds,
                    "is_air_leg": leg.is_air_leg,
                }
            })
        
        geojson_response = {
            "type": "FeatureCollection",
            "features": features
        }
        
        print(f"      GeoJSON has {len(features)} features")
        
        # Count total coordinates in GeoJSON
        total_geojson_coords = sum(
            len(f['geometry'].get('coordinates', [])) 
            for f in features 
            if f['geometry'].get('type') == 'LineString'
        )
        print(f"      Total coordinates in GeoJSON: {total_geojson_coords}")
        
        if total_geojson_coords > len(legs) * 2:
            print(f"      ✅ GeoJSON looks good (more than 2 points per leg)")
        else:
            print(f"      ⚠️  GeoJSON only has start/end points (straight lines!)")
        
        print("")


def main():
    parser = argparse.ArgumentParser(description="Verify journey path geometry")
    parser.add_argument("--imei", type=str, help="Check journeys for specific IMEI")
    parser.add_argument("--journey-id", type=str, help="Check specific journey ID")
    
    args = parser.parse_args()
    
    # Get database session
    db = next(get_db())
    
    try:
        verify_journey_paths(db, imei=args.imei, journey_id=args.journey_id)
        
        print("")
        print("=" * 80)
        print("✅ Verification complete!")
        print("=" * 80)
        
    except Exception as e:
        print(f"❌ Error: {e}")
        import traceback
        traceback.print_exc()
    finally:
        db.close()


if __name__ == "__main__":
    main()
