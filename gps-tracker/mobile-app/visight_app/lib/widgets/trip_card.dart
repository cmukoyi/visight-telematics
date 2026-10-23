import 'package:flutter/material.dart';

import '../api/models.dart';
import '../format.dart';
import '../screens/trip_detail_screen.dart';
import '../session.dart';
import '../theme.dart';
import 'common.dart';

/// A trip row: vehicle, start and end address, and when/how far on the grey panel.
class TripCard extends StatelessWidget {
  const TripCard({super.key, required this.trip});
  final Trip trip;

  @override
  Widget build(BuildContext context) {
    final vehicle = SessionScope.of(context).vehicle(trip.imei);
    final name = (vehicle?.name ?? trip.deviceName ?? trip.imei).toUpperCase();
    return Padding(
      padding: const EdgeInsets.only(bottom: 16),
      child: Material(
        color: Colors.transparent,
        child: InkWell(
          borderRadius: BorderRadius.circular(10),
          onTap: () => Navigator.of(context).push(MaterialPageRoute(builder: (_) => TripDetailScreen(trip: trip))),
          child: Ink(
            decoration: cardDecoration(),
            child: IntrinsicHeight(
              child: Row(crossAxisAlignment: CrossAxisAlignment.stretch, children: [
                Expanded(
                  child: Padding(
                    padding: const EdgeInsets.all(10),
                    child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
                      Row(children: [
                        VehicleAvatar(status: vehicle?.status ?? 'offline', size: 52),
                        const SizedBox(width: 14),
                        Expanded(
                          child: Text(name,
                              maxLines: 1,
                              overflow: TextOverflow.ellipsis,
                              style: const TextStyle(fontSize: 18, fontWeight: FontWeight.w600, color: Color(0xFF3A3A3A))),
                        ),
                        _ExceptionBell(count: trip.exceptions),
                      ]),
                      const SizedBox(height: 10),
                      _AddressLine(text: trip.startAddress ?? 'Unknown start'),
                      const SizedBox(height: 6),
                      _AddressLine(text: trip.isOpen ? 'Trip in progress' : (trip.endAddress ?? 'Unknown end')),
                    ]),
                  ),
                ),
                Container(
                  width: 120,
                  decoration: const BoxDecoration(
                    color: AppColors.panel,
                    borderRadius: BorderRadius.horizontal(right: Radius.circular(10)),
                  ),
                  padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 12),
                  child: Column(mainAxisAlignment: MainAxisAlignment.center, children: [
                    Text('${fmtDate(trip.startedAt)}\n${fmtTime(trip.startedAt)}',
                        textAlign: TextAlign.center,
                        style: const TextStyle(color: Colors.white, fontWeight: FontWeight.w600, fontSize: 15)),
                    const SizedBox(height: 10),
                    Container(
                      padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 6),
                      decoration: BoxDecoration(
                        color: Colors.white,
                        borderRadius: BorderRadius.circular(20),
                        border: Border.all(color: AppColors.navy),
                      ),
                      child: Text(fmtDistance(trip.distanceM),
                          style: const TextStyle(fontWeight: FontWeight.w600, color: AppColors.navy)),
                    ),
                    const SizedBox(height: 4),
                    Text(fmtDuration(trip.durationS), style: const TextStyle(color: Colors.white, fontSize: 13)),
                  ]),
                ),
              ]),
            ),
          ),
        ),
      ),
    );
  }
}

class _AddressLine extends StatelessWidget {
  const _AddressLine({required this.text});
  final String text;

  @override
  Widget build(BuildContext context) {
    return Row(children: [
      const Icon(Icons.location_on, size: 22, color: AppColors.navy),
      const SizedBox(width: 8),
      Expanded(child: Text(text, maxLines: 1, overflow: TextOverflow.ellipsis, style: const TextStyle(fontSize: 14))),
    ]);
  }
}

/// Bell with the number of speeding and harsh-driving events, orange when there are any.
class _ExceptionBell extends StatelessWidget {
  const _ExceptionBell({required this.count});
  final int count;

  @override
  Widget build(BuildContext context) {
    return Badge(
      isLabelVisible: count > 0,
      label: Text('$count'),
      backgroundColor: const Color(0xFFC62828),
      child: Icon(Icons.notifications, size: 28, color: count > 0 ? AppColors.alert : AppColors.panel),
    );
  }
}
