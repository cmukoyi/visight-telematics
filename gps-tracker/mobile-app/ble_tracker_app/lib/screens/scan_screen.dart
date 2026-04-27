import 'dart:async';
import 'dart:math' show pow;

import 'package:flutter/foundation.dart';
import 'package:flutter/material.dart';
import 'package:flutter_map/flutter_map.dart' as fmap;
import 'package:google_fonts/google_fonts.dart';
import 'package:latlong2/latlong.dart' as latlong;

import 'package:ble_tracker_app/models/beacon_sighting_model.dart';
import 'package:ble_tracker_app/services/ble_scan_service.dart';
import 'package:ble_tracker_app/services/pareto_decoder.dart';
import 'package:ble_tracker_app/theme/app_theme.dart';

class ScanScreen extends StatefulWidget {
  const ScanScreen({Key? key}) : super(key: key);

  @override
  State<ScanScreen> createState() => _ScanScreenState();
}

class _ScanScreenState extends State<ScanScreen> {
  final BLEScanService _service = BLEScanService();
  final fmap.MapController _mapController = fmap.MapController();

  List<DiscoveredBeacon> _discovered = [];
  List<BeaconLocation> _savedLocations = [];
  bool _isScanning = false;
  bool _loadingLocations = false;
  String? _error;

  // Local plots: beacon ID → position pinned by user tap
  final Map<String, latlong.LatLng> _localPlotPositions = {};
  final Map<String, DiscoveredBeacon> _localPlotBeacons = {};
  final Set<String> _plotting = {};

  StreamSubscription<List<DiscoveredBeacon>>? _beaconSub;
  StreamSubscription<bool>? _scanningSub;

  // Default map centre (London UK). Overridden when beacons are available.
  latlong.LatLng _mapCentre = const latlong.LatLng(51.5074, -0.1278);
  double _mapZoom = 5.0;

  @override
  void initState() {
    super.initState();
    _beaconSub = _service.beaconStream.listen((beacons) {
      if (mounted) setState(() => _discovered = beacons);
    });
    _scanningSub = _service.scanningStream.listen((scanning) {
      if (mounted) setState(() => _isScanning = scanning);
    });
    _loadSavedLocations();
  }

  @override
  void dispose() {
    _beaconSub?.cancel();
    _scanningSub?.cancel();
    // Don't stop the scan on dispose – user may have navigated to another tab;
    // stopping is explicit via the Stop button.
    super.dispose();
  }

  Future<void> _loadSavedLocations() async {
    setState(() => _loadingLocations = true);
    final locs = await _service.getBeaconLocations();
    if (!mounted) return;
    setState(() {
      _savedLocations = locs;
      _loadingLocations = false;
      if (locs.isNotEmpty) {
        _mapCentre = latlong.LatLng(locs.first.lat, locs.first.lon);
        _mapZoom = 13.0;
      }
    });
  }

  Future<void> _plotBeacon(DiscoveredBeacon beacon) async {
    if (_plotting.contains(beacon.id)) return;
    setState(() => _plotting.add(beacon.id));
    try {
      final pos = await _service.getCurrentPosition();
      if (pos != null && mounted) {
        final ll = latlong.LatLng(pos.latitude, pos.longitude);
        setState(() {
          _localPlotPositions[beacon.id] = ll;
          _localPlotBeacons[beacon.id] = beacon;
          _plotting.remove(beacon.id);
        });
        _mapController.move(ll, 15.0);
      } else if (mounted) {
        setState(() => _plotting.remove(beacon.id));
        ScaffoldMessenger.of(context).showSnackBar(
          const SnackBar(
              content: Text('Could not get your location. Check GPS permissions.')),
        );
      }
    } catch (e) {
      if (mounted) setState(() => _plotting.remove(beacon.id));
    }
  }

  Future<void> _toggleScan() async {
    setState(() => _error = null);
    try {
      if (_isScanning) {
        await _service.stopScan();
        // Refresh saved locations after a scan ends.
        await _loadSavedLocations();
      } else {
        await _service.startScan(timeout: const Duration(seconds: 30));
      }
    } on UnsupportedError catch (e) {
      setState(() => _error = e.message);
    } catch (e) {
      setState(
          () => _error = e.toString().replaceFirst('Exception: ', ''));
    }
  }

  // ── Build ──────────────────────────────────────────────────────────────────

