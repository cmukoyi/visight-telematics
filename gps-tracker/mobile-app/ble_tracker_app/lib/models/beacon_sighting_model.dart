/// Data models for the BLE Scan feature.
///
/// [DiscoveredBeacon]  — a device found during the current phone scan session.
/// [BeaconLocation]    — the backend-stored last known location of a BLE tag.

// ─── Discovered Beacon (in-session, from flutter_blue_plus) ─────────────────

class DiscoveredBeacon {
  final String id;
  final String? name;
  final int rssi;
  final DateTime lastSeen;
  final Map<int, List<int>> manufacturerData;

  /// BLE service data keyed by lowercase UUID string
  /// (e.g. "0000feaa-0000-1000-8000-00805f9b34fb" for Eddystone).
  final Map<String, List<int>> serviceData;

  const DiscoveredBeacon({
    required this.id,
    this.name,
    required this.rssi,
    required this.lastSeen,
    this.manufacturerData = const {},
    this.serviceData = const {},
  });

  /// A human-readable identifier: preferred name, otherwise truncated device ID.
  String get displayName {
    if (name != null && name!.isNotEmpty) return name!;
    return id.length > 11 ? '${id.substring(0, 11)}…' : id;
  }

  String get signalLabel {
    if (rssi > -50) return 'Excellent';
    if (rssi > -65) return 'Good';
    if (rssi > -80) return 'Fair';
    return 'Weak';
  }

  /// Bar count 1–4 for RSSI (Excellent → Weak).
  int get signalBars {
    if (rssi > -50) return 4;
    if (rssi > -65) return 3;
    if (rssi > -80) return 2;
    return 1;
  }

  DiscoveredBeacon copyWith({int? rssi, DateTime? lastSeen}) => DiscoveredBeacon(
        id: id,
        name: name,
        rssi: rssi ?? this.rssi,
        lastSeen: lastSeen ?? this.lastSeen,
        manufacturerData: manufacturerData,
        serviceData: serviceData,
      );
}

// ─── Beacon Location (persisted on backend) ──────────────────────────────────

class BeaconLocation {
  final String tagId;
  final String? tagName;
  final double lat;
  final double lon;
  final int? rssi;
  final DateTime lastSeen;

  const BeaconLocation({
    required this.tagId,
    this.tagName,
    required this.lat,
    required this.lon,
    this.rssi,
    required this.lastSeen,
  });

  String get displayName =>
      (tagName != null && tagName!.isNotEmpty) ? tagName! : tagId;

  factory BeaconLocation.fromJson(Map<String, dynamic> json) => BeaconLocation(
        tagId: json['tag_id'] as String,
        tagName: json['tag_name'] as String?,
        lat: (json['lat'] as num).toDouble(),
        lon: (json['lon'] as num).toDouble(),
        rssi: json['rssi'] as int?,
        lastSeen: DateTime.parse(json['last_seen'] as String),
      );
}
