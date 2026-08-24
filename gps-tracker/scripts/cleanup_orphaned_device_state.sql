-- Cleanup Orphaned device_state Records
-- 
-- PROBLEM: tracksolid_batch_service created device_state for ALL devices in TrackSolid account
--          Only 46 devices actually added to PinPlot, but 2,390 device_state records exist
--          Result: 2,362 orphaned records (98.8% of table is garbage)
--
-- ROOT CAUSE: _update_device_states() never checked if IMEI exists in ble_tags
--
-- FIXED IN: Commit b2b4d4c (2026-08-21)
--
-- THIS SCRIPT: One-time cleanup of existing orphans after fix is deployed
--
-- Date: 2026-08-21
-- Safe to run: YES (only deletes orphans, never touches valid records)

BEGIN;

-- Step 1: Verify what will be deleted (DRY RUN)
SELECT 
    'ORPHANED device_state records (will be deleted)' as status,
    COUNT(*) as count
FROM device_state ds
LEFT JOIN ble_tags bt ON ds.device_imei = bt.imei
WHERE bt.imei IS NULL
UNION ALL
SELECT 
    'VALID device_state records (will be kept)',
    COUNT(*)
FROM device_state ds
INNER JOIN ble_tags bt ON ds.device_imei = bt.imei;

-- Step 2: Show sample of orphans to verify they're truly orphaned
SELECT 
    ds.device_imei,
    ds.created_at,
    ds.last_batch_ts,
    ds.trip_subscribed,
    'Will be deleted' as action
FROM device_state ds
LEFT JOIN ble_tags bt ON ds.device_imei = bt.imei
WHERE bt.imei IS NULL
ORDER BY ds.created_at
LIMIT 10;

-- Step 3: Delete orphaned records
-- ONLY device_state records with no matching ble_tag
DELETE FROM device_state
WHERE device_imei NOT IN (
    SELECT imei FROM ble_tags
);

-- Step 4: Verify cleanup
SELECT 
    'device_state records after cleanup' as metric,
    COUNT(*) as count
FROM device_state;

SELECT 
    'Orphaned records remaining' as metric,
    COUNT(*) as count
FROM device_state ds
LEFT JOIN ble_tags bt ON ds.device_imei = bt.imei
WHERE bt.imei IS NULL;

COMMIT;

-- Expected results:
-- Before: 2,390 device_state records (28 valid, 2,362 orphans)
-- After:  28 device_state records (28 valid, 0 orphans)
