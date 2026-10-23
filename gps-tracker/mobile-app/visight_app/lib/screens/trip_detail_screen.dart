import 'dart:async';

import 'package:flutter/material.dart';
import 'package:flutter_map/flutter_map.dart';

import '../api/models.dart';
import '../format.dart';
import '../session.dart';
import '../theme.dart';
import '../widgets/common.dart';

/// A trip's route on the map with a replay, its totals and its events.
class TripDetailScreen extends StatelessWidget {
  const TripDetailScreen({super.key, required this.trip, this.autoplay = false});
  final Trip trip;
  final bool autoplay;

  @override
  Widget build(BuildContext context) {
    final session = SessionScope.read(context);
    final name = session.vehicle(trip.imei)?.name ?? trip.deviceName ?? trip.imei;
    return Scaffold(
      appBar: AppBar(title: Text(name), backgroundColor: Colors.white, surfaceTintColor: Colors.transparent),
      body: AsyncView<TripDetail>(
        load: () async => TripDetail.fromJson(await session.api.get('/api/v2/trips/${trip.id}')),
        builder: (context, detail, _) => _TripView(detail: detail, autoplay: autoplay),
      ),
    );
  }
}

class _TripView extends StatefulWidget {
  const _TripView({required this.detail, required this.autoplay});
  final TripDetail detail;
  final bool autoplay;

  @override
  State<_TripView> createState() => _TripViewState();
}

class _TripViewState extends State<_TripView> {
  int _index = 0;
  Timer? _timer;

  List<RoutePoint> get _points => widget.detail.points;

  @override
  void initState() {
    super.initState();
    if (widget.autoplay && _points.length > 1) _play();
  }

  @override
  void dispose() {
    _timer?.cancel();
    super.dispose();
  }

  /// Replays the route in about 20 seconds, whatever its length.
  void _play() {
    if (_index >= _points.length - 1) _index = 0;
    final step = (_points.length / 200).ceil();
    _timer = Timer.periodic(const Duration(milliseconds: 100), (t) {
      setState(() => _index = (_index + step).clamp(0, _points.length - 1));
      if (_index >= _points.length - 1) _stop();
    });
    setState(() {});
  }

  void _stop() {
    _timer?.cancel();
    _timer = null;
    setState(() {});
  }

  @override
  Widget build(BuildContext context) {
    final d = widget.detail;
    final route = [for (final p in _points) p.position];
    final current = _points.isEmpty ? null : _points[_index];
    return Column(children: [
      SizedBox(
        height: MediaQuery.sizeOf(context).height * 0.45,
        child: route.isEmpty
            ? const MessageView(icon: Icons.route, title: 'No route', message: 'This trip has no recorded positions.')
            : FlutterMap(
                options: MapOptions(
                  initialCameraFit: route.length > 1
                      ? CameraFit.coordinates(coordinates: route, padding: const EdgeInsets.all(40))
                      : null,
                  initialCenter: route.first,
                  initialZoom: 15,
                ),
                children: [
                  ...baseMapLayers(),
                  PolylineLayer(polylines: [
                    Polyline(points: route, strokeWidth: 5, color: AppColors.blue),
                    if (_index > 0)
                      Polyline(points: route.sublist(0, _index + 1), strokeWidth: 5, color: AppColors.navy),
                  ]),
                  MarkerLayer(markers: [
                    for (final e in d.events)
                      if (e.position != null && e.kind != 'info')
                        Marker(
                          point: e.position!,
                          width: 22,
                          height: 22,
                          child: Tooltip(
                            message: e.label,
                            child: const Icon(Icons.warning_rounded, color: AppColors.alert, size: 22),
                          ),
                        ),
                    Marker(point: route.first, child: const Icon(Icons.trip_origin, color: Color(0xFF2E9E44))),
                    Marker(point: route.last, child: const Icon(Icons.flag, color: Colors.red)),
                    if (current != null)
                      Marker(
                        point: current.position,
                        width: 34,
                        height: 34,
                        child: Container(
                          decoration: const BoxDecoration(color: AppColors.navy, shape: BoxShape.circle),
                          child: const Icon(Icons.directions_car_filled, color: Colors.white, size: 20),
                        ),
                      ),
                  ]),
                ],
              ),
      ),
      if (_points.length > 1)
        Padding(
          padding: const EdgeInsets.symmetric(horizontal: 8),
          child: Row(children: [
            IconButton(
              icon: Icon(_timer == null ? Icons.play_arrow : Icons.pause),
              onPressed: _timer == null ? _play : _stop,
            ),
            Expanded(
              child: Slider(
                value: _index.toDouble(),
                max: (_points.length - 1).toDouble(),
                onChanged: (v) => setState(() => _index = v.round()),
              ),
            ),
            SizedBox(
              width: 92,
              child: Text(
                '${current?.at == null ? '' : fmtTime(current!.at!)}  ${current?.speed ?? 0} km/h',
                style: const TextStyle(fontSize: 12),
              ),
            ),
          ]),
        ),
      Expanded(
        child: ListView(padding: const EdgeInsets.all(16), children: [
          _Row(Icons.trip_origin, d.startAddress ?? 'Unknown start', fmtDateTime(d.startedAt)),
          _Row(Icons.flag, d.isOpen ? 'Trip in progress' : (d.endAddress ?? 'Unknown end'),
              d.endedAt == null ? '' : fmtDateTime(d.endedAt!)),
          const SizedBox(height: 12),
          Wrap(spacing: 10, runSpacing: 10, children: [
            _Pill('Distance', fmtDistance(d.distanceM)),
            _Pill('Duration', fmtDuration(d.durationS)),
            _Pill('Max speed', '${d.maxSpeed} km/h'),
            if (d.avgSpeed != null) _Pill('Avg speed', '${d.avgSpeed!.round()} km/h'),
            _Pill('Exceptions', '${d.exceptions}'),
            if (d.driver != null) _Pill('Driver', d.driver!),
          ]),
          if (d.events.isNotEmpty) ...[
            const SizedBox(height: 20),
            const Text('Events', style: TextStyle(fontSize: 16, fontWeight: FontWeight.w600)),
            for (final e in d.events)
              ListTile(
                contentPadding: EdgeInsets.zero,
                dense: true,
                leading: Icon(e.kind == 'info' ? Icons.info_outline : Icons.warning_rounded,
                    color: e.kind == 'info' ? AppColors.muted : AppColors.alert),
                title: Text(e.label),
                subtitle: Text([if (e.at != null) fmtTime(e.at!), if (e.speed != null) '${e.speed} km/h'].join(' · ')),
              ),
          ],
        ]),
      ),
    ]);
  }
}

class _Row extends StatelessWidget {
  const _Row(this.icon, this.title, this.subtitle);
  final IconData icon;
  final String title, subtitle;

  @override
  Widget build(BuildContext context) => ListTile(
        contentPadding: EdgeInsets.zero,
        leading: Icon(icon, color: AppColors.navy),
        title: Text(title),
        subtitle: subtitle.isEmpty ? null : Text(subtitle),
      );
}

class _Pill extends StatelessWidget {
  const _Pill(this.label, this.value);
  final String label, value;

  @override
  Widget build(BuildContext context) {
    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 14, vertical: 10),
      decoration: cardDecoration(),
      child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
        Text(label, style: const TextStyle(fontSize: 12, color: AppColors.muted)),
        Text(value, style: const TextStyle(fontSize: 16, fontWeight: FontWeight.w600)),
      ]),
    );
  }
}
