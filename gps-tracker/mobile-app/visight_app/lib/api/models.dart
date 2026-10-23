import 'package:latlong2/latlong.dart';

DateTime? _date(dynamic v) => v is String ? DateTime.tryParse(v)?.toLocal() : null;
double? _num(dynamic v) => v is num ? v.toDouble() : (v is String ? double.tryParse(v) : null);
LatLng? _latLng(dynamic lat, dynamic lng) {
  final a = _num(lat), b = _num(lng);
  return a == null || b == null ? null : LatLng(a, b);
}

/// GET /api/v2/me — who is signed in and whose vehicles they see.
class Me {
  Me.fromJson(Map<String, dynamic> j)
      : email = j['email'] ?? '',
        firstName = j['first_name'],
        lastName = j['last_name'],
        usergroup = j['usergroup'],
        roles = List<String>.from(j['roles'] ?? const []),
        permissions = Set<String>.from(j['permissions'] ?? const []),
        isAdmin = j['is_admin'] == true,
        securityGroup = j['security_group'];

  final String email;
  final String? firstName, lastName, usergroup, securityGroup;
  final List<String> roles;
  final Set<String> permissions;
  final bool isAdmin;

  String get displayName {
    final n = [firstName, lastName].where((s) => s != null && s.isNotEmpty).join(' ');
    return n.isEmpty ? email : n;
  }

  /// Admins (and roles with "See vehicles in all security groups") see every vehicle.
  bool get seesAllVehicles => isAdmin || permissions.contains('security.all_vehicles');
}

/// GET /api/v2/vehicles — one vehicle the user may see.
class Vehicle {
  Vehicle.fromJson(Map<String, dynamic> j)
      : id = j['id'],
        imei = j['imei'],
        name = j['name'] ?? j['imei'],
        deviceModel = j['device_model'],
        vehicleGroup = j['vehicle_group'],
        registration = j['registration'],
        make = j['make'],
        model = j['model'],
        year = j['year'],
        driver = j['driver'],
        status = j['status'] ?? 'offline',
        lastSeen = _date(j['last_seen']),
        position = _latLng(j['latitude'], j['longitude']);

  final String id, imei, name, status;
  final String? deviceModel, vehicleGroup, registration, make, model, year, driver;
  final DateTime? lastSeen;
  final LatLng? position;

  bool get isMoving => status == 'active';
}

/// GET /api/v2/fleet-status — a vehicle's latest event and its street address.
class FleetStatus {
  FleetStatus.fromJson(Map<String, dynamic> j)
      : imei = j['imei'],
        event = j['event'],
        recordedAt = _date(j['recorded_at']),
        speed = (j['speed'] as num?)?.toInt() ?? 0,
        ignition = j['ignition'],
        odometerKm = _num(j['odometer_km']),
        address = j['address'];

  final String imei;
  final String? event, address;
  final DateTime? recordedAt;
  final int speed;
  final bool? ignition;
  final double? odometerKm;
}

/// GET /api/v2/vehicles/{imei}/status — position, readings and today's totals.
class VehicleStatus {
  VehicleStatus.fromJson(Map<String, dynamic> j)
      : lastReport = _date(j['last_report']),
        lastEvent = j['last_event'],
        address = (j['position'] as Map?)?['address'],
        position = j['position'] == null ? null : _latLng(j['position']['latitude'], j['position']['longitude']),
        speed = ((j['position'] as Map?)?['speed'] as num?)?.toInt(),
        readings = [
          for (final r in (j['readings'] as List? ?? const []))
            Reading(r['name'] ?? '', '${r['display'] ?? r['value'] ?? ''}')
        ],
        tripsToday = (j['today']?['trips'] as num?)?.toInt() ?? 0,
        distanceTodayKm = _num(j['today']?['distance_km']) ?? 0,
        drivingTodayS = (j['today']?['driving_s'] as num?)?.toInt() ?? 0;

  final DateTime? lastReport;
  final String? lastEvent, address;
  final LatLng? position;
  final int? speed;
  final List<Reading> readings;
  final int tripsToday, drivingTodayS;
  final double distanceTodayKm;
}

class Reading {
  const Reading(this.name, this.display);
  final String name, display;
}

