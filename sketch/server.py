"""
Pareto Anywhere — Floor Plan Backend
Serves floor plan data and provides BLE gateway/tag location API
Compatible with the Pareto Anywhere BLE platform
"""

from flask import Flask, jsonify, request, send_from_directory, abort
from flask_cors import CORS
import json
import os
import uuid
from datetime import datetime
from pathlib import Path

app = Flask(__name__, static_folder='.')
CORS(app)

DATA_DIR = Path('./data')
DATA_DIR.mkdir(exist_ok=True)
FLOORS_FILE = DATA_DIR / 'floorplans.json'
GATEWAYS_FILE = DATA_DIR / 'gateways.json'
TAGS_FILE = DATA_DIR / 'tags.json'

# ─── Helper ───────────────────────────────────────────────────────────────────
def load_json(path, default):
    try:
        if path.exists():
            return json.loads(path.read_text())
    except Exception:
        pass
    return default

def save_json(path, data):
    path.write_text(json.dumps(data, indent=2))

# ─── Floor Plans ──────────────────────────────────────────────────────────────

@app.route('/api/floorplans', methods=['GET'])
def get_floorplans():
    """Return all saved floor plans"""
    data = load_json(FLOORS_FILE, {'floors': [], 'version': '1.0'})
    return jsonify(data)

@app.route('/api/floorplans', methods=['POST'])
def save_floorplans():
    """Save floor plan data from the builder tool"""
    payload = request.get_json()
    if not payload or 'floors' not in payload:
        abort(400, 'Invalid floor plan data')
    payload['saved_at'] = datetime.utcnow().isoformat() + 'Z'
    payload.setdefault('version', '1.0')
    save_json(FLOORS_FILE, payload)
    return jsonify({'status': 'ok', 'saved_at': payload['saved_at']}), 200

@app.route('/api/floorplans/<int:floor_id>', methods=['GET'])
def get_floor(floor_id):
    """Return a specific floor's elements"""
    data = load_json(FLOORS_FILE, {'floors': []})
    for fl in data.get('floors', []):
        if fl['id'] == floor_id:
            return jsonify(fl)
    abort(404, f'Floor {floor_id} not found')

# ─── Gateways ─────────────────────────────────────────────────────────────────

@app.route('/api/gateways', methods=['GET'])
def get_gateways():
    """
    Return all BLE gateways with their floor plan positions.
    Merges saved gateway positions from the floor plan with live BLE data.
    """
    data = load_json(FLOORS_FILE, {'floors': []})
    gateways = []

    for fl in data.get('floors', []):
        for el in fl.get('elements', []):
            if el['type'] == 'gateway':
                gateways.append({
                    'id': el.get('label', el['id']),
                    'floor_id': fl['id'],
                    'floor_name': fl['name'],
                    'x': el['x1'],
                    'y': el['y1'],
                    'label': el.get('label', ''),
                    'color': el.get('color', '#006400'),
                    # Leaflet coordinates (map lat/lng from canvas x/y)
                    'leaflet_latlng': canvas_to_latlng(el['x1'], el['y1'])
                })

    return jsonify({'gateways': gateways, 'count': len(gateways)})

@app.route('/api/gateways/<gateway_id>/seen', methods=['POST'])
def gateway_seen(gateway_id):
    """
    Pareto Anywhere webhook: called when a gateway detects BLE tags.
    Expected body: { "gateway_id": "...", "tags": [...], "timestamp": "..." }
    """
    body = request.get_json() or {}
    tags = body.get('tags', [])
    ts = body.get('timestamp', datetime.utcnow().isoformat() + 'Z')

    # Load existing tag sightings
    tag_data = load_json(TAGS_FILE, {'sightings': {}})
    for tag in tags:
        tid = tag.get('id') or tag.get('mac', 'unknown')
        rssi = tag.get('rssi', -100)
        tag_data['sightings'][tid] = {
            'tag_id': tid,
            'last_seen_gateway': gateway_id,
            'rssi': rssi,
            'timestamp': ts,
            'raw': tag
        }
    save_json(TAGS_FILE, tag_data)

    return jsonify({'status': 'ok', 'tags_processed': len(tags)}), 200

# ─── Tags / Location ──────────────────────────────────────────────────────────

@app.route('/api/tags', methods=['GET'])
def get_tags():
    """Return all currently tracked BLE tags and their estimated positions"""
    tag_data = load_json(TAGS_FILE, {'sightings': {}})
    floor_data = load_json(FLOORS_FILE, {'floors': []})

    # Build a gateway position lookup
    gw_pos = {}
    for fl in floor_data.get('floors', []):
        for el in fl.get('elements', []):
            if el['type'] == 'gateway':
                gid = el.get('label', el['id'])
                gw_pos[gid] = {
                    'x': el['x1'], 'y': el['y1'],
                    'floor_id': fl['id'], 'floor_name': fl['name']
                }

    results = []
    for tid, sight in tag_data['sightings'].items():
        gw = gw_pos.get(sight.get('last_seen_gateway', ''), {})
        results.append({
            'tag_id': tid,
            'last_seen_gateway': sight.get('last_seen_gateway'),
            'rssi': sight.get('rssi', -100),
            'timestamp': sight.get('timestamp'),
            'estimated_floor': gw.get('floor_name', 'Unknown'),
            'estimated_x': gw.get('x'),
            'estimated_y': gw.get('y'),
            'leaflet_latlng': canvas_to_latlng(gw.get('x', 0), gw.get('y', 0)) if gw else None
        })

    return jsonify({'tags': results, 'count': len(results)})

