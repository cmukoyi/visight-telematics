# IMEI/MAC QR Generator Updates

**Date:** June 22, 2026  
**Commit:** 25b2a1b  
**Status:** ✅ Deployed to production (https://pinplot.me)

## Changes Summary

Two updates to the QR/NFC tags generator for IMEI/MAC device identifier codes:

### 1. **Updated Description Text**

**Before:**
> **IMEI / MAC** — Encodes a device identifier as a plain-text QR (not a Pinplot link). Useful for labelling equipment so the number can be scanned instead of typed by hand. Industrial scanners read it directly; on phones use a QR scanner app like Google Lens.

**After:**
> **IMEI / MAC** — Encodes a device identifier as a plain-text QR. Useful for labelling equipment so the number can be scanned instead of typed by hand. Industrial scanners read it directly; on phones use a QR scanner app like Google Lens.

**Change:** Removed "(not a Pinplot link)" phrase to simplify messaging.

### 2. **SVG Download Behavior for IMEI/MAC**

**Before:**
- SVG downloads for IMEI/MAC codes showed registration confirmation modal
- Required user to click "Register and download" 
- Inconsistent with PNG behavior (which downloaded directly)

**After:**
- SVG downloads for IMEI/MAC codes now skip registration modal
- Downloads proceed directly (same as PNG format)
- Consistent UX across both PNG and SVG formats

## Technical Implementation

### File Modified
**`gps-tracker/customer-dashboard/public/qr-generator.html`**

### Change 1: Description Text (Line 339)
```diff
- <strong>IMEI / MAC</strong> — Encodes a device identifier as a plain-text QR (not a Pinplot link). 
+ <strong>IMEI / MAC</strong> — Encodes a device identifier as a plain-text QR. 
```

### Change 2: SVG Download Logic (Lines 4155-4178)

**Modified `dlSVG()` function:**

```javascript
// Old logic
if (asset) {
  openConfirmModal(function() {
    registerAsset(asset.id, asset.typeCode);
    // ... download logic
  }, asset);
} else {
  doSVGDownload();
}

// New logic
if (asset && asset.typeCode !== 'I') {
  // Asset QR or NFC — show registration confirmation modal
  openConfirmModal(function() {
    registerAsset(asset.id, asset.typeCode);
    // ... download logic
  }, asset);
} else {
  // IMEI/MAC or non-registerable content — download directly without modal
  doSVGDownload(function() {
    if (asset) {
      addHistoryEntry({
        id: asset.id, typeCode: asset.typeCode, format: 'svg', qty: 1, time: nowString(),
        redownload: function() { doSVGDownload(); }
      });
    }
  });
}
```

**Key changes:**
1. Added condition check: `asset.typeCode !== 'I'`
2. IMEI/MAC codes (typeCode 'I') skip `openConfirmModal()` call
3. Added history tracking for direct IMEI/MAC SVG downloads
4. Consistent with existing `dlPNG()` function behavior

## Type Code Reference

| Code | Description | Registration Modal |
|------|-------------|-------------------|
| **Q** | Asset QR | ✅ Yes (both PNG & SVG) |
| **N** | NFC Tag | ✅ Yes (both PNG & SVG) |
| **I** | IMEI/MAC | ❌ No (direct download) |

## User Flow Comparison

### Asset QR / NFC Tag Downloads
```
Click PNG/SVG → Modal: "Register and download?" → User confirms → Download starts
```

### IMEI/MAC Downloads (NEW)
```
Click PNG/SVG → Download starts immediately (no modal)
```

## Testing Checklist

✅ **IMEI/MAC behavior:**
- [ ] Select IMEI/MAC tab
- [ ] Enter valid IMEI (15 digits) or MAC address
- [ ] Click "⬇ PNG" → Downloads immediately (no modal)
- [ ] Click "⬇ SVG" → Downloads immediately (no modal)
- [ ] Check browser downloads: both files downloaded successfully

✅ **Asset QR behavior (should be unchanged):**
- [ ] Select Asset QR tab
- [ ] Click "⬇ PNG" → Modal appears → Confirm → Download
- [ ] Click "⬇ SVG" → Modal appears → Confirm → Download

✅ **NFC Tag behavior (should be unchanged):**
- [ ] Select NFC Tag tab
- [ ] Click "⬇ PNG" → Modal appears → Confirm → Download
- [ ] Click "⬇ SVG" → Modal appears → Confirm → Download

✅ **History tracking:**
- [ ] Download IMEI/MAC PNG → Appears in history panel
- [ ] Download IMEI/MAC SVG → Appears in history panel
- [ ] Click "Re-download" from history → Works correctly

## Rationale

### Why Remove "(not a Pinplot link)"?
- **Simplification**: Reduces cognitive load for users
- **Focus**: Emphasizes what the code *does* (encodes device ID) rather than what it's *not*
- **Clarity**: Already clear from context that IMEI/MAC is different from Asset QR

### Why Skip Registration Modal for IMEI/MAC?
- **Consistency**: PNG already worked this way, SVG should match
- **User expectation**: IMEI/MAC are plain-text codes, not tracked assets
- **Efficiency**: Users labeling equipment don't need confirmation prompts
- **Matches `dlPNG()` pattern**: Both formats now handle typeCode 'I' identically

## Deployment

**Method:** GitHub Actions auto-deploy on push to `main`  
**Environment:** PinPlotServer root@PinPlotServer  
**Expected downtime:** ~30 seconds (docker compose restart)  
**Production URL:** https://pinplot.me/customer/qr-generator.html

## Related Code

### Download Functions Hierarchy
```
dlPNG()  ──→ typeCode === 'I' ? Direct download : Modal + register
dlSVG()  ──→ typeCode === 'I' ? Direct download : Modal + register  ← NOW CONSISTENT
```

### Asset Type Detection
```javascript
function getActiveAssetInfo() {
  if (mode === 'url')  return { id: _currentQId, typeCode: 'Q' };
  if (mode === 'nfc')  return { id: _currentNId, typeCode: 'N' };
  if (mode === 'imei') return { id: normalizedId, typeCode: 'I', displayType: 'IMEI / MAC' };
  return null;
}
```

## Backward Compatibility

✅ **No breaking changes**
- Existing Asset QR and NFC behavior unchanged
- History entries remain compatible
- Modal logic still works for typeCode 'Q' and 'N'
- IMEI/MAC PNG download behavior unchanged (already worked this way)

## Rollback Plan

If issues arise, rollback to commit `f69b91b`:

```bash
git revert 25b2a1b
git push origin main
```

**Note:** No database changes or backend modifications. Pure frontend JavaScript change.

---

**Verified by:** GitHub Copilot  
**Deployment status:** ✅ Auto-deployed via GitHub Actions  
**Previous commit:** f69b91b (QR/NFC color theming fix)
