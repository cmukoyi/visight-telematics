/// Trip model matching MZone API Trips response
class Trip {
  final String id;
  final String vehicleId;
  final String vehicleDescription;
  final String? driverDescription;
  final String? driverKeyCode;
  final double? distance; // in miles (received from API)
  final int duration; // in seconds
  final DateTime startUtcTimestamp;
  final DateTime endUtcTimestamp;
  final String? startLocationDescription;
  final String? endLocationDescription;
  
  Trip({
    required this.id,
    required this.vehicleId,
    required this.vehicleDescription,
    this.driverDescription,
    this.driverKeyCode,
    this.distance,
    required this.duration,
    required this.startUtcTimestamp,
    required this.endUtcTimestamp,
    this.startLocationDescription,
    this.endLocationDescription,
  });
  
  factory Trip.fromJson(Map<String, dynamic> json) {
    return Trip(
      id: json['id'] ?? '',
      vehicleId: json['vehicle_Id'] ?? '',
      vehicleDescription: json['vehicle_Description'] ?? 'Unknown Vehicle',
      driverDescription: json['driver_Description'],
      driverKeyCode: json['driverKeyCode'],
      distance: json['distance']?.toDouble(),
      duration: json['duration'] ?? 0,
      startUtcTimestamp: json['startUtcTimestamp'] != null
          ? DateTime.parse(json['startUtcTimestamp'])
          : DateTime.now(),
      endUtcTimestamp: json['endUtcTimestamp'] != null
          ? DateTime.parse(json['endUtcTimestamp'])
          : DateTime.now(),
      startLocationDescription: json['startLocationDescription'],
      endLocationDescription: json['endLocationDescription'],
    );
  }
  
  Map<String, dynamic> toJson() {
    return {
      'id': id,
      'vehicle_Id': vehicleId,
      'vehicle_Description': vehicleDescription,
      'driver_Description': driverDescription,
      'driverKeyCode': driverKeyCode,
      'distance': distance,
      'duration': duration,
      'startUtcTimestamp': startUtcTimestamp.toIso8601String(),
      'endUtcTimestamp': endUtcTimestamp.toIso8601String(),
      'startLocationDescription': startLocationDescription,
      'endLocationDescription': endLocationDescription,
    };
  }
  
  /// Format duration as "Xh Ym" or "Ym"
  String get formattedDuration {
    final hours = duration ~/ 3600;
    final minutes = (duration % 3600) ~/ 60;
    
    if (hours > 0) {
      return '${hours}h ${minutes}m';
    }
    return '${minutes}m';
  }
  
  /// Format distance with 2 decimal places (already in miles)
  String get formattedDistance {
    if (distance == null) return 'N/A';
    return '${distance!.toStringAsFixed(2)} mi';
  }
  
  /// Get short time format (HH:mm)
  String get startTimeFormatted {
    final hour = startUtcTimestamp.toLocal().hour.toString().padLeft(2, '0');
    final minute = startUtcTimestamp.toLocal().minute.toString().padLeft(2, '0');
    return '$hour:$minute';
  }
  
  String get endTimeFormatted {
    final hour = endUtcTimestamp.toLocal().hour.toString().padLeft(2, '0');
    final minute = endUtcTimestamp.toLocal().minute.toString().padLeft(2, '0');
    return '$hour:$minute';
  }
  
  /// Get date formatted as "MMM dd, yyyy"
  String get dateFormatted {
    final months = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'];
    final local = startUtcTimestamp.toLocal();
    return '${months[local.month - 1]} ${local.day}, ${local.year}';
  }
}

/// Trip event/waypoint for route plotting
class TripEvent {
  final String id;
  final DateTime utcTimestamp;
  final double latitude;
  final double longitude;
  final int? direction;
  final int? speed;
  final double? decimalOdometer;
  final String? eventTypeId;
  final String? eventTypeDescription;
  final String? eventTypeMapMarker;
  
  TripEvent({
    required this.id,
    required this.utcTimestamp,
    required this.latitude,
    required this.longitude,
    this.direction,
    this.speed,
    this.decimalOdometer,
    this.eventTypeId,
    this.eventTypeDescription,
    this.eventTypeMapMarker,
  });
  
  factory TripEvent.fromJson(Map<String, dynamic> json) {
    return TripEvent(
      id: json['id'] ?? '',
      utcTimestamp: json['utcTimestamp'] != null
          ? DateTime.parse(json['utcTimestamp'])
          : DateTime.now(),
      latitude: (json['latitude'] ?? 0).toDouble(),
      longitude: (json['longitude'] ?? 0).toDouble(),
      direction: json['direction'],
      speed: json['speed'],
      decimalOdometer: json['decimalOdometer']?.toDouble(),
      eventTypeId: json['eventType_Id'],
      eventTypeDescription: json['eventType_Description'],
      eventTypeMapMarker: json['eventType_MapMarker2'],
    );
  }
  
  Map<String, dynamic> toJson() {
    return {
      'id': id,
      'utcTimestamp': utcTimestamp.toIso8601String(),
      'latitude': latitude,
      'longitude': longitude,
      'direction': direction,
      'speed': speed,
      'decimalOdometer': decimalOdometer,
      'eventType_Id': eventTypeId,
      'eventType_Description': eventTypeDescription,
      'eventType_MapMarker2': eventTypeMapMarker,
    };
  }
  
  bool get hasValidCoordinates {
    return latitude != 0 && longitude != 0;
  }
}
