# PinPlot API Documentation

**Base URL:** `https://pinplot.me`  
**API Version:** 1.0.0  
**Interactive Docs:** [https://pinplot.me/docs](https://pinplot.me/docs)

## Overview

The PinPlot RESTful API allows you to programmatically manage BLE tracking tags, monitor locations, and integrate real-time tracking into your applications.

## Authentication

All API endpoints require **Bearer Token authentication** (except login and registration).

### Getting Started

#### 1. Login to Get Access Token

**Endpoint:** `POST /api/v1/auth/login`

**Request:**
```bash
curl -X POST "https://pinplot.me/api/v1/auth/login" \
  -H "Content-Type: application/json" \
  -d '{
    "email": "your-email@example.com",
    "password": "your-password"
  }'
```

**Response:**
```json
{
  "access_token": "eyJ0eXAiOiJKV1QiLCJhbGc...",
  "token_type": "bearer"
}
```

#### 2. Use Token in Requests

Include the access token in the `Authorization` header for all subsequent requests:

```bash
curl "https://pinplot.me/api/v1/ble-tags" \
  -H "Authorization: Bearer eyJ0eXAiOiJKV1QiLCJhbGc..."
```

### Token Lifecycle

- **Validity:** Tokens expire after **24 hours**
- **Refresh:** Call `/api/v1/auth/refresh` before expiration to get a new token
- **Security:** Store tokens securely, never commit them to version control

## Core Endpoints

### Authentication

| Method | Endpoint | Description |
|--------|----------|-------------|
| `POST` | `/api/v1/auth/login` | Login with email/password to get access token |
| `POST` | `/api/v1/auth/register` | Register new user account |
| `POST` | `/api/v1/auth/refresh` | Refresh expiring token |
| `GET` | `/api/v1/auth/me` | Get current user profile |

### BLE Tag Management

| Method | Endpoint | Description |
|--------|----------|-------------|
| `GET` | `/api/v1/ble-tags` | List all your active tags |
| `POST` | `/api/v1/ble-tags` | Register a new BLE tag |
| `GET` | `/api/v1/ble-tags/{tag_id}` | Get specific tag details |
| `DELETE` | `/api/v1/ble-tags/{tag_id}` | Deactivate a tag |
| `POST` | `/api/v1/ble-tags/validate` | Validate IMEI before registration |
| `GET` | `/api/v1/ble-tags/supported-types` | Get supported tag types for your account |

### Location & Tracking

| Method | Endpoint | Description |
|--------|----------|-------------|
| `GET` | `/api/trips` | Get trip/journey history for tags |
| `GET` | `/api/v1/pois` | List points of interest (geofences) |
| `POST` | `/api/v1/pois` | Create new POI |
| `GET` | `/api/v1/alerts` | Get geofence breach alerts |

## Example Workflows

### Register a New BLE Tag

```bash
# 1. Login
TOKEN=$(curl -X POST "https://pinplot.me/api/v1/auth/login" \
  -H "Content-Type: application/json" \
  -d '{"email":"user@example.com","password":"password123"}' \
  | jq -r '.access_token')

# 2. Validate IMEI (optional but recommended)
curl -X POST "https://pinplot.me/api/v1/ble-tags/validate" \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "imei": "123456789012345",
    "tag_type": "series2"
  }'

# 3. Register tag
curl -X POST "https://pinplot.me/api/v1/ble-tags" \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "imei": "123456789012345",
    "tag_type": "series2",
    "device_name": "Asset Tracker 1"
  }'
```

### List All Tags with Battery Levels

```bash
curl "https://pinplot.me/api/v1/ble-tags" \
  -H "Authorization: Bearer $TOKEN" \
  | jq '.[] | {name: .device_name, imei: .imei, battery: .battery_level}'
```

### Create a Geofence (POI)

```bash
curl -X POST "https://pinplot.me/api/v1/pois" \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "name": "Warehouse",
    "latitude": 51.5074,
    "longitude": -0.1278,
    "radius": 100,
    "alert_on_entry": true,
    "alert_on_exit": true
  }'
```

## Rate Limiting

- **Default Tier:** 100 requests per minute
- **Enterprise Tier:** Custom limits available
- **Headers:** Check `X-RateLimit-*` response headers for current status

**Response when rate limited:**
```json
{
  "detail": "Rate limit exceeded. Try again in 60 seconds."
}
```

## Error Handling

### HTTP Status Codes

| Code | Meaning |
|------|---------|
| `200` | Success |
| `201` | Created (new resource) |
| `400` | Bad Request (invalid input) |
| `401` | Unauthorized (invalid/missing token) |
| `403` | Forbidden (insufficient permissions) |
| `404` | Not Found |
| `422` | Unprocessable Entity (validation failed) |
| `429` | Too Many Requests (rate limited) |
| `500` | Internal Server Error |

### Error Response Format

```json
{
  "detail": "Error message explaining what went wrong"
}
```

### Common Errors

**401 Unauthorized:**
```json
{
  "detail": "Could not validate credentials"
}
```
→ Your token is invalid or expired. Login again or refresh your token.

**422 Validation Error:**
```json
{
  "detail": "IMEI not found in vendor system"
}
```
→ The IMEI number doesn't exist or is incorrectly formatted.

## Interactive API Explorer

Visit **[https://pinplot.me/docs](https://pinplot.me/docs)** for:

- ✅ Interactive "Try it out" functionality
- ✅ Complete schema documentation
- ✅ Request/response examples
- ✅ Authentication testing
- ✅ Auto-generated client code

### Using Swagger UI

1. Go to [https://pinplot.me/docs](https://pinplot.me/docs)
2. Click **"Authorize"** button (🔒 icon)
3. Enter your token in format: `Bearer <your_token>`
4. Click **"Authorize"** then **"Close"**
5. Try any endpoint with the **"Try it out"** button

## SDKs & Code Examples

### Python

```python
import requests

class PinPlotClient:
    def __init__(self, email, password):
        self.base_url = "https://pinplot.me"
        self.token = self._login(email, password)
    
    def _login(self, email, password):
        response = requests.post(
            f"{self.base_url}/api/v1/auth/login",
            json={"email": email, "password": password}
        )
        response.raise_for_status()
        return response.json()["access_token"]
    
    @property
    def headers(self):
        return {"Authorization": f"Bearer {self.token}"}
    
    def get_tags(self):
        response = requests.get(
            f"{self.base_url}/api/v1/ble-tags",
            headers=self.headers
        )
        response.raise_for_status()
        return response.json()
    
    def add_tag(self, imei, tag_type="series2", device_name=None):
        response = requests.post(
            f"{self.base_url}/api/v1/ble-tags",
            headers=self.headers,
            json={
                "imei": imei,
                "tag_type": tag_type,
                "device_name": device_name
            }
        )
        response.raise_for_status()
        return response.json()

# Usage
client = PinPlotClient("user@example.com", "password123")
tags = client.get_tags()
print(f"You have {len(tags)} tags")
```

### JavaScript/Node.js

```javascript
const axios = require('axios');

class PinPlotClient {
  constructor(email, password) {
    this.baseURL = 'https://pinplot.me';
    this.token = null;
    this.login(email, password);
  }

  async login(email, password) {
    const response = await axios.post(`${this.baseURL}/api/v1/auth/login`, {
      email,
      password
    });
    this.token = response.data.access_token;
  }

  get headers() {
    return {
      Authorization: `Bearer ${this.token}`
    };
  }

  async getTags() {
    const response = await axios.get(`${this.baseURL}/api/v1/ble-tags`, {
      headers: this.headers
    });
    return response.data;
  }

  async addTag(imei, tagType = 'series2', deviceName = null) {
    const response = await axios.post(
      `${this.baseURL}/api/v1/ble-tags`,
      { imei, tag_type: tagType, device_name: deviceName },
      { headers: this.headers }
    );
    return response.data;
  }
}

// Usage
(async () => {
  const client = new PinPlotClient('user@example.com', 'password123');
  await client.login('user@example.com', 'password123');
  const tags = await client.getTags();
  console.log(`You have ${tags.length} tags`);
})();
```

## Webhooks (Coming Soon)

Subscribe to real-time events:
- Geofence breach alerts
- Low battery warnings
- Device online/offline status
- Tag movement updates

## Support

- **Email:** support@pinplot.me
- **Documentation:** https://pinplot.me/docs
- **Status Page:** https://status.pinplot.me _(coming soon)_

## Changelog

### Version 1.0.0 (2026-06-17)
- ✅ Initial API release
- ✅ Bearer token authentication
- ✅ BLE tag management
- ✅ Geofencing & POI management
- ✅ Trip/journey history
- ✅ Real-time alerts
- ✅ Interactive Swagger documentation
