'use strict';

/**
 * Pareto Anywhere → Mosquitto MQTT bridge
 *
 * Connects to Pareto Anywhere's Socket.IO endpoint (port 3001),
 * listens for raddec events, computes the nearest gateway position,
 * and publishes to Mosquitto so the Pinplot customer portal can
 * display live BLE tag positions on the indoor Leaflet map.
 *
 * ENV VARS:
 *   PARETO_URL          — Socket.IO URL of Pareto Anywhere  (default: http://pareto-anywhere:3001)
 *   MQTT_URL            — MQTT broker URL                  (default: mqtt://mosquitto:1883)
 *   BACKEND_URL         — Backend API URL                  (default: http://backend:8000)
 *   BRIDGE_API_KEY      — Shared secret for /api/portal/gateways (default: bridge-key-change-me)
 *   GATEWAY_POSITIONS   — JSON fallback if API unavailable  (default: {})
 *                         Example: '{"aabbccddeeff":{"x":185,"y":125}}'
 */

const { io }  = require('socket.io-client');
const mqtt    = require('mqtt');

const PARETO_URL    = process.env.PARETO_URL    || 'http://pareto-anywhere:3001';
const MQTT_URL      = process.env.MQTT_URL      || 'mqtt://mosquitto:1883';
const BACKEND_URL   = process.env.BACKEND_URL   || 'http://backend:8000';
const BRIDGE_API_KEY = process.env.BRIDGE_API_KEY || 'bridge-key-change-me';

// Gateway positions: receiverId → { x, y, floor_id, floor_label, building_id }
// Seeded from env var fallback, refreshed from API every 60 s
let gatewayPositions = {};
try {
    const envPositions = JSON.parse(process.env.GATEWAY_POSITIONS || '{}');
    if (Object.keys(envPositions).length) {
        gatewayPositions = envPositions;
        console.log(`[config] ${Object.keys(gatewayPositions).length} gateway position(s) loaded from env fallback`);
    }
} catch (e) {
    console.warn('[config] GATEWAY_POSITIONS is not valid JSON — skipping env fallback');
}

async function fetchGatewayPositions() {
    try {
        const res = await fetch(`${BACKEND_URL}/api/portal/gateways`, {
            headers: { 'X-Bridge-Key': BRIDGE_API_KEY }
        });
        if (!res.ok) throw new Error('HTTP ' + res.status);
        const data = await res.json();
        gatewayPositions = data;
        console.log(`[api]   ${Object.keys(gatewayPositions).length} gateway position(s) loaded from API`);
    } catch (e) {
        console.warn('[api]   Could not fetch gateway positions:', e.message, '— using last known / env fallback');
    }
}

// Fetch on startup and refresh every 60 seconds
fetchGatewayPositions();
const _gwRefreshTimer = setInterval(fetchGatewayPositions, 60_000);

// ── MQTT client ──────────────────────────────────────────────────────────────
const mqttClient = mqtt.connect(MQTT_URL, {
    clientId: 'pinplot-bridge-' + Math.random().toString(16).slice(2, 8),
    reconnectPeriod: 5000,
    connectTimeout: 15000,
});

mqttClient.on('connect', () => console.log(`[mqtt]  Connected to ${MQTT_URL}`));
mqttClient.on('error',   e  => console.error('[mqtt]  Error:', e.message));
mqttClient.on('close',   ()  => console.warn('[mqtt]  Disconnected'));

function publish(topic, payload) {
    if (!mqttClient.connected) return;
    mqttClient.publish(topic, JSON.stringify(payload), { qos: 0, retain: false });
}

// ── Pareto Anywhere Socket.IO ────────────────────────────────────────────────
console.log(`[pareto] Connecting to ${PARETO_URL}`);

const socket = io(PARETO_URL, {
    transports:       ['polling', 'websocket'],
    reconnection:     true,
    reconnectionDelay: 5000,
    timeout:          10000,
});

socket.on('connect',       ()  => console.log('[pareto] Socket.IO connected'));
socket.on('disconnect',    ()  => console.warn('[pareto] Socket.IO disconnected'));
socket.on('connect_error', e   => console.error('[pareto] Socket.IO error:', e.message));

// ── raddec handler ───────────────────────────────────────────────────────────
socket.on('raddec', raddec => {
    const devId = raddec.transmitterId;
    if (!devId) return;

    // Always publish the raw raddec
    publish(`raddec/${devId}`, raddec);

    // Find the gateway with the strongest RSSI
    const sigs    = raddec.rssiSignature || [];
    if (!sigs.length) return;
    const nearest = sigs.reduce((best, s) => (!best || s.rssi > best.rssi) ? s : best, null);
    const gwId    = nearest?.receiverId?.toLowerCase().replace(/:/g, '');

    // Compute position from nearest gateway
    const pos = gwId ? gatewayPositions[gwId] : null;

    const posPayload = {
        deviceId:       devId,
        nearestGateway: gwId,
        rssi:           nearest?.rssi,
        timestamp:      raddec.timestamp || Date.now(),
        x:              pos?.x ?? null,
        y:              pos?.y ?? null,
        floor_id:       pos?.floor_id    ?? null,
        floor_label:    pos?.floor_label ?? null,
        building_id:    pos?.building_id ?? null,
    };

    publish(`position/${devId}`, posPayload);

    if (pos) {
        console.log(`[tag]   ${devId} → GW ${gwId} RSSI ${nearest.rssi} pos(${pos.x},${pos.y})`);
    } else {
        console.log(`[tag]   ${devId} → GW ${gwId || 'unknown'} RSSI ${nearest?.rssi} (no position for gateway)`);
    }
});

// ── spatem / GeoJSON handler (chimps output) ─────────────────────────────────
socket.on('spatem', spatem => {
    try {
        const feat   = spatem?.data?.features?.[0] || spatem?.features?.[0];
        if (!feat) return;
        const devId  = spatem.deviceId || feat.properties?.deviceId;
        const [x, y] = feat.geometry?.coordinates || [];
        if (!devId || x == null) return;
        publish(`position/${devId}`, { deviceId: devId, x, y, timestamp: Date.now() });
    } catch (e) { /* ignore malformed */ }
});
