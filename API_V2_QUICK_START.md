# API v2 Quick Start Guide

## 🚀 Deployed to Main PinPlot

**Base URL:** `https://pinplot.me`  
**Documentation:** https://pinplot.me/docs (Swagger UI)

---

## 📖 Authentication

All API v2 endpoints require **Bearer token authentication**.

### 1. Get Token

```bash
curl -X POST https://pinplot.me/api/portal/login \
  -H "Content-Type: application/json" \
  -d '{
    "email": "your-email@example.com",
    "password": "your-password"
  }'
```

**Response:**
```json
{
  "access_token": "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9...",
  "token_type": "bearer",
  "usergroup_id": "abc-123-def",
  "portal_user_id": "xyz-789-uvw"
}
```

### 2. Use Token

Include the token in the `Authorization` header for all subsequent requests:

```bash
Authorization: Bearer eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9...
```

---

## 📡 API Endpoints

### 1. List All Devices with Last Positions

```bash
GET /api/v2/devices
```

**Example:**
```bash
curl -X GET https://pinplot.me/api/v2/devices \
  -H "Authorization: Bearer YOUR_TOKEN"
```

**Response:**
```json
{
  "total": 5,
  "devices": [
    {
      "imei": "781950640095475",
      "latitude": 51.5074,
      "longitude": -0.1278,
      "timestamp": "2026-07-26T10:30:00Z",
      "battery_level": 85,
      "is_indoor": false,
      "address": "London, UK"
    }
  ]
}
```

---

### 2. Get Movement History

```bash
GET /api/v2/movement-history/{imei}?start_date={ISO8601}&end_date={ISO8601}&limit=1000
```

**Example:**
```bash
curl -X GET "https://pinplot.me/api/v2/movement-history/781950640095475?start_date=2026-07-01T00:00:00Z&end_date=2026-07-26T23:59:59Z&limit=1000" \
  -H "Authorization: Bearer YOUR_TOKEN"
```

**Response:**
```json
{
  "imei": "781950640095475",
  "total_positions": 245,
  "start_date": "2026-07-01T00:00:00Z",
  "end_date": "2026-07-26T23:59:59Z",
  "positions": [
    {
      "imei": "781950640095475",
      "timestamp": "2026-07-26T10:30:00Z",
      "latitude": 51.5074,
      "longitude": -0.1278,
      "speed_kmh": 45.2,
      "bearing": 135,
      "battery_level": 85,
      "address": "London, UK"
    }
  ]
}
```

---

### 3. Get Hive Breaches

```bash
GET /api/v2/hive-breaches?active_only=false&start_date={ISO8601}&end_date={ISO8601}
```

**Example:**
```bash
curl -X GET "https://pinplot.me/api/v2/hive-breaches?active_only=true" \
  -H "Authorization: Bearer YOUR_TOKEN"
```

**Response:**
```json
[
  {
    "hive_id": "abc-123",
    "hive_name": "Warehouse Zone A",
    "tag_id": "tag-456",
    "tag_name": "Asset #42",
    "breach_start": "2026-07-26T09:15:00Z",
    "breach_end": null,
    "duration_seconds": null,
    "is_active": true
  }
]
```

---

### 4. Get Geofences

```bash
GET /api/v2/geofences?armed_only=false
```

**Example:**
```bash
curl -X GET "https://pinplot.me/api/v2/geofences?armed_only=true" \
  -H "Authorization: Bearer YOUR_TOKEN"
```

**Response:**
```json
[
  {
    "id": "poi-789",
    "name": "Office Building",
    "is_armed": true,
    "latitude": 51.5074,
    "longitude": -0.1278,
    "radius_m": 100.0,
    "created_at": "2026-06-15T08:00:00Z"
  }
]
```

---

### 5. Get Alerts

```bash
GET /api/v2/alerts?alert_type={type}&start_date={ISO8601}&end_date={ISO8601}&unread_only=false&limit=100
```

**Alert Types:**
- `geofence_exit` - Asset left a geofence
- `battery_low` - Asset battery is low
- `offline` - Asset went offline
- `hive_breach` - Hive was breached

**Example:**
```bash
curl -X GET "https://pinplot.me/api/v2/alerts?alert_type=geofence_exit&unread_only=true&limit=50" \
  -H "Authorization: Bearer YOUR_TOKEN"
```

**Response:**
```json
[
  {
    "id": "alert-123",
    "alert_type": "geofence_exit",
    "message": "Asset #42 left Office Building",
    "tag_id": "tag-456",
    "tag_name": "Asset #42",
    "geofence_name": "Office Building",
    "created_at": "2026-07-26T10:45:00Z",
    "is_read": false
  }
]
```

---

## 🔒 Security Features

✅ **Bearer Token Authentication** - All endpoints require valid token  
✅ **Multi-tenant Isolation** - Only see data from your usergroup  
✅ **Token Expiry** - Tokens expire after 12 hours  
✅ **Rate Limiting** - Login endpoint rate-limited (5 attempts per 60 seconds)

---

## 🧪 Testing with Swagger UI

Visit **https://pinplot.me/docs** for interactive testing:

1. Click **Authorize** button (top right)
2. Get token from `POST /api/portal/login`
3. Enter token as: `Bearer YOUR_TOKEN`
4. Test all endpoints interactively

---

## 📝 Use Cases

- **Mobile Apps:** Fetch device positions for map view
- **Dashboards:** Build custom analytics dashboards
- **Integrations:** Connect to SIEM, monitoring, or BI tools
- **Automation:** Trigger actions based on alerts or breaches
- **Data Export:** Extract historical data for analysis

---

## 🚨 Error Responses

**401 Unauthorized:**
```json
{
  "detail": "Invalid or expired token"
}
```

**404 Not Found:**
```json
{
  "detail": "Device not found or not accessible"
}
```

**429 Too Many Requests:**
```json
{
  "detail": "Too many failed login attempts. Try again in 900 seconds."
}
```

---

## 📞 Support

For API support, contact: support@pinplot.me
