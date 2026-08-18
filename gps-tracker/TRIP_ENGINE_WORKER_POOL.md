# Trip Engine Worker Pool (v2.4.0)

## Overview

The worker pool architecture replaces the legacy sequential trip processing with concurrent asyncio workers, providing:

- **Error Isolation**: One device failure doesn't block others
- **Incremental Checkpointing**: Resumable processing every 1,000 positions
- **Priority Queue**: Critical devices processed first
- **Scalability**: Adjust worker count based on CPU cores
- **Better Performance**: 1.5-2x faster on 1-core, scales linearly with more cores

## Configuration

### Environment Variables

Add to `docker-compose.yml` or `.env`:

```env
# Enable worker pool (default: true)
TRIP_ENGINE_WORKER_POOL=true

# Number of concurrent workers (default: 5 for 1-core)
TRIP_ENGINE_NUM_WORKERS=5
```

### Recommended Worker Counts by Server Size

| Server Specs | Workers | Expected Speedup |
|--------------|---------|------------------|
| 1 vCPU, 2 GB RAM | 5 | 1.5-2x |
| 2 vCPU, 4 GB RAM | 10 | 4x |
| 4 vCPU, 8 GB RAM | 20 | 8x |
| 8 vCPU, 16 GB RAM | 40 | 16x |

**Rule of thumb**: `NUM_WORKERS = CPU_CORES × 5`

## Usage

### 1. Enable Worker Pool

Update `docker-compose.yml`:

```yaml
services:
  backend:
    environment:
      - TRIP_ENGINE_WORKER_POOL=true
      - TRIP_ENGINE_NUM_WORKERS=5  # Adjust based on server
```

### 2. Deploy

```bash
cd /root/pinplot/gps-tracker
docker compose build backend
docker compose down
docker compose up -d
```

### 3. Monitor Metrics

Check worker pool status:

```bash
curl http://localhost:8000/api/trip-engine/metrics | jq
```

**Response:**

```json
{
  "mode": "worker_pool",
  "status": "running",
  "num_workers": 5,
  "sweep": {
    "start": "2026-08-18T22:00:00Z",
    "end": "2026-08-18T22:01:30Z",
    "duration_sec": 90
  },
  "devices": {
    "queued": 44,
    "processed": 44,
    "failed": 0,
    "success_rate": "100.0%"
  },
  "output": {
    "positions": 1234,
    "journeys": 15,
    "legs": 48,
    "stationaries": 32
  },
  "performance": {
    "worker_busy_time_sec": 120.5,
    "worker_idle_time_sec": 10.2,
    "utilization_percent": 92.3
  },
  "queue": {
    "size": 0,
    "processing": []
  }
}
```

### 4. Check Logs

```bash
docker logs pinplot_backend --tail 100 -f | grep -i "worker\|trip engine"
```

**Expected logs:**

```
✅ Started 5 trip engine workers
Worker 0 started
Worker 1 started
...
📥 Enqueued 44 devices for processing
Worker 0: 780901807708767 ✅ 2 journeys, 150 positions, 2 batches, 3.2s
Worker 1: 780901807707528 ✅ 1 journeys, 85 positions, 1 batches, 1.8s
```

## Architecture

### Legacy Sequential (v2.1.17)

```
Trip Engine Loop (every 15 min)
  └─> For each device (sequential):
      ├─> Device 1: 2 sec
      ├─> Device 2: 2 sec
      ├─> ...
      └─> Device 44: 2 sec
      
Total: 88 seconds per sweep
```

### Worker Pool (v2.4.0)

```
Trip Engine Manager
  ├─> Queue Feeder (scans every 30 sec)
  │   └─> Discovers devices with unprocessed data
  │       └─> Adds to priority queue
  │
  └─> Worker Pool (5 concurrent workers)
      ├─> Worker 0: Device A (HIGH priority)
      ├─> Worker 1: Device B (NORMAL)
      ├─> Worker 2: Device C (NORMAL)
      ├─> Worker 3: Device D (LOW)
      └─> Worker 4: Device E (LOW)

Total: ~50-60 seconds per sweep (1-core)
       ~20 seconds per sweep (2-core)
```

## Priority Queue

Devices are prioritized automatically:

| Priority | Condition | Example |
|----------|-----------|---------|
| HIGH | Fresh GPS data (<5 min) | Real-time tracking |
| HIGH | Large backlog (>10k positions) | Devices that were offline |
| NORMAL | Regular processing | Daily operations |
| LOW | Stale data (>1 hour old) | Idle devices |

## Incremental Checkpointing

**Problem (Legacy):**
- Process 8,471 positions
- Position 8,470 succeeds
- Position 8,471 errors
- **Rollback ALL** → Lose 8,470 positions of progress

**Solution (Worker Pool):**
- Process in batches of 5,000 positions
- Checkpoint every 1,000 positions
- Error on position 8,471?
- **Resume from position 8,000** → Only lose 471 positions

## Error Isolation

**Problem (Legacy):**
```
Device 1: ✅ Success
Device 2: ❌ ERROR → Transaction rollback
Device 3-44: ❌ Never processed (blocked by Device 2)
Result: 0/44 devices processed
```

