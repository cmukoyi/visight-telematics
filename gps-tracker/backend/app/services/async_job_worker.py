"""
Async Job Worker Service (v2.2 A5)

Background worker that processes long-running admin operations:
- batch_backfill: Backfill positions for all subscribed devices in a tenant
- batch_reprocess: Reprocess trips for all subscribed devices in a tenant

Architecture:
- Polls async_jobs table for pending jobs
- Processes devices one at a time (sequential for safety)
- Updates progress in real-time
- Handles errors gracefully (continues processing, logs failures)
- Resumable (tracks last_processed_imei)

Run as a background service:
    python -m app.services.async_job_worker
"""

import asyncio
import logging
import uuid
from datetime import datetime, timezone
from typing import List, Dict, Optional
from sqlalchemy import select, and_
from sqlalchemy.orm import Session

from app.database import get_db_context
from app.models_admin import AsyncJob
from app.models import DeviceState, BLETag
# from app.services.trip_backfill_service import backfill_device_positions, BackfillPreset  # DISABLED: Import errors
from app.services.trip_reprocess_service import replay_device_trips

logger = logging.getLogger(__name__)
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)


# ═══════════════════════════════════════════════════════════════════════════
# JOB EXECUTION
# ═══════════════════════════════════════════════════════════════════════════

async def execute_batch_backfill(job: AsyncJob, db: Session) -> None:
    """
    Execute batch backfill job for all subscribed devices in a tenant.
    
    Args:
        job: AsyncJob instance
        db: Database session
    
    Job params:
        {
            "tenant_id": "uuid-string",
            "preset": "last_7_days"
        }
    """
    params = job.params
    tenant_id = params.get("tenant_id")
    preset_str = params.get("preset", "last_7_days")
    
    logger.info("🔄 Executing batch backfill job %s: tenant=%s, preset=%s", job.id, tenant_id, preset_str)
    
    # Validate preset
    try:
        preset = BackfillPreset(preset_str)
    except ValueError:
        job.status = "failed"
        job.error_message = f"Invalid preset: {preset_str}"
        db.commit()
        return
    
    # Get all subscribed devices for this tenant
    devices = db.query(BLETag).join(
        DeviceState, BLETag.imei == DeviceState.device_imei
    ).filter(
        and_(
            BLETag.user_group_id == tenant_id,
            DeviceState.trip_subscribed == True
        )
    ).all()
    
    if not devices:
        logger.warning("⚠️  No subscribed devices found for tenant %s", tenant_id)
        job.status = "completed"
        job.total_devices = 0
        job.completed_devices = 0
        job.completed_at = datetime.now(timezone.utc)
        db.commit()
        return
    
    job.total_devices = len(devices)
    db.commit()
    
    logger.info("📊 Found %d subscribed devices to backfill", len(devices))
    
    # Initialize results accumulator
    results = {
        "positions_fetched": 0,
        "positions_inserted": 0,
        "positions_processed": 0,
        "journeys_created": 0,
        "legs_created": 0,
        "stationaries_created": 0,
        "errors": []
    }
    
    # Process devices one at a time
    for device in devices:
        try:
            logger.info("📥 Backfilling device %s (%d/%d)", device.imei, job.completed_devices + 1, job.total_devices)
            
            # Call backfill service
            result = await backfill_device_positions(
                db=db,
                device_imei=device.imei,
                preset=preset
            )
            
            # Accumulate results
            results["positions_fetched"] += result["positions_fetched"]
            results["positions_inserted"] += result["positions_inserted"]
            results["positions_processed"] += result["positions_processed"]
            results["journeys_created"] += result["journeys_created"]
            results["legs_created"] += result["legs_created"]
            results["stationaries_created"] += result["stationaries_created"]
            
            # Update job progress
            job.completed_devices += 1
            job.last_processed_imei = device.imei
            job.results = results
            db.commit()
            
            logger.info("✅ Device %s backfilled: %d journeys", device.imei, result["journeys_created"])
            
        except Exception as e:
            logger.error("❌ Device %s backfill failed: %s", device.imei, e, exc_info=True)
            
            # Log error but continue processing
            job.failed_devices += 1
            results["errors"].append({
                "device_imei": device.imei,
                "error": str(e)
            })
            job.results = results
            db.commit()
    
    # Mark job as completed
    job.status = "completed"
    job.completed_at = datetime.now(timezone.utc)
    db.commit()
    
    logger.info(
        "✅ Batch backfill complete: %d/%d devices succeeded, %d failed",
        job.completed_devices,
        job.total_devices,
        job.failed_devices
    )


