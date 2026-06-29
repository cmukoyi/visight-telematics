# 🚨 FLOOR PLAN BUTTONS INVISIBLE - EMERGENCY FIX

## Status: Buttons Exist in DOM ✅ but Not Visible ❌

Your console test confirmed:
```javascript
Setup: true     ✅
Publish: true   ✅
MAC input: true ✅
Register: true  ✅
```

**ALL BUTTONS EXIST** but you can't see them!

---

## 🔧 IMMEDIATE FIX (Copy & Paste in Console)

### Option 1: Quick Force Visible

Open console (F12) and paste:

```javascript
// QUICK FIX - Force everything visible
document.getElementById('setupFloorBtn').style.cssText = 'display:inline-flex !important; visibility:visible !important; opacity:1 !important';
document.getElementById('publishFloorBtn').style.cssText = 'display:inline-flex !important; visibility:visible !important; opacity:1 !important';
const header = document.querySelector('.sk-header');
if (header) header.style.cssText = 'display:flex !important; visibility:visible !important; opacity:1 !important';
const root = document.getElementById('sketch-root');
if (root) root.style.cssText = 'display:block !important; visibility:visible !important; opacity:1 !important';
const canvas = document.getElementById('canvas');
if (canvas) canvas.style.cssText = 'display:block !important; visibility:visible !important; opacity:1 !important';
if (window.render) window.render();
console.log('✅ FORCED VISIBLE - Check UI now!');
```

### Option 2: Full Diagnostic (Paste entire debug_buttons.js)

See `debug_buttons.js` file - paste entire content in console.

---

## 🔍 Most Likely Causes

### 1. **Wrong Tab Active** ⭐ MOST COMMON
You might not be on the Floor Plan Sketch tab!

**CHECK:**
- Look at left sidebar
- Is "Floor Plan Sketch (Beta)" highlighted?
- If not, click it!

**In Console:**
```javascript
// Check which tab is active
const buildingTab = document.getElementById('tab-building');
console.log('Floor Plan Sketch tab display:', window.getComputedStyle(buildingTab).display);
// Should be: 'flex' (visible) not 'none' (hidden)

// Auto-switch to it
if (window.switchTab) window.switchTab('building');
```

### 2. **Parent Container Hidden**
The header or sketch-root might be hidden.

**In Console:**
```javascript
const header = document.querySelector('.sk-header');
const root = document.getElementById('sketch-root');
console.log('Header visible:', header.offsetParent !== null);
console.log('Root visible:', root.offsetParent !== null);
```

### 3. **CSS Caching**
Old CSS might be cached.

**FIX:**
- Hard refresh: `Ctrl + Shift + R` (Windows) or `Cmd + Shift + R` (Mac)
- Or open in incognito window

### 4. **Browser Zoom**
Buttons might be off-screen.

**FIX:**
- Reset zoom: `Ctrl + 0` (Windows) or `Cmd + 0` (Mac)
- Make browser window wider

### 5. **Sketch App Not Initialized**
The sketch drawing app didn't load.

**In Console:**
```javascript
console.log('Sketch state:', !!window.state);
console.log('Render function:', typeof window.render);
// Both should be true/'function'
```

---

## 🧪 Test with cURL (Already Done)

```bash
# Setup button exists ✅
curl -s https://pinplot.me/customer/ | grep setupFloorBtn
# Result: Found with style="background:var(--primary-dim);color:var(--primary)"

# Publish button exists ✅
curl -s https://pinplot.me/customer/ | grep publishFloorBtn  
# Result: Found with style="display:none" (correct - hidden until Setup)

# Resources loading ✅
curl -s https://pinplot.me/customer/ | grep sketch/app.js
# Result: <script src="/customer/sketch/app.js"></script>
```

**Deployment is CORRECT!** Issue is in browser display.

---

## 🎯 Step-by-Step Debug Process

### Step 1: Verify Tab
```javascript
// 1. Check if on Floor Plan Sketch tab
const tab = document.getElementById('tab-building');
console.log('Tab display:', window.getComputedStyle(tab).display);

// 2. If display is 'none', switch to it
if (window.switchTab) {
  window.switchTab('building');
  console.log('✅ Switched to Floor Plan Sketch');
}
```

