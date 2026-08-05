-- Fix Duplicate Journeys (UniqueViolation on ux_journey_device_start)
-- Finds duplicate (device_imei, started_at) pairs and keeps only the oldest journey

-- Step 1: Identify duplicates
SELECT 
    device_imei,
    started_at,
    COUNT(*) as duplicate_count,
    MIN(created_at) as oldest_created,
    MAX(created_at) as newest_created,
    ARRAY_AGG(id ORDER BY created_at) as journey_ids
FROM journeys
GROUP BY device_imei, started_at
HAVING COUNT(*) > 1
ORDER BY device_imei, started_at;

-- Step 2: For each duplicate, delete all except the oldest
-- (Run this only if you see duplicates above)
WITH duplicates AS (
    SELECT 
        device_imei,
        started_at,
        id,
        created_at,
        ROW_NUMBER() OVER (PARTITION BY device_imei, started_at ORDER BY created_at ASC) as rn
    FROM journeys
    WHERE (device_imei, started_at) IN (
        SELECT device_imei, started_at
        FROM journeys
        GROUP BY device_imei, started_at
        HAVING COUNT(*) > 1
    )
)
DELETE FROM journeys
WHERE id IN (
    SELECT id FROM duplicates WHERE rn > 1
);

-- Step 3: Verify no duplicates remain
SELECT 
    device_imei,
    started_at,
    COUNT(*) as count
FROM journeys
GROUP BY device_imei, started_at
HAVING COUNT(*) > 1;
-- Should return 0 rows
