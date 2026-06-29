// ═══════════════════════════════════════════════════════════════
// FLOOR PLAN BUTTONS - ULTIMATE FIX & DIAGNOSTIC
// Paste this ENTIRE script in browser console (F12 > Console)
// ═══════════════════════════════════════════════════════════════

console.clear();
console.log('%c╔══════════════════════════════════════╗', 'color: #00ff00');
console.log('%c║  FLOOR PLAN BUTTONS DIAGNOSTIC       ║', 'color: #00ff00; font-weight: bold');
console.log('%c╚══════════════════════════════════════╝', 'color: #00ff00');

// Helper function to log results
function logTest(name, pass, details = '') {
  const icon = pass ? '✅' : '❌';
  const color = pass ? '#00ff00' : '#ff6666';
  console.log(`%c${icon} ${name}`, `color: ${color}; font-weight: bold`);
  if (details) console.log(`   ${details}`);
}

// ═══════════════════════════════════════════════════════════════
// STEP 1: Check tab existence and visibility
// ═══════════════════════════════════════════════════════════════
console.log('\n%c📍 STEP 1: Tab Existence', 'color: #3b82f6; font-size: 14px; font-weight: bold');

const tab = document.getElementById('tab-building');
logTest('Tab #tab-building exists', !!tab);

if (!tab) {
  console.log('%c⛔ CRITICAL ERROR: Floor Plan Sketch tab not found in DOM!', 'color: #ff0000; font-size: 14px; font-weight: bold');
  console.log('   This means the HTML was not deployed correctly.');
  console.log('   Action: Hard refresh (Ctrl+Shift+R) or check deployment.');
  throw new Error('Tab not found');
}

const tabDisplay = window.getComputedStyle(tab).display;
const tabVisible = tabDisplay !== 'none';
logTest('Tab is visible', tabVisible, `display: ${tabDisplay}`);

// ═══════════════════════════════════════════════════════════════
// STEP 2: Check sketch-root container
// ═══════════════════════════════════════════════════════════════
console.log('\n%c📍 STEP 2: Sketch Root Container', 'color: #3b82f6; font-size: 14px; font-weight: bold');

const sketchRoot = document.getElementById('sketch-root');
logTest('sketch-root exists', !!sketchRoot);

if (sketchRoot) {
  const rootStyle = window.getComputedStyle(sketchRoot);
  const rootVisible = rootStyle.display !== 'none';
  logTest('sketch-root visible', rootVisible, `display: ${rootStyle.display}`);
  
  const cssVars = rootStyle.getPropertyValue('--primary');
  logTest('CSS variables loaded', !!cssVars, `--primary: ${cssVars || 'NOT LOADED'}`);
}

// ═══════════════════════════════════════════════════════════════
// STEP 3: Check header and buttons
// ═══════════════════════════════════════════════════════════════
console.log('\n%c📍 STEP 3: Header & Buttons', 'color: #3b82f6; font-size: 14px; font-weight: bold');

const header = document.querySelector('#sketch-root .sk-header');
logTest('sk-header exists', !!header);

if (header) {
  const headerStyle = window.getComputedStyle(header);
  const headerVisible = header.offsetParent !== null;
  logTest('sk-header visible', headerVisible, `display: ${headerStyle.display}`);
}

const setupBtn = document.getElementById('setupFloorBtn');
logTest('setupFloorBtn exists', !!setupBtn);

if (setupBtn) {
  const btnStyle = window.getComputedStyle(setupBtn);
  const btnVisible = setupBtn.offsetParent !== null;
  logTest('setupFloorBtn visible', btnVisible, 
    `display: ${btnStyle.display}, visibility: ${btnStyle.visibility}, opacity: ${btnStyle.opacity}`);
  
  // Check parent chain
  let parent = setupBtn.parentElement;
  let depth = 0;
  console.log('   Parent chain:');
  while (parent && depth < 5) {
    const pStyle = window.getComputedStyle(parent);
    const pVisible = pStyle.display !== 'none' && pStyle.visibility !== 'hidden';
    console.log(`     ${depth + 1}. <${parent.tagName}> ${parent.id ? '#' + parent.id : ''} ${parent.className ? '.' + parent.className.split(' ').join('.') : ''} - visible: ${pVisible}`);
    parent = parent.parentElement;
    depth++;
  }
}

const publishBtn = document.getElementById('publishFloorBtn');
logTest('publishFloorBtn exists', !!publishBtn);

if (publishBtn) {
  const btnStyle = window.getComputedStyle(publishBtn);
  logTest('publishFloorBtn display', btnStyle.display === 'none', 
    `display: ${btnStyle.display} (should be 'none' initially)`);
}

// ═══════════════════════════════════════════════════════════════
// STEP 4: Check canvas and sketch app
// ═══════════════════════════════════════════════════════════════
console.log('\n%c📍 STEP 4: Canvas & Sketch App', 'color: #3b82f6; font-size: 14px; font-weight: bold');

const canvas = document.getElementById('mainCanvas');
logTest('mainCanvas exists', !!canvas);

