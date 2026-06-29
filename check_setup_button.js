// ══════════════════════════════════════════════════════════════
// SETUP BUTTON DIAGNOSTIC - Paste in console
// ══════════════════════════════════════════════════════════════

console.clear();
console.log('%c🔧 SETUP BUTTON DIAGNOSTIC', 'font-size: 20px; color: #f59e0b; font-weight: bold');
console.log('═══════════════════════════════════════\n');

// Check if setup button exists
const setupBtn = document.getElementById('setupFloorBtn');
console.log('1️⃣  Setup Button:', setupBtn ? '✅ EXISTS' : '❌ NOT FOUND');

if (setupBtn) {
  // Check if event listener is attached
  const listeners = getEventListeners(setupBtn);
  console.log('2️⃣  Event Listeners:', listeners.click ? `✅ ${listeners.click.length} click handler(s)` : '❌ NONE');
  
  // Check modal exists
  const modal = document.getElementById('sketchSetupModal');
  console.log('3️⃣  Setup Modal:', modal ? '✅ EXISTS' : '❌ NOT FOUND');
  
  // Check if restoreFloorLink function exists
  console.log('4️⃣  Integration Script Loaded:', typeof restoreFloorLink !== 'undefined' ? '❌ NO (restoreFloorLink in global scope)' : '✅ YES (functions are scoped)');
  
  // Try to click programmatically
  console.log('\n📍 Trying to click Setup button...');
  try {
    setupBtn.click();
    console.log('✅ Click executed');
    
    setTimeout(() => {
      const modalVisible = modal && window.getComputedStyle(modal).display !== 'none';
      console.log('📍 Modal visible after click:', modalVisible ? '✅ YES' : '❌ NO');
      
      if (!modalVisible && modal) {
        console.log('   Modal display:', window.getComputedStyle(modal).display);
      }
    }, 100);
  } catch (e) {
    console.error('❌ Click failed:', e);
  }
}

// Check for JavaScript errors
console.log('\n5️⃣  Check browser console for RED errors above this line');

// Check deployment timestamp
console.log('\n6️⃣  Checking deployment timestamp...');
const scripts = Array.from(document.querySelectorAll('script'));
const inlineScripts = scripts.filter(s => !s.src && s.textContent.includes('Floor Plan'));
console.log('   Inline scripts with "Floor Plan":', inlineScripts.length);

// Look for the new logging
const hasNewLogging = inlineScripts.some(s => s.textContent.includes('[Floor Plan]'));
console.log('   New logging code present:', hasNewLogging ? '✅ YES (deployed)' : '❌ NO (not deployed yet)');

// Check if localStorage persistence code exists
const hasLocalStorageCode = inlineScripts.some(s => s.textContent.includes('pinplot_floor_link_v1'));
console.log('   localStorage persistence:', hasLocalStorageCode ? '✅ YES' : '❌ NO');

console.log('\n═══════════════════════════════════════');
console.log('%c📊 DIAGNOSIS', 'color: #3b82f6; font-size: 14px; font-weight: bold\n');

if (!hasNewLogging) {
  console.log('%c❌ NEW CODE NOT DEPLOYED YET', 'color: #ef4444; font-weight: bold');
  console.log('   GitHub Actions is still deploying.');
  console.log('   Wait 1-2 more minutes, then hard refresh (Ctrl+Shift+R)');
} else {
  console.log('%c✅ NEW CODE IS DEPLOYED', 'color: #10b981; font-weight: bold');
  console.log('   If Setup button does nothing:');
  console.log('   1. Check for RED JavaScript errors in console');
  console.log('   2. Try hard refresh: Ctrl+Shift+R (Windows) or Cmd+Shift+R (Mac)');
  console.log('   3. Try opening in incognito window');
}

console.log('\n═══════════════════════════════════════\n');
