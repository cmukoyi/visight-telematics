// Ultimate Setup Button Diagnostic
// Run this in browser console at https://pinplot.me/customer/
// After going to Floor Plan Sketch tab

console.log('=== Ultimate Setup Button Diagnostic ===\n');

// 1. Check if we're on the right page
console.log('1️⃣ Current URL:', window.location.href);
if (!window.location.href.includes('pinplot.me/customer')) {
  console.error('❌ Wrong URL! Go to: https://pinplot.me/customer/');
}

// 2. Check if apiFetch exists
console.log('\n2️⃣ Checking apiFetch...');
if (typeof apiFetch === 'function') {
  console.log('✅ apiFetch function exists');
} else {
  console.error('❌ apiFetch NOT FOUND');
}

// 3. Check if Setup button exists
console.log('\n3️⃣ Checking Setup button...');
const setupBtn = document.getElementById('setupFloorBtn');
if (setupBtn) {
  console.log('✅ Setup button found:', setupBtn);
  console.log('   Visible:', setupBtn.offsetParent !== null);
  console.log('   Disabled:', setupBtn.disabled);
  console.log('   Display:', window.getComputedStyle(setupBtn).display);
} else {
  console.error('❌ Setup button NOT found in DOM');
  console.log('➡️ Make sure you switched to "Floor Plan Sketch" tab first');
}

// 4. Check if modal exists
console.log('\n4️⃣ Checking Setup modal...');
const modal = document.getElementById('sketchSetupModal');
if (modal) {
  console.log('✅ Modal found');
  console.log('   Display:', window.getComputedStyle(modal).display);
} else {
  console.error('❌ Modal NOT found');
}

// 5. Check if session exists
console.log('\n5️⃣ Checking user session...');
try {
  const session = getSession();
  if (session && session.token) {
    console.log('✅ User logged in');
    console.log('   User ID:', session.user_id);
    console.log('   Username:', session.username);
  } else {
    console.error('❌ No session token - user not logged in');
  }
} catch (err) {
  console.error('❌ getSession() failed:', err);
}

// 6. Test clicking the button programmatically
console.log('\n6️⃣ Testing button click...');
if (setupBtn) {
  console.log('Simulating click in 2 seconds...');
  console.log('Watch for "[Floor Plan]" log messages...\n');
  
  setTimeout(() => {
    console.log('>>> CLICKING SETUP BUTTON NOW <<<');
    setupBtn.click();
  }, 2000);
} else {
  console.error('Cannot test click - button not found');
}

console.log('\n=== Waiting for button click... ===');
console.log('After 2 seconds, you should see:');
console.log('  [Floor Plan] Setup button clicked');
console.log('  [Floor Plan] Loading buildings and floors...');
console.log('  [Floor Plan] Fetching buildings from /api/portal/buildings...');
console.log('  etc...');
console.log('\nIf you DON\'T see those messages, the event listener failed to attach.');