  @override
  Widget build(BuildContext context) {
    if (kIsWeb) return _buildWebUnavailable();

    return Column(
      children: [
        // Space below the top nav bar rendered by MapScreen's Stack.
        const SizedBox(height: 80),

        // ── Map area ──────────────────────────────────────────────────────
        Expanded(child: _buildMap()),

        // ── Control panel ─────────────────────────────────────────────────
        _buildControlPanel(),
      ],
    );
  }

  Widget _buildMap() {
    final markers = _buildMarkers();
    return fmap.FlutterMap(
      mapController: _mapController,
      options: fmap.MapOptions(
        initialCenter: _mapCentre,
        initialZoom: _mapZoom,
        interactionOptions: const fmap.InteractionOptions(
          flags: fmap.InteractiveFlag.all,
        ),
      ),
      children: [
        fmap.TileLayer(
          urlTemplate: 'https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png',
          subdomains: const ['a', 'b', 'c'],
          userAgentPackageName: 'com.beacontelematics.tracker',
          maxZoom: 18,
          tileSize: 256,
          tileDisplay: fmap.TileDisplay.fadeIn(
            duration: const Duration(milliseconds: 50),
          ),
        ),
        if (markers.isNotEmpty) fmap.MarkerLayer(markers: markers),
      ],
    );
  }

  List<fmap.Marker> _buildMarkers() {
    final markers = <fmap.Marker>[];

    // Build a set of IDs that were detected as Pareto devices in this session.
    final paretoIds = {
      for (final b in _discovered)
        if (ParetoDecoder.decode(b).isPareto) b.id,
    };

    for (final loc in _savedLocations) {
      final isPareto = paretoIds.contains(loc.tagId);
      final liveMatches = _discovered.where((b) => b.id == loc.tagId);
      final liveBeacon = liveMatches.isEmpty ? null : liveMatches.first;
      final isLive = liveBeacon != null;
      final color = isPareto ? Colors.indigo.shade700 : Colors.teal.shade700;
      final icon = isPareto ? Icons.sensors : Icons.bluetooth;

      markers.add(
        fmap.Marker(
          point: latlong.LatLng(loc.lat, loc.lon),
          width: 44,
          height: 44,
          child: GestureDetector(
            onTap: () => _showMarkerDetail(
              id: loc.tagId,
              displayName: loc.displayName,
              liveBeacon: liveBeacon,
              savedLocation: loc,
            ),
            child: Container(
              decoration: BoxDecoration(
                color: color,
                shape: BoxShape.circle,
                border: Border.all(
                  color: isLive ? Colors.greenAccent.shade400 : Colors.white,
                  width: isLive ? 3 : 2,
                ),
                boxShadow: const [
                  BoxShadow(color: Colors.black26, blurRadius: 4)
                ],
              ),
              child: Icon(icon, color: Colors.white, size: 20),
            ),
          ),
        ),
      );
    }

    // Local user-tapped plot markers (pinned by tapping a device in the list)
    for (final id in _localPlotPositions.keys) {
      final ll = _localPlotPositions[id]!;
      final beacon = _localPlotBeacons[id];
      markers.add(
        fmap.Marker(
          point: ll,
          width: 44,
          height: 44,
          child: GestureDetector(
            onTap: () => _showMarkerDetail(
              id: id,
              displayName: beacon?.displayName ?? id,
              liveBeacon: beacon,
            ),
            child: Container(
              decoration: BoxDecoration(
                color: Colors.orange.shade600,
                shape: BoxShape.circle,
                border: Border.all(color: Colors.white, width: 2),
                boxShadow: const [
                  BoxShadow(color: Colors.black26, blurRadius: 4),
                ],
              ),
              child: const Icon(Icons.my_location, color: Colors.white, size: 20),
            ),
          ),
        ),
      );
    }

    return markers;
  }

  Widget _buildControlPanel() {
    return Container(
      decoration: BoxDecoration(
        color: Colors.white,
        boxShadow: [
          BoxShadow(
            color: Colors.black.withOpacity(0.12),
            blurRadius: 12,
            offset: const Offset(0, -4),
          ),
        ],
      ),
      child: Column(
        mainAxisSize: MainAxisSize.min,
        children: [
          // ── Scan button row ──
          Padding(
            padding: const EdgeInsets.fromLTRB(16, 16, 16, 8),
            child: Row(
              children: [
                Expanded(child: _buildScanButton()),
                const SizedBox(width: 12),
                _buildRefreshButton(),
              ],
            ),
          ),

          // ── Error banner ──
          if (_error != null)
            Padding(
              padding: const EdgeInsets.fromLTRB(16, 0, 16, 8),
              child: Container(
                width: double.infinity,
                padding: const EdgeInsets.all(10),
                decoration: BoxDecoration(
                  color: Colors.red.shade50,
                  borderRadius: BorderRadius.circular(8),
                  border: Border.all(color: Colors.red.shade200),
                ),
                child: Text(
                  _error!,
                  style: GoogleFonts.inter(color: Colors.red.shade700, fontSize: 13),
                ),
              ),
            ),

          // ── Nearby beacons list ──
          _buildNearbyList(),

          // ── Pareto summary bar ──
          _buildParetoSummary(),

          SizedBox(height: MediaQuery.of(context).padding.bottom + 8),
        ],
      ),
    );
  }

