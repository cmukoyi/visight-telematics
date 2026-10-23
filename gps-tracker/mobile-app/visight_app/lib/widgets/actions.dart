import 'package:flutter/material.dart';
import 'package:share_plus/share_plus.dart';

import '../api/api_client.dart';
import '../api/models.dart';
import '../format.dart';
import '../screens/trip_detail_screen.dart';
import '../session.dart';
import 'common.dart';

/// Share where a vehicle is: its name, last address and a Google Maps link.
Future<void> shareLocation(BuildContext context, Vehicle v) async {
  final pos = v.position;
  if (pos == null) {
    ScaffoldMessenger.of(context).showSnackBar(SnackBar(content: Text('${v.name} has no position yet.')));
    return;
  }
  final address = SessionScope.read(context).fleet[v.imei]?.address;
  final text = [
    '${v.name}${v.registration != null ? ' (${v.registration})' : ''}',
    ?address,
    'Last seen ${fmtAgo(v.lastSeen)}',
    mapsLink(pos.latitude, pos.longitude),
  ].join('\n');
  await SharePlus.instance.share(ShareParams(text: text, subject: '${v.name} location'));
}

/// Open the vehicle's most recent trip with its replay running.
Future<void> replayLatestTrip(BuildContext context, Vehicle v) async {
  final session = SessionScope.read(context);
  try {
    final rows = await session.api.get('/api/v2/trips', {'imei': v.imei, 'limit': '1'}) as List;
    if (!context.mounted) return;
    if (rows.isEmpty) {
      ScaffoldMessenger.of(context).showSnackBar(SnackBar(content: Text('${v.name} has no trips yet.')));
      return;
    }
    Navigator.of(context).push(
        MaterialPageRoute(builder: (_) => TripDetailScreen(trip: Trip.fromJson(rows.first), autoplay: true)));
  } on ApiException catch (e) {
    if (context.mounted) showError(context, e);
  }
}
