# Nginx Configuration Update - API Documentation Endpoints

**Date:** 2026-06-17  
**Purpose:** Expose Swagger/ReDoc API documentation at `/docs` and `/redoc`

## Changes Required

Add these location blocks to nginx.conf **before** the `location /api/` block:

```nginx
    # API Documentation (Swagger UI) - public access for customer developers
    location /docs {
        proxy_pass http://backend/docs;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }
    
    # API Documentation (ReDoc alternative) - public access
    location /redoc {
        proxy_pass http://backend/redoc;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }
    
    # OpenAPI JSON schema - public access
    location /openapi.json {
        proxy_pass http://backend/openapi.json;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }
```

## Deployment Steps

### Pinplot Server

```bash
# SSH to server
ssh root@PinPlotServer

# Navigate to nginx config
cd /root/pinplot/gps-tracker/nginx

# Backup current config
cp nginx.conf nginx.conf.backup.$(date +%Y%m%d_%H%M%S)

# Edit the config
nano nginx.conf
# Add the three location blocks above, right after the /manifest.json block
# and BEFORE the /api/ block

# Test nginx config
docker exec pinplot_nginx nginx -t

# If test passes, reload nginx
docker exec pinplot_nginx nginx -s reload

# Verify
curl -I https://pinplot.me/docs
# Should return 200 OK with HTML content
```

### BeaconTelematics Server

```bash
# SSH to server
ssh root@beacontelematics.co.uk

# Navigate to nginx config
cd /root/beacon-telematics/gps-tracker/nginx

# Backup current config
cp nginx.conf nginx.conf.backup.$(date +%Y%m%d_%H%M%S)

# Edit the config
nano nginx.conf
# Add the three location blocks above, right after the /manifest.json block
# and BEFORE the /api/ block

# Test nginx config
docker exec beacon_telematics_nginx nginx -t

# If test passes, reload nginx
docker exec beacon_telematics_nginx nginx -s reload

# Verify
curl -I https://beacontelematics.co.uk/docs
# Should return 200 OK with HTML content
```

## Verification

After deployment, verify each endpoint:

### Pinplot
- Swagger UI: https://pinplot.me/docs
- ReDoc: https://pinplot.me/redoc
- OpenAPI Schema: https://pinplot.me/openapi.json

### BeaconTelematics
- Swagger UI: https://beacontelematics.co.uk/docs
- ReDoc: https://beacontelematics.co.uk/redoc
- OpenAPI Schema: https://beacontelematics.co.uk/openapi.json

## Testing Authentication

1. Go to https://pinplot.me/docs
2. Click the **"Authorize"** button (🔒 lock icon)
3. Enter: `Bearer <your_actual_token>`
4. Click **"Authorize"** then **"Close"**
5. Try the `/api/v1/ble-tags` endpoint with **"Try it out"**

## Rollback

If there are any issues:

```bash
# Restore from backup
cp nginx.conf.backup.YYYYMMDD_HHMMSS nginx.conf

# Reload nginx
docker exec <container_name>_nginx nginx -s reload
```

## Notes

- The FastAPI backend already serves these endpoints
- Nginx just needs to proxy them through
- No backend restart required, only nginx reload
- Changes are public-facing (no authentication required to view docs)
- Authentication is required to execute the API calls from the UI