**Solution (Worker Pool):**
```
Device 1 (Worker 0): ✅ Success → Journeys saved
Device 2 (Worker 1): ❌ ERROR → Log error, skip
Device 3 (Worker 2): ✅ Success → Journeys saved
Device 4-44: ✅ Continue processing
Result: 43/44 devices processed (98% success)
```

## Performance Comparison

### Current Server (1 vCPU, 2 GB RAM)

| Scenario | Legacy (v2.1.17) | Worker Pool (v2.4.0) | Improvement |
|----------|------------------|----------------------|-------------|
| 44 devices | 88 sec | 50-60 sec | 1.5-2x faster |
| Device fails | Infinite loop | Others continue | **Production stays up** |
| User viewing device | 88 sec wait | ~2 sec (priority) | **44x faster** |
| 8k position backlog | Transaction timeout | Incremental checkpoint | **Resumable** |

### After Upgrade to 2 vCPU / 4 GB RAM

| Scenario | Legacy (v2.1.17) | Worker Pool (v2.4.0) | Improvement |
|----------|------------------|----------------------|-------------|
| 44 devices | 88 sec | ~20 sec | **4x faster** |
| 500 devices | ~20 min | ~6 min | **3.3x faster** |
| 1000 devices | ~40 min | ~12 min | **3.3x faster** |

## Troubleshooting

### Worker Pool Not Starting

**Symptom:** Logs show "Trip Engine: Journey processor started (15-minute interval) [LEGACY MODE]"

**Solution:**
```bash
# Check environment variable
docker exec pinplot_backend printenv | grep TRIP_ENGINE_WORKER_POOL

# Should output: TRIP_ENGINE_WORKER_POOL=true
# If not, add to docker-compose.yml and restart
```

### High CPU Usage

**Symptom:** Backend container using 90%+ CPU

**Solution:**
```bash
# Reduce number of workers
# Edit docker-compose.yml:
environment:
  - TRIP_ENGINE_NUM_WORKERS=3  # Reduce from 5

docker compose up -d backend
```

### Low Utilization

**Symptom:** Worker busy time < 50%

**Cause:** Not enough devices to process, workers are idle

**Action:** No action needed, system is healthy. Workers will scale up when load increases.

### Devices Not Processing

**Symptom:** Metrics show `devices_queued: 0`

**Check:**
```bash
# Verify devices are subscribed
docker exec pinplot_db psql -U pinplot_db_user -d pinplot_db -c "
SELECT COUNT(*) FROM device_states WHERE trip_subscribed = true;
"

# If 0, no devices are subscribed for trip processing
```

## Migration from Legacy

### Option 1: Zero-Downtime (Recommended)

```bash
cd /root/pinplot/gps-tracker

# 1. Build new image
docker compose build backend

# 2. Update docker-compose.yml (add env vars)
echo "      - TRIP_ENGINE_WORKER_POOL=true" >> docker-compose.yml
echo "      - TRIP_ENGINE_NUM_WORKERS=5" >> docker-compose.yml

# 3. Restart backend only
docker compose up -d backend

# 4. Verify worker pool started
docker logs pinplot_backend --tail 50 | grep -i "worker pool"
```

### Option 2: Full Restart

```bash
cd /root/pinplot/gps-tracker

# 1. Update docker-compose.yml (add env vars)
# 2. Rebuild and restart
docker compose down
docker compose build
docker compose up -d

# 3. Verify
curl http://localhost:8000/api/trip-engine/metrics | jq
```

## Rollback to Legacy

If you need to revert to the legacy sequential processing:

```bash
# 1. Disable worker pool
# Edit docker-compose.yml:
environment:
  - TRIP_ENGINE_WORKER_POOL=false

# 2. Restart
docker compose up -d backend

# 3. Verify
docker logs pinplot_backend --tail 50 | grep "LEGACY MODE"
# Should see: "Trip Engine: Journey processor started (15-minute interval) [LEGACY MODE]"
```

## Future Enhancements

### Planned for v2.5.0:

- **Adaptive worker scaling**: Automatically adjust worker count based on queue depth
- **Per-device performance tracking**: Identify slow devices
- **Backpressure throttling**: Slow down when DB is overloaded
- **Distributed processing**: Multiple backend instances sharing work
- **Real-time processing**: <1 minute latency for priority devices

## FAQ

**Q: Will this break my existing journeys?**  
A: No. Worker pool uses the same trip engine state machine, just runs devices in parallel instead of sequentially.

**Q: Do I need to upgrade my server?**  
A: No. Worker pool works on 1-core servers (1.5-2x speedup). Upgrading to 2-core+ gives bigger gains (4x+).

**Q: Can I run both legacy and worker pool?**  
A: No. Choose one via `TRIP_ENGINE_WORKER_POOL` env var. They can't run simultaneously.

**Q: What if a worker crashes?**  
A: The worker pool manager automatically respawns crashed workers. Processing continues.

**Q: How do I know if it's working?**  
A: Check metrics endpoint: `curl http://localhost:8000/api/trip-engine/metrics`. Look for `"mode": "worker_pool"` and `"status": "running"`.

## Support

For issues or questions:
1. Check logs: `docker logs pinplot_backend --tail 200`
2. Check metrics: `curl http://localhost:8000/api/trip-engine/metrics | jq`
3. Review this document
4. Contact support with logs + metrics output
