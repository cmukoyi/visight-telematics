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
    
    # Verify device exists
    tag = db.execute(
        select(BLETag).where(BLETag.imei == device_imei)
    ).scalar_one_or_none()
    
    if not tag:
        raise ValueError(f"Device {device_imei} not found")
    
    # Step 1: Delete existing derived data (transactional)
    logger.info("🗑️  REPROCESS: Deleting existing derived data for %s", device_imei)
    
    # Build delete filters
    delete_filters = [Leg.device_imei == device_imei]
    if start_date:
        delete_filters.append(Leg.started_at >= start_date)
    if end_date:
        delete_filters.append(Leg.ended_at <= end_date)
    
    # Delete legs (cascade will handle associated data)
    legs_deleted = db.execute(
        delete(Leg).where(*delete_filters)
    ).rowcount
    
    # Delete stationaries
    stat_filters = [Stationary.device_imei == device_imei]
    if start_date:
        stat_filters.append(Stationary.started_at >= start_date)
    if end_date:
        stat_filters.append(Stationary.ended_at <= end_date)
    
    stationaries_deleted = db.execute(
        delete(Stationary).where(*stat_filters)
    ).rowcount
    
    # Delete journeys
    journey_filters = [Journey.device_imei == device_imei]
    if start_date:
        journey_filters.append(Journey.started_at >= start_date)
    if end_date:
        journey_filters.append(Journey.ended_at <= end_date)
    
    journeys_deleted = db.execute(
        delete(Journey).where(*journey_filters)
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
    
    # Step 3: Fetch positions from DB
    logger.info("📥 REPROCESS: Fetching positions for replay")
    
    position_filters = [DevicePosition.device_imei == device_imei]
    if start_date:
        position_filters.append(DevicePosition.observed_at >= start_date)
    if end_date:
        position_filters.append(DevicePosition.observed_at <= end_date)
    
    positions = db.execute(
        select(DevicePosition)
        .where(*position_filters)
        .order_by(DevicePosition.observed_at.asc())
    ).scalars().all()
    
    if not positions:
        logger.warning("⚠️  REPROCESS: No positions found for %s in window", device_imei)
        return {
            "positions_processed": 0,
            "journeys_created": 0,
            "legs_created": 0,
            "stationaries_created": 0
        }
    
    logger.info("📥 REPROCESS: Found %d positions to replay", len(positions))
    
    # Step 4: Replay positions through trip engine
    logger.info("⚙️  REPROCESS: Replaying positions through engine v%s", ENGINE_VERSION)
    
    # Create engine instance with current config
    # TODO: Pass tenant_id when TripEngine supports per-tenant config (A1)
    engine = TripEngine(db=db, device_imei=device_imei)
    
    # Process each position
    for i, pos in enumerate(positions):
        if i % 100 == 0:
            logger.info("⚙️  REPROCESS: Processing position %d/%d", i + 1, len(positions))
        
        engine.process_position(
            lat=float(pos.latitude),
            lng=float(pos.longitude),
            observed_at=pos.observed_at,
            position_id=str(pos.id)
        )
    
    # Flush any remaining engine state
    engine.flush()
    db.flush()
    
    # Step 5: Count what was created
    journeys_created = db.execute(
        select(Journey)
        .where(Journey.device_imei == device_imei)
    ).scalars().all()
    
    legs_created = db.execute(
        select(Leg)
        .where(Leg.device_imei == device_imei)
    ).scalars().all()
    
    stationaries_created = db.execute(
        select(Stationary)
        .where(Stationary.device_imei == device_imei)
    ).scalars().all()
    
    result = {
        "positions_processed": len(positions),
        "journeys_created": len(journeys_created),
        "legs_created": len(legs_created),
        "stationaries_created": len(stationaries_created)
    }
    
    logger.info(
        "✅ REPROCESS COMPLETE: device_imei=%s positions=%d journeys=%d legs=%d stationaries=%d",
        device_imei,
        result["positions_processed"],
        result["journeys_created"],
        result["legs_created"],
        result["stationaries_created"]
    )
    
    return result