  Widget _buildParetoSummary() {
    final paretoCount =
        _discovered.where((b) => ParetoDecoder.decode(b).isPareto).length;
    if (paretoCount == 0) return const SizedBox.shrink();
    return Padding(
      padding: const EdgeInsets.fromLTRB(16, 0, 16, 4),
      child: Row(
        children: [
          Icon(Icons.sensors, size: 14, color: Colors.indigo.shade600),
          const SizedBox(width: 6),
          Text(
            '$paretoCount Pareto-compatible device${paretoCount != 1 ? 's' : ''} nearby',
            style: GoogleFonts.inter(
                fontSize: 12,
                color: Colors.indigo.shade700,
                fontWeight: FontWeight.w500),
          ),
        ],
      ),
    );
  }

  Widget _buildScanButton() {
    return ElevatedButton.icon(
      onPressed: _toggleScan,
      icon: Icon(
        _isScanning ? Icons.stop_circle_outlined : Icons.bluetooth_searching,
        size: 22,
      ),
      label: Text(
        _isScanning ? 'Stop Scan' : 'Start Scan',
        style: GoogleFonts.inter(fontWeight: FontWeight.w600, fontSize: 15),
      ),
      style: ElevatedButton.styleFrom(
        backgroundColor: _isScanning ? Colors.red.shade600 : AppTheme.brandPrimary,
        foregroundColor: Colors.white,
        elevation: 0,
        minimumSize: const Size(0, 52),
        padding: const EdgeInsets.symmetric(vertical: 14, horizontal: 16),
        shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(10)),
      ),
    );
  }

  Widget _buildRefreshButton() {
    return SizedBox(
      height: 48,
      width: 48,
      child: IconButton.filled(
        onPressed: _loadingLocations ? null : _loadSavedLocations,
        icon: _loadingLocations
            ? const SizedBox(
                width: 18,
                height: 18,
                child: CircularProgressIndicator(
                  strokeWidth: 2,
                  color: Colors.white,
                ),
              )
            : const Icon(Icons.refresh, size: 22),
        style: IconButton.styleFrom(
          backgroundColor: AppTheme.brandPrimaryHover,
          foregroundColor: Colors.white,
          shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(10)),
        ),
      ),
    );
  }

  Widget _buildNearbyList() {
    if (!_isScanning && _discovered.isEmpty) {
      return Padding(
        padding: const EdgeInsets.fromLTRB(16, 4, 16, 12),
        child: Row(
          children: [
            Icon(Icons.info_outline, size: 16, color: Colors.grey.shade500),
            const SizedBox(width: 6),
            Text(
              _savedLocations.isEmpty
                  ? 'Tap Start Scan to find nearby BLE tags'
                  : '${_savedLocations.length} tag${_savedLocations.length != 1 ? 's' : ''} on map  •  tap Start Scan to update',
              style: GoogleFonts.inter(color: Colors.grey.shade600, fontSize: 13),
            ),
          ],
        ),
      );
    }

    return ConstrainedBox(
      constraints: const BoxConstraints(maxHeight: 180),
      child: ListView.builder(
        shrinkWrap: true,
        padding: const EdgeInsets.only(bottom: 4),
        itemCount: _discovered.isEmpty ? 0 : _discovered.length,
        itemBuilder: (context, index) {
          final beacon = _discovered[index];
          return _BeaconListTile(
            beacon: beacon,
            isPlotting: _plotting.contains(beacon.id),
            isPlotted: _localPlotPositions.containsKey(beacon.id),
            onTap: () => _plotBeacon(beacon),
          );
        },
      ),
    );
  }

  Widget _buildWebUnavailable() {
    return Padding(
      padding: const EdgeInsets.only(top: 80),
      child: Center(
        child: Padding(
          padding: const EdgeInsets.all(32),
          child: Column(
            mainAxisSize: MainAxisSize.min,
            children: [
              Icon(Icons.bluetooth_disabled,
                  size: 64, color: Colors.grey.shade400),
              const SizedBox(height: 20),
              Text(
                'BLE Scanning requires the mobile app',
                style: GoogleFonts.inter(
                    fontSize: 18,
                    fontWeight: FontWeight.w600,
                    color: Colors.grey.shade700),
                textAlign: TextAlign.center,
              ),
              const SizedBox(height: 12),
              Text(
                'Download the Pinplot app on Android or iOS to scan for nearby BLE tags and report their locations.',
                style: GoogleFonts.inter(
                    fontSize: 14, color: Colors.grey.shade500),
                textAlign: TextAlign.center,
              ),
            ],
          ),
        ),
      ),
    );
  }

  String _formatTime(DateTime dt) {
    final diff = DateTime.now().difference(dt);
    if (diff.inMinutes < 1) return 'just now';
    if (diff.inHours < 1) return '${diff.inMinutes}m ago';
    if (diff.inDays < 1) return '${diff.inHours}h ago';
    return '${diff.inDays}d ago';
  }

  void _showMarkerDetail({
    required String id,
    required String displayName,
    DiscoveredBeacon? liveBeacon,
    BeaconLocation? savedLocation,
  }) {
    if (!mounted) return;
    final rssi = liveBeacon?.rssi ?? savedLocation?.rssi;
    final lastSeen =
        liveBeacon?.lastSeen ?? savedLocation?.lastSeen ?? DateTime.now();
    final paretoInfo =
        liveBeacon != null ? ParetoDecoder.decode(liveBeacon) : null;

    showModalBottomSheet(
      context: context,
      shape: const RoundedRectangleBorder(
        borderRadius: BorderRadius.vertical(top: Radius.circular(20)),
      ),
      backgroundColor: Colors.white,
      builder: (_) => _MarkerDetailSheet(
        displayName: displayName,
        id: id,
        isLive: liveBeacon != null,
        rssi: rssi,
        lastSeen: lastSeen,
        paretoInfo: paretoInfo,
      ),
    );
  }
}

