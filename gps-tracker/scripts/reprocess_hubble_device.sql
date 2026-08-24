-- Reprocess Hubble device 6796e753-707d-40ce-8ce1-8315e19b71ff with verbose logging
-- This will force the trip engine to reprocess today's positions
-- Verbose logs will reveal why orphan stationaries were created without a journey

-- Step 1: Delete orphan stationaries (journey_id=NULL) from today
DELETE FROM stationaries
WHERE device_imei = '6796e753-707d-40ce-8ce1-8315e19b71ff'
  AND started_at >= '2026-08-19 14:57:00'
  AND journey_id IS NULL;

-- Step 2: Reset engine watermarks to reprocess today's positions
UPDATE engine_state
SET 
    last_processed_at = '2026-08-19 14:57:00',
    last_received_at = '2026-08-19 14:57:00',
    last_reconciled_received_at = '2026-08-19 14:57:00'
WHERE device_imei = '6796e753-707d-40ce-8ce1-8315e19b71ff';

-- Step 3: Clear device_positions leg_id/stationary_id for today (so they get reassigned)
UPDATE device_positions
SET 
    leg_id = NULL,
    stationary_id = NULL
WHERE device_imei = '6796e753-707d-40ce-8ce1-8315e19b71ff'
  AND observed_at >= '2026-08-19 14:57:00';

-- Verification: Check what we're about to reprocess
SELECT 
    COUNT(*) as positions_to_reprocess,
    MIN(observed_at) as earliest,
    MAX(observed_at) as latest
FROM device_positions
WHERE device_imei = '6796e753-707d-40ce-8ce1-8315e19b71ff'
  AND observed_at >= '2026-08-19 14:57:00';
