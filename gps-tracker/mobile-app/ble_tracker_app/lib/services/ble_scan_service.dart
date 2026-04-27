import 'dart:async';
import 'dart:convert';

import 'package:flutter/foundation.dart';
import 'package:geolocator/geolocator.dart';
import 'package:http/http.dart' as http;
import 'package:permission_handler/permission_handler.dart';

import '../config/environment.dart';
import '../models/beacon_sighting_model.dart';
import 'auth_service.dart';
import '_ble_platform.dart';

/// Service that co-ordinates BLE scanning, phone GPS, and backend reporting.
///
/// Design goals:
///   Singleton     – one shared instance, no repeated bluetooth setup.
///   Observable    – [beaconStream] / [scanningStream] drive reactive UIs.
///   Expandable    – BLE hardware logic lives in [BlePlatform] only.
///                   Filtering, iBeacon UUID allowlists, RSSI smoothing, etc.
///                   can be added here without touching the UI layer.
///   Rate-limited  – each tag is reported to the backend at most once per
///                   [_reportCooldown] to avoid flooding the API.
class BLEScanService {
  // ── Singleton ──────────────────────────────────────────────────────────────
  static final BLEScanService _instance = BLEScanService._internal();
  factory BLEScanService() => _instance;
  BLEScanService._internal();

  // ── Dependencies ───────────────────────────────────────────────────────────
  final BlePlatform _ble = const BlePlatform();
  final AuthService _auth = AuthService();

  // ── State ──────────────────────────────────────────────────────────────────
  final Map<String, DiscoveredBeacon> _beaconMap = {};
  final _beaconsCtrl =
      StreamController<List<DiscoveredBeacon>>.broadcast();
  final _scanningCtrl = StreamController<bool>.broadcast();

  StreamSubscription<List<DiscoveredBeacon>>? _scanSub;
  bool _isScanning = false;

  // Rate-limit backend calls: same tag → max 1 report per [_reportCooldown].
  final Map<String, DateTime> _lastReported = {};
  static const _reportCooldown = Duration(seconds: 30);

  // ── Public API ─────────────────────────────────────────────────────────────

  /// Emits the latest list of beacons seen in the current scan session.
  Stream<List<DiscoveredBeacon>> get beaconStream => _beaconsCtrl.stream;

  /// Emits `true` when scanning starts and `false` when it stops.
  Stream<bool> get scanningStream => _scanningCtrl.stream;

  bool get isScanning => _isScanning;

  /// `false` on Flutter Web (BLE not available in browsers).
  bool get isAvailable => _ble.isAvailable;

  /// Snapshot of beacons found in the current scan.
  List<DiscoveredBeacon> get discoveredBeacons =>
      List.unmodifiable(_beaconMap.values.toList());

  /// Request Bluetooth + location permissions.
  /// Returns `true` if all required permissions were granted.
  Future<bool> requestPermissions() async {
    if (!_ble.isAvailable) return false;
    final results = await [
      Permission.locationWhenInUse,
      Permission.bluetoothScan,
      Permission.bluetoothConnect,
    ].request();
    return results.values.every((s) => s.isGranted);
  }

  /// Start a BLE scan that auto-stops after [timeout].
  ///
  /// Throws [UnsupportedError] on web.
  /// Throws [Exception] if permissions are denied.
  Future<void> startScan({
    Duration timeout = const Duration(seconds: 30),
  }) async {
    if (!_ble.isAvailable) {
      throw UnsupportedError('BLE scanning is not available on this platform.');
    }
    if (_isScanning) return;

    final granted = await requestPermissions();
    if (!granted) throw Exception('Bluetooth and location permissions are required.');

    _beaconMap.clear();
    _setScanning(true);

    await _ble.startScan(timeout: timeout);

    _scanSub = _ble.scanResults.listen(
      _onResults,
      onDone: () => _setScanning(false),
      onError: (_) => _setScanning(false),
    );
  }

  Future<void> stopScan() async {
    if (!_isScanning) return;
    await _ble.stopScan();
    await _scanSub?.cancel();
    _scanSub = null;
    _setScanning(false);
  }

  /// Returns the device's current GPS position, or `null` on failure / timeout.
  Future<Position?> getCurrentPosition() => _getPosition();

  /// Returns the last known location of every BLE tag sighted by this user.
  Future<List<BeaconLocation>> getBeaconLocations() async {
    try {
      final token = await _auth.getToken();
      if (token == null) return [];

      final response = await http
          .get(
            Uri.parse('${Environment.apiBaseUrl}/api/v1/beacons/locations'),
            headers: {'Authorization': 'Bearer $token'},
          )
          .timeout(const Duration(seconds: 10));

      if (response.statusCode == 200) {
        final data = json.decode(response.body) as List<dynamic>;
        return data
            .map((j) => BeaconLocation.fromJson(j as Map<String, dynamic>))
            .toList();
      }
    } catch (e) {
      debugPrint('[BLEScanService] getBeaconLocations: $e');
    }
    return [];
  }

  void dispose() {
    stopScan();
    _beaconsCtrl.close();
    _scanningCtrl.close();
  }

  // ── Private helpers ────────────────────────────────────────────────────────

  void _setScanning(bool value) {
    _isScanning = value;
    if (!_scanningCtrl.isClosed) _scanningCtrl.add(value);
  }

  Future<void> _onResults(List<DiscoveredBeacon> beacons) async {
    Position? position;
    final now = DateTime.now();

    for (final beacon in beacons) {
      _beaconMap[beacon.id] = beacon;

      // Only report when the cooldown has elapsed for this specific tag.
      final last = _lastReported[beacon.id];
      if (last == null || now.difference(last) >= _reportCooldown) {
        position ??= await _getPosition();
        if (position != null) {
          _reportSighting(beacon, position).ignore();
          _lastReported[beacon.id] = now;
        }
      }
    }

    if (!_beaconsCtrl.isClosed) {
      _beaconsCtrl.add(discoveredBeacons);
    }
  }

  Future<Position?> _getPosition() async {
    try {
      return await Geolocator.getCurrentPosition(
        desiredAccuracy: LocationAccuracy.high,
        timeLimit: const Duration(seconds: 5),
      );
    } catch (e) {
      debugPrint('[BLEScanService] GPS error: $e');
      return null;
    }
  }

  Future<void> _reportSighting(DiscoveredBeacon beacon, Position pos) async {
    try {
      final token = await _auth.getToken();
      if (token == null) return;

      await http
          .post(
            Uri.parse('${Environment.apiBaseUrl}/api/v1/beacons/sighting'),
            headers: {
              'Content-Type': 'application/json',
              'Authorization': 'Bearer $token',
            },
            body: json.encode({
              'tag_id': beacon.id,
              'tag_name': beacon.name,
              'lat': pos.latitude,
              'lon': pos.longitude,
              'rssi': beacon.rssi,
              'timestamp': DateTime.now().toUtc().toIso8601String(),
            }),
          )
          .timeout(const Duration(seconds: 8));
    } catch (e) {
      debugPrint('[BLEScanService] reportSighting: $e');
    }
  }
}
