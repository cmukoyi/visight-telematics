import 'package:flutter/material.dart';
import 'package:flutter_map/flutter_map.dart';

import '../api/models.dart';
import '../format.dart';
import '../session.dart';
import '../theme.dart';
import '../widgets/actions.dart';
import '../widgets/common.dart';
import '../widgets/trip_card.dart';
import 'vehicle_screen.dart';

/// Vehicle chips, the selected vehicle on a map, and Shortcuts | Insights | Latest trips.
class HomeScreen extends StatefulWidget {
  const HomeScreen({super.key});

  @override
  State<HomeScreen> createState() => _HomeScreenState();
}

class _HomeScreenState extends State<HomeScreen> {
  int _section = 0;

  @override
  Widget build(BuildContext context) {
    final session = SessionScope.of(context);
    final v = session.selected;
    return Column(children: [
      const AppHeader(title: 'Home'),
      Expanded(
        child: RefreshIndicator(
          onRefresh: session.refreshVehicles,
          child: ListView(padding: const EdgeInsets.fromLTRB(16, 4, 16, 24), children: [
            if (v == null)
              Padding(
                padding: const EdgeInsets.only(top: 80),
                child: MessageView(
                  icon: Icons.directions_car_outlined,
                  title: 'No vehicles to show',
                  message: session.vehiclesError ??
                      "Your security group doesn't contain any vehicles yet. Ask your administrator.",
                ),
              )
            else ...[
              _VehicleChips(vehicles: session.vehicles, selected: v.imei, onSelect: session.select),
              const SizedBox(height: 12),
              _VehicleMap(key: ValueKey(v.imei), vehicle: v),
              const SizedBox(height: 16),
              SegmentTabs(
                labels: const ['Shortcuts', 'Insights', 'Latest trips'],
                index: _section,
                onChanged: (i) => setState(() => _section = i),
              ),
              const SizedBox(height: 16),
              switch (_section) {
                0 => _Shortcuts(vehicle: v),
                1 => _Insights(key: ValueKey('insights-${v.imei}'), vehicle: v),
                _ => _LatestTrips(key: ValueKey('trips-${v.imei}'), vehicle: v),
              },
            ],
          ]),
        ),
      ),
    ]);
  }
}

class _VehicleChips extends StatelessWidget {
  const _VehicleChips({required this.vehicles, required this.selected, required this.onSelect});
  final List<Vehicle> vehicles;
  final String selected;
  final ValueChanged<String> onSelect;

  @override
  Widget build(BuildContext context) {
    return SizedBox(
      height: 48,
      child: ListView.separated(
        scrollDirection: Axis.horizontal,
        itemCount: vehicles.length,
        separatorBuilder: (_, _) => const SizedBox(width: 10),
        itemBuilder: (context, i) {
          final v = vehicles[i];
          final on = v.imei == selected;
          return InkWell(
            borderRadius: BorderRadius.circular(24),
            onTap: () => onSelect(v.imei),
            child: Container(
              padding: const EdgeInsets.fromLTRB(6, 6, 16, 6),
              decoration: BoxDecoration(
                color: on ? const Color(0xFFDDE3EA) : AppColors.segment,
                borderRadius: BorderRadius.circular(24),
                border: Border.all(color: on ? AppColors.navy : Colors.transparent, width: 1.5),
              ),
              child: Row(children: [
                CircleAvatar(
                  radius: 17,
                  backgroundColor: statusColor(v.status),
                  child: const Icon(Icons.directions_car_filled, size: 18, color: AppColors.navy),
                ),
                const SizedBox(width: 10),
                Text(v.name.toUpperCase(), style: const TextStyle(fontSize: 17, color: AppColors.navy)),
              ]),
            ),
          );
        },
      ),
    );
  }
}

/// The selected vehicle on a small map; tap to open it in Map view.
class _VehicleMap extends StatefulWidget {
  const _VehicleMap({super.key, required this.vehicle});
  final Vehicle vehicle;

  @override
  State<_VehicleMap> createState() => _VehicleMapState();
}

class _VehicleMapState extends State<_VehicleMap> {
  final _map = MapController();

  void _zoom(double by) => _map.move(_map.camera.center, _map.camera.zoom + by);

  @override
  Widget build(BuildContext context) {
    final v = widget.vehicle;
    final pos = v.position;
    return ClipRRect(
      borderRadius: BorderRadius.circular(12),
      child: SizedBox(
        height: 320,
        child: pos == null
            ? Container(
                color: AppColors.segment,
                alignment: Alignment.center,
                child: Text('${v.name} has not reported a position yet', style: const TextStyle(color: AppColors.muted)),
              )
            : Stack(children: [
                FlutterMap(
                  mapController: _map,
                  options: MapOptions(
                    initialCenter: pos,
                    initialZoom: 16,
                    // Drags scroll the page; zoom with pinch or the buttons.
                    interactionOptions:
                        const InteractionOptions(flags: InteractiveFlag.pinchZoom | InteractiveFlag.doubleTapZoom),
                    onTap: (_, _) => SessionScope.read(context).showOnMap(v.imei),
                  ),
                  children: [
                    ...baseMapLayers(),
                    MarkerLayer(markers: [vehicleMarker(v, selected: true)]),
                  ],
                ),
                Positioned(
                  right: 10,
                  bottom: 10,
                  child: Column(children: [
                    MapButton(icon: Icons.add, onTap: () => _zoom(1)),
                    MapButton(icon: Icons.remove, onTap: () => _zoom(-1)),
                  ]),
                ),
              ]),
      ),
    );
  }
}

class _Shortcuts extends StatelessWidget {
  const _Shortcuts({required this.vehicle});
  final Vehicle vehicle;

