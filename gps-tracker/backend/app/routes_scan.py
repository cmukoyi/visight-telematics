"""Scan recording and Server-Sent Events for real-time updates"""
import asyncio
import json
import os
from datetime import datetime
from typing import AsyncGenerator
from fastapi import APIRouter, HTTPException, Request, Depends
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session
from sqlalchemy import text
from app.database import get_db
from app.schemas.asset import ScanRequest, ScanResponse

router = APIRouter(prefix="/api/scan", tags=["scan"])

# SSE subscriber queues for broadcasting location updates
_sse_subscribers: list[asyncio.Queue] = []

# GPS accuracy limit (meters) - scans with worse accuracy are rejected
GPS_ACCURACY_LIMIT = float(os.getenv("GPS_ACCURACY_LIMIT", "500"))


def _broadcast(event_data: dict):
    """
    Broadcast an event to all connected SSE clients.
    Removes dead queues that are full (client disconnected).
    """
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
    Record a GPS scan for an asset.
    
    Flow:
    1. Validate GPS accuracy (reject if > 500m)
    2. Verify asset exists in database
    3. Insert row into scan_events (immutable history)
    4. Upsert row in asset_locations (latest position cache)
    5. Broadcast location_update event to SSE subscribers
    6. Return success response with asset name and scan count
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
    
    # Get client info for audit trail
    scanner_ip = request.client.host if request.client else None
    user_agent = request.headers.get("user-agent")
    
    # Begin transaction
    try:
        # Check asset exists
        asset_row = db.execute(
            text("SELECT id, name, type_code FROM assets WHERE id = :asset_id"),
            {"asset_id": body.asset_id}
        ).fetchone()
        
        if not asset_row:
            raise HTTPException(
                status_code=404,
                detail={"error": "Asset not found", "asset_id": body.asset_id}
            )
        
        # Insert scan event (permanent history record)
        db.execute(
            text("""
                INSERT INTO scan_events 
                (asset_id, lat, lng, accuracy, location, source, scanner_ip, user_agent)
                VALUES (:asset_id, :lat, :lng, :accuracy, 
                        ST_SetSRID(ST_MakePoint(:lng, :lat), 4326), 
                        :source, :scanner_ip, :user_agent)
            """),
            {
                "asset_id": body.asset_id,
                "lat": body.lat,
                "lng": body.lng,
                "accuracy": body.accuracy,
                "source": body.source,
                "scanner_ip": scanner_ip,
                "user_agent": user_agent
            }
        )
        
        # Upsert asset_locations (latest position cache)
        result = db.execute(
            text("""
                INSERT INTO asset_locations 
                (asset_id, lat, lng, accuracy, location, source, last_seen, scan_count)
                VALUES (:asset_id, :lat, :lng, :accuracy,
                        ST_SetSRID(ST_MakePoint(:lng, :lat), 4326),
                        :source, NOW(), 1)
                ON CONFLICT (asset_id) DO UPDATE SET
                    lat = EXCLUDED.lat,
                    lng = EXCLUDED.lng,
                    accuracy = EXCLUDED.accuracy,
                    location = EXCLUDED.location,
                    source = EXCLUDED.source,
                    last_seen = EXCLUDED.last_seen,
                    scan_count = asset_locations.scan_count + 1
                RETURNING scan_count
            """),
            {
                "asset_id": body.asset_id,
                "lat": body.lat,
                "lng": body.lng,
                "accuracy": body.accuracy,
                "source": body.source
            }
        ).fetchone()
        
        scan_count = result.scan_count
        
        # Commit transaction
        db.commit()
        
    except HTTPException:
        db.rollback()
        raise
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail={"error": "Database error", "message": str(e)})
    
    # Broadcast to SSE subscribers (after successful commit)
    _broadcast({
        "type": "location_update",
        "asset_id": body.asset_id,
        "asset_name": asset_row.name or body.asset_id,
        "type_code": asset_row.type_code,
        "source": body.source,
        "lat": body.lat,
        "lng": body.lng,
        "accuracy": body.accuracy,
        "scan_count": scan_count,
        "timestamp": datetime.utcnow().isoformat() + "Z"
    })
    
    return ScanResponse(
        success=True,
        asset_id=body.asset_id,
        asset_name=asset_row.name,
        scan_count=scan_count,
        message=f"Location updated for {asset_row.name or body.asset_id}"
    )


@router.get("/events")
async def scan_events_stream(request: Request):
    """
    Server-Sent Events (SSE) endpoint for real-time location updates.
    
    Clients connect once and receive a stream of events:
    - Initial 'connected' event
    - 'location_update' events when assets are scanned
    - Periodic 'heartbeat' events (every 25s) to keep connection alive
    
    EventSource (browser API) automatically reconnects on disconnect.
    """
    queue: asyncio.Queue = asyncio.Queue(maxsize=100)
    _sse_subscribers.append(queue)
    
    async def event_generator() -> AsyncGenerator[str, None]:
        # Send initial connected event
        yield 'data: {"type":"connected"}\n\n'
        
        try:
            while True:
                # Check if client disconnected
                if await request.is_disconnected():
                    break
                
                try:
                    # Wait for event with 25s timeout
                    event_data = await asyncio.wait_for(queue.get(), timeout=25.0)
                    yield f"data: {json.dumps(event_data)}\n\n"
                    
                except asyncio.TimeoutError:
                    # Send heartbeat to prevent proxy timeout
                    yield 'data: {"type":"heartbeat"}\n\n'
                    
        finally:
            # Clean up on disconnect
            if queue in _sse_subscribers:
                _sse_subscribers.remove(queue)
    
    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",  # Disable Nginx buffering for SSE
            "Connection": "keep-alive"
        }
    )
