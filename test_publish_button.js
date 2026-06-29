// Test Publish Button - Simplified Workflow
// Run in browser console at https://pinplot.me/customer/ after going to Floor Plan Sketch tab

console.log('=== Publish Button Test ===\n');

// 1. Check if Publish button exists and is visible
const publishBtn = document.getElementById('publishFloorBtn');
if (publishBtn) {
  const styles = window.getComputedStyle(publishBtn);
  console.log('✅ Publish button found');
  console.log('   Display:', styles.display);
  console.log('   Visibility:', styles.visibility);
  console.log('   Background:', styles.backgroundColor);
  console.log('   Is visible:', publishBtn.offsetParent !== null);
} else {
  console.error('❌ Publish button NOT found');
}

// 2. Check if Setup button is hidden
const setupBtn = document.getElementById('setupFloorBtn');
if (setupBtn) {
  const styles = window.getComputedStyle(setupBtn);
  console.log('\n⚠️ Setup button still exists (should be hidden)');
  console.log('   Display:', styles.display);
  console.log('   Is visible:', setupBtn.offsetParent !== null);
} else {
  console.log('\n✅ Setup button removed or hidden');
}

// 3. Check if modal exists
const modal = document.getElementById('sketchSetupModal');
if (modal) {
  console.log('\n✅ Setup modal exists');
  console.log('   Display:', window.getComputedStyle(modal).display);
} else {
  console.error('\n❌ Setup modal NOT found');
}

// 4. Check if we have floor plan data
if (window.state && window.state.floors) {
  const elements = window.state.floors[window.state.currentFloor]?.elements || [];
  console.log('\n📊 Floor plan data:');
  console.log('   Total elements:', elements.length);
  console.log('   Gateways:', elements.filter(e => e.type === 'gateway').length);
  console.log('   Walls:', elements.filter(e => e.type === 'wall').length);
  console.log('   Rooms:', elements.filter(e => e.type === 'room').length);
} else {
  console.log('\n⚠️ No floor plan data (window.state not initialized)');
}

// 5. Test clicking Publish
console.log('\n🧪 Testing Publish button click in 2 seconds...');
setTimeout(() => {
  console.log('\n>>> CLICKING PUBLISH BUTTON <<<');
  publishBtn.click();
  console.log('Expected behavior:');
  console.log('- If no building/floor linked: Modal opens');
  console.log('- If linked: Confirmation dialog appears');
}, 2000);

console.log('\n=== Waiting for click... ===');
