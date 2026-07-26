"""
Trip Engine Reprocess Service (v2.2 A2/A4)

Provides admin operations to rebuild trip segmentation from stored positions.
Supports both full-history replay (A4) and backfill+replay (A3).

The engine is a pure function of positions — positions are never modified,
only the derived layer (legs/journeys/stationaries) and engine_state are rebuilt.
"""
import logging
from datetime import datetime, timezone
from typing import Optional, Dict, Any
from uuid import UUID

from sqlalchemy import select, delete
from sqlalchemy.orm import Session

from app.models import (
    DeviceState, EngineState, Leg, Stationary, Journey,
    DevicePosition, BLETag
)
from app.services.trip_engine import TripEngine

logger = logging.getLogger(__name__)

# Engine version identifier for journey tracking
ENGINE_VERSION = "v2.1"


def replay_device_trips(
    db: Session,
    device_imei: str,
    start_date: Optional[datetime] = None,
    end_date: Optional[datetime] = None,
    tenant_id: Optional[str] = None
) -> Dict[str, Any]:
    """
    Reprocess trips for a device from stored positions (A4: Reprocess).
    
    Deletes all derived trip data and replays positions through the current
    engine with current parameters. This is the core operation for adopting
    engine refinements (e.g. v2.1 settle-dwell/merge/air-leg fixes).
    
    Args:
        db: Database session (must be in a transaction)
        device_imei: Device to reprocess
        start_date: Optional start of replay window (default: all history)
        end_date: Optional end of replay window (default: now)
        tenant_id: Tenant ID for resolving per-tenant config (A1)
    
    Returns:
        Dict with stats: journeys_created, legs_created, stationaries_created, positions_processed
    
    Raises:
        ValueError: If device not found or no positions available
    
    Note:
        This is a DESTRUCTIVE operation — all existing journeys/legs/stationaries
        for this device (in the window) are deleted. Use with caution.
        
        Positions table is NEVER modified (source of truth).
    """
    logger.info(
        "🔄 REPROCESS: device_imei=%s start=%s end=%s tenant_id=%s",
        device_imei, start_date, end_date, tenant_id
    )
    
    # v1: Full history only (windowed reprocess deferred per spec)
    if start_date or end_date:
        logger.warning(
            "⚠️  REPROCESS: start_date/end_date parameters ignored in v1 (full history only)"
        )
    
    # Verify device exists
    tag = db.execute(
        select(BLETag).where(BLETag.imei == device_imei)
    ).scalar_one_or_none()
    
    if not tag:
        raise ValueError(f"Device {device_imei} not found")
    
    # Step 1: Delete existing derived data (transactional)
    logger.info("🗑️  REPROCESS: Deleting existing derived data for %s", device_imei)
    
    # Delete all legs for this device
    legs_deleted = db.execute(
        delete(Leg).where(Leg.device_imei == device_imei)
    ).rowcount
    
    # Delete all stationaries
    stationaries_deleted = db.execute(
        delete(Stationary).where(Stationary.device_imei == device_imei)
    ).rowcount
    
    # Delete all journeys
    journeys_deleted = db.execute(
        delete(Journey).where(Journey.device_imei == device_imei)
    ).rowcount
    
    logger.info(
        "🗑️  REPROCESS: Deleted %d journeys, %d legs, %d stationaries",
        journeys_deleted, legs_deleted, stationaries_deleted
    )
    
    # Step 2: Reset engine state for this device
    logger.info("🔄 REPROCESS: Resetting engine state for %s", device_imei)
    
    engine_state = db.execute(
        select(EngineState).where(EngineState.device_imei == device_imei)
    ).scalar_one_or_none()
    
    if engine_state:
        db.delete(engine_state)
        db.flush()
    
    # Also reset DeviceState trip tracking fields
    device_state = db.execute(
        select(DeviceState).where(DeviceState.device_imei == device_imei)
    ).scalar_one_or_none()
    
    if device_state:
        # Don't reset trip_subscribed or last_position_ts (owned by forward pipeline)
        # Just ensure engine state is clean
        pass
    
    logger.info("✅ REPROCESS: Engine state reset complete")
    
    # Step 3: Replay positions through trip engine
    logger.info("⚙️  REPROCESS: Replaying positions through engine v%s", ENGINE_VERSION)
    
    # Create engine instance
    engine = TripEngine(db=db, device_imei=device_imei)
    
    # Process all positions (engine_state was reset, so last_processed_at is None)
    # This will process ALL positions for this device through the current engine
    stats = engine.process_positions()
    
    logger.info(
        "✅ REPROCESS COMPLETE: device_imei=%s positions=%d journeys=%d legs=%d stationaries=%d",
        device_imei,
        stats['positions_processed'],
        stats.get('journeys_created', 0),
        stats.get('legs_created', 0),
        stats.get('stationaries_created', 0)
    )
    
    return {
        "positions_processed": stats['positions_processed'],
        "journeys_created": stats.get('journeys_created', 0),
        "legs_created": stats.get('legs_created', 0),
        "stationaries_created": stats.get('stationaries_created', 0),
        "engine_version": ENGINE_VERSION,
    }
