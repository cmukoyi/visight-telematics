// Debug Why Modal Won't Open
// Run this in console AFTER clicking Setup button

console.log('=== Modal Debug ===\n');

const modal = document.getElementById('sketchSetupModal');

console.log('1️⃣ Modal element:', modal);
console.log('2️⃣ Current display style:', modal.style.display);
console.log('3️⃣ Computed display:', window.getComputedStyle(modal).display);
console.log('4️⃣ Parent element:', modal.parentElement);
console.log('5️⃣ Modal classes:', modal.className);

console.log('\n6️⃣ Checking for CSS that might hide it...');
const styles = window.getComputedStyle(modal);
console.log('   visibility:', styles.visibility);
console.log('   opacity:', styles.opacity);
console.log('   z-index:', styles.zIndex);
console.log('   position:', styles.position);

console.log('\n7️⃣ Trying to force modal open...');
modal.style.display = 'flex';
modal.style.visibility = 'visible';
modal.style.opacity = '1';
modal.style.zIndex = '9999';

console.log('   After forced display:', modal.style.display);
console.log('   After computed display:', window.getComputedStyle(modal).display);

console.log('\n8️⃣ Is modal visible now?');
setTimeout(() => {
  console.log('   Computed display after 1s:', window.getComputedStyle(modal).display);
  console.log('   Modal rect:', modal.getBoundingClientRect());
}, 1000);
