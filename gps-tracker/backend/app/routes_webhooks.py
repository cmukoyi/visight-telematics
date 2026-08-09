"""
Webhook endpoints for external service integrations.
Currently supports:
- Hubble Network BLE packet webhooks
"""

from fastapi import APIRouter, Request, HTTPException, Depends, Header
from sqlalchemy.orm import Session
from sqlalchemy.orm.attributes import flag_modified
from typing import List, Dict, Any, Optional
from datetime import datetime, timezone
import logging
import os
import base64

from app.database import get_db
from app.models import BLETag, User
from app.services.geofence_service import GeofenceService
from app.services.geocoding_service import GeocodingService
from app.services.device_providers.hubble_provider import HubbleTagProvider

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/webhooks", tags=["webhooks"])


@router.post("/hubble")
async def hubble_webhook(
    request: Request,
    db: Session = Depends(get_db),
    x_hubble_token: Optional[str] = Header(None, alias="HTTP-X-HUBBLE-TOKEN")
):
    """
    Receive packet data from Hubble Network via webhook.
    
    Hubble will POST an array of up to 1,000 packets as they arrive.
    We validate the webhook secret, process each packet, and update
    the corresponding BLE tag in our database.
    
    Webhook payload structure:
    {
        "packets": [
            {
                "device": {
                    "id": "device-uuid",
                    "timestamp": 1234567890.123,
                    "rssi": -65,
                    "payload": "base64-encoded-data"
                },
                "location": {
                    "latitude": 51.5074,
                    "longitude": -0.1278,
                    "altitude": 10.5,
                    "horizontal_accuracy": 5.0,
                    "vertical_accuracy": 3.0,
                    "timestamp": 1234567890.456
                },
                "network": {
                    "type": "TERRESTRIAL"
                }
            },
            ...
        ]
    }
    
    Returns 200 OK on success to acknowledge receipt.
    """
    # Validate webhook secret
    webhook_secret = os.getenv("HUBBLE_WEBHOOK_SECRET")
    if webhook_secret and x_hubble_token != webhook_secret:
        logger.warning("⚠️  Hubble webhook rejected: invalid token")
        raise HTTPException(status_code=401, detail="Invalid webhook token")
    
    # Parse payload
    try:
        payload = await request.json()
        packets = payload.get("packets", [])
        
        if not packets:
            logger.warning("⚠️  Hubble webhook received with no packets")
            return {"status": "ok", "processed": 0}
        
        logger.info(f"📨 Hubble webhook: processing {len(packets)} packet(s)")
        
        # Group packets by device for efficient processing
        device_packets = {}
        for packet in packets:
            device_info = packet.get("device", {})
            device_id = device_info.get("id")
            
            if not device_id:
                continue
            
            if device_id not in device_packets:
                device_packets[device_id] = []
            device_packets[device_id].append(packet)
        
        # Process each device's packets (use latest packet per device)
        updated_count = 0
        geocoding_service = GeocodingService()
        
        for device_id, device_packet_list in device_packets.items():
            # Get the most recent packet for this device
            # Packets are ordered by timestamp, so take the last one
            latest_packet = device_packet_list[-1]
            
            # Find the BLE tag in our database
            tracker = db.query(BLETag).filter(
                BLETag.imei == device_id,
                BLETag.tag_type == "series_5_hubble"
            ).first()
            
            if not tracker:
                logger.debug(f"⏭️  Device {device_id[:8]}... not found in database, skipping")
                continue
            
            try:
                # Extract data from packet
                device_info = latest_packet.get("device", {})
                location = latest_packet.get("location", {})
                
                lat = location.get("latitude")
                lng = location.get("longitude")
                
                if lat is None or lng is None:
                    logger.warning(f"⚠️  Device {device_id[:8]}: packet has no location")
                    continue
                
                # Update position
                tracker.latitude = str(lat)
                tracker.longitude = str(lng)
                
                # Update last_seen timestamp
                device_ts = device_info.get("timestamp")
                if device_ts:
                    tracker.last_seen = datetime.fromtimestamp(device_ts, tz=timezone.utc)
                else:
                    tracker.last_seen = datetime.now(timezone.utc)
                
                # Decode sensor data from payload
                payload_b64 = device_info.get("payload")
                sensor_data = {}
                if payload_b64:
                    sensor_data = HubbleTagProvider.decode_minew_payload(payload_b64)
                
                # Build attributes dict
                attrs = tracker.attributes or {}
                
                # RSSI
                rssi = device_info.get("rssi")
                if rssi is not None:
                    attrs["RSSI"] = {"value": f"{rssi} dBm", "show_on_map": True}
                
                # Temperature
                temperature = sensor_data.get("temperature")
                if temperature is not None:
                    attrs["Temperature"] = {"value": f"{temperature}°C", "show_on_map": True}
                
                # Humidity
                humidity = sensor_data.get("humidity")
                if humidity is not None:
                    attrs["Humidity"] = {"value": f"{humidity}%", "show_on_map": True}
                
                # Battery
                battery = sensor_data.get("battery")
                if battery is not None:
                    tracker.battery_level = battery
                    attrs["Battery"] = {"value": f"{battery}%", "show_on_map": True}
                
                # Altitude
                altitude = location.get("altitude")
                if altitude is not None:
                    attrs["Altitude"] = {"value": f"{altitude:.1f}m", "show_on_map": False}
                
                # GPS Accuracy
                h_accuracy = location.get("horizontal_accuracy")
                if h_accuracy is not None:
                    attrs["GPS_Accuracy"] = {"value": f"{h_accuracy:.1f}m", "show_on_map": False}
                
                # Raw packet data (for debugging)
                payload_hex = sensor_data.get("raw_hex")
                if payload_hex:
                    attrs["Payload"] = {"value": payload_hex, "show_on_map": False}
                
                frame_type = sensor_data.get("frame_type")
                if frame_type is not None:
                    attrs["Frame_Type"] = {"value": f"0x{frame_type:02X}", "show_on_map": False}
                
                tracker.attributes = attrs
                flag_modified(tracker, "attributes")
                
                # Reverse geocode for address
                try:
                    geo_result = geocoding_service.reverse_geocode(
                        device_imei=device_id,
                        lat=lat,
                        lng=lng
                    )
                    tracker.location_description = geo_result["address"]
                except Exception as exc:
                    logger.warning(f"⚠️  Device {device_id[:8]} geocode failed: {exc}")
                
                # Check geofences
                user = db.query(User).filter(User.id == tracker.user_id).first()
                if user:
                    try:
                        GeofenceService.check_geofences_for_tracker(
                            db, str(tracker.id), lat, lng, str(user.id)
                        )
                    except Exception as exc:
                        logger.error(f"❌ Geofence check error for {device_id[:8]}: {exc}")
                
                updated_count += 1
                logger.info(f"✅ Webhook: device {device_id[:8]} updated (temp={temperature}°C, rssi={rssi}dBm)")
                
            except Exception as exc:
                logger.error(f"❌ Error processing packet for device {device_id[:8]}: {exc}", exc_info=True)
                continue
        
        # Commit all updates
        db.commit()
        
        logger.info(f"📨 Hubble webhook: processed {updated_count}/{len(device_packets)} device(s)")
        
        # Return 200 OK to acknowledge receipt
        return {
            "status": "ok",
            "received": len(packets),
            "devices": len(device_packets),
            "updated": updated_count
        }
        
    except Exception as exc:
        logger.error(f"❌ Hubble webhook error: {exc}", exc_info=True)
        db.rollback()
        raise HTTPException(status_code=500, detail="Webhook processing failed")
