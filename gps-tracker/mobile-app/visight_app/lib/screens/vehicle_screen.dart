import 'package:flutter/material.dart';

import '../api/models.dart';
import '../format.dart';
import '../session.dart';
import '../theme.dart';
import '../widgets/actions.dart';
import '../widgets/common.dart';

/// A vehicle's details, where it is, today's driving and its latest readings.
/// Read-only: vehicles are edited in the customer dashboard.
class VehicleScreen extends StatelessWidget {
  const VehicleScreen({super.key, required this.imei});
  final String imei;

  @override
  Widget build(BuildContext context) {
    final session = SessionScope.of(context);
    final v = session.vehicle(imei);
    if (v == null) {
      return Scaffold(
        appBar: AppBar(),
        body: const MessageView(icon: Icons.directions_car_outlined, title: 'Vehicle not found',
            message: "It's no longer in your security group."),
      );
    }
    void back(VoidCallback then) {
      Navigator.of(context).popUntil((r) => r.isFirst);
      then();
    }

    return Scaffold(
      appBar: AppBar(title: Text(v.name), backgroundColor: Colors.white, surfaceTintColor: Colors.transparent),
      body: ListView(padding: const EdgeInsets.all(16), children: [
        Row(children: [
          VehicleAvatar(status: v.status),
          const SizedBox(width: 16),
          Expanded(
            child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
              Text(v.name, style: const TextStyle(fontSize: 22, fontWeight: FontWeight.w600)),
              if (v.registration != null) Text(v.registration!, style: const TextStyle(fontSize: 16)),
              Text(switch (v.status) { 'active' => 'Moving', 'idle' => 'Idle', _ => 'Offline' },
                  style: const TextStyle(color: AppColors.muted)),
            ]),
          ),
        ]),
        const SizedBox(height: 16),
        Row(children: [
          _Action(Icons.map_outlined, 'Map', () => back(() => session.showOnMap(imei))),
          _Action(Icons.my_location, 'Live', () => back(() => session.followLive(imei))),
          _Action(Icons.route, 'Trips', () => back(() => session.showTrips(imei))),
          _Action(Icons.share, 'Share', () => shareLocation(context, v)),
        ]),
        const SizedBox(height: 16),
        _Section('Details', [
          ('Make', v.make),
          ('Model', v.model),
          ('Year', v.year),
          ('Driver', v.driver),
          ('Vehicle group', v.vehicleGroup),
          ('Device', v.deviceModel),
          ('IMEI', v.imei),
        ]),
        AsyncView<VehicleStatus>(
          padding: const EdgeInsets.symmetric(vertical: 24),
          load: () async => VehicleStatus.fromJson(await session.api.get('/api/v2/vehicles/$imei/status')),
          builder: (context, s, _) => Column(children: [
            _Section('Now', [
              ('Location', s.address),
              ('Last report', s.lastReport == null ? null : fmtAgo(s.lastReport)),
              ('Last event', s.lastEvent),
              ('Speed', s.speed == null ? null : '${s.speed} km/h'),
            ]),
            _Section('Today', [
              ('Trips', '${s.tripsToday}'),
              ('Distance', '${s.distanceTodayKm.toStringAsFixed(1)} km'),
              ('Driving', fmtDuration(s.drivingTodayS)),
            ]),
            _Section('Readings', [for (final r in s.readings) (r.name, r.display)]),
          ]),
        ),
      ]),
    );
  }
}

class _Action extends StatelessWidget {
  const _Action(this.icon, this.label, this.onTap);
  final IconData icon;
  final String label;
  final VoidCallback onTap;

  @override
  Widget build(BuildContext context) {
    return Expanded(
      child: InkWell(
        borderRadius: BorderRadius.circular(12),
        onTap: onTap,
        child: Padding(
          padding: const EdgeInsets.symmetric(vertical: 8),
          child: Column(children: [
            CircleAvatar(radius: 24, backgroundColor: AppColors.segment, child: Icon(icon, color: AppColors.navy)),
            const SizedBox(height: 4),
            Text(label, style: const TextStyle(fontSize: 13)),
          ]),
        ),
      ),
    );
  }
}

/// A titled card of label/value rows; rows without a value are left out.
class _Section extends StatelessWidget {
  const _Section(this.title, this.rows);
  final String title;
  final List<(String, String?)> rows;

  @override
  Widget build(BuildContext context) {
    final shown = rows.where((r) => r.$2 != null && r.$2!.isNotEmpty).toList();
    if (shown.isEmpty) return const SizedBox.shrink();
    return Padding(
      padding: const EdgeInsets.only(bottom: 16),
      child: Container(
        decoration: cardDecoration(),
        padding: const EdgeInsets.all(14),
        child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
          Text(title, style: const TextStyle(fontSize: 16, fontWeight: FontWeight.w600)),
          const SizedBox(height: 8),
          for (final (label, value) in shown)
            Padding(
              padding: const EdgeInsets.symmetric(vertical: 4),
              child: Row(crossAxisAlignment: CrossAxisAlignment.start, children: [
                SizedBox(width: 120, child: Text(label, style: const TextStyle(color: AppColors.muted))),
                Expanded(child: Text(value!)),
              ]),
            ),
        ]),
      ),
    );
  }
}
