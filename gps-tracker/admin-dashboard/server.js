const express = require('express');
const path = require('path');
const fs = require('fs');
const app = express();

const PORT = process.env.PORT || 3000;
const API_URL = process.env.BACKEND_URL || process.env.NEXT_PUBLIC_API_URL || 'http://backend:8000';

// Comprehensive logging for deployment verification
console.log('='.repeat(60));
console.log('🚀 ADMIN DASHBOARD STARTING');
console.log('='.repeat(60));
console.log(`📦 Environment: ${process.env.NODE_ENV || 'development'}`);
console.log(`📍 API URL: ${API_URL}`);
console.log(`🖥️  Server PORT: ${PORT}`);
console.log(`📂 Public directory: ${path.join(__dirname, 'public')}`);
console.log(`⏰ Deployment timestamp: ${new Date().toISOString()}`);

// List all files in public directory for verification
const publicDir = path.join(__dirname, 'public');
if (fs.existsSync(publicDir)) {
  const files = fs.readdirSync(publicDir);
  console.log(`\n📋 Files in public directory (${files.length} files):`);
  files.forEach(file => {
    const filePath = path.join(publicDir, file);
    const stat = fs.statSync(filePath);
    console.log(`   ✅ ${file} (${stat.size} bytes, modified: ${stat.mtime.toISOString()})`);
  });
}
console.log('='.repeat(60) + '\n');

// Middleware: No cache for HTML files
app.use((req, res, next) => {
  // Disable caching for all requests to ensure latest code is served
  res.set('Cache-Control', 'no-store, no-cache, must-revalidate, max-age=0, post-check=0, pre-check=0');
  res.set('Pragma', 'no-cache');
  res.set('Expires', '0');
  res.set('ETag', `"${Date.now()}"`); // Dynamic ETag to force refresh
  next();
});

app.use(express.static('public'));
app.use(express.json());

// Health check endpoint for deployment verification
app.get('/health', (req, res) => {
  const checks = {
    status: 'healthy',
    timestamp: new Date().toISOString(),
    uptime: process.uptime(),
    files: {
      publicDir: fs.existsSync(publicDir),
      tripHtml: fs.existsSync(path.join(publicDir, 'trips.html')),
      indexHtml: fs.existsSync(path.join(publicDir, 'index.html')),
      billingHtml: fs.existsSync(path.join(publicDir, 'billing.html'))
    }
  };
  
  console.log(`✅ Health check requested: ${JSON.stringify(checks.files)}`);
  res.json(checks);
});

// Manifest endpoint for deployment verification
app.get('/api/manifest', (req, res) => {
  try {
    const publicDir = path.join(__dirname, 'public');
    const files = fs.existsSync(publicDir) ? fs.readdirSync(publicDir) : [];
    
    const manifest = {
      deployment: {
        timestamp: new Date().toISOString(),
        version: 'beacon-admin-dashboard',
        environment: process.env.NODE_ENV || 'development'
      },
      files: files
        .map(file => {
          try {
            const filePath = path.join(publicDir, file);
            const stat = fs.statSync(filePath);
            return {
              name: file,
              path: `/public/${file}`,
              size: stat.size,
              modified: stat.mtime.toISOString()
            };
          } catch (err) {
            console.warn(`⚠️  Could not stat file ${file}: ${err.message}`);
            return null;
          }
        })
        .filter(item => item !== null) // Remove null entries from failed stats
    };

    console.log(`📋 Manifest requested with ${manifest.files.length} files available`);
    res.json(manifest);
  } catch (error) {
    console.error(`❌ Manifest endpoint error: ${error.message}`);
    res.status(500).json({ 
      error: 'Failed to generate manifest',
      message: error.message
    });
  }
});

// Serve the admin dashboard
app.get('/', (req, res) => {
  console.log(`🔗 Index requested from ${req.ip}`);
  res.sendFile(path.join(__dirname, 'public', 'index.html'));
});

// Explicit routes for dashboard pages
app.get('/index.html', (req, res) => {
  res.sendFile(path.join(__dirname, 'public', 'index.html'));
});

app.get('/billing.html', (req, res) => {
  res.sendFile(path.join(__dirname, 'public', 'billing.html'));
});

app.get('/trips.html', (req, res) => {
  const filePath = path.join(__dirname, 'public', 'trips.html');
  if (!fs.existsSync(filePath)) {
    console.error(`❌ trips.html not found at ${filePath}`);
    return res.status(404).json({ 
      error: 'trips.html not found',
      path: filePath,
      publicDirContents: fs.readdirSync(path.join(__dirname, 'public'))
    });
  }
  console.log(`🗺️  Trips page requested from ${req.ip}`);
  res.sendFile(filePath);
});

// Proxy API requests
app.use('/api', async (req, res) => {
  try {
    const fetch = (await import('node-fetch')).default;
    const url = `${API_URL}${req.originalUrl.replace('/api', '/api')}`;
    
    console.log(`🔗 Proxying ${req.method} ${req.originalUrl} → ${url}`);
    
    const response = await fetch(url, {
      method: req.method,
      headers: {
        ...req.headers,
        'Content-Type': 'application/json',
        'User-Agent': 'AdminDashboard/1.0'
      },
      body: req.method !== 'GET' && req.method !== 'HEAD' ? JSON.stringify(req.body) : undefined
    });
    
    const data = await response.json();
    console.log(`   ✅ Response from API: ${response.status}`);
    res.status(response.status).json(data);
  } catch (error) {
    console.error(`❌ API Proxy Error: ${error.message}`);
    res.status(500).json({ 
      error: `API request failed: ${error.message}`,
      apiUrl: API_URL
    });
  }
});

// 404 handler
app.use((req, res) => {
  console.warn(`⚠️  404 Not Found: ${req.method} ${req.originalUrl}`);
  res.status(404).json({ 
    error: 'Not found',
    path: req.originalUrl,
    availableRoutes: ['/', '/index.html', '/billing.html', '/trips.html', '/api/*', '/health', '/api/manifest']
  });
});

// Error handler
app.use((err, req, res, next) => {
  console.error(`❌ Server Error: ${err.message}`);
  res.status(500).json({ error: err.message });
});

app.listen(PORT, '0.0.0.0', () => {
  console.log('='.repeat(60));
  console.log('✅ ADMIN DASHBOARD READY FOR TRAFFIC');
  console.log('='.repeat(60));
  console.log(`🌐 Access urls:`);
  console.log(`   📍 http://localhost:${PORT}`);
  console.log(`   📍 http://localhost:${PORT}/trips.html`);
  console.log(`   📍 http://localhost:${PORT}/health (deployment check)`);
  console.log(`   📍 http://localhost:${PORT}/api/manifest (file manifest)`);
  console.log(`   🔗 API endpoints proxied to: ${API_URL}`);
  console.log('='.repeat(60) + '\n');
});
