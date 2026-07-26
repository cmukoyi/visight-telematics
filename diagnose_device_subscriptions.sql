-- Diagnostic SQL to find why no devices show for usergroup_id = 29b6677a-f4b7-4a23-bffd-fe208049ea84

-- Step 1: Check if user group exists
SELECT 'User Group:' as check_type, id, name, email_domain 
FROM user_groups 
WHERE id = '29b6677a-f4b7-4a23-bffd-fe208049ea84';

-- Step 2: Check portal_users in this group
SELECT 'Portal Users:' as check_type, email, role, is_active
FROM portal_users
WHERE usergroup_id = '29b6677a-f4b7-4a23-bffd-fe208049ea84';

-- Step 3: Check if users table has matching emails
SELECT 'Matched Users:' as check_type, u.id, u.email
FROM users u
INNER JOIN portal_users pu ON u.email = pu.email
WHERE pu.usergroup_id = '29b6677a-f4b7-4a23-bffd-fe208049ea84';

-- Step 4: Check tags owned by those users
SELECT 'Tags (with IMEI):' as check_type, 
       bt.id, bt.imei, bt.device_name, bt.tag_type, bt.is_active, bt.user_id
FROM ble_tags bt
INNER JOIN users u ON bt.user_id = u.id
INNER JOIN portal_users pu ON u.email = pu.email
WHERE pu.usergroup_id = '29b6677a-f4b7-4a23-bffd-fe208049ea84'
  AND bt.imei IS NOT NULL
  AND bt.is_active = true;

-- Step 5: Check device_state for those tags
SELECT 'Device States:' as check_type,
       ds.device_imei, ds.trip_subscribed, ds.last_position_ts, ds.last_tracklist_pull_at
FROM device_state ds
WHERE ds.device_imei IN (
    SELECT bt.imei
    FROM ble_tags bt
    INNER JOIN users u ON bt.user_id = u.id
    INNER JOIN portal_users pu ON u.email = pu.email
    WHERE pu.usergroup_id = '29b6677a-f4b7-4a23-bffd-fe208049ea84'
      AND bt.imei IS NOT NULL
      AND bt.is_active = true
);

-- Step 6: Check ALL tags for this user group (including without IMEIs)
SELECT 'All Tags in Group:' as check_type,
       bt.id, bt.imei, bt.mac_address, bt.device_name, bt.tag_type, bt.is_active
FROM ble_tags bt
INNER JOIN users u ON bt.user_id = u.id
INNER JOIN portal_users pu ON u.email = pu.email
WHERE pu.usergroup_id = '29b6677a-f4b7-4a23-bffd-fe208049ea84'
  AND bt.is_active = true
LIMIT 20;

-- Step 7: Check if there are ANY GPS tags with trip subscriptions (regardless of group)
SELECT 'Sample Subscribed Devices (any group):' as check_type,
       bt.imei, bt.device_name, ds.trip_subscribed, u.email
FROM ble_tags bt
INNER JOIN device_state ds ON bt.imei = ds.device_imei
INNER JOIN users u ON bt.user_id = u.id
WHERE bt.imei IS NOT NULL
  AND bt.is_active = true
  AND ds.trip_subscribed = true
LIMIT 5;
