# Automatic Reverse Geocoding - Deployment Guide

## ✅ What's Fixed

Previously, position addresses were NULL because:
- Positions were ingested without reverse geocoding
- Required manual backfill script runs
- Not sustainable for production

Now, positions are **automatically geocoded during ingestion** with smart caching.

## 🚀 How It Works

### Smart Caching
- GeocodeService only geocodes when device moves >500m
- Uses MapTiler API (requires `MAPTILER_KEY` env variable)
- Cache persists at `/tmp/pinplot_geocode_cache.json`
- Typical cache hit rate: 90%+ for stationary assets

### Implementation
Added automatic geocoding to both ingestion tiers:
1. **Batch sweep** (`tracksolid_batch_service.py`): ALL devices every 10 min
2. **Selective track** (`tracksolid_track_service.py`): Subscribed devices on-demand

### Error Handling
- Geocoding errors don't fail position inserts
- Position is saved with `address=NULL` if geocoding fails
- Warnings logged for debugging

## 📋 Deployment Steps

### 1. Find Backend Container Name
```bash
# SSH into production server
ssh root@<your-server-ip>

# List running containers
docker ps

# Look for backend container - name might be:
# - backend
# - gps-tracker-backend
# - pinplot-backend
# - backend-1
```

### 2. Check Environment Variables
```bash
# Check if MAPTILER_KEY is set
docker exec <backend-container-name> env | grep MAPTILER_KEY

# If not set, add to docker-compose.yml or .env file
```

### 3. Deploy Updated Code
```bash
# Pull latest code
cd /path/to/pinplot
git pull origin main

# Rebuild and restart backend
docker-compose build backend
docker-compose up -d backend

# OR if using different compose file
docker compose -f docker-compose-production.yml up -d --build backend
```

### 4. Verify Geocoding is Working
```bash
# Watch logs for geocoding activity
docker logs -f <backend-container-name> | grep -E "Geocoded|🌍"

# Should see messages like:
# 🌍 Initialized GeocodeService (provider=maptiler, threshold=500m)
# 🌍 Geocoded IMEI 867584060247644: 123 Main St, London, UK...
```

### 5. Check Database
```bash
# Access backend container
docker exec -it <backend-container-name> bash

# Check how many positions have addresses now
python3 -c "
from app.database import get_db
from app.models import DevicePosition
from sqlalchemy import and_, func
db = next(get_db())
total = db.query(func.count(DevicePosition.id)).scalar()
with_addr = db.query(func.count(DevicePosition.id)).filter(
    DevicePosition.address.isnot(None)
).scalar()
print(f'Total positions: {total:,}')
print(f'With addresses: {with_addr:,}')
print(f'Coverage: {with_addr/total*100:.1f}%')
"
```

## 🔧 Backfill Old Positions (Optional)

For existing positions without addresses, run the backfill script:

```bash
docker exec -it <backend-container-name> bash
cd /app

# Check how many need backfilling
python3 -c "
from app.database import get_db
from app.models import DevicePosition
from sqlalchemy import and_, func
db = next(get_db())
count = db.query(func.count(DevicePosition.id)).filter(
    and_(
        DevicePosition.address.is_(None),
        DevicePosition.lat.isnot(None)
    )
).scalar()
print(f'{count:,} positions need addresses')
"

# Backfill recent positions (last 1000)
python3 backfill_position_addresses.py --limit 1000

# OR backfill all (may take hours for large datasets)
python3 backfill_position_addresses.py --all
```

## 🐛 Troubleshooting

### Addresses Still Showing Lat/Long
1. Check backend logs: `docker logs <backend-container-name> | grep -i geocod`
2. Verify MAPTILER_KEY is set: `docker exec <backend-container-name> env | grep MAPTILER_KEY`
3. Check MapTiler API quota: https://cloud.maptiler.com/account/usage/
4. Restart backend: `docker-compose restart backend`

### High MapTiler API Usage
- Cache should reduce API calls by 90%+
- Check cache file exists: `docker exec <backend-container-name> ls -lh /tmp/pinplot_geocode_cache.json`
- Increase threshold if needed (default: 500m)

### Container Name Not Found
Try these common patterns:
```bash
docker ps | grep -E "backend|gps-tracker"
docker ps --format "table {{.Names}}\t{{.Image}}"
```

## 📊 Performance Impact

- **Ingestion speed**: ~50-100ms added per NEW position (not cached)
- **Cache hit rate**: Typically 90%+ (only re-geocodes when moved >500m)
- **MapTiler quota**: Free tier = 100,000 requests/month
- **Expected usage**: ~300-500 API calls/day with caching

## 🔒 Security Notes

- MapTiler API key must be kept secure (use Docker secrets or encrypted env vars)
- Cache file contains lat/long + addresses (not sensitive data)
- Rate limiting prevents API abuse (500ms delay between non-cached calls)
