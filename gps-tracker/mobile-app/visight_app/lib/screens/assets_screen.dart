import 'package:flutter/material.dart';
import 'package:share_plus/share_plus.dart';

import '../api/models.dart';
import '../format.dart';
import '../session.dart';
import '../theme.dart';
import '../widgets/common.dart';
import 'vehicle_screen.dart';

/// The vehicles in the user's security group (every vehicle for administrators).
class AssetsScreen extends StatefulWidget {
  const AssetsScreen({super.key});

  @override
  State<AssetsScreen> createState() => _AssetsScreenState();
}

class _AssetsScreenState extends State<AssetsScreen> {
  bool _searching = false;
  String _q = '';

  /// One message with every vehicle's last location.
  Future<void> _shareAll(Session session, List<Vehicle> vehicles) async {
    final lines = [
      for (final v in vehicles)
        if (v.position != null)
          '${v.name}: ${session.fleet[v.imei]?.address ?? ''} ${mapsLink(v.position!.latitude, v.position!.longitude)}'
    ];
    if (lines.isEmpty) return;
    await SharePlus.instance.share(ShareParams(text: lines.join('\n'), subject: 'Vehicle locations'));
  }

  @override
  Widget build(BuildContext context) {
    final session = SessionScope.of(context);
    final q = _q.toLowerCase();
    final vehicles = session.vehicles
        .where((v) => q.isEmpty ||
            '${v.name} ${v.registration ?? ''} ${v.driver ?? ''} ${v.vehicleGroup ?? ''}'.toLowerCase().contains(q))
        .toList();
    return Column(children: [
      const AppHeader(title: 'Assets'),
      Container(
        color: const Color(0xFFE6E9ED),
        padding: const EdgeInsets.symmetric(horizontal: 16, vertical: 8),
        child: Row(children: [
          const Text('Actions', style: TextStyle(fontSize: 18, color: AppColors.muted)),
          const Spacer(),
          OutlinedButton(
            onPressed: () => _shareAll(session, vehicles),
            style: OutlinedButton.styleFrom(backgroundColor: Colors.white, side: const BorderSide(color: AppColors.border)),
            child: const Icon(Icons.share, size: 20),
          ),
        ]),
      ),
      Padding(
        padding: const EdgeInsets.fromLTRB(16, 12, 16, 4),
        child: _searching
            ? TextField(
                autofocus: true,
                decoration: InputDecoration(
                  hintText: 'Name, registration, driver or group',
                  prefixIcon: const Icon(Icons.search),
                  suffixIcon: IconButton(
                    icon: const Icon(Icons.close),
                    onPressed: () => setState(() {
                      _searching = false;
                      _q = '';
                    }),
                  ),
                ),
                onChanged: (s) => setState(() => _q = s),
              )
            : Align(
                alignment: Alignment.centerLeft,
                child: MapButton(icon: Icons.search, onTap: () => setState(() => _searching = true)),
              ),
      ),
      Expanded(
        child: RefreshIndicator(
          onRefresh: session.refreshVehicles,
          child: vehicles.isEmpty
              ? ListView(children: [
                  const SizedBox(height: 60),
                  MessageView(
                    icon: Icons.directions_car_outlined,
                    title: 'No vehicles',
                    message: _q.isNotEmpty
                        ? 'Nothing matches "$_q".'
                        : session.vehiclesError ?? "Your security group doesn't contain any vehicles yet.",
                  ),
                ])
              : ListView.builder(
                  padding: const EdgeInsets.fromLTRB(16, 8, 16, 16),
                  itemCount: vehicles.length,
                  itemBuilder: (_, i) => _AssetCard(vehicle: vehicles[i]),
                ),
        ),
      ),
    ]);
  }
}

class _AssetCard extends StatelessWidget {
  const _AssetCard({required this.vehicle});
  final Vehicle vehicle;

  @override
  Widget build(BuildContext context) {
    final v = vehicle;
    final session = SessionScope.read(context);
    return Padding(
      padding: const EdgeInsets.only(bottom: 16),
      child: Material(
        color: Colors.transparent,
        child: InkWell(
          borderRadius: BorderRadius.circular(10),
          onTap: () => Navigator.of(context).push(MaterialPageRoute(builder: (_) => VehicleScreen(imei: v.imei))),
          child: Ink(
            decoration: cardDecoration(),
            padding: const EdgeInsets.fromLTRB(16, 10, 8, 10),
            child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
              Row(crossAxisAlignment: CrossAxisAlignment.start, children: [
                VehicleAvatar(status: v.status),
                const SizedBox(width: 20),
                Expanded(
                  child: Padding(
                    padding: const EdgeInsets.only(top: 8),
                    child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
                      Text(v.name.toUpperCase(),
                          style: const TextStyle(fontSize: 20, fontWeight: FontWeight.w500, color: Color(0xFF3A3A3A))),
                      if (v.registration != null) Text(v.registration!, style: const TextStyle(fontSize: 15)),
                    ]),
                  ),
                ),
                IconButton(
                  tooltip: 'Show on map',
                  icon: const Icon(Icons.location_on, color: AppColors.navy, size: 28),
                  onPressed: v.position == null ? null : () => session.showOnMap(v.imei),
                ),
              ]),
              const SizedBox(height: 6),
              Text(
                [v.vehicleGroup ?? v.deviceModel, 'Last seen ${fmtAgo(v.lastSeen)}'].whereType<String>().join(' · '),
                style: const TextStyle(fontSize: 14, color: AppColors.navy),
              ),
            ]),
          ),
        ),
      ),
    );
  }
}
