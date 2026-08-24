-- One-time recovery for devices stuck in late-arrival rewind loop
-- v2.1.19 D1-FIX
-- Date: 2026-08-19
-- Run AFTER deploying v2.1.19 and applying add_reconciliation_watermark.sql

-- List of 8 devices stuck as of 19 Aug 07:41 (from trip-engine-watermark-rewind-loop-fix.md)
-- These devices have current engine.Updated timestamp but frozen last_processed_at

BEGIN;

-- 1. Set last_reconciled_received_at to current max received_at for each device
--    This marks all existing old buffered points as "already seen"
UPDATE engine_state es
SET last_reconciled_received_at = (
    SELECT MAX(dp.received_at)
    FROM device_positions dp
    WHERE dp.device_imei = es.device_imei
)
WHERE device_imei IN (
    '780901807708767',
    '780901807707502',
    '780901807707363',
    '780901807707528',
    '780901807705907',
    '780901807706650',
    '780901807706664',
    '780901807706631'
);

-- 2. Advance last_processed_at to current position timestamp
--    This allows forward processing to resume from where positions actually are
UPDATE engine_state es
SET last_processed_at = (
    SELECT MAX(dp.observed_at)
    FROM device_positions dp
    WHERE dp.device_imei = es.device_imei
)
WHERE device_imei IN (
    '780901807708767',
    '780901807707502',
    '780901807707363',
    '780901807707528',
    '780901807705907',
    '780901807706650',
    '780901807706664',
    '780901807706631'
);

-- 3. Also advance last_received_at to match
UPDATE engine_state es
SET last_received_at = (
    SELECT MAX(dp.received_at)
    FROM device_positions dp
    WHERE dp.device_imei = es.device_imei
)
WHERE device_imei IN (
    '780901807708767',
    '780901807707502',
    '780901807707363',
    '780901807707528',
    '780901807705907',
    '780901807706650',
    '780901807706664',
    '780901807706631'
);

-- Verify recovery
SELECT 
    es.device_imei,
    es.last_processed_at,
    es.last_received_at,
    es.last_reconciled_received_at,
    (SELECT MAX(dp.observed_at) FROM device_positions dp WHERE dp.device_imei = es.device_imei) as latest_position,
    (SELECT COUNT(*) FROM device_positions dp 
     WHERE dp.device_imei = es.device_imei 
       AND dp.received_at > es.last_reconciled_received_at) as unprocessed_after_recovery
FROM engine_state es
WHERE device_imei IN (
    '780901807708767',
    '780901807707502',
    '780901807707363',
    '780901807707528',
    '780901807705907',
    '780901807706650',
    '780901807706664',
    '780901807706631'
)
ORDER BY device_imei;

COMMIT;

-- Expected result: unprocessed_after_recovery should be 0 for all devices
-- Worker pool will process any NEW positions that arrive after this recovery