### Step 2: Check Containers
```javascript
// Check all parent containers
const containers = {
  'tab-building': document.getElementById('tab-building'),
  'sketch-root': document.getElementById('sketch-root'),
  'sk-header': document.querySelector('.sk-header'),
  'header-actions': document.querySelector('.header-actions')
};

Object.entries(containers).forEach(([name, el]) => {
  if (el) {
    const style = window.getComputedStyle(el);
    console.log(`${name}:`, {
      display: style.display,
      visibility: style.visibility,
      opacity: style.opacity,
      visible: el.offsetParent !== null
    });
  }
});
```

### Step 3: Force Everything Visible
```javascript
// Nuclear option - force EVERYTHING visible
['tab-building', 'sketch-root'].forEach(id => {
  const el = document.getElementById(id);
  if (el) el.style.cssText = 'display:block !important; visibility:visible !important; opacity:1 !important';
});

['.sk-header', '.header-actions'].forEach(sel => {
  const el = document.querySelector(sel);
  if (el) el.style.cssText = 'display:flex !important; visibility:visible !important; opacity:1 !important';
});

['setupFloorBtn', 'publishFloorBtn'].forEach(id => {
  const el = document.getElementById(id);
  if (el) el.style.cssText = 'display:inline-flex !important; visibility:visible !important; opacity:1 !important';
});

console.log('✅ NUCLEAR OPTION APPLIED');
```

### Step 4: Grid Lines Issue
If canvas shows but grid is missing:

```javascript
// Check canvas
const canvas = document.getElementById('canvas');
console.log('Canvas:', {
  exists: !!canvas,
  width: canvas?.width,
  height: canvas?.height,
  display: canvas ? window.getComputedStyle(canvas).display : 'N/A'
});

// Force re-render
if (window.render) {
  window.render();
  console.log('✅ Render called');
}

// Check state
if (window.state) {
  console.log('State:', {
    floors: window.state.floors?.length,
    currentFloor: window.state.currentFloor,
    showGrid: window.state.showGrid,
    zoom: window.state.zoom
  });
}
```

---

## 📸 What You Should See

After fixes, the **top toolbar** should show:

```
┌──────────────────────────────────────────────────────────┐
│ [PinPlot Sketch]                                         │
│                                                          │
│ [↶] [↷] │ [↑] [💾] [↓] [↓] [🔍] │ [🔷 Setup] [🟢 Publish] │
│  Undo Redo Import Save  Export Preview    Setup  Publish │
└──────────────────────────────────────────────────────────┘
```

- **Setup button**: Blue background, building icon
- **Publish button**: Green background (initially hidden is OK)
- **Grid lines**: Should be visible on canvas
- **Left toolbar**: Shows SELECT, WALLS, OPENINGS, AREAS, FEATURES sections

---

## 🆘 If Nothing Works

### Last Resort Options:

1. **Different Browser**
   - Try Chrome/Edge/Firefox
   - Try incognito mode

2. **Clear Everything**
   ```javascript
   // Clear localStorage (will lose unsaved sketches!)
   localStorage.clear();
   location.reload();
   ```

3. **Direct URL**
   - Try: https://pinplot.me/customer/#/building
   - This forces Floor Plan Sketch tab

4. **Check Browser Console**
   - Look for RED errors
   - Screenshot and share with me

5. **Manual Deploy Check**
   ```bash
   # When did GitHub Actions last deploy?
   curl -s https://api.github.com/repos/PinPlot/PinPlot-HPS/actions/runs \
     | jq '.workflow_runs[0] | {status, conclusion, updated_at}'
   ```

---

## 📝 Summary

✅ **Buttons exist in DOM** (confirmed by your console test)  
❌ **Buttons not visible** (CSS/display issue)  
✅ **Deployment successful** (cURL confirms correct HTML)  

**Most likely cause:** You're not on the Floor Plan Sketch tab, OR parent container is hidden.

**Quick fix:** Paste the quick_fix.js script in console.

**For debugging:** Use debug_buttons.js for full diagnostic.

---

## 🎬 What to Do NOW

1. Open https://pinplot.me/customer/
2. Press `F12` to open console
3. Paste the QUICK FIX script (above)
4. Check if buttons appear
5. If not, paste full debug_buttons.js
6. Share console output with me

Take a break - I'll fix this! 💪
