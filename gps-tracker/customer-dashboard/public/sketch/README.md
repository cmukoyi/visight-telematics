# Pareto Anywhere — Floor Plan Builder

A web-based floor plan drawing tool for mapping BLE gateway positions, designed to integrate with the [Pareto Anywhere](https://www.reelyactive.com/pareto/anywhere/) platform.

---

## Features

- **Drawing tools**: Concrete walls, drywall partitions, glass walls, exterior walls, single/double doors, windows, rooms (rectangle & polygon), stairs, lifts, structural columns, text labels, BLE gateways
- **Tracing overlay**: Upload an existing floor plan (PNG, JPG, SVG) as a semi-transparent reference layer to trace over — with adjustable opacity
- **Multi-floor support**: Add and switch between floors, each with independent elements
- **Dark / Light mode**: Follows the Pareto Anywhere UI aesthetic with a configurable primary colour (`--primary` in CSS)
- **Grid & Snap**: 20px grid with magnetic snap-to-grid
- **Full undo/redo**: Up to 50 history steps
- **Export**: JSON (for backend/Leaflet) and SVG per floor
- **Import**: Re-load previously saved JSON floor plans

---

## Quick Start

### 1. Run the Python server

```bash
pip install -r requirements.txt
python server.py
```

Open `http://localhost:5000` in your browser.

### 2. Use the drawing tool

| Action | How |
|--------|-----|
| Select tool | Click `Select` or press `V` |
| Draw walls/rooms | Click and drag |
| Draw polygon room | Click to add vertices, **double-click** to close |
| Place gateway | Click once where the gateway is mounted |
| Add text label | Click to place, type in popup |
| Pan canvas | `Alt + drag` or middle-mouse drag |
| Zoom | Mouse wheel |
| Undo / Redo | `Ctrl+Z` / `Ctrl+Y` |
| Delete selected | `Delete` key or Properties panel |
| Cancel polygon | Right-click or `Escape` |
| Deselect | `Escape` or right-click empty canvas |

### 3. Tracing an existing floor plan

1. In the left panel, under **TRACE**, click **Upload Image**
2. Select a PNG, JPG, or SVG of your existing floor plan
3. Adjust **Opacity** so you can see both the overlay and your drawing
4. Toggle **Show overlay** on/off as needed
5. Trace walls and features on top
6. The overlay is NOT exported — only your drawn elements are saved

> **PDF floor plans**: Export/screenshot your PDF to PNG first before uploading as an overlay.

### 4. Save & Export

- **Export JSON** — saves your full multi-floor plan as `floorplan.json`
- **Export SVG** — exports the current floor as a vector SVG
- The JSON can also be POSTed to the backend: `POST /api/floorplans`

---

## API Reference

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/api/health` | Health check |
| `GET` | `/api/floorplans` | Get all saved floor plans |
| `POST` | `/api/floorplans` | Save floor plan (from Export JSON) |
| `GET` | `/api/floorplans/:id` | Get a specific floor |
| `GET` | `/api/gateways` | List all gateways with canvas positions |
| `POST` | `/api/gateways/:id/seen` | Pareto Anywhere webhook for BLE sightings |
| `GET` | `/api/tags` | List all tracked BLE tags + estimated positions |
| `GET` | `/api/tags/:id` | Get a specific tag's last sighting |
| `GET` | `/api/map/:floor_id` | GeoJSON for Leaflet.js rendering |

---

## Pareto Anywhere Integration

### Posting sightings from Pareto Anywhere

Configure your Pareto Anywhere instance to POST sightings to:

```
POST http://your-server:5000/api/gateways/{gateway_id}/seen
Content-Type: application/json

{
  "gateway_id": "GW-1",
  "tags": [
    { "id": "aa:bb:cc:dd:ee:ff", "rssi": -72 }
  ],
  "timestamp": "2025-01-01T12:00:00Z"
}
```

### Displaying on a Leaflet map

```javascript
fetch('/api/map/1')
  .then(r => r.json())
  .then(data => {
    L.geoJSON(data, {
      style: f => ({ color: f.properties.color, weight: f.properties.width })
    }).addTo(map);

    data.gateways.forEach(gw => {
      L.marker(gw.latlng).bindPopup(gw.label).addTo(map);
    });
  });
```

---

## Changing the Primary Colour

Edit the `--primary` variable at the top of `styles.css`:

```css
:root {
  --primary: #006400;  /* ← Change this */
}
```

---

## File Structure

```
floorplan-tool/
├── index.html        # Main UI
├── styles.css        # Dark/light theme styles
├── app.js            # Canvas drawing engine
├── server.py         # Flask API backend
├── requirements.txt  # Python dependencies
├── data/
│   ├── floorplans.json   # Saved floor plans
│   ├── gateways.json     # Gateway config
│   └── tags.json         # BLE tag sightings
└── README.md
```
