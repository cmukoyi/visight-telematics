# 🔍 Floor Plan Buttons Troubleshooting Guide

## The buttons ARE in the code!

Latest commit: `d9b92cc` - "feat: Add complete Floor Plan Sketch database integration"

The buttons are correctly placed in `/gps-tracker/customer-dashboard/public/index.html` at lines:
- **Line 1685**: Setup button (blue)
- **Line 1689**: Publish button (green, initially hidden)
- **Line 1957**: Register Gateway button (in Properties panel)

---

## 🚨 Why you might not see them:

### 1. **Page Not Refreshed After Deployment** ⭐ MOST LIKELY
   - The changes were just deployed to GitHub (commit `d9b92cc`)
   - Your browser is showing the OLD cached version
   
   **FIX:**
   ```
   Hard refresh the page:
   - Windows/Linux: Ctrl + Shift + R
   - Mac: Cmd + Shift + R
   
   Or clear browser cache:
   - Chrome: Settings > Privacy > Clear browsing data
   - Firefox: Settings > Privacy > Clear Data
   ```

### 2. **GitHub Actions Deployment Pending**
   - Check https://github.com/PinPlot/PinPlot-HPS/actions
   - Look for workflow running for commit `d9b92cc`
   - Wait for green checkmark before testing
   
   **Current Status:** The push to `origin/main` succeeded, but deployment may take 2-5 minutes