/// GET /api/v2/vehicles/{imei}/live — latest position and trail.
class LiveTrack {
  LiveTrack.fromJson(Map<String, dynamic> j)
      : position = j['position'] == null ? null : _latLng(j['position']['latitude'], j['position']['longitude']),
        speed = ((j['position'] as Map?)?['speed'] as num?)?.toInt() ?? 0,
        heading = _num((j['position'] as Map?)?['heading']),
        recordedAt = _date((j['position'] as Map?)?['recorded_at']),
        ignition = (j['position'] as Map?)?['ignition'],
        onTrip = j['trip'] != null,
        trail = [
          for (final p in (j['trail'] as List? ?? const [])) ?_latLng(p[0], p[1])
        ];

  final LatLng? position;
  final int speed;
  final double? heading;
  final DateTime? recordedAt;
  final bool? ignition;
  final bool onTrip;
  final List<LatLng> trail;
}

/// GET /api/v2/trips — one trip.
class Trip {
  Trip.fromJson(Map<String, dynamic> j)
      : id = j['id'],
        imei = j['imei'],
        deviceName = j['device_name'],
        driver = j['driver'],
        isOpen = j['status'] == 'open',
        startedAt = _date(j['started_at'])!,
        endedAt = _date(j['ended_at']),
        startAddress = j['start_address'],
        endAddress = j['end_address'],
        start = j['start'] == null ? null : _latLng(j['start'][0], j['start'][1]),
        end = j['end'] == null ? null : _latLng(j['end'][0], j['end'][1]),
        distanceM = (j['distance_m'] as num?)?.toInt() ?? 0,
        durationS = (j['duration_s'] as num?)?.toInt() ?? 0,
        maxSpeed = (j['max_speed'] as num?)?.toInt() ?? 0,
        avgSpeed = _num(j['avg_speed']),
        exceptions = ['speeding_count', 'harsh_acceleration_count', 'harsh_braking_count', 'harsh_cornering_count']
            .fold(0, (sum, k) => sum + ((j[k] as num?)?.toInt() ?? 0));

  final String id, imei;
  final String? deviceName, driver, startAddress, endAddress;
  final bool isOpen;
  final DateTime startedAt;
  final DateTime? endedAt;
  final LatLng? start, end;
  final int distanceM, durationS, maxSpeed, exceptions;
  final double? avgSpeed;
}

/// GET /api/v2/trips/{id} — the trip with its route and events.
class TripDetail extends Trip {
  TripDetail.fromJson(super.j)
      : points = [
          for (final p in (j['points'] as List? ?? const []))
            if (_latLng(p[0], p[1]) case final ll?) RoutePoint(ll, (p[2] as num?)?.toInt() ?? 0, _date(p[3]))
        ],
        events = [for (final e in (j['events'] as List? ?? const [])) TripEvent.fromJson(e)],
        super.fromJson();

  final List<RoutePoint> points;
  final List<TripEvent> events;
}

class RoutePoint {
  const RoutePoint(this.position, this.speed, this.at);
  final LatLng position;
  final int speed;
  final DateTime? at;
}

class TripEvent {
  TripEvent.fromJson(Map<String, dynamic> j)
      : label = j['label'] ?? '',
        kind = j['kind'] ?? 'info',
        at = _date(j['recorded_at']),
        position = _latLng(j['latitude'], j['longitude']),
        speed = (j['speed'] as num?)?.toInt();

  final String label, kind;
  final DateTime? at;
  final LatLng? position;
  final int? speed;
}

/// GET /api/v2/places — a geofence.
class Place {
  Place.fromJson(Map<String, dynamic> j)
      : name = j['name'] ?? '',
        centre = _latLng(j['latitude'], j['longitude'])!,
        radius = _num(j['radius']),
        isCircle = (j['shape_type'] ?? 'circle') == 'circle',
        corners = _corners(j['coordinates']);

  final String name;
  final LatLng centre;
  final double? radius;
  final bool isCircle;
  final List<LatLng> corners;

  static List<LatLng> _corners(dynamic raw) {
    if (raw is! String || raw.isEmpty) return const [];
    final m = RegExp(r'\[\s*(-?[\d.]+)\s*,\s*(-?[\d.]+)\s*\]').allMatches(raw);
    return [for (final c in m) LatLng(double.parse(c[1]!), double.parse(c[2]!))];
  }
}
