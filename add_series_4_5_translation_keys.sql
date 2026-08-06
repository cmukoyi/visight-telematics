-- Add Series 4 and Series 5 translation keys to support Hubble integration
-- Run this on production after deploying Series 5 code changes
-- 
-- Usage:
--   docker exec pinplot_db psql -U pinplot_db_user -d pinplot_db -f /path/to/this/file.sql
--
-- Or copy-paste into psql:
--   docker exec -it pinplot_db psql -U pinplot_db_user -d pinplot_db

-- Insert Series 4 translation key if not exists
INSERT INTO translation_keys (key, category, default_text, context)
SELECT 'general.series_4', 'general', 'Series 4', 'Tag type label for BLE Indoor (DX-Smart) tags'
WHERE NOT EXISTS (
    SELECT 1 FROM translation_keys WHERE key = 'general.series_4'
);

-- Insert Series 5 translation key if not exists
INSERT INTO translation_keys (key, category, default_text, context)
SELECT 'general.series_5', 'general', 'Series 5', 'Tag type label for Hubble Platform BLE tags'
WHERE NOT EXISTS (
    SELECT 1 FROM translation_keys WHERE key = 'general.series_5'
);

-- Verify keys were added
SELECT key, category, default_text, context 
FROM translation_keys 
WHERE key IN ('general.series_4', 'general.series_5')
ORDER BY key;
