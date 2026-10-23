import 'dart:async';

import 'package:flutter/material.dart';
import 'package:flutter_map/flutter_map.dart';
import 'package:latlong2/latlong.dart';

import '../api/api_client.dart';
import '../api/models.dart';
import '../format.dart';
import '../session.dart';
import '../theme.dart';
import '../widgets/common.dart';
import 'vehicle_screen.dart';

/// Every vehicle on the map, a swipeable card per vehicle, places and live follow.
class MapScreen extends StatefulWidget {
  const MapScreen({super.key});

  @override
  State<MapScreen> createState() => _MapScreenState();
}

class _MapScreenState extends State<MapScreen> {
  final _map = MapController();
  final _pages = PageController(viewportFraction: 0.86);
  bool _ready = false, _fitted = false, _swiping = false;
  String? _shownImei;

  List<Place>? _places;
  bool _showPlaces = false;

  String? _followImei;
  LiveTrack? _live;
  Timer? _liveTimer;
  late Session _session;

  @override
  void didChangeDependencies() {
    super.didChangeDependencies();
    _session = SessionScope.of(context);
    _session.follow.removeListener(_onFollowRequest);
    _session.follow.addListener(_onFollowRequest);
    final imei = _session.selected?.imei;
    if (imei != _shownImei) {
      _shownImei = imei;
      WidgetsBinding.instance.addPostFrameCallback((_) => _focusSelected());
    }
  }

  @override
  void dispose() {
    _session.follow.removeListener(_onFollowRequest);
    _liveTimer?.cancel();
    _pages.dispose();
    super.dispose();
  }

  /// Centre on the selected vehicle and bring its card into view.
  void _focusSelected({bool animatePage = true}) {
    final v = _session.selected;
    if (v == null || !mounted) return;
    if (_followImei != null && _followImei != v.imei) _stopFollow();
    if (_ready && v.position != null) {
      _map.move(v.position!, _map.camera.zoom < 13 ? 15 : _map.camera.zoom);
    }
    final page = _session.vehicles.indexWhere((x) => x.imei == v.imei);
    if (animatePage && page >= 0 && _pages.hasClients && _pages.page?.round() != page) {
      _swiping = true;
      _pages.animateToPage(page, duration: const Duration(milliseconds: 250), curve: Curves.easeOut)
          .whenComplete(() => _swiping = false);
    }
  }

  void _fitAll() {
    final pts = [for (final v in _session.vehicles) ?v.position];
    if (!_ready || pts.isEmpty) return;
    if (pts.length == 1) {
      _map.move(pts.first, 15);
    } else {
      _map.fitCamera(CameraFit.coordinates(coordinates: pts, padding: const EdgeInsets.fromLTRB(60, 140, 80, 280)));
    }
  }

  void _zoom(double by) => _map.move(_map.camera.center, _map.camera.zoom + by);

  Future<void> _togglePlaces() async {
    if (_places == null) {
      try {
        final rows = await _session.api.get('/api/v2/places') as List;
        _places = [for (final r in rows) Place.fromJson(r)];
      } on ApiException catch (e) {
        if (mounted) showError(context, e);
        return;
      }
    }
    setState(() => _showPlaces = !_showPlaces);
  }

  void _onFollowRequest() {
    final imei = _session.follow.value;
    if (imei == null) return;
    _session.follow.value = null;
    _startFollow(imei);
  }

  void _toggleFollow() {
    final v = _session.selected;
    if (_followImei != null) {
      _stopFollow();
    } else if (v != null) {
      _startFollow(v.imei);
    }
  }

  Future<void> _startFollow(String imei) async {
    _liveTimer?.cancel();
    setState(() {
      _followImei = imei;
      _live = null;
    });
    await _pollLive();
    if (_followImei == imei) _liveTimer = Timer.periodic(const Duration(seconds: 10), (_) => _pollLive());
  }

  void _stopFollow() {
    _liveTimer?.cancel();
    setState(() {
      _followImei = null;
      _live = null;
    });
  }

  Future<void> _pollLive() async {
    final imei = _followImei;
    if (imei == null) return;
    try {
      final live = LiveTrack.fromJson(await _session.api.get('/api/v2/vehicles/$imei/live'));
      if (!mounted || _followImei != imei) return;
      setState(() => _live = live);
      if (_ready && live.position != null) _map.move(live.position!, _map.camera.zoom < 14 ? 16 : _map.camera.zoom);
    } on ApiException catch (e) {
      if (!mounted) return;
      _stopFollow();
      showError(context, e);
    }
  }

