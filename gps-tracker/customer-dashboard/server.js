const express = require('express');
const cors = require('cors');
const path = require('path');
const fs = require('fs');

const app = express();
const PORT = process.env.PORT || 3001;
const BACKEND_URL = process.env.BACKEND_URL || 'http://backend:8000/api/v1';
const publicDir = path.join(__dirname, 'public');

console.log('='.repeat(60));
console.log('🚀 CUSTOMER DASHBOARD STARTING');
console.log('='.repeat(60));
console.log(`📍 Backend URL: ${BACKEND_URL}`);
console.log(`🖥️  Port: ${PORT}`);
console.log(`📂 Public directory: ${publicDir}`);
console.log(`⏰ Timestamp: ${new Date().toISOString()}`);

// List files in public directory
if (fs.existsSync(publicDir)) {
  const files = fs.readdirSync(publicDir);
  console.log(`\n📋 Files deployed (${files.length} files):`);
  files.forEach(file => {
    const stat = fs.statSync(path.join(publicDir, file));
    console.log(`   ✅ ${file} (${stat.size} bytes)`);
  });
}
console.log('='.repeat(60) + '\n');

// Disable cache for all static files
app.use((req, res, next) => {
  res.set('Cache-Control', 'no-store, no-cache, must-revalidate, max-age=0, post-check=0, pre-check=0');
  res.set('Pragma', 'no-cache');
  res.set('Expires', '0');
  res.set('ETag', `"${Date.now()}"`);
  next();
});

app.use(cors());
app.use(express.json());
app.use(express.static(publicDir));

// Health check endpoint
app.get('/health', (req, res) => {
  res.json({
    status: 'healthy',
    timestamp: new Date().toISOString(),
    uptime: process.uptime()
  });
});

// Pretty help routes - tenant-aware
// Maps /help/movement-analytics to tenant-specific manual based on branding
app.get('/help/movement-analytics', (req, res) => {
  const brandName = process.env.BRAND_NAME || 'PinPlot';
  const isBeacon = process.env.CUSTOMER_TENANT === 'beacon_telematics'
    || brandName.toLowerCase().includes('beacon');
  const language = String(req.query.lang || 'en').toLowerCase().split('-')[0];
  const beaconManuals = {
    de: 'Movement_Analytics_Benutzerhandbuch_v2_1_Beacon_DE.html',
    en: 'Movement_Analytics_User_Manual_v2_1_Beacon_EN.html',
    es: 'Movement_Analytics_Manual_Usuario_v2_1_Beacon_ES.html',
    fr: 'Movement_Analytics_Manuel_Utilisateur_v2_1_Beacon_FR.html',
    it: 'Movement_Analytics_Manuale_Utente_v2_1_Beacon_IT.html',
    nl: 'Movement_Analytics_Gebruikershandleiding_v2_1_Beacon_NL.html',
  };
  const filename = isBeacon
    ? (beaconManuals[language] || beaconManuals.en)
    : 'Movement_Analytics_User_Manual_v2_1_Pinplot.html';
  
  const filePath = path.join(publicDir, 'help', filename);
  
  if (fs.existsSync(filePath)) {
    res.sendFile(filePath);
  } else {
    res.status(404).json({ 
      error: 'Manual not found',
      tenant: brandName,
      expectedFile: filename 
    });
  }
});

// Pretty route for QR/NFC guide
app.get('/help/qr-nfc', (req, res) => {
  const brandName = process.env.BRAND_NAME || 'PinPlot';
  const isBeacon = brandName.toLowerCase().includes('beacon');
  const filename = isBeacon 
    ? 'QR_NFC_Guide_Beacon.html'
    : 'QR_NFC_Guide_Pinplot.html';
  
  const filePath = path.join(publicDir, 'help', filename);
  
  if (fs.existsSync(filePath)) {
    res.sendFile(filePath);
  } else {
    res.status(404).json({ 
      error: 'Guide not found',
      tenant: brandName,
      expectedFile: filename 
    });
  }
});

// Pretty route for HIVE manual
app.get('/help/hive', (req, res) => {
  const filePath = path.join(publicDir, 'help', 'HIVE_User_Manual.html');
  
  if (fs.existsSync(filePath)) {
    res.sendFile(filePath);
  } else {
    res.status(404).json({ error: 'HIVE manual not found' });
  }
});

