# Floor Plan Feature - Complete Workflow

## 📋 Intended Workflow (Step-by-Step)

### Phase 1: Setup (Link Floor Plan to Database)
1. User goes to **Management → Floor Plan Sketch** tab
2. User draws floor plan using canvas tool (walls, rooms, etc.)
3. User clicks **FEATURES → Gateway** tool
4. User places gateway icon on canvas
5. User clicks **Setup** button (in header toolbar)
6. **Modal opens** with dropdown selections:
   - Select existing building OR create new
   - Select existing floor OR create new
7. User selects/creates building + floor
8. User clicks **Save** in modal
9. System saves link: `{ buildingId, floorId, savedAt }` → localStorage
10. **Setup button turns green** (shows linked)
11. **Publish button appears** (green, in toolbar)
12. Modal closes

### Phase 2: Register Gateways
1. User selects a gateway on canvas
2. **Properties panel** appears on right side
3. Panel shows: "MAC Address" input field
4. User enters gateway MAC (e.g., `aa:bb:cc:dd:ee:ff`)
5. User clicks **Register Gateway** button in Properties
6. System saves: `IndoorGateway(mac_address, floor_id, x, y)`
7. Properties panel shows: "✅ Registered"

### Phase 3: Publish Floor Plan
1. User clicks **Publish** button
2. System:
   - Saves all gateway positions to database
   - Updates floor metadata
   - Marks floor as "published"
3. Floor plan is now LIVE for tracking

### Phase 4: View Live Tracking
1. User goes to **Tracking → Floor Plan** tab
2. System loads published floor plan
3. System shows BLE tags moving on floor plan in real-time
4. Data flows:
   - ESP32 gateway → Pareto Anywhere → Backend → TagIndoorPosition
   - Frontend queries positions → displays on canvas

---

## 🐛 Current Problem: Modal Won't Open

### What SHOULD Happen:
```javascript
setupBtn.click()
  → loadBuildingsAndFloors() succeeds
  → setupModal.style.display = 'flex'
  → Modal becomes visible
```

### What ACTUALLY Happens:
```
[Floor Plan] ✅ Buildings and floors loaded
[Floor Plan] ✅ Modal opened    ← LIE! It's not opened
setupModal.style.display = 'flex'  ← This line executes
Modal display: none                 ← But stays hidden!
```

### Possible Causes:
1. **CSS Override** - Another stylesheet forces `display: none !important`
2. **Wrong Modal** - `sketchSetupModal` doesn't point to the right element
3. **Parent Hidden** - Modal's parent has `display: none`
4. **JavaScript Override** - Another script sets it back to `none` immediately
5. **Tab Not Active** - Canvas/sketch not initialized when modal tries to open

---

## 🔍 Code Audit Needed

### Files to Check:
1. `gps-tracker/customer-dashboard/public/index.html`
   - Line 2024-2064: Modal definitions
   - Line 12251-12264: Setup button click handler
   - Line 12242: Modal element selection

2. `gps-tracker/customer-dashboard/public/styles.css`
   - Search for `.modal` or `#sketchSetupModal`
   - Check for `display: none !important`

3. Canvas initialization timing:
   - Does modal need to wait for canvas to be ready?
   - Is there a tab-switch event that hides modals?

---

## ✅ Next Steps

1. **Run debug_modal.js** - Find out WHY style.display doesn't work
2. **Check if forcing it works** - Try setting display in console manually
3. **Check modal parent** - Is parent hidden?
4. **Check CSS overrides** - Is there `!important` blocking it?
5. **Check tab state** - Is Floor Plan Sketch tab actually active?