  @override
  Widget build(BuildContext context) {
    final session = SessionScope.read(context);
    final tiles = [
      _Shortcut(Icons.route, 'Latest trip replay', AppColors.sky, () => replayLatestTrip(context, vehicle)),
      _Shortcut(Icons.share, 'Share location', AppColors.pink, () => shareLocation(context, vehicle)),
      _Shortcut(Icons.my_location, 'Live track', AppColors.lavender, () => session.followLive(vehicle.imei)),
      _Shortcut(Icons.info_outline, 'Vehicle details', AppColors.mint,
          () => Navigator.of(context).push(MaterialPageRoute(builder: (_) => VehicleScreen(imei: vehicle.imei)))),
      _Shortcut(Icons.history, 'All trips', AppColors.sky, () => session.showTrips(vehicle.imei)),
      _Shortcut(Icons.map_outlined, 'Show on map', AppColors.pink, () => session.showOnMap(vehicle.imei)),
    ];
    return GridView.count(
      crossAxisCount: 2,
      shrinkWrap: true,
      physics: const NeverScrollableScrollPhysics(),
      mainAxisSpacing: 14,
      crossAxisSpacing: 14,
      childAspectRatio: 2.4,
      children: tiles,
    );
  }
}

class _Shortcut extends StatelessWidget {
  const _Shortcut(this.icon, this.label, this.colors, this.onTap);
  final IconData icon;
  final String label;
  final (Color, Color) colors;
  final VoidCallback onTap;

  @override
  Widget build(BuildContext context) {
    final (bg, accent) = colors;
    return Material(
      color: bg,
      elevation: 2,
      shadowColor: Colors.black26,
      borderRadius: BorderRadius.circular(8),
      clipBehavior: Clip.antiAlias,
      child: InkWell(
        onTap: onTap,
        child: Row(children: [
          const SizedBox(width: 10),
          CircleAvatar(radius: 20, backgroundColor: Colors.white, child: Icon(icon, color: accent)),
          const SizedBox(width: 10),
          Expanded(child: Text(label, style: TextStyle(color: accent, fontSize: 16, fontWeight: FontWeight.w500))),
          Container(
            width: 22,
            color: accent.withValues(alpha: 0.25),
            alignment: Alignment.center,
            child: const Icon(Icons.chevron_right, size: 18, color: AppColors.navy),
          ),
        ]),
      ),
    );
  }
}

/// Today's driving and the latest readings, from the vehicle's status.
class _Insights extends StatelessWidget {
  const _Insights({super.key, required this.vehicle});
  final Vehicle vehicle;

  @override
  Widget build(BuildContext context) {
    final api = SessionScope.read(context).api;
    return AsyncView<VehicleStatus>(
      load: () async => VehicleStatus.fromJson(await api.get('/api/v2/vehicles/${vehicle.imei}/status')),
      builder: (context, s, _) => Column(crossAxisAlignment: CrossAxisAlignment.stretch, children: [
        Row(children: [
          _Stat('Trips today', '${s.tripsToday}'),
          const SizedBox(width: 10),
          _Stat('Distance today', '${s.distanceTodayKm.toStringAsFixed(1)} km'),
          const SizedBox(width: 10),
          _Stat('Driving today', fmtDuration(s.drivingTodayS)),
        ]),
        const SizedBox(height: 12),
        Container(
          decoration: cardDecoration(),
          child: Column(children: [
            ListTile(
                leading: const Icon(Icons.place_outlined),
                title: const Text('Last location'),
                subtitle: Text(s.address ?? 'Unknown')),
            ListTile(
                leading: const Icon(Icons.schedule),
                title: const Text('Last report'),
                subtitle: Text('${fmtAgo(s.lastReport)}${s.lastEvent != null ? ' · ${s.lastEvent}' : ''}')),
            if (s.speed != null)
              ListTile(leading: const Icon(Icons.speed), title: const Text('Speed'), subtitle: Text('${s.speed} km/h')),
          ]),
        ),
      ]),
    );
  }
}

class _Stat extends StatelessWidget {
  const _Stat(this.label, this.value);
  final String label, value;

  @override
  Widget build(BuildContext context) {
    return Expanded(
      child: Container(
        padding: const EdgeInsets.symmetric(vertical: 14, horizontal: 8),
        decoration: cardDecoration(),
        child: Column(children: [
          Text(value, style: const TextStyle(fontSize: 20, fontWeight: FontWeight.w700, color: AppColors.navy)),
          const SizedBox(height: 4),
          Text(label, style: const TextStyle(fontSize: 12, color: AppColors.muted), textAlign: TextAlign.center),
        ]),
      ),
    );
  }
}

class _LatestTrips extends StatelessWidget {
  const _LatestTrips({super.key, required this.vehicle});
  final Vehicle vehicle;

  @override
  Widget build(BuildContext context) {
    final session = SessionScope.read(context);
    return AsyncView<List<Trip>>(
      load: () async => [
        for (final r in await session.api.get('/api/v2/trips', {'imei': vehicle.imei, 'limit': '5'}) as List)
          Trip.fromJson(r)
      ],
      builder: (context, trips, _) => trips.isEmpty
          ? const Padding(
              padding: EdgeInsets.all(24),
              child: Text('No trips yet', textAlign: TextAlign.center, style: TextStyle(color: AppColors.muted)))
          : Column(crossAxisAlignment: CrossAxisAlignment.stretch, children: [
              for (final t in trips) TripCard(trip: t),
              TextButton(onPressed: () => session.showTrips(vehicle.imei), child: const Text('See all trips')),
            ]),
    );
  }
}