if (canvas) {
  const canvasStyle = window.getComputedStyle(canvas);
  logTest('canvas visible', canvasStyle.display !== 'none', 
    `display: ${canvasStyle.display}, ${canvas.width}x${canvas.height}`);
}

logTest('window.state exists', !!window.state, typeof window.state);
logTest('window.render exists', typeof window.render === 'function', typeof window.render);
logTest('window.resizeCanvases exists', typeof window.resizeCanvases === 'function', typeof window.resizeCanvases);

// ═══════════════════════════════════════════════════════════════
// DIAGNOSIS & RECOMMENDATIONS
// ═══════════════════════════════════════════════════════════════
console.log('\n%c━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━', 'color: #6b7280');
console.log('%c📊 DIAGNOSIS', 'color: #f59e0b; font-size: 16px; font-weight: bold');

let issues = [];
let canAutoFix = true;

if (!tabVisible) {
  issues.push('❌ Floor Plan Sketch tab is NOT visible');
  console.log('%c⚠️ You need to click "Floor Plan Sketch (Beta)" in the sidebar!', 'color: #f59e0b; font-size: 14px');
  canAutoFix = true;
} else if (setupBtn && setupBtn.offsetParent === null) {
  issues.push('❌ Setup button exists but not visible');
  console.log('%c⚠️ Button is in DOM but CSS is hiding it', 'color: #f59e0b; font-size: 14px');
  canAutoFix = true;
} else if (!window.state) {
  issues.push('❌ Sketch app not initialized');
  console.log('%c⚠️ sketch/app.js did not load or threw an error', 'color: #f59e0b; font-size: 14px');
  canAutoFix = false;
} else if (setupBtn && setupBtn.offsetParent !== null) {
  console.log('%c✅ ALL SYSTEMS NORMAL!', 'color: #10b981; font-size: 14px; font-weight: bold');
  console.log('   Setup button should be visible in the top toolbar.');
  console.log('   If you still can\'t see it:');
  console.log('   1. Try zooming out (Ctrl+- or Cmd+-)');
  console.log('   2. Make browser window wider');
  console.log('   3. Scroll the toolbar area');
}

// ═══════════════════════════════════════════════════════════════
// AUTO-FIX FUNCTION
// ═══════════════════════════════════════════════════════════════
if (canAutoFix && issues.length > 0) {
  console.log('\n%c🔧 AUTO-FIX AVAILABLE', 'color: #10b981; font-size: 14px; font-weight: bold');
  console.log('   Run this command to fix:');
  console.log('%c   fixButtons()', 'background: #10b981; color: #000; padding: 4px 8px; font-weight: bold');
}

window.fixButtons = function() {
  console.log('%c🔧 Applying fixes...', 'color: #f59e0b; font-weight: bold');
  
  // Force tab visible
  if (tab) {
    tab.classList.add('active');
    tab.style.display = 'flex';
    console.log('✅ Tab forced visible');
  }
  
  // Force sketch-root visible
  if (sketchRoot) {
    sketchRoot.style.display = 'flex';
    sketchRoot.style.visibility = 'visible';
    sketchRoot.style.opacity = '1';
    console.log('✅ sketch-root forced visible');
  }
  
  // Force header visible
  if (header) {
    header.style.display = 'flex';
    header.style.visibility = 'visible';
    header.style.opacity = '1';
    console.log('✅ sk-header forced visible');
  }
  
  // Force setup button visible
  if (setupBtn) {
    setupBtn.style.display = 'inline-flex';
    setupBtn.style.visibility = 'visible';
    setupBtn.style.opacity = '1';
    setupBtn.style.position = '';
    setupBtn.style.left = '';
    setupBtn.style.top = '';
    console.log('✅ Setup button forced visible');
  }
  
  // Force publish button visible (for testing)
  if (publishBtn) {
    publishBtn.style.display = 'inline-flex';
    publishBtn.style.visibility = 'visible';
    publishBtn.style.opacity = '1';
    console.log('✅ Publish button forced visible (for testing)');
  }
  
  // Resize and render
  if (window.resizeCanvases) {
    window.resizeCanvases();
    console.log('✅ Canvas resized');
  }
  
  if (window.render) {
    window.render();
    console.log('✅ Canvas rendered');
  }
  
  console.log('%c✅ FIX COMPLETE! Check the UI now.', 'color: #10b981; font-size: 14px; font-weight: bold');
};

// Also create a tab switcher
window.switchToSketch = function() {
  if (window.switchTab) {
    window.switchTab('building');
    console.log('%c✅ Switched to Floor Plan Sketch tab', 'color: #10b981; font-weight: bold');
    setTimeout(() => {
      if (window.resizeCanvases) window.resizeCanvases();
      if (window.render) window.render();
    }, 100);
  } else {
    console.log('%c❌ switchTab function not found', 'color: #ff0000');
  }
};

console.log('\n%c━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━', 'color: #6b7280');
console.log('%c🎮 AVAILABLE COMMANDS', 'color: #3b82f6; font-size: 14px; font-weight: bold');
console.log('   fixButtons()      - Force all buttons visible');
console.log('   switchToSketch()  - Switch to Floor Plan Sketch tab');
console.log('%c━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n', 'color: #6b7280');
