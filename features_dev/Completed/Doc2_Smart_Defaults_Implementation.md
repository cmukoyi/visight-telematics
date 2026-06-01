# HIVE Wizard — Smart Suggestion Implementation

**For:** Engineering team
**Scope:** Setup wizard, Step 2 — the "Suggested" badge on profile options
**Status:** Implementation required — current behaviour is static and misleading

---

## Background

The wizard currently shows a "Suggested" badge on one of the three profile options, implying the recommendation is data-driven. It isn't — the badge appears statically regardless of context. This document specifies how to make the suggestion genuinely informed by user history.

The approach is deliberately minimal: a soft hint backed by the user's own recent hive choices, not a heavy analytics pipeline. Engineering effort should match the value of the feature, which is a nudge, not a binding recommendation.

---

## Approach

**Look at the user's own recent hive history and suggest the profile they typically choose.**

Past hive profiles capture user intent in a way that raw tag movement data cannot. A user who has consistently chosen Mobile for their tracking is signalling what kind of tracking they want, regardless of whether their currently-selected tags happen to have been sitting still recently.

This avoids per-tag analysis entirely, which is appropriate because most tags will never be used in a hive, and tags can be re-used across hives with very different profiles.

---

## Logic

### Query

For the current user, fetch the profile field of their most recent N hives (suggest **N = 5**) within the last **90 days**. Include both active and archived hives. Exclude purged hives (data may be gone).

Pseudo-SQL:

```sql
SELECT mobility_profile
FROM hives
WHERE created_by = :current_user_id
  AND status IN ('active', 'archived')
  AND created_at >= NOW() - INTERVAL '90 days'
ORDER BY created_at DESC
LIMIT 5
```

Note on the profile field: this should reference the resolved profile at hive creation, available either directly on the `hives` table or in the initial `hive_config_versions` row for the hive.

### Mapping

```
recent_profiles = result of the query above

if recent_profiles.length >= 2 AND all values in recent_profiles are the same:
    suggested_profile = recent_profiles[0]
    show_badge = true

else:
    suggested_profile = null
    show_badge = false
```

That's the entire logic. Two states: show the badge with a suggestion, or don't.

The rule deliberately requires 2+ matching hives. A single hive isn't a pattern. Mixed profiles aren't a pattern either — if the user has done both Stationary and Mobile recently, we can't confidently predict which they want now.

---

## UI Behaviour

### When `show_badge = true`

- Display the **"Suggested"** badge on the recommended option
- Display a rationale string as italic text at the end of that option's description (see below)
- Pre-select the suggested option as the active radio

### When `show_badge = false`

- Display **no badge** on any option
- Display **no italic rationale** on any option
- Do not pre-select any option — the user makes a fresh choice

There is no middle state. The badge is either earned or not shown.

---

## Rationale Strings

The italic rationale line appears next to the "Suggested" badge and explains why the recommendation was made. Single sentence, plain language, accurate.

Use the following based on how strong the pattern is:

**All recent hives match the suggestion (strongest case):**

> *— based on your recent hives, you typically use this profile.*

**Most recent hives match (2 of the last 3, or 3 of the last 5, etc.):**

> *— based on your recent hive setup.*

Pick whichever phrasing fits given the data. If you implement only the strict "all match" case (per the mapping rule above), use the first variant exclusively.

---

## Where This Lives in Code

Two reasonable placements:

**Option 1 — Add to the existing wizard-prep endpoint.** If there's already an endpoint that returns initial data when the wizard opens (selected tags' availability, current user info, etc.), add `suggested_profile` and `rationale` fields to the response.

**Option 2 — Tiny standalone helper.** A function `suggest_profile_for_user(user_id) → (profile | null, rationale | null)` called from wherever the wizard data is assembled.

Either is fine. Avoid creating a new endpoint just for this — the query is small enough to bundle.

---

## Testing

### Unit tests

Three cases are sufficient:

**Test 1 — Clear pattern:** User has 5 recent hives, all Mobile. Expected: `suggested_profile = "mobile"`, `show_badge = true`.

**Test 2 — Mixed history:** User has 3 recent hives — two Mobile and one Stationary. Expected: `suggested_profile = null`, `show_badge = false` (no clear pattern).

**Test 3 — New user:** User has zero recent hives. Expected: `suggested_profile = null`, `show_badge = false`.

### Manual verification

After deploying, check the wizard for a few real users:

- A user with a clear history pattern should see the badge on the matching option
- A user with no hives or mixed history should see no badge
- Confirm the rationale string renders correctly

---

## Acceptance Criteria

- [ ] Query returns the user's most recent 5 hive profiles within the last 90 days
- [ ] Suggestion is made only when 2+ recent hives all share the same profile
- [ ] Wizard displays "Suggested" badge and italic rationale only when a suggestion is made
- [ ] Wizard displays no badge and pre-selects no option when no suggestion is made
- [ ] Three unit tests pass (clear pattern, mixed history, new user)
- [ ] Rationale strings match those specified above

---

## What This Doesn't Do (Deliberately)

A few things this implementation explicitly does not attempt:

- **No analysis of tag movement history.** The user's past choices are the signal, not the tags' raw positions.
- **No outcome-based learning.** Whether past hives generated many alerts or none doesn't feed back into the suggestion. (Future enhancement if needed.)
- **No org-wide or system-wide aggregation.** Suggestions are scoped to the individual user. (Can be extended later if multi-user orgs become a use case.)
- **No caching.** The query is too cheap to need it.
- **No feature flag.** This is a soft hint that either appears or doesn't — there's no risk in shipping it directly.

These are all reasonable future extensions if the basic version proves valuable. They are explicitly out of scope for v1.

---

*End of implementation guide*
