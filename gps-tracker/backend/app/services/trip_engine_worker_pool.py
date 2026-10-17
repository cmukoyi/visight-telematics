"""
Trip Engine Worker Pool (v2.4.0)

Asyncio-based worker pool for parallel trip processing.
Handles 1000+ devices with configurable concurrent workers.

Benefits:
- Error isolation: One device failure doesn't block others
- Incremental checkpointing: Resumable processing every N positions
- Priority queue: Critical devices processed first
- Scalable: Adjust worker count based on CPU cores

Architecture:
    Manager (1 task)
        ├─> Priority Queue (devices to process)
        ├─> Worker Pool (N concurrent workers)
        │   ├─> Worker 1: Processing device A
        │   ├─> Worker 2: Processing device B
        │   └─> Worker N: Processing device Z
        └─> Metrics Collector

Performance:
    1 vCPU:  5 workers  → ~1.5-2x speedup (I/O concurrency)
    2 vCPU:  10 workers → ~4x speedup
    4 vCPU:  20 workers → ~8x speedup
"""

import asyncio
import logging
from datetime import datetime, timezone, timedelta
from dataclasses import dataclass, field
from enum import Enum
from typing import List, Dict, Optional, Set
from collections import defaultdict

from sqlalchemy import select, text
from sqlalchemy.orm import Session

from app.models import DeviceState, DevicePosition, EngineState

logger = logging.getLogger(__name__)

# ═══════════════════════════════════════════════════════════════════════════
# CONFIGURATION
# ═══════════════════════════════════════════════════════════════════════════

# Worker pool sizing (adjust based on CPU cores)
DEFAULT_NUM_WORKERS = 5  # Conservative for 1-core, increase for multi-core
DEFAULT_BATCH_SIZE = 5000  # Positions per batch
DEFAULT_CHECKPOINT_INTERVAL = 1000  # Save watermark every N positions
DEFAULT_QUEUE_SCAN_INTERVAL_SEC = 30  # How often to scan for new work
DEFAULT_MAX_BATCH_COUNT = 10  # Max batches per device per sweep (prevent runaway)

# Priority thresholds
HIGH_PRIORITY_AGE_SEC = 300  # GPS data <5 min old = HIGH priority
HIGH_PRIORITY_BACKLOG = 10000  # >10k unprocessed positions = HIGH priority
LOW_PRIORITY_AGE_SEC = 3600  # GPS data >1 hour old = LOW priority


# ═══════════════════════════════════════════════════════════════════════════
# DATA CLASSES
# ═══════════════════════════════════════════════════════════════════════════

class Priority(Enum):
    """Work item priority levels."""
    HIGH = 1    # New GPS data (<5 min) or large backlogs
    NORMAL = 2  # Regular processing
    LOW = 3     # Idle devices (>1 hour old)


@dataclass(order=True)
class WorkItem:
    """
    Work item for priority queue.
    
    Ordering: By priority (ascending), then by queued_at (FIFO within priority).
    """
    priority: int = field(compare=True)  # 1=HIGH, 2=NORMAL, 3=LOW
    queued_at: datetime = field(compare=True)
    device_imei: str = field(compare=False)
    unprocessed_count: int = field(default=0, compare=False)
    latest_position_age_sec: float = field(default=0, compare=False)


@dataclass
class ProcessingResult:
    """Result from processing one device."""
    device_imei: str
    positions_processed: int
    journeys_created: int
    legs_created: int
    stationaries_created: int
    duration_sec: float
    error: Optional[str] = None
    batches_processed: int = 0


@dataclass
class WorkerPoolMetrics:
    """Aggregate metrics for worker pool."""
    sweep_start: datetime
    sweep_end: Optional[datetime] = None
    devices_queued: int = 0
    devices_processed: int = 0
    devices_failed: int = 0
    total_positions: int = 0
    total_journeys: int = 0
    total_legs: int = 0
    total_stationaries: int = 0
    worker_idle_time_sec: float = 0
    worker_busy_time_sec: float = 0
    results: List[ProcessingResult] = field(default_factory=list)