// ── Beacon list tile ─────────────────────────────────────────────────────────

class _BeaconListTile extends StatelessWidget {
  const _BeaconListTile({
    required this.beacon,
    this.onTap,
    this.isPlotting = false,
    this.isPlotted = false,
  });
  final DiscoveredBeacon beacon;
  final VoidCallback? onTap;
  final bool isPlotting;
  final bool isPlotted;

  @override
  Widget build(BuildContext context) {
    final paretoInfo = ParetoDecoder.decode(beacon);
    final isPareto = paretoInfo.isPareto;

    final iconBg = isPareto ? Colors.indigo.shade50 : AppTheme.brandPrimaryLight;
    final iconColor = isPareto ? Colors.indigo.shade700 : AppTheme.brandPrimary;
    final iconData = isPareto ? Icons.sensors : Icons.bluetooth;

    return Container(
      margin: const EdgeInsets.symmetric(horizontal: 12, vertical: 3),
      padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 8),
      decoration: BoxDecoration(
        color: isPareto ? Colors.indigo.shade50.withOpacity(0.4) : Colors.grey.shade50,
        borderRadius: BorderRadius.circular(8),
        border: Border.all(
          color: isPareto ? Colors.indigo.shade100 : Colors.grey.shade200,
        ),
      ),
      child: Row(
        children: [
          Container(
            width: 36,
            height: 36,
            decoration: BoxDecoration(
              color: iconBg,
              shape: BoxShape.circle,
            ),
            child: Icon(iconData, color: iconColor, size: 20),
          ),
          const SizedBox(width: 10),
          Expanded(
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Text(
                  beacon.displayName,
                  style: GoogleFonts.inter(
                      fontWeight: FontWeight.w600, fontSize: 13),
                  maxLines: 1,
                  overflow: TextOverflow.ellipsis,
                ),
                Text(
                  beacon.id,
                  style: GoogleFonts.inter(
                      fontSize: 11, color: Colors.grey.shade600),
                  maxLines: 1,
                  overflow: TextOverflow.ellipsis,
                ),
                if (isPareto) ...
                  [
                    const SizedBox(height: 3),
                    Container(
                      padding: const EdgeInsets.symmetric(
                          horizontal: 6, vertical: 2),
                      decoration: BoxDecoration(
                        color: Colors.indigo.shade100,
                        borderRadius: BorderRadius.circular(4),
                      ),
                      child: Text(
                        paretoInfo.typeLabel,
                        style: GoogleFonts.inter(
                            fontSize: 10,
                            color: Colors.indigo.shade800,
                            fontWeight: FontWeight.w600),
                      ),
                    ),
                  ],
              ],
            ),
          ),
          _SignalBars(bars: beacon.signalBars, rssi: beacon.rssi),
          const SizedBox(width: 6),
          _buildPlotButton(),
        ],
      ),
    );
  }

  Widget _buildPlotButton() {
    if (isPlotting) {
      return SizedBox(
        width: 32,
        height: 32,
        child: Center(
          child: SizedBox(
            width: 16,
            height: 16,
            child: CircularProgressIndicator(
              strokeWidth: 2,
              color: Colors.orange.shade400,
            ),
          ),
        ),
      );
    }
    return SizedBox(
      width: 32,
      height: 32,
      child: Material(
        color: isPlotted ? Colors.green.shade50 : Colors.orange.shade50,
        shape: const CircleBorder(),
        child: InkWell(
          onTap: onTap,
          customBorder: const CircleBorder(),
          child: Icon(
            isPlotted ? Icons.location_on : Icons.location_on_outlined,
            size: 18,
            color: isPlotted ? Colors.green.shade600 : Colors.orange.shade600,
          ),
        ),
      ),
    );
  }
}

