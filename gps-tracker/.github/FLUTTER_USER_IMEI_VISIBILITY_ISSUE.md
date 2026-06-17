# 🐛 Flutter User IMEI Visibility Issue in Customer Portal

## Issue Summary

**When a Flutter mobile app user is manually assigned to a usergroup** (because their email domain doesn't match the group's `email_domain`), **their IMEIs do not appear** in the customer portal's tag list (`GET /api/portal/tags`).

---

## Example Case

| Field | Value |
|---|---|
| User Email | albaek.lars@gmail.com |
| IMEI | 781950640095676 |
| UserGroup | "Al-Kon" |
| Assignment Method | **Manual** (admin assigned via portal) |
| UserGroup `email_domain` | Likely `al-kon.com` or similar (NOT `gmail.com`) |

### Current State
- ✅ User exists in `users` table with `user_id` and `email = albaek.lars@gmail.com`
- ✅ IMEI exists in `ble_tags` table with `user_id = albaek.lars@gmail.com's user ID`
- ✅ `PortalUser` record created linking user to UserGroup "Al-Kon"
- ✅ User type shows as "Flutter+Portal" in admin portal
- ✅ User can login to customer portal
- ❌ **IMEI 781950640095676 does NOT appear in customer portal tag list**

---

## Root Cause Analysis

### Current Tag Filtering Logic in `/api/portal/tags`

Located in: `backend/app/routes_portal.py` lines 1673-1760

```python
@router.get("/tags", response_model=List[PortalTagOut])
def list_group_tags(request: Request, db: Session = Depends(get_db)):
    me = get_portal_user_from_request(request, db)
    group = db.query(UserGroup).filter(UserGroup.id == me.usergroup_id).first()
    
    # Step 1: Get group's email domain(s)
    domains = _domains(group)  # e.g., ["al-kon.com"]
    
    # Step 2: Find all users whose email matches those domains
    owner_rows = db.query(User.id, User.email).filter(_domain_filter(domains)).all()
    owner_ids = [uid for uid, _ in owner_rows]
    # ⚠️ albaek.lars@gmail.com does NOT match @al-kon.com → NOT in owner_ids
    
    # Step 3: Query tags using domain-based filter
    tag_scope_filter = (
        or_(
            BLETag.user_id.in_(owner_ids),  # ❌ Excludes gmail.com users
            BLETag.attributes.op("->>")("_created_usergroup_id") == group_id,
        )
        if owner_ids
        else BLETag.attributes.op("->>")("_created_usergroup_id") == group_id
    )
```

### Helper Functions

```python
def _domains(group: UserGroup) -> list:
    """Return comma-separated domains from group.email_domain."""
    if not group or not group.email_domain:
        return []
    return [d.strip().lower() for d in group.email_domain.split(",") if d.strip()]

def _domain_filter(domains: list):
    """Filter users by email domain."""
    return or_(*(User.email.ilike(f"%@{d}") for d in domains))
```

### Why It Fails

The filter assumes **all users in a usergroup match the group's `email_domain`**. This works for:

✅ **Auto-assignment scenario:**
- User registers with `email = john@al-kon.com`
- Backend auto-creates `PortalUser` because email matches UserGroup "Al-Kon" `email_domain = al-kon.com`
- Tags owned by `john@al-kon.com` appear in portal ✓

❌ **Manual assignment scenario:**
- User registers with `email = albaek.lars@gmail.com`
- Admin manually assigns user to UserGroup "Al-Kon" (creates `PortalUser` record)
- `_domain_filter(["al-kon.com"])` does NOT match `gmail.com` → user ID excluded
- Tags owned by this user are NOT returned ✗

---

## Database State Breakdown

### Table: `users`
```sql
id                | email                   | first_name | last_name
------------------+-------------------------+------------+----------
<user_uuid>       | albaek.lars@gmail.com   | Lars       | Albaek
```

### Table: `ble_tags`
```sql
id              | user_id      | imei            | is_active | attributes
----------------+--------------+-----------------+-----------+------------
<tag_uuid>      | <user_uuid>  | 781950640095676 | true      | NULL or {}
```
**Key:** `user_id` links to the Flutter user ✓

### Table: `portal_users`
```sql
id              | usergroup_id  | email                   | role     | is_active
----------------+---------------+-------------------------+----------+----------
<portal_uuid>   | <al-kon_uuid> | albaek.lars@gmail.com   | reporter | true
```
**Key:** Manual assignment creates this record ✓