# ═══════════════════════════════════════════════════════════════════════════
# WORKER POOL MANAGER
# ═══════════════════════════════════════════════════════════════════════════

class TripEngineWorkerPool:
    """
    Asyncio-based worker pool for parallel trip processing.
    """
    
    def __init__(
        self,
        num_workers: int = DEFAULT_NUM_WORKERS,
        batch_size: int = DEFAULT_BATCH_SIZE,
        checkpoint_interval: int = DEFAULT_CHECKPOINT_INTERVAL,
        max_batch_count: int = DEFAULT_MAX_BATCH_COUNT,
    ):
        self.num_workers = num_workers
        self.batch_size = batch_size
        self.checkpoint_interval = checkpoint_interval
        self.max_batch_count = max_batch_count
        
        # Priority queue: (priority, queued_at, work_item)
        self.work_queue: asyncio.PriorityQueue = asyncio.PriorityQueue()
        
        # Track devices currently being processed (prevent duplicates)
        self.processing_devices: Set[str] = set()
        self.processing_lock = asyncio.Lock()
        
        # Workers
        self.workers: List[asyncio.Task] = []
        self.running = False
        
        # Metrics
        self.metrics: Optional[WorkerPoolMetrics] = None
    
    async def start(self):
        """Start worker pool."""
        if self.running:
            logger.warning("⚠️  Worker pool already running")
            return
        
        self.running = True
        self.metrics = WorkerPoolMetrics(sweep_start=datetime.now(timezone.utc))
        
        # Spawn workers
        for i in range(self.num_workers):
            worker = asyncio.create_task(
                self._worker(worker_id=i),
                name=f"trip-worker-{i}"
            )
            self.workers.append(worker)
        
        logger.info(f"✅ Started {self.num_workers} trip engine workers")
    
    async def stop(self):
        """Graceful shutdown."""
        if not self.running:
            return
        
        self.running = False
        
        # Wait for queue to drain (with timeout)
        try:
            await asyncio.wait_for(self.work_queue.join(), timeout=300)
        except asyncio.TimeoutError:
            logger.warning("⚠️  Queue drain timeout (5 min)")
        
        # Cancel workers
        for worker in self.workers:
            worker.cancel()
        
        # Wait for cancellation
        await asyncio.gather(*self.workers, return_exceptions=True)
        
        self.workers.clear()
        logger.info("✅ Worker pool stopped")
    
    async def enqueue_work(self, db: Session) -> int:
        """
        Scan for devices with unprocessed data and enqueue them.
        
        Returns:
            Number of devices enqueued
        """
        items = self._discover_work(db)
        
        enqueued = 0
        for item in items:
            # Skip if already being processed
            async with self.processing_lock:
                if item.device_imei in self.processing_devices:
                    continue
            
            # Add to priority queue
            await self.work_queue.put((
                item.priority,
                item.queued_at,
                item
            ))
            enqueued += 1
        
        if enqueued > 0:
            logger.info(f"📥 Enqueued {enqueued} devices for processing")
        
        if self.metrics:
            self.metrics.devices_queued += enqueued
        
        return enqueued
    
    def _discover_work(self, db: Session) -> List[WorkItem]:
        """
        Query database for devices needing processing.
        
        Finds devices with EITHER:
        1. Orphaned positions (leg_id IS NULL) - must be processed regardless of watermark
        2. New positions after watermark
        
        Returns:
            List of WorkItem objects, prioritized
        """
        # Find devices with orphaned OR new unprocessed positions
        query = text("""
        SELECT 
            ds.device_imei,
            COUNT(dp.id) as unprocessed_count,
            MAX(dp.received_at) as latest_position,
            es.last_received_at,
            EXTRACT(EPOCH FROM (NOW() - MAX(dp.received_at))) as age_seconds
        FROM device_state ds
        LEFT JOIN engine_state es ON es.device_imei = ds.device_imei
        LEFT JOIN device_positions dp ON dp.device_imei = ds.device_imei
            AND (
                -- New positions after watermark (normal case)
                dp.received_at > COALESCE(es.last_received_at, '1970-01-01'::timestamp)
                -- OR orphaned positions AFTER last_processed_at (v2.1.25: avoid rebuild loop)
                -- Only recent orphaned positions to prevent infinite re-enqueuing of devices
                OR (
                    dp.leg_id IS NULL 
                    AND dp.stationary_id IS NULL
                    AND dp.observed_at > COALESCE(es.last_processed_at, NOW() - INTERVAL '7 days')
                )
            )
        WHERE ds.trip_subscribed = true
        GROUP BY ds.device_imei, es.last_received_at
        HAVING COUNT(dp.id) > 0
            OR es.last_received_at > NOW() + INTERVAL '5 minutes'
            OR (
                es.last_received_at IS NOT NULL
                AND es.last_received_at > (
                    SELECT MAX(latest.received_at)
                    FROM device_positions latest
                    WHERE latest.device_imei = ds.device_imei
                      AND latest.received_at <= NOW() + INTERVAL '5 minutes'
                )
            )
        ORDER BY age_seconds ASC  -- Oldest data first
        """)
        
        result = db.execute(query)
        rows = result.fetchall()
        
        items = []
        for row in rows:
            age_seconds = row.age_seconds or 0
            count = row.unprocessed_count
            
            # Determine priority
            if age_seconds < HIGH_PRIORITY_AGE_SEC:
                # Fresh GPS data (<5 min)
                priority = Priority.HIGH
            elif count > HIGH_PRIORITY_BACKLOG:
                # Large backlog (>10k positions)
                priority = Priority.HIGH
            elif age_seconds > LOW_PRIORITY_AGE_SEC:
                # Stale data (>1 hour old)
                priority = Priority.LOW
            else:
                # Normal processing
                priority = Priority.NORMAL
            
            items.append(WorkItem(
                priority=priority.value,
                queued_at=datetime.now(timezone.utc),
                device_imei=row.device_imei,
                unprocessed_count=count,
                latest_position_age_sec=age_seconds
            ))
        
        return items
    
    async def _worker(self, worker_id: int):
        """
        Worker coroutine: Pulls items from queue and processes them.
        """
        logger.info(f"Worker {worker_id} started")
        
        while self.running:
            work_item = None
            idle_start = datetime.now(timezone.utc)
            
            try:
                # Get work item (blocks if queue empty)
                priority, queued_at, work_item = await asyncio.wait_for(
                    self.work_queue.get(),
                    timeout=60.0  # Timeout to check self.running
                )
                
                idle_duration = (datetime.now(timezone.utc) - idle_start).total_seconds()
                if self.metrics:
                    self.metrics.worker_idle_time_sec += idle_duration
                
                # Mark device as being processed
                async with self.processing_lock:
                    if work_item.device_imei in self.processing_devices:
                        # Already being processed (shouldn't happen, but guard)
                        self.work_queue.task_done()
                        continue
                    self.processing_devices.add(work_item.device_imei)
                
                # Process device
                busy_start = datetime.now(timezone.utc)
                
                from app.database import SessionLocal
                db = SessionLocal()
                try:
                    # Run blocking database operations in thread pool to avoid blocking event loop
                    loop = asyncio.get_event_loop()
                    result = await loop.run_in_executor(
                        None,  # Use default ThreadPoolExecutor
                        self._process_device_batched,
                        db,
                        work_item.device_imei,
                        self.batch_size,
                        self.max_batch_count
                    )
                finally:
                    db.close()
                
                busy_duration = (datetime.now(timezone.utc) - busy_start).total_seconds()
                if self.metrics:
                    self.metrics.worker_busy_time_sec += busy_duration
                
                # Log result
                if result.error:
                    logger.error(
                        f"Worker {worker_id}: {work_item.device_imei} "
                        f"❌ ERROR: {result.error}"
                    )
                    if self.metrics:
                        self.metrics.devices_failed += 1
                else:
                    logger.info(
                        f"Worker {worker_id}: {work_item.device_imei} "
                        f"✅ {result.journeys_created} journeys, "
                        f"{result.positions_processed} positions, "
                        f"{result.batches_processed} batches, "
                        f"{result.duration_sec:.1f}s"
                    )
                    if self.metrics:
                        self.metrics.devices_processed += 1
                        self.metrics.total_positions += result.positions_processed
                        self.metrics.total_journeys += result.journeys_created
                        self.metrics.total_legs += result.legs_created
                        self.metrics.total_stationaries += result.stationaries_created
                
                if self.metrics:
                    self.metrics.results.append(result)
                
                # Mark device as no longer processing
                async with self.processing_lock:
                    self.processing_devices.discard(work_item.device_imei)
                
                # Mark task complete
                self.work_queue.task_done()
                
            except asyncio.TimeoutError:
                # No work available, check if still running
                continue
            
            except Exception as e:
                logger.error(f"Worker {worker_id} error: {e}", exc_info=True)
                
                if work_item:
                    # Mark device as no longer processing
                    async with self.processing_lock:
                        self.processing_devices.discard(work_item.device_imei)
                    
                    # Record failure
                    if self.metrics:
                        self.metrics.devices_failed += 1
                        self.metrics.results.append(ProcessingResult(
                            device_imei=work_item.device_imei,
                            positions_processed=0,
                            journeys_created=0,
                            legs_created=0,
                            stationaries_created=0,
                            duration_sec=0,
                            error=str(e)
                        ))
                    
                    self.work_queue.task_done()
                
                # Back off on error
                await asyncio.sleep(5)
        
        logger.info(f"Worker {worker_id} stopped")
    
    def _process_device_batched(
        self,
        db: Session,
        device_imei: str,
        batch_size: int,
        max_batch_count: int
    ) -> ProcessingResult:
        """
        Process device in batches with incremental checkpointing.
        
        Key features:
        - Processes up to max_batch_count batches per sweep
        - Commits every checkpoint_interval positions
        - Graceful error handling (skip bad positions, continue)
        
        Returns:
            ProcessingResult with statistics
        """
        from app.services.trip_engine import TripEngine
        
        start_time = datetime.now(timezone.utc)
        
        total_journeys = 0
        total_legs = 0
        total_stationaries = 0
        total_positions = 0
        batches_processed = 0
        error_msg = None
        
        try:
            for batch_num in range(max_batch_count):
                try:
                    # CRITICAL: Create fresh TripEngine instance for each batch
                    # This ensures we load the updated watermark from engine_state
                    # after the previous batch committed. Without this, we reprocess
                    # the same data repeatedly because the old instance has stale state.
                    processor = TripEngine(db, device_imei)
                    
                    # Process one batch
                    stats = processor.process_positions(limit=batch_size)
                    
                    if stats['positions_processed'] == 0:
                        # No more data
                        break
                    
                    total_positions += stats['positions_processed']
                    total_journeys += stats['journeys_created']
                    total_legs += stats['legs_created']
                    total_stationaries += stats['stationaries_created']
                    batches_processed += 1
                    
                    # CRITICAL FIX (v2.1.23): Commit after EVERY batch
                    # Because we create fresh TripEngine per batch (af7d1ba fix), each instance
                    # must commit its state changes immediately so the next batch sees updated
                    # anchor_count, watermarks, etc. Without this, single-position batches from
                    # polling devices (TrackSolid) never accumulate anchor_count and can't create
                    # stationaries/journeys.
                    db.commit()
                    
                    # Checkpoint logging at intervals
                    if total_positions % self.checkpoint_interval == 0:
                        logger.debug(
                            f"{device_imei}: Checkpoint at {total_positions} positions"
                        )
                    
                    # Safety: Don't process too many batches in one sweep
                    if batches_processed >= max_batch_count:
                        logger.info(
                            f"{device_imei}: Reached max batch limit ({max_batch_count}), "
                            f"will resume in next sweep"
                        )
                        break
                
                except Exception as e:
                    # Log error but continue with next batch
                    logger.warning(
                        f"{device_imei}: Batch {batch_num} error: {e}, continuing..."
                    )
                    db.rollback()
                    
                    # If first batch fails, give up on this device
                    if batch_num == 0:
                        error_msg = str(e)
                        break
            
            # Final commit
            db.commit()
        
        except Exception as e:
            logger.error(f"{device_imei}: Processing failed: {e}", exc_info=True)
            error_msg = str(e)
            db.rollback()
        
        duration = (datetime.now(timezone.utc) - start_time).total_seconds()
        
        return ProcessingResult(
            device_imei=device_imei,
            positions_processed=total_positions,
            journeys_created=total_journeys,
            legs_created=total_legs,
            stationaries_created=total_stationaries,
            duration_sec=duration,
            error=error_msg,
            batches_processed=batches_processed
        )
    
    def get_metrics(self) -> Optional[WorkerPoolMetrics]:
        """Get current metrics."""
        if self.metrics:
            # Update sweep_end if still running
            if self.running:
                self.metrics.sweep_end = datetime.now(timezone.utc)
        return self.metrics


