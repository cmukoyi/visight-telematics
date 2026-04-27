# PinPlot — RFID Asset Tracker

A modern, dark-theme single-page application for tracking RFID/AirTag-protocol assets using the **Tracksolid Pro (JIMI Cloud) Open API**.

---

## Live Entry Point

| Path | Description |
|------|-------------|
| `index.html` | Main application shell — all views are rendered here |

---

## Completed Features

### 1. Live Map Dashboard (`/` → `dashboard` view)
- Full-screen Leaflet map (OpenStreetMap tiles with dark filter)
- Colour-coded asset markers: 🟢 Online · 🟡 Idle · 🔴 Offline
- Clickable markers open a detail popup with a **View History** shortcut
- Left sidebar: asset list, live search, category filter chips, status stats (Total / Online / Idle / Offline)
- Selecting an asset pans the map and reveals a bottom detail panel (status, battery, speed, address, IMEI, position type)
- Category quick-filter bar (Vehicles · Equipment · Containers · Personnel)

### 2. Asset List (`assets` view)
- Paginated table: name, RFID tag, category, status, battery, address, last update
- Category filter chips with counts
- Search by name or tag ID
- Row actions: **pin on map**, **view history**, **edit**
- API reference: `jimi.user.device.list` · `jimi.device.group.list`

### 3. Movement History (`history` view)
- Asset selector dropdown (switch between any tracked device)
- Date/time range pickers (aligned to `jimi.device.track.list` constraints: ≤7 days, ≤3 months ago)
- **Interactive Leaflet map** showing exactly **6 sequential numbered position markers** (1–6)
  - 🟢 Position 1 = Start (green)
  - 🔵 Positions 2–5 = Waypoints (blue)
  - 🔴 Position 6 = Current / Last known (red)
  - Dashed polyline connecting all positions in order
- **Synchronized timeline panel** on the right:
  - Each step shows: event name, address, timestamp, speed, position type (BEACON / GPS)
  - Clicking a timeline entry flies the map to that position and opens its popup
  - Clicking a map marker highlights the matching timeline entry
- Export button (demo toast)
- API reference: `jimi.device.track.list` · `jimi.device.location.getTagMsg`

### 4. User Account Management (`accounts` view)
- Table of all sub-accounts: name, email, role, account type (User/Distributor), permission bits, device count, created date, status
- **Add User** modal with: name, email, role, type, active toggle
- **Edit** and **Delete** actions per row
- Permission bits display (6-bit visual indicator: Login · Cmd · Edit · View · Report · Config)
- API reference: `jimi.user.child.list` · `jimi.user.child.create` · `jimi.user.child.update` · `jimi.user.child.del`

### 5. Asset Management (`asset-mgmt` view)
- Card grid layout — one card per device
- Each card shows: category, RFID tag, IMEI, model, battery, last seen
- **Add Asset** modal: name, IMEI, RFID tag, model, category/group
- **Edit** and **Delete** per card
- Category summary bar at top
- API reference: `jimi.user.device.list` · `jimi.device.group.list` · `jimi.open.device.rfid.list` · `jimi.device.location.getTagMsg`

### 6. API Service Layer (`js/api.js`)
Full Tracksolid Pro API integration module with:
- MD5 signature generation (via SparkMD5)
- Token management: `jimi.oauth.token.get` / `jimi.oauth.token.refresh`
- Auto session persistence in `localStorage`
- Modules: `Auth`, `Devices`, `Tracking`, `History`, `RFID`, `Accounts`
- All methods documented with parameter and response field comments

---

## File Structure

```
index.html          — App shell, all 5 view sections, 2 modals
css/
  style.css         — Complete dark-theme design system
js/
  data.js           — Demo/sample data (mirrors real API response shapes)
  app.js            — Router, Dashboard, AssetsView, HistoryView,
                      AccountsView, AssetMgmt controllers
  api.js            — Tracksolid Pro API integration layer
```

---

## API Integration Map

| Feature | API Method | Module |
|---------|-----------|--------|
| Login / token | `jimi.oauth.token.get` | `Auth.login()` |
| Refresh token | `jimi.oauth.token.refresh` | `Auth.refresh()` |
| List devices | `jimi.user.device.list` | `Devices.list()` |
| Device detail | `jimi.track.device.detail` | `Devices.detail()` |
| Device groups (categories) | `jimi.device.group.list` | `Devices.groups()` |
| Bulk locations | `jimi.user.device.location.list` | `Tracking.bulkLocations()` |
| Tag latest location | `jimi.device.location.getTagMsg` | `Tracking.tagLocation()` |
| Track history (6 positions) | `jimi.device.track.list` | `History.track()` |
| Mileage summary | `jimi.device.track.mileage` | `History.mileage()` |
| RFID reports | `jimi.open.device.rfid.list` | `RFID.list()` |
| List sub-accounts | `jimi.user.child.list` | `Accounts.list()` |
| Create sub-account | `jimi.user.child.create` | `Accounts.create()` |
| Update sub-account | `jimi.user.child.update` | `Accounts.update()` |
| Remove sub-account | `jimi.user.child.del` | `Accounts.remove()` |

---

## Demo Data

Sample data in `js/data.js` mirrors real API response shapes:
- **11 assets** across 4 categories (Vehicles, Equipment, Containers, Personnel)
- **6-stop movement history** for "Truck Alpha-1" (Miami, FL area)
- **4 sub-accounts** with different roles and permission levels
- **4 alerts** (low battery, geofence exit, offline, geofence entry)

All other assets auto-generate a 6-point random history on first selection.

---

## Switching from Demo to Live API

1. Open `js/api.js`
2. Set `API_CONFIG.BASE_URL` to your JIMI node URL
3. Set `API_CONFIG.APP_KEY` and `API_CONFIG.APP_SECRET` from JIMI
4. In `js/app.js`, set `demoMode: false` in the state object
5. Replace demo data calls with the corresponding `JimiAPI.*` method calls

> ⚠️ The API requires a backend proxy to avoid CORS issues in production.
> Your app server should forward requests to `api.tracksolidpro.com`.

---

## Features Not Yet Implemented

- Real-time auto-refresh / WebSocket push (`jimi.push.device.alarm`)
- Geofence management (`jimi.open.device.fence.create` / `delete`)
- RFID card scan report table (`jimi.open.device.rfid.list` UI)
- Mileage / trips report page (`jimi.open.platform.report.trips`)
- Device command sending (`jimi.open.instruction.send`)
- Map satellite/terrain tile switcher
- Mobile-responsive collapsible timeline panel
- Login screen with real `jimi.oauth.token.get` flow
- Bulk device import / CSV upload
- Notification push subscription

---

## Recommended Next Steps

1. **Add a login page** — call `Auth.login()` and store session
2. **Backend proxy** — Node.js/Express or Cloudflare Worker to sign and forward JIMI requests
3. **Real-time polling** — `setInterval` calling `Tracking.bulkLocations()` every 30s, update markers in place
4. **Geofence layer** — draw polygons on the map using Leaflet.Draw
5. **RFID event log** — dedicated table view for `jimi.open.device.rfid.list` results
6. **Flutter port** — use the same data contracts defined in `js/api.js` to build Dart models
