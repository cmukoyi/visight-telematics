# Series 5 (Hubble Platform) Integration - Preparation Complete

## Overview
Prepared the PinPlot codebase to support **Series 5** tags that use the **Hubble Platform** for BLE tracking. This is distinct from Series 4 (DX-Smart BLE indoor tags) because Hubble tags use the Hubble Cloud API instead of local infrastructure.

**Date**: 2026-08-06  
**Status**: ✅ Code prepared, ready for Hubble API credentials and testing

---

## What Was Done

### 1. ✅ Backend Provider System
**File**: `gps-tracker/backend/app/services/device_providers/hubble_provider.py` (NEW)
- Created `HubbleTagProvider` class implementing the Strategy pattern
- Device ID validation with regex pattern (8-32 alphanumeric chars)
- Placeholder for Hubble API integration (commented TODO sections)
- Environment variable support:
  - `HUBBLE_API_KEY`: Bearer token from Hubble dashboard
  - `HUBBLE_ORG_ID`: Organization ID
  - `HUBBLE_API_BASE`: API base URL (default: https://api.hubble.com)
- Rate limiting awareness (3 req/sec per endpoint, 15 req/sec per org)

**File**: `gps-tracker/backend/app/services/device_providers/provider_factory.py`
- Added `hubble`, `series_5`, and `series5` aliases to provider registry
- Maps to `HubbleTagProvider` class

### 2. ✅ Database Model
**File**: `gps-tracker/backend/app/models.py`
- Updated `tag_type` column comment to include `'series_5' (Hubble)`, `'hubble'`

### 3. ✅ Backend Routes
**File**: `gps-tracker/backend/app/routes_portal.py`
- Added Series 5 to `/api/portal/tag-types` endpoint
  - `{"value": "series_5", "label": "Series 5 (Hubble)", "description": "Hubble Platform BLE tracking"}`
- Updated `_TAG_TYPE_ALIAS` map:
  - `"series5": "hubble"`
  - `"series_5": "hubble"`

### 4. ✅ Admin Portal UI
**File**: `gps-tracker/admin-portal/index.html`
- Added Series 4 and Series 5 checkboxes to **Create Usergroup** modal
  - Checkbox ID: `cgTypeSeries4`, value: `series_4`
  - Checkbox ID: `cgTypeSeries5`, value: `series_5`
- Added Series 4 and Series 5 checkboxes to **Edit Usergroup** modal
  - Checkbox ID: `egTypeSeries4`, value: `series_4`
  - Checkbox ID: `egTypeSeries5`, value: `series_5`
- Updated JavaScript functions:
  - `createUsergroup()`: Collects series_4 and series_5 checkbox values
  - `editUsergroup()`: Populates series_4 and series_5 checkboxes from usergroup data
  - Default allowed types now include all 5 series

### 5. ✅ Customer Dashboard UI
**File**: `gps-tracker/customer-dashboard/public/index.html`
- Added Series 5 to tag type dropdown in Asset Management:
  - `<option value="series_5">Series 5 (Hubble)</option>`
- Updated `_ppTagTypeLabel()` function:
  - Maps `series_5`, `series5`, and `hubble` → `'Series 5'`
- Updated default `allowedTypes` arrays:
  - Now includes `'series_5'` in defaults (2 locations)
- Updated `_typeAliasToSelect` mapping:
  - `hubble: 'series_5'`, `series5: 'series_5'`, `series_5: 'series_5'`

### 6. ✅ Translation Keys
**File**: `add_series_4_5_translation_keys.sql` (NEW)
- SQL script to add `general.series_4` and `general.series_5` keys
- Can be run on production or will be auto-detected by `add_missing_translation_keys.py`

---

## What's Next (To Complete Integration)

### 1. ⏳ Hubble API Credentials
Add environment variables to production `.env`:
```bash
# Hubble Platform Configuration (Series 5)
HUBBLE_API_KEY=your_bearer_token_here
HUBBLE_ORG_ID=your_org_id_here
HUBBLE_API_BASE=https://api.hubble.com  # optional, has default
```

Get credentials from Hubble dashboard:
- Navigate to **Developer Tools > API Tokens**
- Create new API key with required scopes:
  - `read-devices` (required)
  - `write-devices` (optional, for registration)
  - `read-packets` (for location data)

### 2. ⏳ Implement Hubble API Integration
**File**: `gps-tracker/backend/app/services/device_providers/hubble_provider.py`

Uncomment and implement `_verify_with_hubble_api()`:
```python
async def _verify_with_hubble_api(self, device_id: str) -> TagValidationResult:
    import httpx
    
    headers = {
        "Authorization": f"Bearer {self.api_key}",
        "X-Request-ID": f"pinplot-validation-{device_id}",
    }
    
    async with httpx.AsyncClient() as client:
        response = await client.get(
            f"{self.api_base}/v1/organizations/{self.org_id}/devices/{device_id}",
            headers=headers,
            timeout=10.0,
        )
        
        if response.status_code == 200:
            return TagValidationResult(
                is_valid=True,
                message=f"Series 5 Hubble tag verified via API (Device ID: {device_id}).",
            )
        elif response.status_code == 404:
            return TagValidationResult(
                is_valid=False,
                message=f"Device ID {device_id} not found in Hubble platform.",
            )
        else:
            return TagValidationResult(
                is_valid=False,
                message=f"Hubble API error: {response.status_code}",
            )
```

Update `validate_tag()` to call API when credentials are configured:
```python
# If API credentials are configured, verify device exists in Hubble
if self.api_key and self.org_id:
    return await self._verify_with_hubble_api(device_id)
```

### 3. ⏳ Location Polling Service
**File**: `gps-tracker/backend/app/services/location_poller_service.py`

Add Series 5 polling logic:
- Fetch device locations from Hubble API `/v1/organizations/{org_id}/devices/{device_id}/packets`
- Respect rate limits (3 req/sec per endpoint, 15 req/sec org-wide)
- Store latest location in `ble_tags` table (latitude, longitude, last_seen)
- Similar to Series 2 (TrackSolid) polling pattern

### 4. ⏳ Database Migration (Optional)
If device ID format differs from current `imei` field constraints:
- Create Alembic migration to adjust `ble_tags.imei` validation
- Or ensure Hubble device IDs fit existing constraints

### 5. ⏳ Add Translation Keys to Production
Run the SQL script on production:
```bash
docker exec pinplot_db psql -U pinplot_db_user -d pinplot_db < add_series_4_5_translation_keys.sql
```

Or let `add_missing_translation_keys.py` auto-detect them on next run.

### 6. ⏳ Auto-Translate Series 4 & 5 Keys
After keys are added, use admin portal to auto-translate:
1. Go to https://pinplot.me/admin/index.html#translations
2. Click **🤖 Auto** button next to French
3. Click **🤖 Auto** button next to Dutch
4. Wait for translations to complete

### 7. ⏳ Testing Checklist
- [ ] Register a Series 5 tag via customer dashboard
- [ ] Verify device ID validation works (format check)
- [ ] Verify device ID validation against Hubble API (once implemented)
- [ ] Test tag display in Asset Management table
- [ ] Test tag type filter shows Series 5
- [ ] Verify usergroup restrictions work (admin can enable/disable Series 5)
- [ ] Test location polling (once implemented)
- [ ] Verify Series 5 tags appear on map (if location data available)

---

## Deployment Steps

### 1. Commit Changes
```bash
cd /Users/carl/Documents/MobileCode/Pinplot
git add .
git commit -m "feat(series-5): prepare codebase for Hubble Platform BLE tag integration

- Add HubbleTagProvider with device ID validation
- Add series_5 to provider factory, models, and routes
- Add Series 5 UI elements to admin portal and customer dashboard
- Add translation keys for Series 4 and 5
- Prepare for Hubble API integration (credentials and location polling TBD)

Refs: Series 5 uses Hubble Cloud Platform (different from Series 4 Pareto Anywhere)"
```

### 2. Push to GitHub
```bash
# Main branch (auto-deploys to pinplot.me)
git push origin main

# Prod/beacon branch (auto-deploys to beacontelematics.co.uk)
git checkout prod/beacon
git merge main
git push origin prod/beacon
```

### 3. Add Environment Variables
SSH to production and add Hubble credentials to `.env`:
```bash
ssh root@pinplot.me
cd /root/pinplot/gps-tracker/backend
nano .env

# Add:
# HUBBLE_API_KEY=your_token
# HUBBLE_ORG_ID=your_org_id

# Restart backend
docker restart pinplot_backend
```

### 4. Add Translation Keys
```bash
docker exec pinplot_db psql -U pinplot_db_user -d pinplot_db < /root/pinplot/add_series_4_5_translation_keys.sql
```

### 5. Auto-Translate (Admin Portal)
Visit https://pinplot.me/admin/index.html#translations and auto-translate Series 4/5 keys.

---

## Architecture Notes

### Series Comparison

| Series | Type | Platform | Location Source | Validation |
|--------|------|----------|----------------|------------|
| **Series 1** | GPS | MZone API | MZone polling | MZone API |
| **Series 2** | GPS | TrackSolid API | TrackSolid polling | TrackSolid API |
| **Series 3** | QR/NFC | Local | QR scan events | None (self-provisioned) |
| **Series 4** | BLE Indoor | Pareto Anywhere | ESP32 gateways → Pareto | MAC format only |
| **Series 5** | BLE | Hubble Cloud | Hubble API polling | Hubble API |

### Hubble API Reference
- **Base URL**: https://api.hubble.com
- **Auth**: `Authorization: Bearer {api_key}` (JWT)
- **Rate Limits**: 3 req/sec per endpoint, 15 req/sec per org
- **Device Endpoint**: `GET /v1/organizations/{org_id}/devices/{device_id}`
- **Packets Endpoint**: `GET /v1/organizations/{org_id}/devices/{device_id}/packets`
- **OpenAPI**: https://hubble.com/docs/openapi.yaml

### Provider Pattern
All tag series follow the same Strategy pattern:
1. Implement `DeviceTagProvider` base class
2. Provide `validate_tag()` method
3. Register in `provider_factory.py`
4. Backend routes use factory to get correct provider

This makes adding new series clean and isolated.

---

## Files Changed

### Backend
- ✅ `gps-tracker/backend/app/services/device_providers/hubble_provider.py` (NEW)
- ✅ `gps-tracker/backend/app/services/device_providers/provider_factory.py`
- ✅ `gps-tracker/backend/app/models.py`
- ✅ `gps-tracker/backend/app/routes_portal.py`

### Frontend
- ✅ `gps-tracker/admin-portal/index.html`
- ✅ `gps-tracker/customer-dashboard/public/index.html`

### Database
- ✅ `add_series_4_5_translation_keys.sql` (NEW)

### Documentation
- ✅ `SERIES_5_INTEGRATION.md` (this file)

---

## Questions & Decisions

### Device ID Format
**Current assumption**: Alphanumeric, 8-32 characters  
**Action needed**: Verify actual Hubble device ID format and adjust regex if needed

### Location Polling Frequency
**Current Series 2 (GPS)**: 10 minutes  
**Current Series 4 (BLE)**: Real-time via webhooks from Pareto  
**Series 5 (Hubble)**: TBD - depends on Hubble API rate limits and data freshness

**Recommendation**: Start with 5-minute polling, adjust based on:
- Rate limit budget (15 req/sec org-wide)
- Number of Series 5 tags deployed
- User expectations for location freshness

### Webhook vs Polling
**Option A**: Poll Hubble API periodically (like Series 2)  
**Option B**: Use Hubble webhooks if available (like Pareto Anywhere for Series 4)

**Recommendation**: Check Hubble docs for webhook support. If available, prefer webhooks for real-time updates.

---

## Support

For Hubble API issues:
- Check https://hubble.com/docs/
- Use `X-Request-ID` header for debugging
- Contact Hubble Support with Request ID

For PinPlot integration issues:
- Check backend logs: `docker logs pinplot_backend --tail 100 -f`
- Verify environment variables are set
- Test Hubble API directly with curl before debugging provider code