@app.route('/api/tags/<tag_id>', methods=['GET'])
def get_tag(tag_id):
    """Return a specific tag's last known location"""
    tag_data = load_json(TAGS_FILE, {'sightings': {}})
    sight = tag_data['sightings'].get(tag_id)
    if not sight:
        abort(404, f'Tag {tag_id} not found')
    return jsonify(sight)

# ─── Leaflet Map ──────────────────────────────────────────────────────────────

@app.route('/api/map/<int:floor_id>', methods=['GET'])
def get_leaflet_map_data(floor_id):
    """
    Return floor plan data formatted for Leaflet.js rendering.
    The floor plan is rendered as an image overlay + GeoJSON features.
    """
    floor_data = load_json(FLOORS_FILE, {'floors': []})
    floor = next((f for f in floor_data.get('floors', []) if f['id'] == floor_id), None)
    if not floor:
        abort(404, f'Floor {floor_id} not found')

    features = []
    for el in floor.get('elements', []):
        feat = element_to_geojson(el)
        if feat:
            features.append(feat)

    return jsonify({
        'floor_id': floor_id,
        'floor_name': floor['name'],
        'type': 'FeatureCollection',
        'features': features,
        'gateways': [
            {
                'id': el.get('label', el['id']),
                'latlng': canvas_to_latlng(el['x1'], el['y1']),
                'label': el.get('label', '')
            }
            for el in floor.get('elements', []) if el['type'] == 'gateway'
        ]
    })

# ─── Coordinate Conversion ────────────────────────────────────────────────────

SCALE = 0.001  # 1 canvas pixel = 0.001 degrees

def canvas_to_latlng(x, y):
    """Convert canvas coordinates to Leaflet lat/lng (simple linear mapping)."""
    return [-(y * SCALE), x * SCALE]

def element_to_geojson(el):
    """Convert a floor plan element to GeoJSON for Leaflet overlay."""
    t = el['type']
    props = {
        'id': el['id'],
        'type': t,
        'label': el.get('label', ''),
        'color': el.get('color', '#006400'),
        'width': el.get('width', 2)
    }

    if t in ('wall-concrete', 'wall-drywall', 'wall-glass', 'wall-exterior',
             'door-single', 'door-double', 'window'):
        return {
            'type': 'Feature',
            'properties': props,
            'geometry': {
                'type': 'LineString',
                'coordinates': [
                    [el['x1'] * SCALE, -(el['y1'] * SCALE)],
                    [el['x2'] * SCALE, -(el['y2'] * SCALE)]
                ]
            }
        }

    if t in ('room', 'stairs', 'lift', 'column'):
        x1, y1, x2, y2 = el['x1'], el['y1'], el['x2'], el['y2']
        coords = [
            [x1 * SCALE, -(y1 * SCALE)],
            [x2 * SCALE, -(y1 * SCALE)],
            [x2 * SCALE, -(y2 * SCALE)],
            [x1 * SCALE, -(y2 * SCALE)],
            [x1 * SCALE, -(y1 * SCALE)],
        ]
        return {
            'type': 'Feature',
            'properties': props,
            'geometry': {'type': 'Polygon', 'coordinates': [coords]}
        }

    if t == 'polygon' and el.get('points'):
        coords = [[p['x'] * SCALE, -(p['y'] * SCALE)] for p in el['points']]
        if el.get('closed') and coords:
            coords.append(coords[0])
        return {
            'type': 'Feature',
            'properties': props,
            'geometry': {'type': 'Polygon' if el.get('closed') else 'LineString',
                        'coordinates': [coords] if el.get('closed') else coords}
        }

    if t == 'gateway':
        return {
            'type': 'Feature',
            'properties': {**props, 'marker_type': 'gateway'},
            'geometry': {
                'type': 'Point',
                'coordinates': [el['x1'] * SCALE, -(el['y1'] * SCALE)]
            }
        }

    return None

# ─── Static Files ─────────────────────────────────────────────────────────────

@app.route('/')
def index():
    return send_from_directory('.', 'index.html')

@app.route('/<path:filename>')
def static_files(filename):
    return send_from_directory('.', filename)

# ─── Health ───────────────────────────────────────────────────────────────────

@app.route('/api/health', methods=['GET'])
def health():
    return jsonify({
        'status': 'ok',
        'service': 'Pareto Anywhere Floor Plan Builder API',
        'version': '1.0.0',
        'timestamp': datetime.utcnow().isoformat() + 'Z'
    })

# ─── Entry Point ──────────────────────────────────────────────────────────────

if __name__ == '__main__':
    print("=" * 60)
    print("  Pareto Anywhere Floor Plan Builder")
    print("  Backend API + Static File Server")
    print("=" * 60)
    print(f"  UI:     http://localhost:5000/")
    print(f"  API:    http://localhost:5000/api/")
    print(f"  Health: http://localhost:5000/api/health")
    print("=" * 60)
    app.run(debug=True, host='0.0.0.0', port=5000)
