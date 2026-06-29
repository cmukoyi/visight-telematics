# Floor Plan Publishing - Status Update

## ✅ WORKING NOW (After Deployment ~4 min)

### Simplified Publish Workflow
1. **Draw floor plan** in Floor Plan Sketch tab
2. **Click Publish** button (green, always visible)
3. **First time only:**
   - Browser prompt: "Enter building name" → type name
   - Browser prompt: "Enter floor name" → type name  
   - System creates building + floor automatically
4. **Publishes** floor plan to database
5. **Button changes** to green "Published ✅"
6. **Success message** appears

### What Gets Saved
- ✅ Building record in `buildings` table
- ✅ Floor record in `floors` table  
- ✅ Floor plan data (walls, rooms, gateways) in `floor_plan_data` JSON column
- ✅ Gateway positions in `indoor_gateways` table
- ✅ Link saved to localStorage (persists across refreshes)

---

## ❌ NOT WORKING YET

### Tracking → Floor Plan View
**Problem:** Shows hardcoded demo layouts (Ground Floor - Warehouse, First Floor - Offices, etc.)

**What's Missing:** Code to load published floors from database

**Location:** `gps-tracker/customer-dashboard/public/floorplan/app.js`

**Hardcoded Data (lines 15-150):**
```javascript
const FLOORS = {
  'G': { name: 'Ground Floor — Warehouse', ... },
  '1F': { name: 'First Floor — Offices', ... },
  '2F': { name: 'Second Floor — Retail', ... }
};
```

**Needs:**
- Fetch published floors from `/api/portal/buildings?published=true`
- Convert API response to FLOORS format
- Dynamically populate floor tabs
- Load floor plan JSON from `floor_plan_data` column
- Query real-time tag positions from `tag_indoor_positions` table

---

## 🧪 Test After Deployment

### Step 1: Publish a Floor Plan
1. Go to **Management → Floor Plan Sketch**
2. Draw something (wall, room, gateway)
3. Click **Publish**
4. Enter building name when prompted
5. Enter floor name when prompted
6. See "Published ✅" button (green)
7. Check console for success logs

### Step 2: Verify Database Save
Check backend logs or database:
```sql
SELECT * FROM buildings ORDER BY created_at DESC LIMIT 1;
SELECT * FROM floors WHERE building_id = <above_id>;
SELECT * FROM indoor_gateways WHERE floor_id = <above_id>;
```

### Step 3: Try to View (Will Show Demo Data)
1. Go to **Tracking → Floor Plan**
2. See hardcoded "Ground Floor — Warehouse"
3. **Your published floor NOT visible yet**

---

## 📋 Next Steps (Priority Order)

### HIGH PRIORITY: Make Published Floors Visible
1. Modify `floorplan/app.js` line 794 `_init()` function
2. Add `async function loadPublishedFloors()` before init
3. Fetch `/api/portal/buildings` with `is_published = true`
4. Convert response to FLOORS format:
   ```javascript
   FLOORS[floor.id] = {
     name: floor.name,
     width: floor.width || 1000,
     height: floor.height || 680,
     shell: floorPlanData.shell,
     rooms: floorPlanData.rooms,
     // etc...
   };
   ```
5. Dynamically create floor tabs based on published floors
6. Default to first published floor instead of 'G'

### MEDIUM PRIORITY: Real-Time Tag Display
- Query `/api/portal/tags/indoor-positions?floor_id=<id>`
- Show BLE tags moving on canvas
- Poll every 2 seconds for updates

### LOW PRIORITY: Floor Plan Editor
- Edit published floor plans
- Re-publish after changes
- Version history

---

## 🎯 Summary

**MODAL REMOVED** - No more wasting time on CSS issues  
**PUBLISH WORKS** - Simple prompts, creates building/floor, saves to database  
**TRACKING BROKEN** - Needs database loading instead of hardcoded demo data

After deployment, you can PUBLISH floor plans successfully. They just won't SHOW UP in tracking view yet because that view doesn't query the database - it uses hardcoded layouts from 2 months ago.

Next work session: Make Tracking → Floor Plan load from database.