// Manifest endpoint
app.get('/api/manifest', (req, res) => {
  const files = fs.existsSync(publicDir) ? fs.readdirSync(publicDir) : [];
  res.json({
    deployment: {
      timestamp: new Date().toISOString(),
      version: 'beacon-customer-dashboard'
    },
    files: files.map(file => ({
      name: file,
      size: fs.statSync(path.join(publicDir, file)).size
    }))
  });
});

// Serve index.html with server-side tenant-specific meta tag injection
// This ensures social media scrapers (WhatsApp, Facebook, Slack) that don't
// execute JavaScript see the correct tenant branding in Open Graph meta tags.
app.get('/', (req, res) => {
  const indexPath = path.join(publicDir, 'index.html');
  
  // Read the HTML file
  let html = fs.readFileSync(indexPath, 'utf8');
  
  // Read tenant branding from environment variables (same as /api/branding endpoint)
  const brandName = process.env.BRAND_NAME || 'PinPlot';
  const brandProduct = process.env.BRAND_PRODUCT || 'Customer Portal — Asset Tracking';
  const brandDomain = process.env.BRAND_DOMAIN || 'pinplot.me';
  const brandTagline = process.env.BRAND_TAGLINE || 'Live asset tracking, geofencing, and reporting for your fleet of GPS and BLE-tagged assets.';
  
  // Inject tenant-specific values into meta tags
  // These replacements target the generic placeholder values in the static HTML
  html = html
    .replace(/<title>Customer Portal — Asset Tracking<\/title>/, `<title>${brandProduct}</title>`)
    .replace(
      /<meta name="description" content="Customer Portal — Live asset tracking[^"]*">/,
      `<meta name="description" content="${brandProduct} — ${brandTagline}">`
    )
    .replace(
      /<meta property="og:title" content="Customer Portal — Asset Tracking">/,
      `<meta property="og:title" content="${brandProduct}">`
    )
    .replace(
      /<meta property="og:description" content="Live asset tracking[^"]*">/,
      `<meta property="og:description" content="${brandTagline}">`
    )
    .replace(
      /<meta property="og:url" content="__OG_URL__">/,
      `<meta property="og:url" content="https://${brandDomain}/customer">`
    )
    .replace(
      /<meta property="og:site_name" content="Customer Portal">/,
      `<meta property="og:site_name" content="${brandName}">`
    )
    .replace(
      /<meta property="og:image" content="__OG_IMAGE__">/,
      `<meta property="og:image" content="https://${brandDomain}/customer/assets/logo.png">`
    )
    .replace(
      /<meta property="og:image:alt" content="Customer Portal Logo">/,
      `<meta property="og:image:alt" content="${brandName} Logo">`
    )
    .replace(
      /<meta name="twitter:title" content="Customer Portal — Asset Tracking">/,
      `<meta name="twitter:title" content="${brandProduct}">`
    )
    .replace(
      /<meta name="twitter:description" content="Live asset tracking[^"]*">/,
      `<meta name="twitter:description" content="${brandTagline}">`
    );
  
  // Send the modified HTML
  res.set('Content-Type', 'text/html');
  res.send(html);
});

// Proxy API requests to backend
app.use('/api', async (req, res) => {
  const fullUrl = `${BACKEND_URL}${req.url}`;
  
  console.log(`🔗 Proxying ${req.method} ${req.url} → ${fullUrl}`);
  
  try {
    const fetch = (await import('node-fetch')).default;
    const response = await fetch(fullUrl, {
      method: req.method,
      headers: {
        'Content-Type': 'application/json',
        'User-Agent': 'CustomerDashboard/1.0',
        ...req.headers
      },
      body: req.method !== 'GET' && req.method !== 'HEAD' ? JSON.stringify(req.body) : undefined
    });
    
    const data = await response.json();
    console.log(`   ✅ ${response.status}`);
    res.status(response.status).json(data);
  } catch (error) {
    console.error(`❌ API proxy error: ${error.message}`);
    res.status(500).json({ error: 'Failed to reach backend', backendUrl: BACKEND_URL });
  }
});

// 404 handler
app.use((req, res) => {
  res.status(404).json({ error: 'Not found', path: req.originalUrl });
});

app.listen(PORT, '0.0.0.0', () => {
  console.log('='.repeat(60));
  console.log('✅ CUSTOMER DASHBOARD READY');
  console.log('='.repeat(60));
  console.log(`🌐 Access: http://localhost:${PORT}`);
  console.log(`🔗 Backend: ${BACKEND_URL}`);
  console.log('='.repeat(60) + '\n');
});
