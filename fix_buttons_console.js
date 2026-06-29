/**
 * FLOOR PLAN BUTTONS - QUICK FIX
 * 
 * If buttons are not visible after deployment, paste this in browser console:
 */

(function quickFix() {
  console.log('%c🔧 Floor Plan Buttons Quick Fix', 'font-size: 18px; color: #10b981; font-weight: bold');
  
  // 1. Check if we're on the right tab
  const buildingTab = document.getElementById('tab-building');
  if (!buildingTab || window.getComputedStyle(buildingTab).display === 'none') {
    console.error('❌ Floor Plan Sketch tab is not active!');
    console.log('Please go to: Management > Floor Plan Sketch');
    return;
  }
  
  // 2. Force Setup button visible
  const setupBtn = document.getElementById('setupFloorBtn');
  if (setupBtn) {
    setupBtn.style.display = '';
    setupBtn.style.visibility = 'visible';
    setupBtn.style.opacity = '1';
    console.log('✅ Setup button forced visible');
  } else {
    console.error('❌ Setup button not found in DOM - page may need hard refresh (Ctrl+Shift+R)');
  }
  
  // 3. Check Publish button (initially hidden is correct)
  const publishBtn = document.getElementById('publishFloorBtn');
  if (publishBtn) {
    console.log('✅ Publish button exists (hidden until Setup complete - this is correct)');
  } else {
    console.error('❌ Publish button not found in DOM');
  }
  
  // 4. Check Gateway Properties panel
  const propGatewayGroup = document.getElementById('propGatewayGroup');
  const propGatewayRegister = document.getElementById('propGatewayRegister');
  
  if (propGatewayGroup && propGatewayRegister) {
    console.log('✅ Gateway Properties panel and Register button exist');
    console.log('   (They show when you select a gateway icon)');
  } else {
    console.error('❌ Gateway Properties elements not found');
  }
  
  // 5. Check integration script loaded
  setTimeout(() => {
    if (window.showProperties && window.showProperties.toString().length > 200) {
      console.log('✅ Integration script appears to be loaded');
    } else {
      console.warn('⚠️ Integration script may not have loaded - try hard refresh');
    }
  }, 1000);
  
  console.log('\n%c📋 Quick Test Checklist:', 'font-size: 14px; font-weight: bold');
  console.log('1. ✓ Refresh page with Ctrl+Shift+R (Windows) or Cmd+Shift+R (Mac)');
  console.log('2. ✓ Go to Management section (left sidebar)');
  console.log('3. ✓ Click "Floor Plan Sketch" (should see canvas drawing tool)');
  console.log('4. ✓ Look at top toolbar - you should see:');
  console.log('     - Undo/Redo buttons');
  console.log('     - Import button');
  console.log('     - Save button');
  console.log('     - Export buttons');
  console.log('     - Preview button');
  console.log('     - [divider line]');
  console.log('     - 🔷 Setup button (blue background)');
  console.log('     - 🟢 Publish button (green, hidden initially)');
  console.log('\n5. ✓ Use Gateway tool (FEATURES section on left) to place gateway');
  console.log('6. ✓ Click the gateway icon to select it');
  console.log('7. ✓ Look at Properties panel (right side) - should show:');
  console.log('     - ESP32 Gateway section');
  console.log('     - MAC Address input field');
  console.log('     - Status indicator');
  console.log('     - Register Gateway button');
  
  console.log('\n%c🔄 If buttons still missing:', 'font-size: 14px; color: #ef4444; font-weight: bold');
  console.log('1. Hard refresh: Ctrl+Shift+R (Windows) or Cmd+Shift+R (Mac)');
  console.log('2. Clear cache: Browser Settings > Clear browsing data');
  console.log('3. Check deployment: GitHub Actions should show latest commit deployed');
  console.log('4. Verify URL: Make sure you\'re on pinplot.me (not localhost)');
  
})();
