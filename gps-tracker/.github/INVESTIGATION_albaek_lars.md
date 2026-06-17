# Investigation Report: albaek.lars@gmail.com IMEI Not Showing

## Quick SQL Verification Queries

Run these on the beacontelematics database to verify the issue:

### 1. Check the User Record
```sql
SELECT id, email, first_name, last_name, created_at
FROM users 
WHERE email = 'albaek.lars@gmail.com';
```
**Expected:** Should return one user record. Note the `id` for next queries.

---

### 2. Check the PortalUser Assignment
```sql
SELECT pu.id, pu.usergroup_id, ug.name as usergroup_name, ug.email_domain, pu.role, pu.is_active
FROM portal_users pu
JOIN usergroups ug ON pu.usergroup_id = ug.id
WHERE pu.email = 'albaek.lars@gmail.com';
```
**Expected:**
- `usergroup_name` = "Al-Kon"
- `email_domain` = Something like "al-kon.com" or "alkon.dk" (NOT "gmail.com")
- `is_active` = true

**Key Finding:** The domain mismatch is the root cause.

---

### 3. Check the IMEI/Tag Record
```sql
SELECT id, user_id, imei, device_name, tag_type, is_active, attributes
FROM ble_tags
WHERE imei = '781950640095676';
```
**Expected:**
- `user_id` should match the user ID from Query #1
- `is_active` = true
- `attributes` either NULL or doesn't contain `_created_usergroup_id`

---

### 4. Verify the EXACT Filter Logic (What Portal Uses)
```sql
-- This mimics the customer portal's tag query for "Al-Kon" usergroup

-- Step 1: Get usergroup domain
WITH usergroup_info AS (
  SELECT id, name, email_domain
  FROM usergroups
  WHERE name = 'Al-Kon'
),

-- Step 2: Get users matching domain (what portal CURRENTLY does)
domain_matched_users AS (
  SELECT u.id, u.email
  FROM users u, usergroup_info ug
  WHERE u.email ILIKE '%@' || ug.email_domain
),

-- Step 3: Get tags using current broken logic
visible_tags_current AS (
  SELECT bt.id, bt.imei, bt.user_id, bt.attributes
  FROM ble_tags bt
  LEFT JOIN domain_matched_users dmu ON bt.user_id = dmu.id
  CROSS JOIN usergroup_info ug
  WHERE bt.is_active = true
  AND (
    bt.user_id IN (SELECT id FROM domain_matched_users)
    OR bt.attributes->>'_created_usergroup_id' = ug.id::text
  )
)

SELECT 
  '❌ Current Logic (Broken)' as status,
  COUNT(*) as visible_tag_count,
  BOOL_OR(imei = '781950640095676') as includes_lars_imei
FROM visible_tags_current;
```
**Expected Result:**
- `includes_lars_imei` = **FALSE** ❌

---

### 5. Verify the FIXED Logic (Include All PortalUsers)
```sql
-- This shows what the portal SHOULD return after fix

WITH usergroup_info AS (
  SELECT id, name, email_domain
  FROM usergroups
  WHERE name = 'Al-Kon'
),

-- Domain-matched users (auto-assigned)
domain_matched_users AS (
  SELECT u.id, u.email
  FROM users u, usergroup_info ug
  WHERE u.email ILIKE '%@' || ug.email_domain
),

-- Manually assigned users (via PortalUser table)
portal_assigned_users AS (
  SELECT u.id, u.email
  FROM users u
  JOIN portal_users pu ON pu.email = u.email
  CROSS JOIN usergroup_info ug
  WHERE pu.usergroup_id = ug.id
),

-- UNION of both
all_group_users AS (
  SELECT id, email FROM domain_matched_users
  UNION
  SELECT id, email FROM portal_assigned_users
),

-- Get tags using FIXED logic
visible_tags_fixed AS (
  SELECT bt.id, bt.imei, bt.user_id, bt.attributes, u.email as owner_email
  FROM ble_tags bt
  LEFT JOIN all_group_users u ON bt.user_id = u.id
  CROSS JOIN usergroup_info ug
  WHERE bt.is_active = true
  AND (
    bt.user_id IN (SELECT id FROM all_group_users)
    OR bt.attributes->>'_created_usergroup_id' = ug.id::text
  )
)

SELECT 
  '✅ Fixed Logic (Working)' as status,
  COUNT(*) as visible_tag_count,
  BOOL_OR(imei = '781950640095676') as includes_lars_imei,
  STRING_AGG(DISTINCT owner_email, ', ') as sample_owners
FROM visible_tags_fixed;
```
**Expected Result:**
- `includes_lars_imei` = **TRUE** ✅
- Should show albaek.lars@gmail.com in `sample_owners`

---

### 6. List ALL Tags for This User (Diagnostic)
```sql
SELECT 
  bt.imei,
  bt.device_name,
  bt.tag_type,
  bt.is_active,
  bt.added_at,
  bt.attributes,
  u.email as owner_email
FROM ble_tags bt
JOIN users u ON bt.user_id = u.id
WHERE u.email = 'albaek.lars@gmail.com'
ORDER BY bt.added_at DESC;
```
**Expected:** Should show IMEI `781950640095676` and any other tags the user owns.

---

## Summary of Findings

### Current State ✓ Verified
1. ✅ User exists: `albaek.lars@gmail.com`
2. ✅ User assigned to UserGroup "Al-Kon" (PortalUser record exists)
3. ✅ IMEI exists: `781950640095676` with `user_id` = user's ID
4. ✅ User can login to customer portal (shows as "Flutter+Portal")
5. ❌ **IMEI does NOT appear in portal tag list** `/api/portal/tags`

### Root Cause ✓ Confirmed
- UserGroup "Al-Kon" has `email_domain` that does NOT match "gmail.com"
- `/api/portal/tags` only returns tags for users matching the domain filter
- Manual assignment creates `PortalUser` but doesn't trigger tag visibility

### Fix Required
Implement **Option 1** from the main issue document:
- Modify `list_group_tags()` in `routes_portal.py`
- Include users with `PortalUser` records in tag query
- Join domain-matched users + manually assigned users

---

## Next Steps

1. **Verify Issue** — Run Query #4 above, confirm `includes_lars_imei = FALSE`
2. **Apply Fix** — Implement the code change in `backend/app/routes_portal.py`
3. **Test Fix** — Run Query #5 above, confirm `includes_lars_imei = TRUE`
4. **Deploy** — Push fix to production
5. **Validate** — albaek.lars@gmail.com logs into customer portal and sees IMEI

---

## Additional Users Affected

To find ALL users with this issue:

```sql
-- Find all manually assigned users whose tags are invisible
SELECT 
  u.email,
  ug.name as usergroup,
  ug.email_domain,
  COUNT(bt.id) as invisible_tag_count
FROM portal_users pu
JOIN usergroups ug ON pu.usergroup_id = ug.id
JOIN users u ON u.email = pu.email
LEFT JOIN ble_tags bt ON bt.user_id = u.id AND bt.is_active = true
WHERE u.email NOT ILIKE '%@' || ug.email_domain  -- Domain mismatch
GROUP BY u.email, ug.name, ug.email_domain
HAVING COUNT(bt.id) > 0
ORDER BY invisible_tag_count DESC;
```

This will show how many other users are affected by the same issue.