// ── Signal bars widget ───────────────────────────────────────────────────────

class _SignalBars extends StatelessWidget {
  const _SignalBars({required this.bars, required this.rssi});
  final int bars;
  final int rssi;

  @override
  Widget build(BuildContext context) {
    return Column(
      mainAxisSize: MainAxisSize.min,
      crossAxisAlignment: CrossAxisAlignment.end,
      children: [
        Row(
          mainAxisSize: MainAxisSize.min,
          crossAxisAlignment: CrossAxisAlignment.end,
          children: List.generate(4, (i) {
            final active = i < bars;
            return Container(
              width: 4,
              height: 6.0 + i * 4,
              margin: const EdgeInsets.symmetric(horizontal: 1),
              decoration: BoxDecoration(
                color: active ? AppTheme.brandPrimary : Colors.grey.shade300,
                borderRadius: BorderRadius.circular(2),
              ),
            );
          }),
        ),
        const SizedBox(height: 2),
        Text(
          '${rssi} dBm',
          style:
              GoogleFonts.inter(fontSize: 10, color: Colors.grey.shade600),
        ),
      ],
    );
  }
}

// ── Marker detail bottom sheet ──────────────────────────────────────────────────────────

class _MarkerDetailSheet extends StatelessWidget {
  const _MarkerDetailSheet({
    required this.displayName,
    required this.id,
    required this.isLive,
    this.rssi,
    required this.lastSeen,
    this.paretoInfo,
  });

  final String displayName;
  final String id;
  final bool isLive;
  final int? rssi;
  final DateTime lastSeen;
  final ParetoInfo? paretoInfo;

  String _distanceText() {
    if (rssi == null) return '–';
    final tx = paretoInfo?.txPower ?? -59; // 1 m reference power
    final dist = pow(10.0, (tx - rssi!) / 20.0); // path loss n=2
    if (dist < 1) return '< 1 m';
    if (dist < 1000) return '~${dist.toStringAsFixed(1)} m';
    return '~${(dist / 1000).toStringAsFixed(2)} km';
  }

  String _batteryText() {
    final mv = paretoInfo?.batteryMv;
    if (mv == null) return '–';
    final pct = ((mv - 2800) / (3600 - 2800) * 100).clamp(0.0, 100.0).round();
    return '$mv mV  ($pct%)';
  }

  Color _batteryColor() {
    final mv = paretoInfo?.batteryMv;
    if (mv == null) return Colors.grey;
    final pct = (mv - 2800) / (3600 - 2800) * 100;
    if (pct > 50) return Colors.green.shade600;
    if (pct > 20) return Colors.orange.shade600;
    return Colors.red.shade600;
  }

  String _ageText() {
    final diff = DateTime.now().difference(lastSeen);
    if (diff.inSeconds < 10) return 'just now';
    if (diff.inMinutes < 1) return '${diff.inSeconds}s ago';
    if (diff.inHours < 1) return '${diff.inMinutes}m ago';
    if (diff.inDays < 1) return '${diff.inHours}h ago';
    return '${diff.inDays}d ago';
  }

