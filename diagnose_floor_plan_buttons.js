/**
 * Floor Plan Sketch Button Diagnostic Script
 * 
 * USAGE:
 * 1. Open pinplot.me customer dashboard
 * 2. Go to Management > Floor Plan Sketch tab
 * 3. Open browser console (F12 > Console tab)
 * 4. Copy and paste this entire script
 * 5. Press Enter to run
 * 6. Check the diagnostic output
 */

(function() {
  console.clear();
  console.log('%c🔍 Floor Plan Sketch Diagnostic', 'font-size: 20px; color: #10b981; font-weight: bold');
  console.log('=====================================\n');

  const tests = [];
  
  // Test 1: Button existence
  console.log('%c📍 Test 1: Button Elements', 'font-size: 16px; color: #3b82f6; font-weight: bold');
  
  const setupBtn = document.getElementById('setupFloorBtn');
  const publishBtn = document.getElementById('publishFloorBtn');
  const propGatewayMac = document.getElementById('propGatewayMac');
  const propGatewayRegister = document.getElementById('propGatewayRegister');
  const propGatewayGroup = document.getElementById('propGatewayGroup');
  const propGatewayStatus = document.getElementById('propGatewayStatus');
  
  if (setupBtn) {
    const visible = setupBtn.offsetParent !== null;
    const style = window.getComputedStyle(setupBtn);
    console.log(`✅ Setup Button: FOUND (${visible ? 'VISIBLE' : 'HIDDEN'})`, {
      element: setupBtn,
      display: style.display,
      visibility: style.visibility,
      position: {
        top: setupBtn.offsetTop,
        left: setupBtn.offsetLeft
      }
    });
    tests.push({ name: 'Setup Button', status: 'pass', visible });
  } else {
    console.log('%c❌ Setup Button: NOT FOUND', 'color: #ef4444; font-weight: bold');
    tests.push({ name: 'Setup Button', status: 'fail' });
  }
  
  if (publishBtn) {
    const visible = publishBtn.offsetParent !== null;
    const style = window.getComputedStyle(publishBtn);
    console.log(`${visible ? '✅' : '⚠️'} Publish Button: FOUND (${visible ? 'VISIBLE' : 'HIDDEN - expected until Setup complete'})`, {
      element: publishBtn,
      display: style.display,
      visibility: style.visibility
    });
    tests.push({ name: 'Publish Button', status: visible ? 'pass' : 'warn', visible });
  } else {
    console.log('%c❌ Publish Button: NOT FOUND', 'color: #ef4444; font-weight: bold');
    tests.push({ name: 'Publish Button', status: 'fail' });
  }
  
  if (propGatewayGroup) {
    const visible = propGatewayGroup.offsetParent !== null;
    const style = window.getComputedStyle(propGatewayGroup);
    console.log(`${visible ? '✅' : '⚠️'} Gateway Properties Panel: FOUND (${visible ? 'VISIBLE' : 'HIDDEN - shows when gateway selected'})`, {
      element: propGatewayGroup,
      display: style.display,
      visibility: style.visibility,
      hasRegisterButton: !!propGatewayRegister,
      hasMacInput: !!propGatewayMac
    });
    tests.push({ name: 'Gateway Properties', status: 'pass', visible });
  } else {
    console.log('%c❌ Gateway Properties Panel: NOT FOUND', 'color: #ef4444; font-weight: bold');
    tests.push({ name: 'Gateway Properties', status: 'fail' });
  }

  // Test 2: Integration script
  console.log('\n%c📍 Test 2: Integration Script', 'font-size: 16px; color: #3b82f6; font-weight: bold');
  
  if (window.showProperties) {
    const hooked = window.showProperties.toString().includes('propGatewayGroup') || 
                   window.showProperties.toString().includes('gateway');
    if (hooked) {
      console.log('✅ showProperties: HOOKED by integration script');
      tests.push({ name: 'showProperties Hook', status: 'pass' });
    } else {
      console.log('⚠️ showProperties: EXISTS but NOT hooked', {
        hint: 'Integration script may not have executed',
        function: window.showProperties
      });
      tests.push({ name: 'showProperties Hook', status: 'warn' });
    }
  } else {
    console.log('%c❌ showProperties: NOT FOUND', 'color: #ef4444; font-weight: bold', {
      hint: 'Sketch app (app.js) may not have loaded'
    });
    tests.push({ name: 'showProperties', status: 'fail' });
  }

  // Test 3: Sketch app state
  console.log('\n%c📍 Test 3: Sketch App State', 'font-size: 16px; color: #3b82f6; font-weight: bold');
  
  if (window.state) {
    console.log('✅ Sketch State: LOADED', {
      state: window.state,
      floors: window.state.floors?.length || 0,
      currentFloor: window.state.currentFloor,
      elements: window.state.floors?.[window.state.currentFloor]?.elements?.length || 0,
      tool: window.state.tool
    });
    tests.push({ name: 'Sketch State', status: 'pass' });
  } else {
    console.log('%c❌ Sketch State: NOT FOUND', 'color: #ef4444; font-weight: bold', {
      hint: 'Sketch app may not have initialized'
    });
    tests.push({ name: 'Sketch State', status: 'fail' });
  }

  // Test 4: Tab visibility
  console.log('\n%c📍 Test 4: Tab Visibility', 'font-size: 16px; color: #3b82f6; font-weight: bold');
  
  const buildingTab = document.getElementById('tab-building');
  if (buildingTab) {
    const style = window.getComputedStyle(buildingTab);
    const visible = style.display !== 'none';
    console.log(`${visible ? '✅' : '❌'} Floor Plan Sketch Tab: ${visible ? 'ACTIVE' : 'HIDDEN'}`, {
      element: buildingTab,
      display: style.display,
      hint: visible ? 'Tab is active' : 'Switch to Floor Plan Sketch tab in Management section'
    });
    tests.push({ name: 'Tab Visibility', status: visible ? 'pass' : 'fail' });
  } else {
    console.log('%c❌ Tab: NOT FOUND', 'color: #ef4444; font-weight: bold');
    tests.push({ name: 'Tab', status: 'fail' });
  }

  // Test 5: Modals
  console.log('\n%c📍 Test 5: Modal Elements', 'font-size: 16px; color: #3b82f6; font-weight: bold');
  
  const setupModal = document.getElementById('sketchSetupModal');
  const gatewayModal = document.getElementById('sketchGatewayModal');
  
  if (setupModal) {
    console.log('✅ Setup Modal: FOUND', { element: setupModal });
    tests.push({ name: 'Setup Modal', status: 'pass' });
  } else {
    console.log('%c❌ Setup Modal: NOT FOUND', 'color: #ef4444; font-weight: bold');
    tests.push({ name: 'Setup Modal', status: 'fail' });
  }
  
  if (gatewayModal) {
    console.log('✅ Gateway Modal: FOUND (optional)', { element: gatewayModal });
    tests.push({ name: 'Gateway Modal', status: 'pass' });
  } else {
    console.log('⚠️ Gateway Modal: NOT FOUND (optional - Properties panel should work)', {
      hint: 'Gateway modal is optional, Properties panel is the main interface'
    });
    tests.push({ name: 'Gateway Modal', status: 'warn' });
  }

  // Summary
  console.log('\n%c━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━', 'color: #6b7280');
  console.log('%c📊 Summary', 'font-size: 18px; color: #10b981; font-weight: bold');
  
  const passed = tests.filter(t => t.status === 'pass').length;
  const failed = tests.filter(t => t.status === 'fail').length;
  const warnings = tests.filter(t => t.status === 'warn').length;
  
  console.log(`✅ Passed: ${passed}`);
  console.log(`❌ Failed: ${failed}`);
  console.log(`⚠️ Warnings: ${warnings}`);
  
  if (failed > 0) {
    console.log('\n%c🔧 ISSUES DETECTED', 'font-size: 16px; color: #ef4444; font-weight: bold');
    console.log('Failed tests:', tests.filter(t => t.status === 'fail').map(t => t.name).join(', '));
    console.log('\n💡 Possible causes:');
    console.log('1. You may not be on the Floor Plan Sketch tab (go to Management > Floor Plan Sketch)');
    console.log('2. The page may not have fully loaded (try refreshing)');
    console.log('3. The integration code may not be deployed yet');
    console.log('4. Check browser console for JavaScript errors');
  } else {
    console.log('\n%c✨ ALL TESTS PASSED!', 'font-size: 16px; color: #10b981; font-weight: bold');
    console.log('\n📝 If you still don\'t see buttons, try:');
    console.log('1. Refresh the page (Ctrl+R / Cmd+R)');
    console.log('2. Clear browser cache (Ctrl+Shift+R / Cmd+Shift+R)');
    console.log('3. Make sure you\'re on the Floor Plan Sketch tab (not Floor Plan viewing tab)');
  }

  // Interactive helpers
  console.log('\n%c🎮 Interactive Helpers', 'font-size: 16px; color: #f59e0b; font-weight: bold');
  console.log('Run these commands to interact with the system:');
  console.log('  showSetupButton()     - Make Setup button visible');
  console.log('  showPublishButton()   - Make Publish button visible');
  console.log('  testSetupFlow()       - Open Setup modal');
  console.log('  testGatewayProps()    - Show Gateway properties panel');
  console.log('  listGateways()        - Show all gateway elements in sketch');

  window.showSetupButton = () => {
    if (setupBtn) {
      setupBtn.style.display = '';
      setupBtn.style.visibility = 'visible';
      console.log('✅ Setup button display forced');
    } else {
      console.log('❌ Setup button not found');
    }
  };

  window.showPublishButton = () => {
    if (publishBtn) {
      publishBtn.style.display = '';
      publishBtn.style.visibility = 'visible';
      console.log('✅ Publish button display forced');
    } else {
      console.log('❌ Publish button not found');
    }
  };

  window.testSetupFlow = () => {
    if (setupBtn) {
      setupBtn.click();
      console.log('✅ Setup button clicked');
    } else {
      console.log('❌ Setup button not found');
    }
  };

  window.testGatewayProps = () => {
    if (propGatewayGroup) {
      propGatewayGroup.style.display = 'block';
      if (propGatewayMac) propGatewayMac.value = 'A4:CF:12:45:AB:CD';
      if (propGatewayStatus) {
        propGatewayStatus.textContent = 'Not Registered';
        propGatewayStatus.style.background = '#f59e0b';
        propGatewayStatus.style.color = 'white';
      }
      console.log('✅ Gateway properties panel shown with test MAC');
    } else {
      console.log('❌ Gateway properties panel not found');
    }
  };

  window.listGateways = () => {
    if (window.state && window.state.floors) {
      const gateways = window.state.floors[window.state.currentFloor]?.elements?.filter(el => el.type === 'gateway') || [];
      console.log(`Found ${gateways.length} gateway(s) in current floor:`, gateways);
      return gateways;
    } else {
      console.log('❌ Sketch state not available');
      return [];
    }
  };

  console.log('\n%c━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━', 'color: #6b7280');
  console.log('Diagnostic complete! Check results above.');

  return tests;
})();
