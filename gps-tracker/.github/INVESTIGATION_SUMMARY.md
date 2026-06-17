# Investigation Complete: Flutter User IMEI Visibility Issue

## 📋 Issue Summary

**User:** albaek.lars@gmail.com  
**IMEI:** 781950640095676  
**UserGroup:** Al-Kon  
**Problem:** IMEI does not appear in customer portal despite user being assigned to the usergroup

---

## 🔍 Root Cause

The `/api/portal/tags` endpoint filters tags using the UserGroup's `email_domain`. When a user is **manually assigned** to a usergroup (their email domain doesn't match), their tags are excluded from the query.

**Example:**
- UserGroup "Al-Kon" has `email_domain = "al-kon.com"`
- User `albaek.lars@gmail.com` was manually assigned
- Filter looks for users with `@al-kon.com` → misses `@gmail.com` → IMEI invisible

---

## 📁 Documentation Files Created

### 1. [FLUTTER_USER_IMEI_VISIBILITY_ISSUE.md](./FLUTTER_USER_IMEI_VISIBILITY_ISSUE.md)
**Complete technical analysis:**
- Root cause deep-dive
- Database schema breakdown
- Three fix options with code examples
- Impact assessment
- Testing checklist

### 2. [INVESTIGATION_albaek_lars.md](./INVESTIGATION_albaek_lars.md)
**SQL verification queries:**
- 6 diagnostic queries to verify the issue
- Queries to test current (broken) vs fixed logic
- Query to find ALL affected users
- Step-by-step investigation guide

### 3. [FIX_IMPLEMENTATION.md](./FIX_IMPLEMENTATION.md)
**Exact code change needed:**
- Current vs fixed code side-by-side
- Line-by-line explanation
- Testing checklist (5 test cases)
- Performance impact analysis
- Deployment steps + rollback plan

---

## ✅ Recommended Fix

**Modify:** `backend/app/routes_portal.py` function `list_group_tags()` (lines 1673-1760)

**Change:** Include users with `PortalUser` records in addition to domain-matched users

**Impact:**
- ✅ Fixes albaek.lars@gmail.com immediately (retroactive)
- ✅ Fixes ALL other manually assigned users
- ✅ Zero breaking changes
- ✅ Backward compatible
- ⚡ +1 database query (~10ms overhead)

---

## 🚀 Quick Start

### Verify the Issue (Run SQL Query)
```sql
-- From INVESTIGATION_albaek_lars.md Query #4
-- Should return includes_lars_imei = FALSE
```

### Apply the Fix (Code Change)
```python
# From FIX_IMPLEMENTATION.md
# Copy the "Fixed Code (Working)" section
# Replace lines 1673-1760 in routes_portal.py
```

### Test the Fix (Run SQL Query)
```sql
-- From INVESTIGATION_albaek_lars.md Query #5
-- Should return includes_lars_imei = TRUE
```

### Deploy
```bash
git add backend/app/routes_portal.py
git commit -m "Fix: Include manually assigned users in customer portal tag list"
git push origin main
```

---

## 📊 Affected Users

Run this query to find ALL users with the same issue:

```sql
-- From INVESTIGATION_albaek_lars.md (bottom section)
SELECT 
  u.email,
  ug.name as usergroup,
  ug.email_domain,
  COUNT(bt.id) as invisible_tag_count
FROM portal_users pu
JOIN usergroups ug ON pu.usergroup_id = ug.id
JOIN users u ON u.email = pu.email
LEFT JOIN ble_tags bt ON bt.user_id = u.id AND bt.is_active = true
WHERE u.email NOT ILIKE '%@' || ug.email_domain
GROUP BY u.email, ug.name, ug.email_domain
HAVING COUNT(bt.id) > 0
ORDER BY invisible_tag_count DESC;
```

---

## 🎯 Expected Outcome

After applying the fix:

1. ✅ albaek.lars@gmail.com logs into customer portal
2. ✅ Navigates to tags/assets page
3. ✅ **IMEI 781950640095676 appears in the list**
4. ✅ All other manually assigned users see their IMEIs too

---

## 🛠️ Alternative Approaches

### Option 2: Stamp Tags During Assignment
Modify admin endpoint to set `_created_usergroup_id` when assigning users. See [FIX_IMPLEMENTATION.md](./FIX_IMPLEMENTATION.md) for details.

**Trade-off:** Doesn't fix existing users retroactively.

### Option 3: Hybrid (Query + Stamp)
Use both approaches for maximum robustness.

---

## 📞 Support

If you need clarification on any part of the investigation:

1. Read the full technical analysis: [FLUTTER_USER_IMEI_VISIBILITY_ISSUE.md](./FLUTTER_USER_IMEI_VISIBILITY_ISSUE.md)
2. Run the diagnostic SQL queries: [INVESTIGATION_albaek_lars.md](./INVESTIGATION_albaek_lars.md)
3. Review the exact code change: [FIX_IMPLEMENTATION.md](./FIX_IMPLEMENTATION.md)

---

## ⏱️ Estimated Fix Time

- **Code Change:** 5 minutes (copy-paste from FIX_IMPLEMENTATION.md)
- **Local Testing:** 10 minutes (run pytest + manual login)
- **Deployment:** 2 minutes (git commit + push → CI/CD auto-deploy)
- **Verification:** 5 minutes (user tests in production)

**Total:** ~20 minutes from start to verified fix in production

---

## 🔒 Safety

- ✅ 100% backward compatible
- ✅ No data migration needed
- ✅ No schema changes
- ✅ Easy rollback (git revert)
- ✅ No downtime required

---

**Status:** Investigation complete. Ready to implement fix.  
**Priority:** HIGH (production functionality broken for manually assigned users)  
**Next Step:** Apply the code change from [FIX_IMPLEMENTATION.md](./FIX_IMPLEMENTATION.md)