### Table: `usergroups`
```sql
id              | name    | email_domain
----------------+---------+-------------
<al-kon_uuid>   | Al-Kon  | al-kon.com
```
**Key:** Domain does NOT match gmail.com → filter breaks ✗

---

## The Fix

### Option 1: Include Manually Assigned Users (Recommended)

Modify `list_group_tags()` to include tags owned by **any user with a `PortalUser` record** in the current usergroup:

```python
@router.get("/tags", response_model=List[PortalTagOut])
def list_group_tags(request: Request, db: Session = Depends(get_db)):
    me = get_portal_user_from_request(request, db)
    group = db.query(UserGroup).filter(UserGroup.id == me.usergroup_id).first()
    
    domains = _domains(group)
    group_id = str(group.id)
    
    # NEW: Get all user IDs with PortalUser in this usergroup
    portal_user_ids = [
        str(pu.user_id) 
        for pu in db.query(PortalUser.user_id)
        .filter(PortalUser.usergroup_id == me.usergroup_id)
        .all()
        if pu.user_id
    ]
    
    # Domain-matched users (auto-assigned)
    domain_user_rows = db.query(User.id, User.email).filter(_domain_filter(domains)).all() if domains else []
    domain_user_ids = [str(uid) for uid, _ in domain_user_rows]
    
    # UNION: domain-matched + manually assigned
    all_owner_ids = list(set(domain_user_ids + portal_user_ids))
    
    # Build owner email map for display
    owner_email_map = {str(uid): email for uid, email in domain_user_rows}
    if portal_user_ids:
        extra_emails = db.query(User.id, User.email).filter(User.id.in_(portal_user_ids)).all()
        owner_email_map.update({str(uid): email for uid, email in extra_emails})
    
    # Updated filter includes ALL users in the group
    tag_scope_filter = (
        or_(
            BLETag.user_id.in_(all_owner_ids),
            BLETag.attributes.op("->>")("_created_usergroup_id") == group_id,
        )
        if all_owner_ids
        else BLETag.attributes.op("->>")("_created_usergroup_id") == group_id
    )
    
    # Rest of function unchanged...
```

### Option 2: Set `_created_usergroup_id` on Manual Assignment

When admin assigns a user to a usergroup, update all their existing tags with `attributes._created_usergroup_id`:

```python
# In admin portal user update endpoint
if payload.usergroup_id:
    # ... create PortalUser ...
    
    # NEW: Stamp all user's existing tags with group ID
    db.query(BLETag).filter(
        BLETag.user_id == user.id
    ).update({
        "attributes": func.jsonb_set(
            func.coalesce(BLETag.attributes, cast({}, JSONB)),
            ["_created_usergroup_id"],
            cast(str(group.id), JSONB)
        )
    }, synchronize_session=False)
```

### Option 3: Hybrid Approach (Most Robust)

Combine both:
1. Use Option 1's query logic for real-time inclusion
2. Use Option 2's stamping for audit trail

---

## Testing Checklist

After implementing the fix, verify:

- [ ] User `albaek.lars@gmail.com` can see IMEI `781950640095676` in customer portal tag list
- [ ] Auto-assigned users (email matches domain) still see their tags
- [ ] Portal-created QR/NFC tags still appear (via `_created_usergroup_id`)
- [ ] Multi-domain usergroups work correctly (e.g., `"al-kon.com,al-kon.dk"`)
- [ ] User with zero tags doesn't cause errors
- [ ] Manually assigned user's new tags (added after assignment) also appear

---

## Impact

**Affected Users:**
- Any Flutter mobile app user manually assigned to a usergroup
- Common scenarios:
  - Users with generic email domains (gmail.com, outlook.com, yahoo.com)
  - Users from partner organizations with different domains
  - Trial/demo accounts
  - Personal accounts for business users

**Workaround (Temporary):**
- Change usergroup's `email_domain` to match user's domain (e.g., set to `gmail.com`)
- **Problem:** This breaks isolation if multiple usergroups have gmail users

---

## Related Code Files

- `backend/app/routes_portal.py` lines 1673-1760 (`list_group_tags`)
- `backend/app/routes_portal.py` lines 2045-2070 (`_domains`, `_domain_filter`)
- `backend/app/models.py` line 339 (`UserGroup.email_domain`)
- `backend/app/main.py` lines 1662-1710 (`update_end_user` - admin assignment)

---

## Priority

**HIGH** — Core functionality broken for manually assigned Flutter users. Affects production data visibility.
