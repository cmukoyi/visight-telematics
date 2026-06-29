/**
 * QUICK FIX - Paste in console NOW
 * Forces buttons visible immediately
 */

// Force buttons visible
document.getElementById('setupFloorBtn').style.cssText = 'display:inline-flex !important; visibility:visible !important; opacity:1 !important';
document.getElementById('publishFloorBtn').style.cssText = 'display:inline-flex !important; visibility:visible !important; opacity:1 !important';

// Force header visible
const header = document.querySelector('.sk-header');
if (header) header.style.cssText = 'display:flex !important; visibility:visible !important; opacity:1 !important';

// Force sketch root visible  
const root = document.getElementById('sketch-root');
if (root) root.style.cssText = 'display:block !important; visibility:visible !important; opacity:1 !important';

// Force canvas visible
const canvas = document.getElementById('canvas');
if (canvas) canvas.style.cssText = 'display:block !important; visibility:visible !important; opacity:1 !important';

// Trigger render
if (window.render) window.render();

console.log('✅ FORCED ALL VISIBLE - Check UI now!');