  @override
  Widget build(BuildContext context) {
    final info = paretoInfo;
    final isIBeacon = info?.type == ParetoDeviceType.iBeacon;

    return Padding(
      padding: EdgeInsets.fromLTRB(
          20, 12, 20, MediaQuery.of(context).padding.bottom + 20),
      child: Column(
        mainAxisSize: MainAxisSize.min,
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          // Handle bar
          Center(
            child: Container(
              width: 40,
              height: 4,
              decoration: BoxDecoration(
                color: Colors.grey.shade300,
                borderRadius: BorderRadius.circular(2),
              ),
            ),
          ),
          const SizedBox(height: 14),
          // Name + live/age badge
          Row(
            crossAxisAlignment: CrossAxisAlignment.center,
            children: [
              Expanded(
                child: Text(
                  displayName,
                  style: GoogleFonts.inter(
                      fontSize: 17, fontWeight: FontWeight.w700),
                ),
              ),
              const SizedBox(width: 8),
              if (isLive)
                Container(
                  padding:
                      const EdgeInsets.symmetric(horizontal: 8, vertical: 4),
                  decoration: BoxDecoration(
                    color: Colors.green.shade500,
                    borderRadius: BorderRadius.circular(6),
                  ),
                  child: Row(
                    mainAxisSize: MainAxisSize.min,
                    children: [
                      Container(
                        width: 6,
                        height: 6,
                        decoration: const BoxDecoration(
                            color: Colors.white, shape: BoxShape.circle),
                      ),
                      const SizedBox(width: 4),
                      Text('LIVE',
                          style: GoogleFonts.inter(
                              color: Colors.white,
                              fontSize: 11,
                              fontWeight: FontWeight.w700)),
                    ],
                  ),
                )
              else
                Container(
                  padding:
                      const EdgeInsets.symmetric(horizontal: 8, vertical: 4),
                  decoration: BoxDecoration(
                    color: Colors.grey.shade200,
                    borderRadius: BorderRadius.circular(6),
                  ),
                  child: Text(
                    _ageText(),
                    style: GoogleFonts.inter(
                        color: Colors.grey.shade700,
                        fontSize: 11,
                        fontWeight: FontWeight.w600),
                  ),
                ),
            ],
          ),
          const SizedBox(height: 4),
          Text(
            id,
            style:
                GoogleFonts.inter(fontSize: 11, color: Colors.grey.shade500),
          ),
          const Divider(height: 24),
          // Signal + distance estimate
          _InfoRow(
            icon: Icons.signal_cellular_alt,
            iconColor: Colors.blue.shade600,
            label: 'Signal',
            value: rssi != null ? '$rssi dBm  ≈ ${_distanceText()}' : '–',
          ),
          // Battery (Eddystone TLM only)
          if (info?.batteryMv != null) ...[  
            const SizedBox(height: 10),
            _InfoRow(
              icon: Icons.battery_full,
              iconColor: _batteryColor(),
              label: 'Battery',
              value: _batteryText(),
            ),
          ],
          // Major / Minor (iBeacon only)
          if (isIBeacon && info != null && info.major != null) ...[  
            const SizedBox(height: 10),
            _InfoRow(
              icon: Icons.tag,
              iconColor: Colors.indigo.shade600,
              label: 'Major / Minor',
              value: '${info.major}  /  ${info.minor ?? '–'}',
            ),
          ],
          // Format label
          if (info?.isPareto == true) ...[  
            const SizedBox(height: 10),
            _InfoRow(
              icon: Icons.sensors,
              iconColor: Colors.indigo.shade400,
              label: 'Format',
              value: info!.typeLabel,
            ),
          ],
        ],
      ),
    );
  }
}

// ── Info row widget ─────────────────────────────────────────────────────────────────

class _InfoRow extends StatelessWidget {
  const _InfoRow({
    required this.icon,
    required this.iconColor,
    required this.label,
    required this.value,
  });

  final IconData icon;
  final Color iconColor;
  final String label;
  final String value;

  @override
  Widget build(BuildContext context) {
    return Row(
      children: [
        Icon(icon, size: 18, color: iconColor),
        const SizedBox(width: 8),
        Text(
          '$label:  ',
          style: GoogleFonts.inter(fontSize: 13, color: Colors.grey.shade600),
        ),
        Expanded(
          child: Text(
            value,
            style: GoogleFonts.inter(
                fontSize: 13, fontWeight: FontWeight.w600),
            overflow: TextOverflow.ellipsis,
          ),
        ),
      ],
    );
  }
}