  void _search() {
    showModalBottomSheet(
      context: context,
      isScrollControlled: true,
      showDragHandle: true,
      builder: (_) => _VehicleSearch(vehicles: _session.vehicles, onPick: _session.select),
    );
  }

  @override
  Widget build(BuildContext context) {
    final session = SessionScope.of(context);
    final vehicles = session.vehicles;
    final selected = session.selected;
    final live = _live;
    final liveVehicle = _followImei == null ? null : session.vehicle(_followImei!);

    return Stack(children: [
      FlutterMap(
        mapController: _map,
        options: MapOptions(
          initialCenter: const LatLng(-26.1, 28.0),
          initialZoom: 10,
          onMapReady: () {
            _ready = true;
            if (!_fitted) {
              _fitted = true;
              _fitAll();
            }
          },
        ),
        children: [
          ...baseMapLayers(),
          if (_showPlaces && _places != null) ...[
            CircleLayer(circles: [
              for (final p in _places!)
                if (p.isCircle && p.radius != null)
                  CircleMarker(
                    point: p.centre,
                    radius: p.radius!,
                    useRadiusInMeter: true,
                    color: AppColors.blue.withValues(alpha: 0.2),
                    borderColor: const Color(0xFF2E9E44),
                    borderStrokeWidth: 2,
                  ),
            ]),
            PolygonLayer(polygons: [
              for (final p in _places!)
                if (!p.isCircle && p.corners.length > 2)
                  Polygon(
                    points: p.corners,
                    color: AppColors.blue.withValues(alpha: 0.2),
                    borderColor: const Color(0xFF2E9E44),
                    borderStrokeWidth: 2,
                  ),
            ]),
          ],
          if (live != null && live.trail.length > 1)
            PolylineLayer(polylines: [Polyline(points: live.trail, strokeWidth: 4, color: AppColors.blue)]),
          MarkerLayer(markers: [
            for (final v in vehicles)
              if (v.position != null && v.imei != _followImei)
                vehicleMarker(v, selected: v.imei == selected?.imei, onTap: () => session.select(v.imei)),
            if (liveVehicle != null && (live?.position ?? liveVehicle.position) != null)
              Marker(
                point: live?.position ?? liveVehicle.position!,
                width: VehicleMarker.size,
                height: VehicleMarker.size,
                alignment: Alignment.topCenter,
                child: VehicleMarker(vehicle: liveVehicle, selected: true),
              ),
          ]),
        ],
      ),
      const Positioned(top: 0, left: 0, right: 0, child: AppHeader(title: 'Map view', translucent: true)),
      Positioned(
        right: 16,
        top: MediaQuery.paddingOf(context).top + 90,
        child: Column(children: [
          MapButton(icon: Icons.fullscreen, tooltip: 'Show all vehicles', onTap: _fitAll),
          MapButton(icon: Icons.add, onTap: () => _zoom(1)),
          MapButton(icon: Icons.remove, onTap: () => _zoom(-1)),
          MapButton(icon: _showPlaces ? Icons.layers : Icons.layers_outlined, tooltip: 'Places', onTap: _togglePlaces),
          MapButton(icon: Icons.gps_fixed, tooltip: 'Centre on vehicle', onTap: () => _focusSelected(animatePage: false)),
          MapButton(
            icon: _followImei != null ? Icons.stop_circle_outlined : Icons.play_circle_outline,
            tooltip: _followImei != null ? 'Stop following' : 'Follow live',
            dark: true,
            onTap: _toggleFollow,
          ),
        ]),
      ),
      if (_followImei != null)
        Positioned(
          left: 16,
          top: MediaQuery.paddingOf(context).top + 90,
          child: Chip(
            avatar: const Icon(Icons.circle, size: 12, color: Colors.red),
            label: Text(live == null
                ? 'Connecting…'
                : 'Live · ${live.speed} km/h${live.recordedAt != null ? ' · ${fmtTime(live.recordedAt!)}' : ''}'),
          ),
        ),
      if (vehicles.isNotEmpty)
        Positioned(
          left: 0,
          right: 0,
          bottom: 12,
          child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
            Padding(
              padding: const EdgeInsets.only(left: 16),
              child: MapButton(icon: Icons.search, tooltip: 'Find a vehicle', onTap: _search),
            ),
            SizedBox(
              height: 200,
              child: PageView.builder(
                controller: _pages,
                itemCount: vehicles.length,
                onPageChanged: (i) {
                  if (_swiping) return;
                  session.select(vehicles[i].imei);
                },
                itemBuilder: (_, i) => _VehicleCard(vehicle: vehicles[i], status: session.fleet[vehicles[i].imei]),
              ),
            ),
          ]),
        ),
    ]);
  }
}

