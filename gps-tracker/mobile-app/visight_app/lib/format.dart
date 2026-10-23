import 'package:intl/intl.dart';

String fmtDate(DateTime d) => DateFormat('d MMM yyyy').format(d);
String fmtTime(DateTime d) => DateFormat('HH:mm').format(d);
String fmtDateTime(DateTime d) => DateFormat('d MMM yyyy, HH:mm').format(d);

String fmtDistance(int metres) => metres < 1000 ? '$metres m' : '${(metres / 1000).toStringAsFixed(1)} km';

String fmtDuration(int seconds) {
  final h = seconds ~/ 3600, m = (seconds % 3600) ~/ 60;
  if (h > 0) return '${h}h ${m.toString().padLeft(2, '0')}m';
  return m > 0 ? '${m}m' : '${seconds}s';
}

/// "5 min ago", "3 h ago", or the date for anything older than a day.
String fmtAgo(DateTime? d) {
  if (d == null) return 'Never';
  final diff = DateTime.now().difference(d);
  if (diff.inMinutes < 1) return 'Just now';
  if (diff.inMinutes < 60) return '${diff.inMinutes} min ago';
  if (diff.inHours < 24) return '${diff.inHours} h ago';
  return fmtDateTime(d);
}

String mapsLink(double lat, double lng) => 'https://www.google.com/maps?q=$lat,$lng';
