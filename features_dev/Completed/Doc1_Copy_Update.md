# HIVE Wizard — Profile Selection Copy Update

**For:** Frontend / UX team
**Scope:** Setup wizard, Step 2 (How much do these items move?)
**Status:** Ready to implement

---

## Background

The current wizard copy for Step 2 is recognition-focused (gives examples) but doesn't explain what HIVE will actually do for each profile. Users picking "They move regularly" don't realise that means "alerts pause during transit and resume when you stop" — a meaningful behavioural difference they should know about before choosing.

This update covers:

1. New step heading and supporting copy
2. Updated descriptions for all three options

---

## 1. Step Heading and Supporting Copy

### Current

> **How much do these items move?**
> *We'll use this to set freshness windows, confirmation rules, and alert sensitivity. You can change this later.*

### Updated

> **How much do these items move?**
> *This affects how quickly HIVE flags problems and how it handles your items being on the move. You can change this later.*

**Why:** "Freshness windows, confirmation rules, and alert sensitivity" is engineering-internal vocabulary that doesn't help users decide. The replacement keeps the same length but uses concepts users actually care about — how fast HIVE notices issues, and how it behaves during movement.

---

## 2. Option Descriptions

Each option follows a three-part structure:

1. **Examples** — concrete cases the user can recognise
2. **Behaviour cue** — what HIVE will actually do for this kind of use case
3. **Best for** — short italicised line clarifying the ideal use case

---

### Option 1 — They stay put

**Title:** `They stay put`

**Description body:**

> Tools in a workshop, equipment in a yard, instruments in a lab. Items that shouldn't normally move from where you've placed them.
>
> *HIVE alerts you to any movement or separation. Tight threshold, fast detection.*
>
> *Best for: theft monitoring, asset location verification, "did this walk away?" tracking.*

---

### Option 2 — They move occasionally

**Title:** `They move occasionally`

**Description body:**

> Livestock, parked vehicles between trips, mobility aids, luggage during a stay. Items that mostly stay put but move slowly when they do.
>
> *HIVE pauses monitoring during movement and resumes when the items are at rest. Alerts arrive once things settle.*
>
> *Best for: tracking items that have long stationary periods with occasional slow movement between locations.*

---

### Option 3 — They move regularly or in transit

**Title:** `They move regularly or in transit`

**Description body:**

> Personal belongings carried day-to-day, shared equipment, couriered packages, fleet items, vehicles on the road. Items that travel with you or are actively being moved.
>
> *HIVE pauses monitoring during transit and resumes when you arrive at your destination. Wider threshold to handle position uncertainty during movement. Alerts arrive after you've stopped.*
>
> *Best for: travel kits ("did everything arrive with me?"), delivery tracking, fleet monitoring. Most accurate at rest; in-transit alerts are paused by design.*

---

## 3. Formatting Notes

### Italic vs. plain text

In each description:

- The main examples line is plain text
- The behaviour cue is italicised — this is the "HIVE will do X" line
- The "Best for" line is italicised — this gives the use-case framing

If the rendering platform supports it, the italics can use a slightly muted colour to create visual hierarchy (examples primary → behaviour secondary → best-for tertiary). If not, plain italics are fine.

### Line breaks

Each option's description is three blocks separated by blank lines (a paragraph break). On smaller screens or constrained card heights, these should render as separate paragraphs rather than running together. Avoid single-line collapses.

### Title-bar consistency

The option titles ("They stay put", "They move occasionally", "They move regularly or in transit") match the existing wizard pattern and don't need formatting changes — just the description bodies.

### Note on the dynamic rationale line

Separate from this copy update, a dynamic italic rationale line may be appended to one option's description when a smart suggestion is made (see `HIVE_Wizard_Smart_Defaults_Implementation.md`). That line is *additional* to the descriptions in this document — it does not replace the "behaviour cue" or "Best for" lines, which are static and apply to every option regardless of suggestion state.

When a suggestion is shown, the recommended option's description will read:

> Examples line (plain text)
>
> *Behaviour cue (italic)*
>
> *Best for: ... (italic)*
>
> *— based on your recent hives, you typically use this profile. (italic, dynamic, only when badge shown)*

When no suggestion is shown, the dynamic line is simply absent on all options. No other copy changes apply.

---

## 4. Acceptance Criteria

When this is shipped, the wizard Step 2 should:

- [ ] Show the updated step heading and supporting copy
- [ ] Show three options with the new three-part description structure
- [ ] Render correctly on desktop and mobile (descriptions should not be truncated)
- [ ] Match existing wizard visual style (colours, spacing, button placement unchanged)

---

*End of copy update brief*
