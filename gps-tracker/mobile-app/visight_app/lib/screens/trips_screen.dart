import 'dart:convert';

import 'package:flutter/material.dart';
import 'package:share_plus/share_plus.dart';

import '../api/models.dart';
import '../format.dart';
import '../session.dart';
import '../theme.dart';
import '../widgets/common.dart';
import '../widgets/trip_card.dart';

/// Trips of the user's vehicles, newest first, filtered by vehicle and period.
class TripsScreen extends StatefulWidget {
  const TripsScreen({super.key});

  @override
  State<TripsScreen> createState() => _TripsScreenState();
}

const _periods = {'Today': 0, '7 days': 7, '30 days': 30, '90 days': 90};

class _TripsScreenState extends State<TripsScreen> {
  String _period = '7 days';
  List<Trip> _shown = const [];

  DateTime get _from {
    final now = DateTime.now();
    return DateTime(now.year, now.month, now.day).subtract(Duration(days: _periods[_period]!));
  }

  Future<List<Trip>> _load(Session session, String? imei) async {
    final rows = await session.api.get('/api/v2/trips', {
      'date_from': _from.toUtc().toIso8601String(),
      'imei': imei,
      'limit': '500',
    }) as List;
    return _shown = [for (final r in rows) Trip.fromJson(r)];
  }

  Future<void> _filters(Session session) async {
    String? imei = session.tripsImei.value;
    String period = _period;
    final apply = await showModalBottomSheet<bool>(
      context: context,
      showDragHandle: true,
      builder: (ctx) => StatefulBuilder(
        builder: (ctx, set) => SafeArea(
          child: Padding(
            padding: const EdgeInsets.fromLTRB(16, 0, 16, 16),
            child: Column(mainAxisSize: MainAxisSize.min, crossAxisAlignment: CrossAxisAlignment.stretch, children: [
              const Text('Vehicle', style: TextStyle(fontWeight: FontWeight.w600)),
              const SizedBox(height: 8),
              DropdownButtonFormField<String?>(
                initialValue: imei,
                isExpanded: true,
                items: [
                  const DropdownMenuItem(value: null, child: Text('All vehicles')),
                  for (final v in session.vehicles) DropdownMenuItem(value: v.imei, child: Text(v.name)),
                ],
                onChanged: (v) => set(() => imei = v),
              ),
              const SizedBox(height: 16),
              const Text('Period', style: TextStyle(fontWeight: FontWeight.w600)),
              const SizedBox(height: 8),
              Wrap(spacing: 8, children: [
                for (final p in _periods.keys)
                  ChoiceChip(label: Text(p), selected: p == period, onSelected: (_) => set(() => period = p)),
              ]),
              const SizedBox(height: 20),
              FilledButton(onPressed: () => Navigator.pop(ctx, true), child: const Text('Apply')),
            ]),
          ),
        ),
      ),
    );
    if (apply != true) return;
    setState(() => _period = period);
    session.tripsImei.value = imei;
  }

  Future<void> _download(Session session) async {
    if (_shown.isEmpty) {
      ScaffoldMessenger.of(context).showSnackBar(const SnackBar(content: Text('No trips to download.')));
      return;
    }
    String cell(Object? v) => '"${'${v ?? ''}'.replaceAll('"', '""')}"';
    final lines = [
      ['Vehicle', 'Driver', 'Started', 'Ended', 'From', 'To', 'Distance (km)', 'Duration (min)', 'Max speed (km/h)',
          'Exceptions'].map(cell).join(','),
      for (final t in _shown)
        [
          session.vehicle(t.imei)?.name ?? t.deviceName ?? t.imei,
          t.driver,
          fmtDateTime(t.startedAt),
          t.endedAt == null ? '' : fmtDateTime(t.endedAt!),
          t.startAddress,
          t.endAddress,
          (t.distanceM / 1000).toStringAsFixed(1),
          (t.durationS / 60).round(),
          t.maxSpeed,
          t.exceptions,
        ].map(cell).join(','),
    ];
    final name = 'trips-${DateTime.now().toIso8601String().substring(0, 10)}.csv';
    await SharePlus.instance.share(ShareParams(
      files: [XFile.fromData(utf8.encode(lines.join('\n')), mimeType: 'text/csv')],
      fileNameOverrides: [name],
      subject: 'Trips',
    ));
  }

  @override
  Widget build(BuildContext context) {
    final session = SessionScope.of(context);
    return Column(children: [
      const AppHeader(title: 'Trips'),
      ValueListenableBuilder<String?>(
        valueListenable: session.tripsImei,
        builder: (context, imei, _) {
          final vehicle = imei == null ? null : session.vehicle(imei);
          return Expanded(
            child: Column(children: [
              Padding(
                padding: const EdgeInsets.fromLTRB(16, 4, 16, 8),
                child: Row(children: [
                  Expanded(
                    child: OutlinedButton.icon(
                      onPressed: () => _filters(session),
                      icon: const Icon(Icons.filter_alt_outlined),
                      label: const Text('Filters'),
                    ),
                  ),
                  const SizedBox(width: 12),
                  Expanded(
                    child: OutlinedButton.icon(
                      onPressed: () => _download(session),
                      icon: const Icon(Icons.download),
                      label: const Text('Download'),
                    ),
                  ),
                ]),
              ),
              Padding(
                padding: const EdgeInsets.symmetric(horizontal: 16),
                child: Row(children: [
                  Text('${vehicle?.name ?? 'All vehicles'} · $_period',
                      style: const TextStyle(color: AppColors.muted)),
                  const Spacer(),
                  if (imei != null)
                    TextButton(onPressed: () => session.tripsImei.value = null, child: const Text('Show all')),
                ]),
              ),
              Expanded(
                child: AsyncView<List<Trip>>(
                  key: ValueKey('$imei|$_period'),
                  load: () => _load(session, imei),
                  builder: (context, trips, reload) => RefreshIndicator(
                    onRefresh: reload,
                    child: trips.isEmpty
                        ? ListView(children: const [
                            SizedBox(height: 80),
                            MessageView(icon: Icons.route, title: 'No trips', message: 'No trips in this period.'),
                          ])
                        : ListView.builder(
                            padding: const EdgeInsets.fromLTRB(16, 4, 16, 16),
                            itemCount: trips.length,
                            itemBuilder: (_, i) => TripCard(trip: trips[i]),
                          ),
                  ),
                ),
              ),
            ]),
          );
        },
      ),
    ]);
  }
}