async def execute_batch_reprocess(job: AsyncJob, db: Session) -> None:
    """
    Execute batch reprocess job for all subscribed devices in a tenant.
    
    Args:
        job: AsyncJob instance
        db: Database session
    
    Job params:
        {
            "tenant_id": "uuid-string"
        }
    """
    params = job.params
    tenant_id = params.get("tenant_id")
    
    logger.info("🔄 Executing batch reprocess job %s: tenant=%s", job.id, tenant_id)
    
    # Get all subscribed devices for this tenant
    devices = db.query(BLETag).join(
        DeviceState, BLETag.imei == DeviceState.device_imei
    ).filter(
        and_(
            BLETag.user_group_id == tenant_id,
            DeviceState.trip_subscribed == True
        )
    ).all()
    
    if not devices:
        logger.warning("⚠️  No subscribed devices found for tenant %s", tenant_id)
        job.status = "completed"
        job.total_devices = 0
        job.completed_devices = 0
        job.completed_at = datetime.now(timezone.utc)
        db.commit()
        return
    
    job.total_devices = len(devices)
    db.commit()
    
    logger.info("📊 Found %d subscribed devices to reprocess", len(devices))
    
    # Initialize results accumulator
    results = {
        "positions_processed": 0,
        "journeys_created": 0,
        "legs_created": 0,
        "stationaries_created": 0,
        "errors": []
    }
    
    # Process devices one at a time
    for device in devices:
        try:
            logger.info("🔄 Reprocessing device %s (%d/%d)", device.imei, job.completed_devices + 1, job.total_devices)
            
            # Call reprocess service
            result = replay_device_trips(
                db=db,
                device_imei=device.imei,
                start_date=None,  # Full history
                end_date=None,
                tenant_id=tenant_id
            )
            
            # Accumulate results
            results["positions_processed"] += result["positions_processed"]
            results["journeys_created"] += result["journeys_created"]
            results["legs_created"] += result["legs_created"]
            results["stationaries_created"] += result["stationaries_created"]
            
            # Update job progress
            job.completed_devices += 1
            job.last_processed_imei = device.imei
            job.results = results
            db.commit()
            
            logger.info("✅ Device %s reprocessed: %d journeys", device.imei, result["journeys_created"])
            
        except Exception as e:
            logger.error("❌ Device %s reprocess failed: %s", device.imei, e, exc_info=True)
            
            # Log error but continue processing
            job.failed_devices += 1
            results["errors"].append({
                "device_imei": device.imei,
                "error": str(e)
            })
            job.results = results
            db.commit()
    
    # Mark job as completed
    job.status = "completed"
    job.completed_at = datetime.now(timezone.utc)
    db.commit()
    
    logger.info(
        "✅ Batch reprocess complete: %d/%d devices succeeded, %d failed",
        job.completed_devices,
        job.total_devices,
        job.failed_devices
    )


# ═══════════════════════════════════════════════════════════════════════════
# JOB WORKER
# ═══════════════════════════════════════════════════════════════════════════

async def process_pending_jobs(db: Session) -> None:
    """
    Find and process all pending jobs.
    
    Args:
        db: Database session
    """
    # Get all pending jobs
    pending_jobs = db.query(AsyncJob).filter(
        AsyncJob.status == "pending"
    ).order_by(AsyncJob.created_at).all()
    
    if not pending_jobs:
        return
    
    logger.info("📋 Found %d pending jobs", len(pending_jobs))
    
    for job in pending_jobs:
        try:
            # Mark job as running
            job.status = "running"
            job.started_at = datetime.now(timezone.utc)
            db.commit()
            
            logger.info("🚀 Starting job %s (type=%s)", job.id, job.job_type)
            
            # Execute job based on type
            if job.job_type == "batch_backfill":
                # DISABLED: trip_backfill_service has import errors (calls non-existent functions)
                logger.error("❌ batch_backfill is disabled (import errors in trip_backfill_service)")
                job.status = "failed"
                job.error_message = "batch_backfill is disabled pending tracksolid_track_service refactor"
                db.commit()
            elif job.job_type == "batch_reprocess":
                await execute_batch_reprocess(job, db)
            else:
                logger.error("❌ Unknown job type: %s", job.job_type)
                job.status = "failed"
                job.error_message = f"Unknown job type: {job.job_type}"
                db.commit()
        
        except Exception as e:
            logger.error("❌ Job %s failed: %s", job.id, e, exc_info=True)
            job.status = "failed"
            job.error_message = str(e)
            job.completed_at = datetime.now(timezone.utc)
            db.commit()


async def worker_loop():
    """
    Main worker loop - polls for pending jobs every 5 seconds.
    """
    logger.info("🚀 Async job worker started")
    
    while True:
        try:
            with get_db_context() as db:
                await process_pending_jobs(db)
        except Exception as e:
            logger.error("❌ Worker loop error: %s", e, exc_info=True)
        
        # Wait 5 seconds before next poll
        await asyncio.sleep(5)


# ═══════════════════════════════════════════════════════════════════════════
# MAIN
# ═══════════════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    asyncio.run(worker_loop())
