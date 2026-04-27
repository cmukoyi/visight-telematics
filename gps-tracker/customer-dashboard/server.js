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

// Serve index.html for SPA routing
app.get('/', (req, res) => {
  res.sendFile(path.join(publicDir, 'index.html'));
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