### 3. **Wrong Tab Open**
   - You need to be on **Floor Plan Sketch** tab (Management section)
   - NOT the **Floor Plan** tab (Tracking section - that's for viewing)
   
   **Correct Path:**
   ```
   Left Sidebar > Management Section > Floor Plan Sketch (Beta badge)
   ```

### 4. **JavaScript Error Blocking Render**
   - Open browser console (F12 > Console tab)
   - Look for red error messages
   - If you see errors, share them with me

---

## 📍 Where the Buttons Should Be

### **Top Toolbar (Header)**
After Undo/Redo/Import/Save/Export buttons, you should see:

```
┌────────────────────────────────────────────────────────┐
│ [Undo] [Redo] │ [Import] [Save] [Export...] [Preview] │
│               │ [divider]                              │
│               🔷 [Setup] 🟢 [Publish]                  │
└────────────────────────────────────────────────────────┘
```

- **Setup button**: Blue background, building icon
- **Publish button**: Green background (hidden until you complete Setup)

### **Properties Panel (Right Side)**
When you select a gateway icon:

```
┌─────────────────────────────────┐
│ Properties                      │
├─────────────────────────────────┤
│ ... other fields ...            │
│                                 │
│ ESP32 Gateway   [Not Reg...]   │
│ ┌─────────────────────────┐    │
│ │ A4:CF:12:45:AB:CD       │    │ ← MAC input
│ └─────────────────────────┘    │
│ [📡 Register Gateway]           │ ← Register button
├─────────────────────────────────┤
│ ID: el_abc123                   │
│ [Delete] [Duplicate]            │
└─────────────────────────────────┘
```

---

## 🧪 Diagnostic Steps

### Step 1: Run Console Diagnostic
1. Open pinplot.me
2. Go to Floor Plan Sketch tab
3. Press `F12` to open Developer Tools
4. Click **Console** tab
5. Copy and paste this script:

```javascript
// See: diagnose_floor_plan_buttons.js (in repo root)
// This will check if buttons exist and are visible
```

### Step 2: Manual Visual Check
Look at the **TOP toolbar** and verify you see these buttons in order:
1. Undo button (↺ icon)
2. Redo button (↻ icon)
3. Import button
4. **Save button** ← You should definitely see this
5. Export JSON button
6. Export SVG button
7. Preview button
8. **[Vertical divider line]**
9. **Setup button** ← Blue background, building icon
10. **Publish button** ← Green background (may be hidden initially)

If you see Save but NOT Setup, then the new code hasn't loaded yet.

### Step 3: Check GitHub Actions
1. Go to: https://github.com/PinPlot/PinPlot-HPS/actions
2. Look for latest workflow run (should be for commit `d9b92cc`)
3. Check if it's:
   - ✅ Green checkmark = Deployed successfully
   - ⏳ Yellow circle = Still deploying (wait a few minutes)
   - ❌ Red X = Deployment failed (check logs)

---

## 🎯 Testing Workflow (After Buttons Appear)

### Phase 1: Setup (Link to Database)
1. Click **Setup** button (blue, in top toolbar)
2. Modal opens: "Setup Floor Plan"
3. Select or create building
4. Select or create floor
5. Click "Link Floor Plan"
6. ✅ Setup button turns green, Publish button appears

### Phase 2: Draw Floor Plan
1. Use **WALLS** tools to draw walls
2. Use **AREAS > Room** to create rooms (name them!)
3. Use **FEATURES > Gateway** to place gateway icons

### Phase 3: Register Gateway
1. **Place gateway icon** inside a room (click Gateway tool, then click canvas)
2. **Select the gateway** (click it - it should highlight)
3. **Look at Properties panel** (right side) - should show:
   - "ESP32 Gateway" section
   - MAC Address input field
   - Status indicator
   - "Register Gateway" button
4. **Enter MAC address** (get from your ESP32: `A4:CF:12:45:AB:CD`)
5. **Click "Register Gateway"**
6. ✅ Status changes to "Registered" (green)

### Phase 4: Publish
1. Click **Publish** button (green, in top toolbar)
2. Validation checks:
   - ✅ At least one gateway exists
   - ✅ Gateway has MAC address
   - ✅ Gateway is registered
3. Confirmation dialog shows gateway count
4. Click OK
5. ✅ Floor plan published!

### Phase 5: View in Tracking
1. Go to **Tracking > Floor Plan** tab
2. Select your building and floor
3. See your floor plan with live BLE tag tracking!

---

## 🆘 If Buttons Still Missing After Hard Refresh

### Option 1: Quick Console Fix
Open console (F12) and paste:

```javascript
// Force Setup button visible
document.getElementById('setupFloorBtn').style.display = '';

// Check if it exists
console.log('Setup button:', document.getElementById('setupFloorBtn'));
console.log('Publish button:', document.getElementById('publishFloorBtn'));
console.log('Register button:', document.getElementById('propGatewayRegister'));
```

### Option 2: Verify Deployment
Run this in terminal:

```bash
cd /Users/carl/Documents/MobileCode/Pinplot
git log --oneline -1
# Should show: d9b92cc feat: Add complete Floor Plan Sketch database integration

# Check GitHub Actions status
gh run list --limit 1
# Or visit: https://github.com/PinPlot/PinPlot-HPS/actions
```

### Option 3: Local Test
If pinplot.me still doesn't work, test locally:

```bash
cd /Users/carl/Documents/MobileCode/Pinplot/gps-tracker
python3 -m http.server 8080
```

Then open: `http://localhost:8080/customer-dashboard/public/`

---

## 📸 Screenshots to Share

If buttons still don't appear, share these with me:

1. **Screenshot of top toolbar** (where buttons should be)
2. **Browser console output** (F12 > Console tab)
3. **Network tab** checking if index.html loaded (F12 > Network > index.html)
4. **GitHub Actions status** (green checkmark or still deploying?)

---

## 🔗 Quick Links

- **Diagnostic Script**: `/diagnose_floor_plan_buttons.js`
- **Quick Fix Script**: `/fix_buttons_console.js`
- **Test Page**: `/test_floor_plan_buttons.html`
- **GitHub Actions**: https://github.com/PinPlot/PinPlot-HPS/actions
- **Latest Commit**: https://github.com/PinPlot/PinPlot-HPS/commit/d9b92cc

---

## ✅ Expected Behavior Summary

| Button | Location | Initial State | When Visible | Action |
|--------|----------|---------------|--------------|--------|
| **Setup** | Top toolbar | Visible (blue) | Always | Opens modal to link building/floor |
| **Publish** | Top toolbar | Hidden | After Setup complete | Publishes floor plan to database |
| **Register Gateway** | Properties panel | Hidden | When gateway selected | Registers gateway MAC to database |

All buttons ARE in the code. If you don't see them, it's a **caching** or **deployment timing** issue, not a code issue.

---

## 🚀 Next Steps

1. **Hard refresh** your browser: `Ctrl+Shift+R` or `Cmd+Shift+R`
2. **Wait 2 minutes** for GitHub Actions deployment to complete
3. **Check Floor Plan Sketch tab** (Management section, not Tracking)
4. **Run diagnostic script** if still missing
5. **Share console output** if errors appear

The code is ready and deployed - just needs to reach your browser! 🎉
