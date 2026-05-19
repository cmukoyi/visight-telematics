/*
 * PinPlot XIAO Gateway — Reference Firmware (MVP)
 *
 * Board:    Seeed Studio XIAO ESP32-S3
 * Role:     Passive BLE scanner. Listens for nearby BLE advertisements
 *           (e.g. Minew tags) and forwards them to a Pareto Anywhere
 *           instance on the local network via HTTP POST /minew. Mimics
 *           the Minew G1 JSON-LONG payload so barnowl-minew parses it
 *           with no custom decoder.
 *
 * Per-unit:    GATEWAY_ID, WIFI_SSID, WIFI_PASS, PARETO_URL.
 *              GATEWAY_ID convention: GW-F{floor}-{nn}, e.g. GW-FG-01,
 *              GW-F1-03. Must match the IndoorGateway.receiver_id
 *              registered via the PinPlot admin API.
 *
 * Floor isolation: TX power held at ESP_PWR_LVL_N12 (~ -12 dBm, ~8 m
 *              open-air range). Tune downward on-site if a tag on the
 *              floor above/below is heard stronger than by its own
 *              floor's gateway.
 *
 * Spec:        features_dev/Pinplot floorplan spec.md sections 3 & 4.
 */

#include <Arduino.h>
#include <WiFi.h>
#include <HTTPClient.h>
#include <ArduinoJson.h>
#include <BLEDevice.h>
#include <BLEScan.h>
#include <BLEAdvertisedDevice.h>
#include "esp_bt.h"
#include "esp_gap_ble_api.h"

// ── Per-unit config — CHANGE BEFORE FLASHING ─────────────────────────────
static const char* WIFI_SSID  = "YOUR_SSID";
static const char* WIFI_PASS  = "YOUR_PASSWORD";
static const char* PARETO_URL = "http://192.168.1.100:3001/minew";
static const char* GATEWAY_ID = "GW-FG-01";        // ← unique per gateway

// ── Behaviour ────────────────────────────────────────────────────────────
static const uint32_t POST_INTERVAL_MS = 500;      // batch scan window
static const uint32_t HEARTBEAT_MS     = 30000;    // send empty POST every N ms

// ── State ────────────────────────────────────────────────────────────────
struct TagSighting {
  String mac;
  int    rssi;
};

static std::vector<TagSighting> g_sightings;
static uint32_t g_last_heartbeat = 0;
static uint32_t g_post_seq       = 0;

// ── BLE callback ─────────────────────────────────────────────────────────
class ScanCallback : public BLEAdvertisedDeviceCallbacks {
 public:
  void onResult(BLEAdvertisedDevice dev) override {
    TagSighting s;
    s.mac  = dev.getAddress().toString().c_str();
    s.rssi = dev.getRSSI();
    g_sightings.push_back(s);
  }
};

// ── Helpers ──────────────────────────────────────────────────────────────
static void connectWifi() {
  Serial.printf("[wifi] connecting to %s\n", WIFI_SSID);
  WiFi.mode(WIFI_STA);
  WiFi.begin(WIFI_SSID, WIFI_PASS);
  uint32_t start = millis();
  while (WiFi.status() != WL_CONNECTED && (millis() - start) < 30000) {
    delay(500);
    Serial.print('.');
  }
  if (WiFi.status() == WL_CONNECTED) {
    Serial.printf("\n[wifi] connected, ip=%s\n", WiFi.localIP().toString().c_str());
  } else {
    Serial.println("\n[wifi] FAILED — will retry");
  }
}

static void postToPareto(const std::vector<TagSighting>& sightings) {
  if (WiFi.status() != WL_CONNECTED) {
    connectWifi();
    if (WiFi.status() != WL_CONNECTED) return;
  }

  // Reasonable upper bound: ~80 bytes per device × 32 max devices + header.
  StaticJsonDocument<4096> doc;
  doc["v"]    = "3.0";
  doc["mid"]  = ++g_post_seq;
  doc["time"] = (uint32_t)(millis() / 1000);
  doc["from"] = GATEWAY_ID;

  JsonArray devices = doc.createNestedArray("devices");
  size_t cap = sightings.size() > 32 ? 32 : sightings.size();
  for (size_t i = 0; i < cap; i++) {
    JsonObject d = devices.createNestedObject();
    d["type"]    = "iBeacon";
    d["mac"]     = sightings[i].mac;
    d["bleName"] = "";
    d["rssi"]    = sightings[i].rssi;
    JsonObject data = d.createNestedObject("data");
    data["mac"]     = sightings[i].mac;
    data["battery"] = 100;   // MVP: static; replace with adv-decoded value later
  }

  String body;
  serializeJson(doc, body);

  HTTPClient http;
  http.setConnectTimeout(2000);
  http.setTimeout(3000);
  http.begin(PARETO_URL);
  http.addHeader("Content-Type", "application/json");
  int code = http.POST(body);
  if (code != 200 && code != 204) {
    Serial.printf("[pareto] POST failed (code=%d) devices=%u\n", code, (unsigned)cap);
  }
  http.end();
}

// ── Arduino entry points ─────────────────────────────────────────────────
void setup() {
  Serial.begin(115200);
  delay(200);
  Serial.printf("\n[pinplot-xiao] gateway=%s pareto=%s\n", GATEWAY_ID, PARETO_URL);

  // TX power reduction MUST be set before BLE init for it to apply to
  // the scanner. ESP_PWR_LVL_N12 ≈ -12 dBm — recommended floor-isolation
  // starting point. Lower (N24) for dense rooms, raise (N0/P3) for
  // single-floor large spaces.
  esp_ble_tx_power_set(ESP_BLE_PWR_TYPE_SCAN, ESP_PWR_LVL_N12);

  BLEDevice::init("");
  BLEScan* scan = BLEDevice::getScan();
  scan->setAdvertisedDeviceCallbacks(new ScanCallback(), /*wantDuplicates=*/true);
  scan->setActiveScan(false);   // passive — don't transmit scan requests
  scan->setInterval(100);
  scan->setWindow(99);

  connectWifi();
  g_last_heartbeat = millis();
}

void loop() {
  g_sightings.clear();

  // Scan for the POST window, then flush. start(0) is non-blocking with
  // an internal duration; we gate on our own delay so timing is precise.
  BLEDevice::getScan()->start(0, /*is_continue=*/false);
  delay(POST_INTERVAL_MS);
  BLEDevice::getScan()->stop();

  const bool heartbeat_due = (millis() - g_last_heartbeat) >= HEARTBEAT_MS;
  if (!g_sightings.empty() || heartbeat_due) {
    postToPareto(g_sightings);
    g_last_heartbeat = millis();
  }
}
