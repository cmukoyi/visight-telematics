# Deploy Async Job Worker - Trip Engine v2.2

## Problem
- Async jobs stuck in "pending" status forever
- Job worker service not running on PinPlotServer

## Solution
Deploy the worker container that processes batch backfill/reprocess jobs.

---

## Deployment Steps

### 1. SSH to Server
```bash
ssh PinPlotServer
cd /opt/PinPlot/gps-tracker
```

### 2. Pull Latest Code
```bash
git pull origin main
```

### 3. Check Current Services
```bash
docker compose ps
```

Expected output (worker is MISSING):
```
NAME                IMAGE                        STATUS
pinplot_backend     gps-tracker-backend         Up
pinplot_customer    gps-tracker-customer        Up
pinplot_db          postgres:15-alpine          Up (healthy)
pinplot_admin       gps-tracker-admin-portal    Up
```

### 4. Build Worker Image
```bash
# Worker uses same backend image, just different command
docker compose build worker
```

### 5. Start Worker Service
```bash
docker compose up -d worker
```

### 6. Verify Worker is Running
```bash
# Check container status
docker compose ps worker

# Check worker logs (should show "Background job worker started")
docker compose logs -f worker --tail 50
```

Expected log output:
```
INFO:app.services.async_job_worker:🚀 Background job worker started (interval: 5s)
INFO:app.services.async_job_worker:📊 Checking for pending jobs...
```

### 7. Test with Existing Stuck Job

The stuck job should start processing automatically:

```bash
# Watch job status
watch -n 2 'curl -s https://pinplot.me/api/admin/jobs | jq'
```

Expected change:
```json
{
  "status": "pending",  // BEFORE
  "status": "running",  // Worker picked it up
  "status": "completed" // After processing
}
```

---

## Worker Container Details

**Service Name:** `worker`
**Container Name:** `pinplot_worker`
**Command:** `python -m app.services.async_job_worker`
**Restart Policy:** `unless-stopped`
**Polling Interval:** 5 seconds

**What it does:**
- Polls `async_jobs` table every 5 seconds
- Picks up jobs with `status='pending'`
- Executes batch backfill or batch reprocess
- Updates job status → running → completed/failed

---

## Troubleshooting

### Worker Fails to Start

**Check logs:**
```bash
docker compose logs worker --tail 100
```

**Common issues:**
- Database connection failed → Check .env file
- Import errors → Rebuild backend image
- Permission issues → Check file ownership

### Worker Running but Jobs Not Processing

**Check worker logs:**
```bash
docker compose logs -f worker
```

**Verify database connection:**
```bash
docker compose exec worker python -c "from app.database import SessionLocal; db = SessionLocal(); print('DB connected')"
```

**Manually trigger job (for testing):**
```bash
# Set job status back to pending
docker compose exec db psql -U pinplot_db_user pinplot_db -c \
  "UPDATE async_jobs SET status='pending', started_at=NULL WHERE id='927d0d51-4352-43b2-bf34-466fe5e4659b';"

# Worker should pick it up in next 5 seconds
docker compose logs -f worker
```

---

## Correct Reprocess URLs

### Single Device Reprocess (Synchronous)
```bash
# Runs immediately, returns result
curl -X POST https://pinplot.me/api/admin/trips/reprocess \
  -H "Content-Type: application/json" \
  -d '{
    "device_imei": "475",
    "start_date": "2026-07-17",
    "end_date": "2026-07-18"
  }'
```

### Batch Reprocess (Asynchronous - uses worker)
```bash
# Creates async job, worker processes it
curl -X POST https://pinplot.me/api/admin/jobs/batch-reprocess \
  -H "Content-Type: application/json" \
  -d '{
    "tenant_id": "scope-technology",
    "start_date": "2026-07-17",
    "end_date": "2026-07-18"
  }'
```

### Check Job Status
```bash
curl https://pinplot.me/api/admin/jobs?limit=10
```

---

## Success Criteria

✅ Worker container running
✅ Worker logs show polling activity
✅ Stuck job (927d0d51) completes or fails (no longer "pending")
✅ New batch jobs get processed

---

## Rollback (if needed)

Stop worker:
```bash
docker compose stop worker
docker compose rm -f worker
```

This won't affect other services (backend, database, admin portal continue running).

---

## Notes

- Worker shares same backend image (no separate build needed after first deploy)
- Worker and backend can scale independently
- Only ONE worker should run (prevents duplicate job processing)
- Worker is stateless (safe to restart anytime)
- Job status transitions: pending → running → completed/failed
