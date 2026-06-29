/**
 * EMERGENCY FLOOR PLAN BUTTONS DEBUG & FIX
 * 
 * Paste this entire script in browser console (F12 > Console)
 * It will diagnose and FIX button visibility issues
 */

(function() {
  console.log('%c🚨 EMERGENCY BUTTON DEBUG', 'font-size: 20px; color: #ef4444; font-weight: bold');
  console.log('=====================================\n');

  // 1. Check if Floor Plan Sketch tab is active
  const buildingTab = document.getElementById('tab-building');
  const buildingNavBtn = document.querySelector('[data-tab="building"]');
  
  if (!buildingTab) {
    console.error('❌ Floor Plan Sketch tab not found!');
    return;
  }
  
  const tabVisible = window.getComputedStyle(buildingTab).display !== 'none';
  console.log(`Tab visibility: ${tabVisible ? '✅ VISIBLE' : '❌ HIDDEN'}`);
  
  if (!tabVisible) {
    console.log('\n%c🔧 FIX: Switching to Floor Plan Sketch tab...', 'color: #f59e0b; font-weight: bold');
    if (window.switchTab) {
      window.switchTab('building');
      console.log('✅ Tab switched!');
    } else if (buildingNavBtn) {
      buildingNavBtn.click();
      console.log('✅ Tab clicked!');
    } else {
      console.error('❌ Cannot switch tab automatically. Please click "Floor Plan Sketch" in the sidebar.');
      return;
    }
  }

  // 2. Check buttons exist
  const setupBtn = document.getElementById('setupFloorBtn');
  const publishBtn = document.getElementById('publishFloorBtn');
  const propMac = document.getElementById('propMac');
  const propRegisterGateway = document.getElementById('propRegisterGateway');
  
  console.log('\n📍 Button Existence Check:');
  console.log('Setup button:', setupBtn ? '✅ EXISTS' : '❌ MISSING');
  console.log('Publish button:', publishBtn ? '✅ EXISTS' : '❌ MISSING');
  console.log('MAC input:', propMac ? '✅ EXISTS' : '❌ MISSING');
  console.log('Register button:', propRegisterGateway ? '✅ EXISTS' : '❌ MISSING');

  if (!setupBtn || !publishBtn) {
    console.error('\n❌ CRITICAL: Buttons missing from DOM!');
    console.log('Hard refresh needed: Ctrl+Shift+R (Windows) or Cmd+Shift+R (Mac)');
    return;
  }

  // 3. Check button visibility
  console.log('\n📍 Button Visibility Check:');
  
  const setupStyle = window.getComputedStyle(setupBtn);
  const setupVisible = setupBtn.offsetParent !== null;
  console.log('Setup button:');
  console.log('  - offsetParent:', setupBtn.offsetParent ? '✅ has parent' : '❌ null (invisible)');
  console.log('  - display:', setupStyle.display);
  console.log('  - visibility:', setupStyle.visibility);
  console.log('  - opacity:', setupStyle.opacity);
  console.log('  - Visible?', setupVisible ? '✅ YES' : '❌ NO');

  const publishStyle = window.getComputedStyle(publishBtn);
  const publishVisible = publishBtn.offsetParent !== null;
  console.log('\nPublish button:');
  console.log('  - offsetParent:', publishBtn.offsetParent ? '✅ has parent' : '❌ null (hidden initially - correct)');
  console.log('  - display:', publishStyle.display);
  console.log('  - visibility:', publishStyle.visibility);
  console.log('  - opacity:', publishStyle.opacity);
  console.log('  - Visible?', publishVisible ? '✅ YES' : '❌ NO (expected - shows after Setup)');

  // 4. Check header visibility
  const header = setupBtn.closest('.sk-header');
  if (header) {
    const headerStyle = window.getComputedStyle(header);
    const headerVisible = header.offsetParent !== null;
    console.log('\nHeader container:');
    console.log('  - display:', headerStyle.display);
    console.log('  - visibility:', headerStyle.visibility);
    console.log('  - opacity:', headerStyle.opacity);
    console.log('  - Visible?', headerVisible ? '✅ YES' : '❌ NO');
    
    if (!headerVisible) {
      console.log('\n%c🔧 FIX: Header hidden - forcing visible...', 'color: #f59e0b; font-weight: bold');
      header.style.display = '';
      header.style.visibility = 'visible';
      header.style.opacity = '1';
      console.log('✅ Header forced visible!');
    }
  }

  // 5. Check sketch-root visibility
  const sketchRoot = document.getElementById('sketch-root');
  if (sketchRoot) {
    const rootStyle = window.getComputedStyle(sketchRoot);
    const rootVisible = sketchRoot.offsetParent !== null;
    console.log('\nSketch root container:');
    console.log('  - display:', rootStyle.display);
    console.log('  - visibility:', rootStyle.visibility);
    console.log('  - opacity:', rootStyle.opacity);
    console.log('  - Visible?', rootVisible ? '✅ YES' : '❌ NO');
    
    if (!rootVisible) {
      console.log('\n%c🔧 FIX: Sketch root hidden - forcing visible...', 'color: #f59e0b; font-weight: bold');
      sketchRoot.style.display = '';
      sketchRoot.style.visibility = 'visible';
      sketchRoot.style.opacity = '1';
      console.log('✅ Sketch root forced visible!');
    }
  }

  // 6. Force buttons visible if needed
  if (!setupVisible) {
    console.log('\n%c🔧 FIX: Setup button hidden - forcing visible...', 'color: #f59e0b; font-weight: bold');
    setupBtn.style.display = '';
    setupBtn.style.visibility = 'visible';
    setupBtn.style.opacity = '1';
    setupBtn.style.position = '';
    setupBtn.style.top = '';
    setupBtn.style.left = '';
    console.log('✅ Setup button forced visible!');
  }

  // 7. Check canvas/grid
  const canvas = document.getElementById('canvas');
  if (canvas) {
    const canvasStyle = window.getComputedStyle(canvas);
    console.log('\n📍 Canvas Check:');
    console.log('  - display:', canvasStyle.display);
    console.log('  - visibility:', canvasStyle.visibility);
    console.log('  - width:', canvas.width);
    console.log('  - height:', canvas.height);
  } else {
    console.log('\n⚠️ Canvas not found - sketch app may not have initialized');
  }

  // 8. Check if sketch app loaded
  console.log('\n📍 Sketch App State:');
  console.log('  - window.state:', window.state ? '✅ EXISTS' : '❌ MISSING');
  console.log('  - window.render:', typeof window.render === 'function' ? '✅ EXISTS' : '❌ MISSING');
  console.log('  - window.showProperties:', typeof window.showProperties === 'function' ? '✅ EXISTS' : '❌ MISSING');

  if (!window.state) {
    console.error('\n❌ Sketch app not initialized!');
    console.log('Check for JavaScript errors in console');
    console.log('Try: Hard refresh (Ctrl+Shift+R)');
  }

  // 9. Summary
  console.log('\n%c━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━', 'color: #6b7280');
  console.log('%c📊 DIAGNOSIS COMPLETE', 'font-size: 16px; color: #10b981; font-weight: bold');
  
  if (setupVisible && window.state) {
    console.log('\n%c✅ ALL SYSTEMS NORMAL!', 'color: #10b981; font-size: 14px; font-weight: bold');
    console.log('Setup button should be visible in the top toolbar.');
    console.log('If you still can\'t see it, try:');
    console.log('1. Zoom out browser (Ctrl+- or Cmd+-)');
    console.log('2. Make window wider');
    console.log('3. Scroll top toolbar left/right');
  } else {
    console.log('\n%c⚠️ ISSUES DETECTED', 'color: #f59e0b; font-size: 14px; font-weight: bold');
    if (!setupVisible) console.log('❌ Setup button not visible');
    if (!window.state) console.log('❌ Sketch app not initialized');
    console.log('\n🔄 RECOMMENDED ACTIONS:');
    console.log('1. Hard refresh: Ctrl+Shift+R (Windows) or Cmd+Shift+R (Mac)');
    console.log('2. Clear browser cache');
    console.log('3. Check browser console for JavaScript errors');
  }

  console.log('\n%c🎮 HELPER FUNCTIONS', 'font-size: 14px; color: #3b82f6; font-weight: bold');
  console.log('Run these to interact:');
  console.log('  forceShowButtons()     - Force all buttons visible');
  console.log('  reinitSketch()         - Reload sketch app');
  console.log('  checkGridLines()       - Check grid rendering');

  window.forceShowButtons = () => {
    if (setupBtn) {
      setupBtn.style.display = '';
      setupBtn.style.visibility = 'visible';
      setupBtn.style.opacity = '1';
    }
    if (publishBtn) {
      publishBtn.style.display = '';
      publishBtn.style.visibility = 'visible';
      publishBtn.style.opacity = '1';
    }
    if (header) {
      header.style.display = '';
      header.style.visibility = 'visible';
      header.style.opacity = '1';
    }
    console.log('✅ All buttons forced visible');
  };

  window.reinitSketch = () => {
    const script = document.createElement('script');
    script.src = '/customer/sketch/app.js?' + Date.now();
    document.body.appendChild(script);
    console.log('✅ Sketch app reload triggered');
  };

  window.checkGridLines = () => {
    const canvas = document.getElementById('canvas');
    if (!canvas) {
      console.log('❌ Canvas not found');
      return;
    }
    const ctx = canvas.getContext('2d');
    console.log('Canvas:', { width: canvas.width, height: canvas.height });
    console.log('Context:', ctx);
    console.log('Grid should be rendered by sketch app');
    if (window.render) {
      console.log('Calling render()...');
      window.render();
    }
  };

  console.log('\n%c━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━', 'color: #6b7280');

})();
