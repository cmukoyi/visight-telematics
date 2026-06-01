"""Scan recording and Server-Sent Events for real-time updates"""
import asyncio
import json
import os
from datetime import datetime, timezone
from fastapi import APIRouter, HTTPException, Request, Depends
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session
from pydantic import BaseModel

from app.database import get_db
from app.models import BLETag

router = APIRouter(prefix="/api/scan", tags=["scan"])

# SSE subscriber queues for broadcasting location updates
_sse_subscribers: list[asyncio.Queue] = []

# GPS accuracy limit (meters) - scans with worse accuracy are rejected
GPS_ACCURACY_LIMIT = float(os.getenv("GPS_ACCURACY_LIMIT", "500"))


class ScanRequest(BaseModel):
    asset_id: str  # IMEI of the QR asset
    lat: float
    lng: float
    accuracy: float | None = None
    source: str = "qr"  # 'qr' | 'nfc' | 'manual'


class ScanResponse(BaseModel):
    success: bool
    message: str
    asset_id: str
    asset_name: str
    scan_count: int | None = None


def _broadcast(event_data: dict):
    """Broadcast an event to all connected SSE clients"""
    dead_queues = []
    for queue in _sse_subscribers:
        try:
            queue.put_nowait(event_data)
        except asyncio.QueueFull:
            dead_queues.append(queue)
    
    for queue in dead_queues:
        _sse_subscribers.remove(queue)


@router.post("", response_model=ScanResponse)
async def record_scan(body: ScanRequest, request: Request, db: Session = Depends(get_db)):
    """
    Record a GPS scan for a QR/NFC asset.
    
    Updates ble_tags.latitude/longitude so asset appears on Live Map with other tags.
    Broadcasts location_update event to SSE subscribers for real-time map updates.
    """
    # Validate GPS accuracy
    if body.accuracy is not None and body.accuracy > GPS_ACCURACY_LIMIT:
        raise HTTPException(
            status_code=422,
            detail={
                "error": "GPS accuracy too low",
                "accuracy": body.accuracy,
                "limit": GPS_ACCURACY_LIMIT,
                "message": f"Accuracy +/-{round(body.accuracy)}m exceeds limit. Move to open area for better GPS signal."
            }
        )
    
    # Find the asset (QR tag in ble_tags table)
    tag = db.query(BLETag).filter(BLETag.imei == body.asset_id).first()
    
    if not tag:
        raise HTTPException(
            status_code=404,
            detail={"error": "Asset not found", "asset_id": body.asset_id}
        )
    
    # Update tag location (same as series_1/series_2 tags)
    tag.latitude = str(body.lat)
    tag.longitude = str(body.lng)
    tag.last_seen = datetime.now(timezone.utc)
    
    # Set activation_date on first GPS fix (starts expiry countdown)
    if not tag.activation_date and tag.package_id:
        tag.activation_date = datetime.now(timezone.utc)
        # expiry_date will be calculated in location_poller_service
    
    db.commit()
    db.refresh(tag)
    
    # Broadcast to SSE subscribers (for Live Map real-time updates)
    _broadcast({
        "event": "location_update",
        "data": {
            "asset_id": body.asset_id,
            "imei": body.asset_id,
            "tag_id": str(tag.id),
            "lat": body.lat,
            "lng": body.lng,
            "accuracy": body.accuracy,
            "source": body.source,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "tag_type": tag.tag_type,
            "device_name": tag.device_name or f"Asset {body.asset_id[:8]}"
        }
    })
    
    return ScanResponse(
        success=True,
        message="Location recorded successfully",
        asset_id=body.asset_id,
        asset_name=tag.device_name or f"Asset {body.asset_id[:8]}",
        scan_count=None  # Can add a counter in attributes if needed
    )


@router.get("/events")
async def sse_events(request: Request):
    """
    Server-Sent Events endpoint for real-time location updates.
    Clients connect with EventSource and receive location_update events.
    """
    async def event_generator():
        queue = asyncio.Queue(maxsize=100)
        _sse_subscribers.append(queue)
        
        try:
            while True:
                # Check if client disconnected
                if await request.is_disconnected():
                    break
                
                try:
                    # Wait for event with timeout for heartbeat
                    event_data = await asyncio.wait_for(queue.get(), timeout=25.0)
                    yield f"event: {event_data['event']}\ndata: {json.dumps(event_data['data'])}\n\n"
                except asyncio.TimeoutError:
                    # Send heartbeat comment to keep connection alive
                    yield ": heartbeat\n\n"
        finally:
            _sse_subscribers.remove(queue)
    
    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no"  # Nginx must not buffer SSE
        }
    )
