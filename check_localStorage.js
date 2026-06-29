// ══════════════════════════════════════════════════════════════
// LOCALSTORAGE CHECKER - Paste in console
// ══════════════════════════════════════════════════════════════

console.clear();
console.log('%c🔍 LOCALSTORAGE DEBUG', 'font-size: 20px; color: #f59e0b; font-weight: bold');
console.log('═══════════════════════════════════════\n');

// Check if the floor link key exists
const FLOOR_LINK_KEY = 'pinplot_floor_link_v1';
const saved = localStorage.getItem(FLOOR_LINK_KEY);

console.log(`1️⃣  Floor Link Key: "${FLOOR_LINK_KEY}"`);
console.log(`2️⃣  Stored Value:`, saved || '❌ NULL (not saved!)');

if (saved) {
  try {
    const data = JSON.parse(saved);
    console.log('\n✅ LINK EXISTS:');
    console.log('   Building ID:', data.buildingId);
    console.log('   Floor ID:', data.floorId);
    console.log('   Saved At:', data.savedAt);
    console.log('\n✅ Publish button SHOULD be visible');
  } catch (e) {
    console.error('❌ Failed to parse:', e);
  }
} else {
  console.log('\n❌ NO LINK SAVED IN LOCALSTORAGE');
  console.log('   This is why Publish button is hidden!');
  console.log('\n📝 SOLUTION:');
  console.log('   Click "Setup" button again to re-link building/floor');
  console.log('   This will save to localStorage and persist across refreshes');
}

// Check sketch data
const SKETCH_KEY = 'pareto_floorplan_v1';
const sketchData = localStorage.getItem(SKETCH_KEY);
console.log(`\n3️⃣  Sketch Data Key: "${SKETCH_KEY}"`);
console.log(`4️⃣  Stored Value:`, sketchData ? '✅ EXISTS' : '❌ NULL');

if (sketchData) {
  try {
    const data = JSON.parse(sketchData);
    console.log('   Floors:', data.floors?.length || 0);
    console.log('   Elements:', data.floors?.[0]?.elements?.length || 0);
    console.log('   Saved At:', data.saved_at);
  } catch (e) {
    console.error('   Failed to parse');
  }
}

console.log('\n═══════════════════════════════════════');
console.log('%c💡 DIAGNOSIS', 'color: #3b82f6; font-size: 14px; font-weight: bold');

if (!saved && sketchData) {
  console.log('%c❌ PROBLEM IDENTIFIED:', 'color: #ef4444; font-weight: bold');
  console.log('   • You HAVE a floor plan drawing (sketch data exists)');
  console.log('   • But NO building/floor link saved (link data missing)');
  console.log('   • You created the link BEFORE persistence code was deployed');
  console.log('\n%c✅ SOLUTION:', 'color: #10b981; font-weight: bold');
  console.log('   1. Click "Setup" button');
  console.log('   2. Select existing building and floor');
  console.log('   3. Click Save');
  console.log('   4. Link will be saved to localStorage');
  console.log('   5. Publish button will stay visible after refresh');
} else if (saved && sketchData) {
  console.log('%c✅ EVERYTHING LOOKS GOOD', 'color: #10b981; font-weight: bold');
  console.log('   • Floor plan drawing exists');
  console.log('   • Building/floor link exists');
  console.log('   • Publish button should be visible');
  console.log('\n   If Publish button is still hidden, run: location.reload()');
} else if (!saved && !sketchData) {
  console.log('%c⚠️ NO DATA FOUND', 'color: #f59e0b; font-weight: bold');
  console.log('   • No floor plan drawing');
  console.log('   • No building/floor link');
  console.log('   • This is a fresh start - click Setup to begin');
}

console.log('\n═══════════════════════════════════════\n');

// Helper to manually save a link (for emergency use)
window.manualSaveLink = function(buildingId, floorId) {
  const data = {
    buildingId: buildingId,
    floorId: floorId,
    savedAt: new Date().toISOString()
  };
  localStorage.setItem(FLOOR_LINK_KEY, JSON.stringify(data));
  console.log('✅ Link saved manually!');
  console.log('   Reload page to see Publish button:', data);
  console.log('   Run: location.reload()');
};

console.log('%c🛠️  HELPER FUNCTION', 'color: #8b5cf6; font-size: 14px; font-weight: bold');
console.log('   manualSaveLink(buildingId, floorId) - Manually save link if needed');
console.log('\n');
