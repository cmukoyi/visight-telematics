-- Fix overlap violations caused by v2.3.0 DESC bug
-- This deletes ALL journeys from July 14 - Aug 2 and resets watermarks
-- so worker pool can reprocess cleanly without overlap violations

BEGIN;

-- 1. Find ALL devices with journeys during v2.3.0 broken period
CREATE TEMP TABLE affected_devices AS
SELECT DISTINCT device_imei 
FROM journeys 
WHERE started_at >= '2026-07-14' 
  AND started_at <= '2026-08-02';

-- Show what we're about to delete
SELECT 
    '🗑️  BEFORE CLEANUP' as status,
    device_imei,
    COUNT(*) as journey_count,
    MIN(started_at) as earliest,
    MAX(ended_at) as latest
FROM journeys
WHERE device_imei IN (SELECT device_imei FROM affected_devices)
  AND started_at >= '2026-07-14'
GROUP BY device_imei
ORDER BY journey_count DESC;

-- 2. Delete ALL journeys from v2.3.0 period
-- (CASCADE will handle legs and stationaries)
DELETE FROM journeys
WHERE device_imei IN (SELECT device_imei FROM affected_devices)
  AND started_at >= '2026-07-14';

-- Get the row count
SELECT '✅ DELETED ' || COUNT(*) || ' journeys' as result
FROM journeys
WHERE FALSE; -- This is just to show the format, actual count was displayed by DELETE

-- 3. Reset engine_state watermarks to July 13 (before v2.3.0 ran)
UPDATE engine_state
SET 
    last_processed_at = '2026-07-13 23:59:59',
    last_received_at = '2026-07-13 23:59:59',
    current_state = 'STATIONARY'
WHERE device_imei IN (SELECT device_imei FROM affected_devices);

-- 4. Show final state - worker pool will process these
SELECT 
    '📊 AFTER CLEANUP' as status,
    device_imei,
    current_state,
    last_processed_at,
    last_received_at,
    (SELECT COUNT(*) 
     FROM device_positions dp 
     WHERE dp.device_imei = es.device_imei 
       AND dp.received_at > es.last_received_at
    ) as unprocessed_positions
FROM engine_state es
WHERE device_imei IN (SELECT device_imei FROM affected_devices)
ORDER BY unprocessed_positions DESC;

COMMIT;

-- Summary
SELECT 
    '🎯 READY FOR WORKER POOL' as status,
    COUNT(DISTINCT device_imei) as devices_cleaned,
    SUM(unprocessed) as total_positions_to_reprocess
FROM (
    SELECT 
        es.device_imei,
        (SELECT COUNT(*) 
         FROM device_positions dp 
         WHERE dp.device_imei = es.device_imei 
           AND dp.received_at > es.last_received_at
        ) as unprocessed
    FROM engine_state es
    WHERE device_imei IN (SELECT device_imei FROM affected_devices)
) subquery;
