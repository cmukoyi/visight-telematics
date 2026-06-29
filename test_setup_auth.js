// Test Setup Button Authentication
// Run this in browser console on pinplot.me

console.log('=== Floor Plan Setup Authentication Diagnostic ===\n');

// 1. Check if user is logged in
console.log('1️⃣ Checking session...');
try {
  const session = getSession();
  console.log('✅ Session exists:', {
    user_id: session.user_id,
    username: session.username,
    usergroup_id: session.usergroup_id,
    token_length: session.token ? session.token.length : 0,
    token_preview: session.token ? session.token.substring(0, 20) + '...' : 'MISSING'
  });
  
  if (!session.token) {
    console.error('❌ NO TOKEN! User is not logged in.');
    console.log('➡️ Please log in first');
  }
} catch (err) {
  console.error('❌ getSession() failed:', err);
  console.log('➡️ User is not logged in');
}

// 2. Check authHeaders function
console.log('\n2️⃣ Checking authHeaders()...');
try {
  const headers = authHeaders();
  console.log('✅ Auth headers:', {
    Authorization: headers.Authorization ? headers.Authorization.substring(0, 30) + '...' : 'MISSING',
    'Content-Type': headers['Content-Type']
  });
} catch (err) {
  console.error('❌ authHeaders() failed:', err);
}

// 3. Test the API call
console.log('\n3️⃣ Testing /api/portal/buildings...');
apiFetch('/api/portal/buildings')
  .then(async res => {
    console.log('Response status:', res.status, res.statusText);
    if (res.ok) {
      const buildings = await res.json();
      console.log('✅ SUCCESS! Buildings:', buildings);
    } else {
      const error = await res.json();
      console.error('❌ API ERROR:', error);
    }
  })
  .catch(err => {
    console.error('❌ Fetch failed:', err);
  });

console.log('\n=== Waiting for API response... ===');