class _VehicleCard extends StatelessWidget {
  const _VehicleCard({required this.vehicle, required this.status});
  final Vehicle vehicle;
  final FleetStatus? status;

  @override
  Widget build(BuildContext context) {
    final v = vehicle;
    final moving = v.isMoving && (status?.speed ?? 0) > 0;
    return Padding(
      padding: const EdgeInsets.symmetric(horizontal: 6),
      child: Container(
        padding: const EdgeInsets.all(12),
        decoration: BoxDecoration(
          color: AppColors.surface,
          borderRadius: BorderRadius.circular(14),
          boxShadow: const [BoxShadow(color: Color(0x33000000), blurRadius: 10, offset: Offset(0, 3))],
        ),
        child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
          Row(children: [
            VehicleAvatar(status: v.status, size: 48),
            const SizedBox(width: 12),
            Expanded(
              child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
                Text(v.name, maxLines: 1, overflow: TextOverflow.ellipsis,
                    style: const TextStyle(fontSize: 20, fontWeight: FontWeight.w600)),
                if (v.registration != null) Text(v.registration!, style: const TextStyle(fontSize: 15)),
              ]),
            ),
          ]),
          const SizedBox(height: 8),
          Expanded(
            child: Container(
              width: double.infinity,
              padding: const EdgeInsets.all(10),
              decoration: BoxDecoration(color: Colors.white, borderRadius: BorderRadius.circular(10)),
              child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
                const Text('Estimated last location', style: TextStyle(fontWeight: FontWeight.w500)),
                const SizedBox(height: 2),
                Text(status?.address ?? 'Address not available',
                    maxLines: 1, overflow: TextOverflow.ellipsis, style: const TextStyle(color: AppColors.muted)),
                const Spacer(),
                Row(children: [
                  Icon(moving ? Icons.navigation : Icons.local_parking, size: 18, color: AppColors.navy),
                  const SizedBox(width: 6),
                  Expanded(
                    child: Text(
                      moving ? 'Moving · ${status!.speed} km/h' : 'Parked · ${fmtAgo(status?.recordedAt ?? v.lastSeen)}',
                      style: const TextStyle(color: AppColors.muted),
                    ),
                  ),
                  GestureDetector(
                    onTap: () =>
                        Navigator.of(context).push(MaterialPageRoute(builder: (_) => VehicleScreen(imei: v.imei))),
                    child: const Text('Manage asset',
                        style: TextStyle(decoration: TextDecoration.underline, color: AppColors.navy, fontSize: 15)),
                  ),
                ]),
              ]),
            ),
          ),
        ]),
      ),
    );
  }
}

class _VehicleSearch extends StatefulWidget {
  const _VehicleSearch({required this.vehicles, required this.onPick});
  final List<Vehicle> vehicles;
  final ValueChanged<String> onPick;

  @override
  State<_VehicleSearch> createState() => _VehicleSearchState();
}

class _VehicleSearchState extends State<_VehicleSearch> {
  String _q = '';

  @override
  Widget build(BuildContext context) {
    final q = _q.toLowerCase();
    final hits = widget.vehicles
        .where((v) => '${v.name} ${v.registration ?? ''} ${v.driver ?? ''} ${v.imei}'.toLowerCase().contains(q))
        .toList();
    return Padding(
      padding: EdgeInsets.only(bottom: MediaQuery.viewInsetsOf(context).bottom),
      child: SizedBox(
        height: MediaQuery.sizeOf(context).height * 0.6,
        child: Column(children: [
          Padding(
            padding: const EdgeInsets.symmetric(horizontal: 16),
            child: TextField(
              autofocus: true,
              decoration: const InputDecoration(hintText: 'Name, registration or driver', prefixIcon: Icon(Icons.search)),
              onChanged: (s) => setState(() => _q = s),
            ),
          ),
          Expanded(
            child: ListView(children: [
              for (final v in hits)
                ListTile(
                  leading: VehicleAvatar(status: v.status, size: 40),
                  title: Text(v.name),
                  subtitle: v.registration == null ? null : Text(v.registration!),
                  onTap: () {
                    Navigator.pop(context);
                    widget.onPick(v.imei);
                  },
                ),
            ]),
          ),
        ]),
      ),
    );
  }
}
