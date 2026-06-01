# 📍 PinPlot — MVP Backend Specification

**BLE Indoor Asset Tracking · Nearest-Gateway Edition**

| | |
|---|---|
| **Version** | MVP 1.0 |
| **Status** | Implementation Ready |
| **Date** | May 2026 |
| **Gateway hardware** | PinPlot XIAO (ESP32-S3 Seeed XIAO) |
| **Middleware** | Pareto Anywhere (reelyActive) |
| **Backend** | Python / Flask · SQLite |
| **Frontend** | PinPlot Floor Plan UI (Canvas · DM Sans) |
| **Positioning** | Nearest gateway — `rssiSignature[0]` |
| **Multi-floor** | Gateway ID namespacing + TX power reduction |

---

## Table of Contents

1. [MVP Scope & Success Criteria](#1-mvp-scope--success-criteria)
2. [System Architecture](#2-system-architecture)
3. [Hardware Setup — PinPlot XIAO Gateway](#3-hardware-setup--pinplot-xiao-gateway)
4. [Gateway Naming Convention & Floor Assignment](#4-gateway-naming-convention--floor-assignment)
5. [Pareto Anywhere Setup](#5-pareto-anywhere-setup)
6. [Database Schema](#6-database-schema)
7. [Flask API](#7-flask-api)
8. [UI Integration Contract](#8-ui-integration-contract)
9. [Step-by-Step Implementation Guide](#9-step-by-step-implementation-guide)
10. [Testing & Validation](#10-testing--validation)
11. [What MVP Intentionally Excludes](#11-what-mvp-intentionally-excludes)

---

## 1. MVP Scope & Success Criteria

### 1.1 What MVP delivers

A working end-to-end system where:

- A Minew BLE tag attached to an asset broadcasts a BLE advertisement
- One or more XIAO gateways hear it and forward the sighting to Pareto Anywhere
- Pareto Anywhere normalises the sighting and streams it via Socket.IO
- The Flask backend subscribes, looks up which gateway saw the tag strongest, resolves that gateway's canvas position, and updates the asset record
- The PinPlot floor plan UI polls Flask every 3 seconds and moves the asset dot to the correct room on the correct floor

### 1.2 Success criteria

| Criterion | Pass condition |
|---|---|
| Tag dot appears on floor plan | Dot visible within 10 s of tag powering on |
| Dot is in the right room | Dot appears at or within the room containing the nearest gateway |
| Floor is correct | Dot appears on the correct floor tab in the UI |
| Floor switch works | Switching floor tabs in the UI shows only assets on that floor |
| Asset list updates | Left panel asset list reflects same floor/status as canvas |
| Offline detection | Dot moves to offline (red) status when tag is powered off for 60 s |

### 1.3 Explicitly not in MVP

- RSSI-weighted centroid (sub-room accuracy)
- WebSocket push from Flask to UI (polling is used)
- Zone breach alerts
- Movement history / playback
- Multi-tenant / multi-site
- Authentication beyond a static admin token

---

## 2. System Architecture

### 2.1 Data flow

```
[Minew Tag]
    │  BLE advertisement (500 ms interval)
    │  TX power: reduced (see Section 3.3)
    ▼
[PinPlot XIAO Gateway]  ── one per room, per floor ──
    │  HTTP POST to http://<host>:3001/minew
    │  Minew G1 payload format (mimicked in firmware)
    │  Gateway ID embedded in payload: e.g. GW-F1-01
    ▼
[Pareto Anywhere]  port 3001
    │  barnowl-minew parses payload automatically
    │  Emits raddec via built-in Socket.IO
    │  rssiSignature[] ordered strongest → weakest
    ▼
[Flask Backend]  port 5000
    │  Subscribes to Pareto Socket.IO (server-side)
    │  Reads rssiSignature[0].receiverId  ← nearest gateway
    │  Looks up gateway in SQLite → gets floor_id, canvas_x, canvas_y
    │  Updates assets table
    │  Serves GET /api/assets and GET /api/floors
    ▼
[PinPlot Floor Plan UI]
    │  Polls GET /api/assets?floor_id=G every 3 s
    │  Places dot at asset.canvas_x, asset.canvas_y
    │  Filters by activeFloor (G / 1F / 2F / 3F)
    │  Shows asset name, zone, lastSeen, battery in tooltip
```

### 2.2 What Pareto Anywhere handles for free

| Capability | Provided by Pareto | Custom work needed |
|---|---|---|
| Minew payload parsing | ✓ barnowl-minew built in | None |
| Multi-gateway deduplication | ✓ barnowl mixing | None |
| rssiSignature ordered by RSSI | ✓ raddec standard | None |
| Real-time Socket.IO stream | ✓ barnacles-socketio built in | None |
| BLE advertisement decoding | ✓ advlib built in | None |
| **Floor detection** | ✗ Not provided | Gateway naming (Section 4) |
| **Canvas position lookup** | ✗ Not provided | Flask DB lookup (Section 7) |
| **Asset metadata** (name, type) | ✗ Not provided | Flask assets table (Section 6) |

### 2.3 Component inventory

| Component | Technology | Where it runs |
|---|---|---|
| PinPlot XIAO firmware | Arduino / ESP-IDF | ESP32-S3 hardware |
| Pareto Anywhere | Node.js | Same Linux host as Flask |
| Flask API | Python 3.11+ | Linux host, port 5000 |
| SQLite database | SQLite3 | `./data/pinplot.db` on host |
| Floor plan UI | HTML / Canvas / JS | Browser (served by Flask) |

---

## 3. Hardware Setup — PinPlot XIAO Gateway

### 3.1 Hardware

- **Board:** Seeed Studio XIAO ESP32-S3
- **Role:** Passive BLE scanner — listens for Minew tag advertisements, does not advertise itself
- **Network:** WiFi station mode — connects to local network, POSTs to Pareto Anywhere

### 3.2 Firmware behaviour

The XIAO firmware must mimic the Minew G1 HTTP payload format exactly so that `barnowl-minew` in Pareto Anywhere parses it without any custom code. The firmware loop:

1. Scan BLE for advertisements (passive scan, all channels)
2. For each advertisement received, build a Minew G1 JSON payload
3. HTTP POST to `http://<pareto-host>:3001/minew` every 500 ms (batch interval)
4. Send a heartbeat POST every 30 s even when no tags are visible (empty `devices` array)

### 3.3 TX power reduction — floor isolation (Option 3)

This is the physical fix for multi-floor BLE bleed. A tag on floor 2 must not be heard more strongly by a gateway on floor 1 than by its own floor's gateway.

Set TX power in firmware **before** starting the BLE scan:

```cpp
// In setup(), before BLE.begin() or esp_ble_gap_start_scanning()
// Target: -12 dBm. Tune on-site — reduce further if inter-floor bleed observed.
esp_ble_tx_power_set(ESP_BLE_PWR_TYPE_SCAN, ESP_PWR_LVL_N12);

// If using NimBLE stack:
NimBLEDevice::setPower(ESP_PWR_LVL_N12);
```

**TX power tuning guide:**

| TX level | Approx range (open space) | Use when |
|---|---|---|
| ESP_PWR_LVL_P9 | ~30 m | Default — too much for multi-floor |
| ESP_PWR_LVL_N0 | ~15 m | Single floor, large open space |
| ESP_PWR_LVL_N12 | ~8 m | **Recommended starting point for multi-floor** |
| ESP_PWR_LVL_N24 | ~3 m | Dense rooms, thin walls only |

> Tune on-site by standing on the floor above/below with a BLE scanner app. If you see the gateway from the wrong floor, reduce TX further. Concrete slabs typically attenuate 15–20 dBm per floor — at −12 dBm a gateway should not be audible two floors away.

### 3.4 Minew G1 payload format the firmware must produce

`barnowl-minew` expects HTTP POST to `/minew` with this JSON structure (Minew JSON-LONG format):

```json
POST http://<pareto-host>:3001/minew
Content-Type: application/json

{
  "v": "3.0",
  "mid": 1,
  "time": 1748772004,
  "devices": [
    {
      "type": "iBeacon",
      "mac":  "AA:BB:CC:DD:EE:FF",
      "bleName": "",
      "rssi": -72,
      "data": {
        "mac": "AA:BB:CC:DD:EE:FF",
        "battery": 88,
        "Temperature": 0,
        "Humidity": 0
      }
    }
  ],
  "from": "GW-F1-01"
}
```

**Critical fields:**

| Field | Value | Notes |
|---|---|---|
| `from` | e.g. `GW-F1-01` | **This becomes `receiverId` in the raddec.** Must match `gateways.id` in SQLite exactly. |
| `devices[].mac` | Tag BLE MAC | Becomes `transmitterId` in the raddec |
| `devices[].rssi` | Integer dBm | Used by Pareto to order `rssiSignature` |
| `v` | `"3.0"` | Required by barnowl-minew parser |
| `time` | Unix timestamp (seconds) | Current epoch |

### 3.5 Firmware sketch outline (Arduino)

```cpp
#include <BLEDevice.h>
#include <WiFi.h>
#include <HTTPClient.h>
#include <ArduinoJson.h>
#include "esp_bt.h"

// ── Config ────────────────────────────────────────────────
const char* WIFI_SSID     = "YOUR_SSID";
const char* WIFI_PASS     = "YOUR_PASSWORD";
const char* PARETO_URL    = "http://192.168.1.100:3001/minew";
const char* GATEWAY_ID    = "GW-F1-01";  // CHANGE PER UNIT
const int   POST_INTERVAL = 500;         // ms

// ── BLE scan callback ─────────────────────────────────────
struct TagSighting { String mac; int rssi; };
std::vector<TagSighting> sightings;

class ScanCallback : public BLEAdvertisedDeviceCallbacks {
  void onResult(BLEAdvertisedDevice dev) override {
    sightings.push_back({ dev.getAddress().toString().c_str(), dev.getRSSI() });
  }
};

void setup() {
  Serial.begin(115200);

  // TX power reduction — set BEFORE BLE init
  esp_ble_tx_power_set(ESP_BLE_PWR_TYPE_SCAN, ESP_PWR_LVL_N12);

  BLEDevice::init("");
  BLEScan* scan = BLEDevice::getScan();
  scan->setAdvertisedDeviceCallbacks(new ScanCallback(), true);
  scan->setActiveScan(false);  // passive — do not send scan requests
  scan->setInterval(100);
  scan->setWindow(99);

  WiFi.begin(WIFI_SSID, WIFI_PASS);
  while (WiFi.status() != WL_CONNECTED) delay(500);
  Serial.println("WiFi connected: " + WiFi.localIP().toString());
}

void postToPareto() {
  StaticJsonDocument<4096> doc;
  doc["v"]    = "3.0";
  doc["mid"]  = 1;
  doc["time"] = millis() / 1000;
  doc["from"] = GATEWAY_ID;

  JsonArray devices = doc.createNestedArray("devices");
  for (auto& s : sightings) {
    JsonObject d = devices.createNestedObject();
    d["type"]    = "iBeacon";
    d["mac"]     = s.mac;
    d["bleName"] = "";
    d["rssi"]    = s.rssi;
    JsonObject data = d.createNestedObject("data");
    data["mac"]  = s.mac;
    data["battery"] = 100;  // static for MVP; read from adv payload later
  }

  String body;
  serializeJson(doc, body);

  HTTPClient http;
  http.begin(PARETO_URL);
  http.addHeader("Content-Type", "application/json");
  int code = http.POST(body);
  if (code != 200) Serial.printf("POST failed: %d\n", code);
  http.end();
}

void loop() {
  sightings.clear();
  BLEDevice::getScan()->start(0, false);  // scan for duration of POST_INTERVAL
  delay(POST_INTERVAL);
  BLEDevice::getScan()->stop();
  postToPareto();
}
```

---

## 4. Gateway Naming Convention & Floor Assignment

### 4.1 The naming convention

This is the entire multi-floor solution for MVP. Every XIAO gateway is flashed with a unique `GATEWAY_ID` constant that encodes its floor. The Flask backend uses this ID to look up which floor the gateway belongs to. No algorithm required.

```
GW - F{floor} - {unit}

Examples:
  GW-FG-01   →  Ground floor, unit 01
  GW-FG-02   →  Ground floor, unit 02
  GW-F1-01   →  First floor,  unit 01
  GW-F2-01   →  Second floor, unit 01
  GW-F3-01   →  Third floor,  unit 01
```

### 4.2 Why this works

When Pareto Anywhere receives a POST from `GW-F1-01`, the `from` field becomes `receiverId` in the raddec output:

```json
{
  "transmitterId": "aabbccddeeff",
  "rssiSignature": [
    { "receiverId": "GW-F1-01", "rssi": -65 },
    { "receiverId": "GW-F1-02", "rssi": -78 }
  ]
}
```

Flask reads `rssiSignature[0].receiverId` → `"GW-F1-01"` → SQLite lookup → `floor_id = "1F"`, `canvas_x = 340`, `canvas_y = 120`. Done.

### 4.3 Floor ID values

These must match exactly what the PinPlot floor plan UI expects in `asset.floor` (the `activeFloor` variable and `FLOORS` object keys in the UI):

| Gateway prefix | `floor_id` in SQLite | UI floor tab label |
|---|---|---|
| `GW-FG-*` | `G` | G |
| `GW-F1-*` | `1F` | 1F |
| `GW-F2-*` | `2F` | 2F |
| `GW-F3-*` | `3F` | 3F |

### 4.4 Deployment checklist per gateway

Before deploying each XIAO unit:

- [ ] Set `GATEWAY_ID` constant in firmware to the correct `GW-F{n}-{nn}` value
- [ ] Flash firmware
- [ ] Confirm gateway appears in Pareto Anywhere UI at `http://localhost:3001`
- [ ] Register gateway in SQLite with correct `floor_id`, `canvas_x`, `canvas_y`, `room_label`
- [ ] Place gateway physically in the ceiling/wall of the target room

---

## 5. Pareto Anywhere Setup

### 5.1 Installation

```bash
# Prerequisites: Node.js 18+ LTS
git clone --recurse-submodules https://github.com/reelyactive/pareto-anywhere.git
cd pareto-anywhere
npm install
```

### 5.2 Start

```bash
npm start
# Pareto Anywhere now running at http://localhost:3001
# barnowl-minew listening at http://localhost:3001/minew
# Socket.IO streaming at ws://localhost:3001
```

### 5.3 Verify XIAO gateway is reaching Pareto

```bash
# Manual test — send a fake sighting from a terminal
curl -X POST http://localhost:3001/minew \
  -H "Content-Type: application/json" \
  -d '{
    "v":"3.0","mid":1,"time":1700000000,
    "from":"GW-FG-01",
    "devices":[{"type":"iBeacon","mac":"AA:BB:CC:DD:EE:FF",
                "bleName":"","rssi":-70,
                "data":{"mac":"AA:BB:CC:DD:EE:FF","battery":88}}]
  }'

# Expected response: HTTP 200
# Browse to http://localhost:3001 to see the device appear
```

### 5.4 Pareto Socket.IO events Flask subscribes to

Flask connects to Pareto's Socket.IO as a **client** (server-to-server). The event to listen for is `raddec`:

```python
# Flask subscribes to Pareto's raddec stream
import socketio

pareto_sio = socketio.Client()

@pareto_sio.on('raddec')
def on_raddec(data):
    process_raddec(data)

pareto_sio.connect('http://localhost:3001')
```

The raddec payload shape from Pareto:

```json
{
  "transmitterId": "aabbccddeeff",
  "transmitterIdType": 2,
  "rssiSignature": [
    { "receiverId": "GW-FG-01", "receiverIdType": 2, "rssi": -65, "numberOfDecodings": 3 },
    { "receiverId": "GW-FG-02", "receiverIdType": 2, "rssi": -81, "numberOfDecodings": 1 }
  ],
  "packets": ["0201060303..."],
  "timestamp": 1748772004123
}
```

> `rssiSignature` is always **sorted strongest first** by Pareto. `rssiSignature[0]` is always the nearest gateway. No sorting needed in Flask.

---

## 6. Database Schema

Single SQLite file at `./data/pinplot.db`. Three tables only for MVP.

```sql
-- ── Floors ────────────────────────────────────────────────────────────
-- One row per floor. floor_id matches the UI's activeFloor key exactly.
CREATE TABLE IF NOT EXISTS floors (
  floor_id    TEXT PRIMARY KEY,   -- 'G' | '1F' | '2F' | '3F'
  name        TEXT NOT NULL,      -- e.g. 'Ground Floor — Warehouse'
  canvas_w    INTEGER NOT NULL DEFAULT 1000,
  canvas_h    INTEGER NOT NULL DEFAULT 680,
  elements    TEXT,               -- JSON blob from Floorplan tool v1 (walls, rooms, doors)
  published   INTEGER NOT NULL DEFAULT 0,
  updated_at  TEXT NOT NULL
);

-- ── Gateways ──────────────────────────────────────────────────────────
-- One row per physical XIAO gateway.
-- gateway_id MUST match the 'from' field in the XIAO firmware exactly.
CREATE TABLE IF NOT EXISTS gateways (
  gateway_id  TEXT PRIMARY KEY,   -- e.g. 'GW-FG-01' — must match firmware GATEWAY_ID
  floor_id    TEXT NOT NULL REFERENCES floors(floor_id),
  room_label  TEXT NOT NULL,      -- e.g. 'Receiving Bay' — shown in UI tooltip zone field
  canvas_x    REAL NOT NULL,      -- x position in floor plan coordinate space (0–1000)
  canvas_y    REAL NOT NULL,      -- y position in floor plan coordinate space (0–680)
  active      INTEGER NOT NULL DEFAULT 1,
  last_seen   TEXT                -- ISO timestamp of last sighting POST received
);

-- ── Assets ────────────────────────────────────────────────────────────
-- One row per tracked tag. Updated on every raddec event.
-- Fields map directly to the PinPlot UI asset object shape.
CREATE TABLE IF NOT EXISTS assets (
  tag_id      TEXT PRIMARY KEY,   -- BLE MAC from raddec transmitterId e.g. 'aabbccddeeff'
  name        TEXT NOT NULL DEFAULT 'Unknown Asset',
  type        TEXT NOT NULL DEFAULT 'equipment',  -- vehicle|equipment|container|personnel
  emoji       TEXT NOT NULL DEFAULT '📦',
  floor_id    TEXT REFERENCES floors(floor_id),   -- derived from nearest gateway's floor_id
  canvas_x    REAL,               -- derived from nearest gateway's canvas_x
  canvas_y    REAL,               -- derived from nearest gateway's canvas_y
  zone        TEXT,               -- derived from nearest gateway's room_label
  gateway_id  TEXT,               -- which gateway last saw this tag strongest
  rssi        INTEGER,            -- RSSI from that gateway
  battery     INTEGER,            -- from raddec dynamb if available, else null
  status      TEXT NOT NULL DEFAULT 'offline',    -- online|idle|offline
  last_seen   TEXT                -- ISO timestamp
);
```

### 6.1 Seed data — register gateways

Run once after creating the DB, before deploying hardware. Canvas coordinates must match positions in the floor plan UI's `BEACONS` array:

```sql
-- Ground floor gateways (matching BEACONS['G'] in pinplot-floorplan.html)
INSERT INTO gateways VALUES ('GW-FG-01','G','Receiving Bay',    200, 140, 1, NULL);
INSERT INTO gateways VALUES ('GW-FG-02','G','Main Warehouse',   450, 140, 1, NULL);
INSERT INTO gateways VALUES ('GW-FG-03','G','Cold Storage',     700, 140, 1, NULL);
INSERT INTO gateways VALUES ('GW-FG-04','G','Dispatch',         200, 350, 1, NULL);
INSERT INTO gateways VALUES ('GW-FG-05','G','Staging Zone',     450, 350, 1, NULL);
INSERT INTO gateways VALUES ('GW-FG-06','G','Battery Charging', 700, 350, 1, NULL);

-- First floor gateways (matching BEACONS['1F'])
INSERT INTO gateways VALUES ('GW-F1-01','1F','Open Plan Office A', 200,  80, 1, NULL);
INSERT INTO gateways VALUES ('GW-F1-02','1F','Meeting Rooms',       500,  80, 1, NULL);
INSERT INTO gateways VALUES ('GW-F1-03','1F','Server Room',         750,  80, 1, NULL);
INSERT INTO gateways VALUES ('GW-F1-04','1F','Open Plan Office B',  200, 400, 1, NULL);
INSERT INTO gateways VALUES ('GW-F1-05','1F','Finance',             620, 400, 1, NULL);
INSERT INTO gateways VALUES ('GW-F1-06','1F','Director Suite',      800, 400, 1, NULL);

-- Second floor gateways (matching BEACONS['2F'])
INSERT INTO gateways VALUES ('GW-F2-01','2F','Sales Floor A',   180,  80, 1, NULL);
INSERT INTO gateways VALUES ('GW-F2-02','2F','Sales Floor B',   460,  80, 1, NULL);
INSERT INTO gateways VALUES ('GW-F2-03','2F','Stockroom',       760,  80, 1, NULL);
INSERT INTO gateways VALUES ('GW-F2-04','2F','Sales Floor A',   180, 450, 1, NULL);
INSERT INTO gateways VALUES ('GW-F2-05','2F','Customer Service',460, 450, 1, NULL);
INSERT INTO gateways VALUES ('GW-F2-06','2F','Manager Office',  760, 450, 1, NULL);

-- Third floor gateways (matching BEACONS['3F'])
INSERT INTO gateways VALUES ('GW-F3-01','3F','Archive Storage A',  200,  80, 1, NULL);
INSERT INTO gateways VALUES ('GW-F3-02','3F','IT Equipment Store',  500,  80, 1, NULL);
INSERT INTO gateways VALUES ('GW-F3-03','3F','General Storage',     200, 480, 1, NULL);
INSERT INTO gateways VALUES ('GW-F3-04','3F','Maintenance Workshop', 490, 480, 1, NULL);
INSERT INTO gateways VALUES ('GW-F3-05','3F','CCTV Hub',            800, 480, 1, NULL);

-- Floors
INSERT INTO floors VALUES ('G',  'Ground Floor — Warehouse', 1000, 680, NULL, 1, datetime('now'));
INSERT INTO floors VALUES ('1F', 'First Floor — Offices',    1000, 680, NULL, 1, datetime('now'));
INSERT INTO floors VALUES ('2F', 'Second Floor — Retail',    1000, 680, NULL, 1, datetime('now'));
INSERT INTO floors VALUES ('3F', 'Third Floor — Plant',      1000, 680, NULL, 1, datetime('now'));
```

---

## 7. Flask API

### 7.1 File structure

```
pinplot-backend/
├── server.py          # Flask app + Pareto Socket.IO subscriber
├── db.py              # SQLite helpers
├── requirements.txt
└── data/
    └── pinplot.db     # auto-created on first run
```

### 7.2 requirements.txt

```
flask>=3.0.0
flask-cors>=4.0.0
python-socketio[client]>=5.11.0
```

### 7.3 db.py

```python
import sqlite3, os
from datetime import datetime, timezone

DB_PATH = os.environ.get('PINPLOT_DB', './data/pinplot.db')

def get_db():
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    db = sqlite3.connect(DB_PATH)
    db.row_factory = sqlite3.Row
    return db

def init_db():
    db = get_db()
    db.executescript(open('schema.sql').read())
    db.commit()
    db.close()

def get_gateway(gateway_id: str) -> dict | None:
    db = get_db()
    row = db.execute(
        'SELECT * FROM gateways WHERE gateway_id = ? AND active = 1',
        (gateway_id,)
    ).fetchone()
    db.close()
    return dict(row) if row else None

def upsert_asset(tag_id, floor_id, canvas_x, canvas_y, zone,
                 gateway_id, rssi, status, battery=None):
    db = get_db()
    db.execute('''
        INSERT INTO assets
          (tag_id, floor_id, canvas_x, canvas_y, zone,
           gateway_id, rssi, status, battery, last_seen)
        VALUES (?,?,?,?,?,?,?,?,?,?)
        ON CONFLICT(tag_id) DO UPDATE SET
          floor_id   = excluded.floor_id,
          canvas_x   = excluded.canvas_x,
          canvas_y   = excluded.canvas_y,
          zone       = excluded.zone,
          gateway_id = excluded.gateway_id,
          rssi       = excluded.rssi,
          status     = excluded.status,
          battery    = COALESCE(excluded.battery, assets.battery),
          last_seen  = excluded.last_seen
    ''', (tag_id, floor_id, canvas_x, canvas_y, zone,
          gateway_id, rssi, status, battery,
          datetime.now(timezone.utc).isoformat()))
    db.execute(
        'UPDATE gateways SET last_seen = ? WHERE gateway_id = ?',
        (datetime.now(timezone.utc).isoformat(), gateway_id)
    )
    db.commit()
    db.close()

def get_assets(floor_id=None, status=None, asset_type=None):
    db = get_db()
    query = 'SELECT * FROM assets WHERE 1=1'
    params = []
    if floor_id:
        query += ' AND floor_id = ?'; params.append(floor_id)
    if status:
        query += ' AND status = ?'; params.append(status)
    if asset_type:
        query += ' AND type = ?'; params.append(asset_type)
    rows = db.execute(query, params).fetchall()
    db.close()
    return [dict(r) for r in rows]

def get_floors():
    db = get_db()
    rows = db.execute('SELECT * FROM floors WHERE published = 1').fetchall()
    db.close()
    return [dict(r) for r in rows]

def get_gateways(floor_id=None):
    db = get_db()
    if floor_id:
        rows = db.execute(
            'SELECT * FROM gateways WHERE floor_id = ? AND active = 1', (floor_id,)
        ).fetchall()
    else:
        rows = db.execute('SELECT * FROM gateways WHERE active = 1').fetchall()
    db.close()
    return [dict(r) for r in rows]

def mark_offline():
    """Mark assets offline if not seen for 60 seconds."""
    db = get_db()
    db.execute("""
        UPDATE assets SET status = 'offline'
        WHERE status != 'offline'
          AND last_seen < datetime('now', '-60 seconds')
    """)
    db.commit()
    db.close()
```

### 7.4 server.py — core logic

```python
import threading, time
from datetime import datetime, timezone
from flask import Flask, jsonify, request
from flask_cors import CORS
import socketio as sio_client
import db

app = Flask(__name__, static_folder='../pinplot-ui', static_url_path='')
CORS(app)

PARETO_URL    = 'http://localhost:3001'
ADMIN_TOKEN   = 'change-me-in-production'

# ── Pareto Socket.IO subscriber ───────────────────────────────────────
pareto = sio_client.Client(reconnection=True, reconnection_attempts=0)

@pareto.on('connect')
def on_connect():
    print('[Pareto] Connected to Socket.IO stream')

@pareto.on('disconnect')
def on_disconnect():
    print('[Pareto] Disconnected — will reconnect automatically')

@pareto.on('raddec')
def on_raddec(data):
    """
    Called for every raddec event from Pareto Anywhere.
    rssiSignature[0] is always the strongest receiver = nearest gateway.
    """
    try:
        tag_id     = data.get('transmitterId', '').replace(':', '').lower()
        signatures = data.get('rssiSignature', [])

        if not tag_id or not signatures:
            return

        # Nearest gateway = first entry (Pareto sorts by RSSI descending)
        nearest    = signatures[0]
        gateway_id = nearest.get('receiverId', '')
        rssi       = nearest.get('rssi', -99)

        # Look up gateway → floor, canvas position, room label
        gateway = db.get_gateway(gateway_id)
        if not gateway:
            # Gateway not registered — log and skip
            print(f'[Warning] Unregistered gateway: {gateway_id}')
            return

        # Classify status from RSSI and recency
        if rssi > -85:
            status = 'online'
        elif rssi > -95:
            status = 'idle'
        else:
            status = 'offline'

        # Battery from dynamb if available (Pareto decodes Minew battery)
        battery = None
        dynamb = data.get('dynamb', {})
        if isinstance(dynamb, dict) and 'batteryPercentage' in dynamb:
            battery = int(dynamb['batteryPercentage'])

        db.upsert_asset(
            tag_id    = tag_id,
            floor_id  = gateway['floor_id'],
            canvas_x  = gateway['canvas_x'],
            canvas_y  = gateway['canvas_y'],
            zone      = gateway['room_label'],
            gateway_id= gateway_id,
            rssi      = rssi,
            status    = status,
            battery   = battery
        )
    except Exception as e:
        print(f'[Error] raddec processing failed: {e}')

def connect_to_pareto():
    """Run in a background thread — keeps reconnecting."""
    while True:
        try:
            pareto.connect(PARETO_URL)
            pareto.wait()
        except Exception as e:
            print(f'[Pareto] Connection error: {e} — retrying in 5s')
            time.sleep(5)

# ── Offline detector background job ──────────────────────────────────
def offline_detector():
    while True:
        time.sleep(15)
        db.mark_offline()

# ── REST API ──────────────────────────────────────────────────────────

@app.route('/api/assets')
def api_assets():
    """
    GET /api/assets
    Query params: floor_id, status, type
    Returns asset list in the shape the PinPlot UI expects.
    """
    floor_id    = request.args.get('floor_id')
    status      = request.args.get('status')
    asset_type  = request.args.get('type')

    assets = db.get_assets(floor_id, status, asset_type)

    # Map DB fields → UI asset object shape
    def to_ui(a):
        last_seen = a.get('last_seen')
        age_str   = 'unknown'
        if last_seen:
            try:
                dt    = datetime.fromisoformat(last_seen)
                secs  = int((datetime.now(timezone.utc) - dt).total_seconds())
                if secs < 60:    age_str = f'{secs}s ago'
                elif secs < 3600:age_str = f'{secs//60}m ago'
                else:            age_str = f'{secs//3600}h ago'
            except Exception:
                pass
        return {
            'id':       a['tag_id'],        # UI uses 'id' for hit testing
            'tagId':    a['tag_id'],
            'name':     a['name'],
            'type':     a['type'],
            'emoji':    a['emoji'],
            'floor':    a['floor_id'],      # UI filters by asset.floor === activeFloor
            'status':   a['status'],
            'zone':     a['zone'] or '',
            'x':        a['canvas_x'],      # UI draws dot at (a.x, a.y)
            'y':        a['canvas_y'],
            'lastSeen': age_str,
            'battery':  a['battery'],
            'gatewayId':a['gateway_id'],
            'rssi':     a['rssi'],
        }

    return jsonify({
        'count':  len(assets),
        'assets': [to_ui(a) for a in assets]
    })

@app.route('/api/floors')
def api_floors():
    """GET /api/floors — list of published floors."""
    return jsonify({'floors': db.get_floors()})

@app.route('/api/gateways')
def api_gateways():
    """GET /api/gateways?floor_id= — gateways with last_seen status."""
    floor_id = request.args.get('floor_id')
    gateways = db.get_gateways(floor_id)
    return jsonify({'gateways': gateways})

@app.route('/api/assets/<tag_id>', methods=['PUT'])
def api_update_asset(tag_id):
    """
    PUT /api/assets/<tag_id>
    Admin: set name, type, emoji for a tag.
    Header: Authorization: Bearer <ADMIN_TOKEN>
    """
    if request.headers.get('Authorization') != f'Bearer {ADMIN_TOKEN}':
        return jsonify({'error': 'Unauthorized'}), 401

    body = request.json or {}
    db_conn = db.get_db()
    db_conn.execute('''
        UPDATE assets SET
          name  = COALESCE(?, name),
          type  = COALESCE(?, type),
          emoji = COALESCE(?, emoji)
        WHERE tag_id = ?
    ''', (body.get('name'), body.get('type'), body.get('emoji'), tag_id))
    db_conn.commit()
    db_conn.close()
    return jsonify({'status': 'ok'})

@app.route('/api/gateways/unregistered')
def api_unregistered():
    """
    GET /api/gateways/unregistered
    Lists gateway IDs seen in recent raddecs but not in the gateways table.
    Useful for debugging naming mismatches.
    """
    # In-memory set populated during on_raddec processing
    return jsonify({'unregistered': list(unregistered_gateways)})

@app.route('/api/health')
def api_health():
    assets   = db.get_assets()
    gateways = db.get_gateways()
    online_gw = [g for g in gateways
                 if g.get('last_seen') and
                    (datetime.now(timezone.utc) -
                     datetime.fromisoformat(g['last_seen'])).total_seconds() < 60]
    return jsonify({
        'status':   'ok',
        'gateways': {'total': len(gateways), 'online': len(online_gw)},
        'assets':   {
            'total':   len(assets),
            'online':  sum(1 for a in assets if a['status']=='online'),
            'idle':    sum(1 for a in assets if a['status']=='idle'),
            'offline': sum(1 for a in assets if a['status']=='offline'),
        },
        'unregistered_gateways': list(unregistered_gateways),
    })

# ── Track unregistered gateway IDs for diagnostics ────────────────────
unregistered_gateways = set()

# Patch on_raddec to track unregistered gateways
_orig_on_raddec = on_raddec.__wrapped__ if hasattr(on_raddec, '__wrapped__') else None

# ── Startup ───────────────────────────────────────────────────────────
if __name__ == '__main__':
    db.init_db()
    threading.Thread(target=connect_to_pareto, daemon=True).start()
    threading.Thread(target=offline_detector,  daemon=True).start()
    print('[PinPlot] Backend starting on http://0.0.0.0:5000')
    app.run(host='0.0.0.0', port=5000, debug=False)
```

### 7.5 Endpoints summary

| Method | Path | Auth | Description |
|---|---|---|---|
| `GET` | `/api/assets` | None | All assets. Query: `?floor_id=G&status=online&type=vehicle` |
| `GET` | `/api/floors` | None | Published floors list |
| `GET` | `/api/gateways` | None | All gateways. Query: `?floor_id=G` |
| `PUT` | `/api/assets/:tag_id` | Bearer token | Set name, type, emoji for a tag |
| `GET` | `/api/gateways/unregistered` | None | Gateway IDs seen but not registered — for debugging |
| `GET` | `/api/health` | None | System health: gateway online count, asset status counts |

---

## 8. UI Integration Contract

This section defines exactly how the PinPlot floor plan UI (`pinplot-floorplan.html`) connects to the Flask backend, replacing the hardcoded `ASSETS` and `BEACONS` demo data.

### 8.1 Asset object shape

The UI's `ASSETS` array currently uses hardcoded demo data. Replace with a `fetchAssets()` function that calls the Flask API. The field names must match exactly:

```javascript
// In pinplot-floorplan.html — replace hardcoded ASSETS array

const PARETO_API = 'http://localhost:5000';
let ASSETS = [];  // populated from API

async function fetchAssets() {
  try {
    const res  = await fetch(`${PARETO_API}/api/assets?floor_id=${activeFloor}`);
    const data = await res.json();
    // Merge: preserve name/type/emoji for known assets, update position/status
    data.assets.forEach(incoming => {
      const idx = ASSETS.findIndex(a => a.id === incoming.id);
      if (idx >= 0) {
        ASSETS[idx] = { ...ASSETS[idx], ...incoming };
      } else {
        ASSETS.push(incoming);
      }
    });
    // Mark assets not in response as offline
    ASSETS.forEach(a => {
      if (a.floor === activeFloor &&
          !data.assets.find(r => r.id === a.id)) {
        a.status = 'offline';
      }
    });
    updateCounts();
    renderList();
    drawAll();
  } catch (e) {
    console.warn('[PinPlot] API fetch failed:', e.message);
  }
}

// Poll every 3 seconds
setInterval(fetchAssets, 3000);

// Also fetch immediately on floor switch
function syncFloorUI(floor) {
  activeFloor = floor;
  document.querySelectorAll('.floor-tab')
    .forEach(t => t.classList.toggle('active', t.textContent === floor));
  document.querySelectorAll('.fsw-btn')
    .forEach(b => b.classList.toggle('active', b.textContent === floor));
  ASSETS = ASSETS.filter(a => a.floor !== floor); // clear this floor
  selectedId = null;
  resetView();
  fetchAssets(); // immediate refresh for new floor
}
```

### 8.2 Gateway/beacon positions

The UI currently uses hardcoded `BEACONS` arrays per floor for the gateway marker overlays. Replace with a call to `/api/gateways`:

```javascript
let BEACONS = { G: [], '1F': [], '2F': [], '3F': [] };

async function fetchGateways() {
  try {
    const res  = await fetch(`${PARETO_API}/api/gateways`);
    const data = await res.json();
    // Reset and repopulate BEACONS from DB
    BEACONS = { G: [], '1F': [], '2F': [], '3F': [] };
    data.gateways.forEach(gw => {
      if (BEACONS[gw.floor_id]) {
        BEACONS[gw.floor_id].push({
          x: gw.canvas_x,
          y: gw.canvas_y,
          id: gw.gateway_id,
          room: gw.room_label,
          lastSeen: gw.last_seen
        });
      }
    });
    drawAll();
  } catch (e) {
    console.warn('[PinPlot] Gateway fetch failed:', e.message);
  }
}
```

### 8.3 UI field mapping — DB → UI asset object

| Flask API field | UI asset field | Used in UI |
|---|---|---|
| `id` (= tag_id) | `a.id` | Asset list `data-id`, hit testing, selection |
| `name` | `a.name` | Asset list name, tooltip |
| `type` | `a.type` | Category chip filter, icon background colour |
| `emoji` | `a.emoji` | Canvas dot emoji, asset list icon |
| `floor` (= floor_id) | `a.floor` | Floor tab filter `a.floor !== activeFloor` |
| `status` | `a.status` | Status dot colour, count cards |
| `zone` | `a.zone` | Tooltip zone field, asset list meta |
| `x` (= canvas_x) | `a.x` | Canvas dot x position |
| `y` (= canvas_y) | `a.y` | Canvas dot y position |
| `lastSeen` | `a.lastSeen` | Asset list meta, tooltip |
| `battery` | `a.battery` | Tooltip battery display |
| `tagId` | `a.tagId` | Tooltip Tag ID field |

### 8.4 Status colour mapping (already in UI)

```javascript
// Already defined in pinplot-floorplan.html — no changes needed
const statusColor = {
  online:  '#22c55e',  // --online  green
  idle:    '#f59e0b',  // --idle    amber
  offline: '#ef4444',  // --offline red
}[a.status];
```

The Flask backend produces `status: 'online' | 'idle' | 'offline'` which maps directly.

### 8.5 Health indicator in UI topbar

The live indicator in the topbar currently always shows "Live". Wire it to `/api/health`:

```javascript
async function updateHealthIndicator() {
  try {
    const res  = await fetch(`${PARETO_API}/api/health`);
    const data = await res.json();
    const live = document.querySelector('.topbar-live');
    const isLive = data.gateways.online > 0;
    live.style.color       = isLive ? 'var(--online)' : 'var(--offline)';
    live.style.borderColor = isLive ? 'rgba(34,197,94,.2)' : 'rgba(239,68,68,.2)';
    live.style.background  = isLive ? 'rgba(34,197,94,.1)' : 'rgba(239,68,68,.1)';
    live.querySelector('span:last-child').textContent =
      isLive ? `Live · ${data.gateways.online} gw` : 'No gateways';
  } catch (e) {}
}
setInterval(updateHealthIndicator, 10000);
```

---

## 9. Step-by-Step Implementation Guide

Follow these steps in order. Each step has a clear done condition before moving to the next.

---

### Step 1 — Install Pareto Anywhere

```bash
# On your Linux host
git clone --recurse-submodules https://github.com/reelyactive/pareto-anywhere.git
cd pareto-anywhere
npm install
npm start
```

**Done when:** `http://localhost:3001` loads the Pareto Anywhere dashboard in a browser.

---

### Step 2 — Verify Pareto accepts Minew payloads

```bash
curl -X POST http://localhost:3001/minew \
  -H "Content-Type: application/json" \
  -d '{
    "v":"3.0","mid":1,"time":1700000000,"from":"GW-FG-01",
    "devices":[{
      "type":"iBeacon","mac":"AA:BB:CC:DD:EE:FF",
      "bleName":"","rssi":-70,
      "data":{"mac":"AA:BB:CC:DD:EE:FF","battery":88}
    }]
  }'
```

**Done when:** Response is HTTP 200 and the device `aabbccddeeff` appears at `http://localhost:3001`.

---

### Step 3 — Flash XIAO firmware

1. Open `firmware/pinplot-xiao.ino` in Arduino IDE
2. Install libraries: `ArduinoJson`, `NimBLE-Arduino` or `ESP32 BLE Arduino`
3. Set constants for the first unit:
   ```cpp
   const char* WIFI_SSID  = "YOUR_SSID";
   const char* WIFI_PASS  = "YOUR_PASSWORD";
   const char* PARETO_URL = "http://192.168.1.100:3001/minew";
   const char* GATEWAY_ID = "GW-FG-01";  // Ground floor, unit 1
   ```
4. Flash to the XIAO board
5. Open Serial Monitor at 115200 baud — confirm `WiFi connected` and HTTP 200 responses

**Done when:** You see `POST ok: 200` in serial output and Pareto dashboard shows `GW-FG-01` as a receiver.

---

### Step 4 — Set up Flask backend

```bash
mkdir pinplot-backend && cd pinplot-backend
python3 -m venv venv && source venv/bin/activate
pip install flask flask-cors "python-socketio[client]"
# Copy server.py and db.py from Section 7
# Copy schema.sql (the CREATE TABLE statements from Section 6)
mkdir data
python3 -c "import db; db.init_db()"
```

Run the seed SQL to register gateways:

```bash
sqlite3 data/pinplot.db < seed.sql
```

Verify:

```bash
sqlite3 data/pinplot.db "SELECT * FROM gateways;"
```

**Done when:** 21 gateway rows appear in the gateways table.

---

### Step 5 — Run Flask and verify the Pareto subscriber

```bash
python3 server.py
# Expected output:
# [PinPlot] Backend starting on http://0.0.0.0:5000
# [Pareto] Connected to Socket.IO stream
```

With the XIAO running and a Minew tag nearby, watch the console for raddec processing. Then:

```bash
curl http://localhost:5000/api/assets
# Should return the tag that was seen, with floor_id, canvas_x, canvas_y, zone
```

**Done when:** `GET /api/assets` returns at least one asset with a non-null `x`, `y`, and the correct `floor` and `zone`.

---

### Step 6 — Verify floor assignment

Hold a tag on the ground floor. Check:

```bash
curl "http://localhost:5000/api/assets?floor_id=G"
# Tag should appear

curl "http://localhost:5000/api/assets?floor_id=1F"
# Tag should NOT appear (empty list)
```

If the tag appears on the wrong floor, check:
1. `GET /api/gateways/unregistered` — is the gateway ID appearing there?
2. Confirm `GATEWAY_ID` in firmware exactly matches the `gateway_id` in the gateways table (case-sensitive)
3. If inter-floor bleed: reduce TX power in firmware (Section 3.3)

**Done when:** Tag consistently appears on the correct floor and not on adjacent floors.

---

### Step 7 — Connect the PinPlot floor plan UI

1. Open `pinplot-floorplan.html` in a text editor
2. Add the `PARETO_API` constant and replace the hardcoded `ASSETS` array with `fetchAssets()` (Section 8.1)
3. Add `fetchGateways()` to replace hardcoded `BEACONS` (Section 8.2)
4. Call `fetchGateways()` once on `DOMContentLoaded`, then `fetchAssets()` every 3 seconds
5. Open the HTML file in a browser (or serve via Flask static folder)

**Done when:** Asset dot appears on the floor plan canvas in the correct room, updates when you move the tag, and disappears to offline status when the tag is powered off.

---

### Step 8 — Onboard assets (name your tags)

By default, tags appear as "Unknown Asset" of type "equipment". Use the admin PUT endpoint to name them:

```bash
curl -X PUT http://localhost:5000/api/assets/aabbccddeeff \
  -H "Authorization: Bearer change-me-in-production" \
  -H "Content-Type: application/json" \
  -d '{"name": "Forklift #1", "type": "vehicle", "emoji": "🚛"}'
```

**Done when:** The correct name and emoji appear in the UI asset list and tooltip.

---

### Step 9 — Deploy remaining XIAO gateways

Repeat Step 3 for each additional XIAO unit, changing only `GATEWAY_ID` each time:

- Ground floor: `GW-FG-02` through `GW-FG-06`
- First floor:  `GW-F1-01` through `GW-F1-06`
- Second floor: `GW-F2-01` through `GW-F2-06`
- Third floor:  `GW-F3-01` through `GW-F3-05`

After each deployment, verify with `/api/health` that gateway online count increases.

**Done when:** All gateways show `last_seen` within the last 60 seconds in `GET /api/gateways`.

---

### Step 10 — Multi-floor validation

With at least one XIAO per floor active:

1. Take a tag to the ground floor — confirm dot on G tab, not on 1F, 2F, 3F
2. Move the tag to the first floor — confirm dot moves to 1F tab within 10 s
3. Stand near a stairwell on floor 1 — confirm tag does not ghost onto the G or 2F tab
4. If ghosting occurs: reduce XIAO TX power (Section 3.3) and repeat

**Done when:** Tag correctly tracks across floors with no persistent ghosting near stairwells.

---

## 10. Testing & Validation

### 10.1 Manual validation checklist

| Test | Expected | How to verify |
|---|---|---|
| Tag appears within 10 s | Dot visible on canvas | Power on tag, watch canvas |
| Tag in correct room | Dot at gateway canvas position | Compare dot to room label |
| Floor is correct | Correct floor tab highlights in UI | Switch floor tabs |
| Status changes to idle | Amber dot after 10 s no sighting | Move tag out of range |
| Status changes to offline | Red dot after 60 s | Power off tag, wait |
| Asset list matches canvas | Same assets in left panel and on map | Cross-reference |
| Asset name/type visible | Correct name in tooltip | Click asset dot |
| Multi-floor isolation | No ghosting across floors | Walk tag up a stairwell |

### 10.2 API smoke tests

```bash
# All assets
curl http://localhost:5000/api/assets | python3 -m json.tool

# Filter by floor
curl "http://localhost:5000/api/assets?floor_id=G"

# Filter by status
curl "http://localhost:5000/api/assets?status=online"

# Health check
curl http://localhost:5000/api/health | python3 -m json.tool

# Unregistered gateway debug
curl http://localhost:5000/api/gateways/unregistered

# Pareto raw stream test (separate terminal)
cd pareto-anywhere
node -e "
  const io = require('socket.io-client');
  const s  = io('http://localhost:3001');
  s.on('raddec', d => console.log(JSON.stringify(d, null, 2)));
"
```

### 10.3 Common failure modes and fixes

| Symptom | Likely cause | Fix |
|---|---|---|
| No assets appear in UI | Flask not connected to Pareto | Check `[Pareto] Connected` in Flask logs |
| Tag appears on wrong floor | Gateway ID mismatch or TX too high | Check `/api/gateways/unregistered`; reduce TX power |
| Gateway ID shows as unregistered | Firmware `GATEWAY_ID` ≠ DB `gateway_id` | Case-sensitive match required — recheck seed SQL |
| Dot jumps between rooms | Multiple gateways in range, RSSI tie | Reduce TX power; add physical separation |
| Dot doesn't update | Polling not firing | Check browser console for fetch errors; verify CORS |
| Battery always null | Tag not sending Minew sensor payload | Check `dynamb.batteryPercentage` in raddec; update firmware data field |
| All assets show offline | Offline detector too aggressive | Check `last_seen` timestamps in DB; verify UTC timezone handling |

---

## 11. What MVP Intentionally Excludes

These are documented decisions, not oversights. Each has a clear upgrade path.

| Feature | Why excluded | Upgrade path |
|---|---|---|
| **RSSI-weighted centroid** | Nearest-gateway meets MVP success criteria; centroid needs physical calibration | Add `positioning.py` after real deployment validates gateway positions |
| **WebSocket push (Flask→UI)** | 3 s polling is imperceptible to humans watching a dot; Socket.IO adds complexity and eventlet dependency | Add `flask-socketio` + `eventlet`; emit on raddec processing; UI subscribes to replace `setInterval` |
| **Zone breach alerts** | No zone management UI yet | Add `zones` table + background job checking `canvas_x,y` vs zone bounds |
| **Movement history** | Sightings not retained; no playback UI | Add `movement_history` table; populate on `upsert_asset`; new `GET /api/assets/:id/history` endpoint |
| **Admin auth (full login)** | Static Bearer token sufficient for single-operator internal tool | Add session-based auth when customer-facing portal is needed |
| **Minew G1 hardware** | XIAO only for MVP simplicity | Add `barnowl-minew` G1 support (already built into Pareto — just connect G1 to same `/minew` endpoint) |
| **Floor plan builder publish flow** | Floor plans loaded from hardcoded UI data in MVP | Add `POST /api/floorplans/publish` to receive Floorplan tool v1 JSON; extract gateway positions automatically |

---

*PinPlot MVP · Internal · BLE Nearest-Gateway Tracking · May 2026*
