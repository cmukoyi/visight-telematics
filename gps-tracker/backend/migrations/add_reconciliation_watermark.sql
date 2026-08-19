-- Migration: Add reconciliation watermark to prevent late-arrival rewind loop
-- v2.1.19 D1-FIX
-- Date: 2026-08-19

-- Add new column to track ingestion-time high-water mark
ALTER TABLE engine_state 
ADD COLUMN last_reconciled_received_at TIMESTAMP WITH TIME ZONE;

-- Initialize for existing devices: set to current last_received_at
-- This marks all existing buffered points as "already seen"
UPDATE engine_state
SET last_reconciled_received_at = last_received_at
WHERE last_received_at IS NOT NULL;

-- For devices with no last_received_at, initialize to epoch (will be set on next processing)
UPDATE engine_state
SET last_reconciled_received_at = '1970-01-01 00:00:00+00'::timestamp with time zone
WHERE last_received_at IS NULL;

-- Verify migration
SELECT 
    device_imei,
    last_processed_at,
    last_received_at,
    last_reconciled_received_at,
    CASE 
        WHEN last_reconciled_received_at IS NULL THEN '❌ NULL'
        WHEN last_reconciled_received_at = last_received_at THEN '✅ Initialized'
        ELSE '⚠️ Mismatch'
    END as status
FROM engine_state
ORDER BY device_imei
LIMIT 20;