# ═══════════════════════════════════════════════════════════════════════════
# GLOBAL INSTANCE
# ═══════════════════════════════════════════════════════════════════════════

_worker_pool: Optional[TripEngineWorkerPool] = None
_worker_pool_task: Optional[asyncio.Task] = None


def get_worker_pool() -> Optional[TripEngineWorkerPool]:
    """Get global worker pool instance."""
    return _worker_pool


async def _worker_pool_loop(
    num_workers: int,
    scan_interval_sec: int = DEFAULT_QUEUE_SCAN_INTERVAL_SEC
):
    """
    Background task that manages the worker pool.
    
    Responsibilities:
    - Start worker pool on first run
    - Periodically scan for new work
    - Keep workers fed with devices to process
    """
    global _worker_pool
    
    from app.database import SessionLocal
    
    logger.info(f"🚀 Worker pool loop started ({num_workers} workers)")
    
    # Create worker pool
    _worker_pool = TripEngineWorkerPool(num_workers=num_workers)
    await _worker_pool.start()
    
    while True:
        try:
            # Scan for devices needing processing
            db = SessionLocal()
            try:
                enqueued = await _worker_pool.enqueue_work(db)
            finally:
                db.close()
            
            if enqueued == 0:
                logger.debug("No devices need processing")
            
            # Wait before next scan
            await asyncio.sleep(scan_interval_sec)
        
        except Exception as exc:
            logger.error(f"❌ Worker pool loop error: {exc}", exc_info=True)
            await asyncio.sleep(60)  # Back off on error


def start_worker_pool(num_workers: int = DEFAULT_NUM_WORKERS):
    """
    Start the worker pool background task.
    
    Args:
        num_workers: Number of concurrent workers (default: 5 for 1-core)
    """
    global _worker_pool_task
    
    if _worker_pool_task is not None:
        logger.warning("⚠️  Worker pool already running")
        return
    
    _worker_pool_task = asyncio.create_task(
        _worker_pool_loop(num_workers),
        name="worker-pool-manager"
    )
    logger.info(f"✅ Worker pool manager scheduled ({num_workers} workers)")


async def stop_worker_pool():
    """Stop the worker pool gracefully."""
    global _worker_pool, _worker_pool_task
    
    if _worker_pool:
        await _worker_pool.stop()
        _worker_pool = None
    
    if _worker_pool_task:
        _worker_pool_task.cancel()
        try:
            await _worker_pool_task
        except asyncio.CancelledError:
            pass
        _worker_pool_task = None
    
    logger.info("✅ Worker pool stopped")
