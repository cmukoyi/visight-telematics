/// Asset model matching mzone API response (renamed from Vehicle)
class Vehicle {
  final String id;
  final String description;
  final String? registration;
  final bool ignitionOn;
  final LastKnownPosition? lastKnownPosition;
  final String? vehicleIcon;
  final String? vehicleIconColor;
  final DateTime? lastKnownEventUtcLastModified;
  final Map<String, dynamic>? attributes;
  final int? batteryLevel;   // Battery % from Series 2 (0-100)
  final String? tagType;     // 'series2' | 'series1'
  
  Vehicle({
    required this.id,
    required this.description,
    this.registration,
    this.ignitionOn = false,
    this.lastKnownPosition,
    this.vehicleIcon,
    this.vehicleIconColor,
    this.lastKnownEventUtcLastModified,
    this.attributes,
    this.batteryLevel,
    this.tagType,
  });
  
  factory Vehicle.fromJson(Map<String, dynamic> json) {
    return Vehicle(
      id: json['id'] ?? '',
      description: json['description'] ?? 'Unknown Asset',
      registration: json['registration'],
      ignitionOn: json['ignitionOn'] ?? false,
      lastKnownPosition: json['lastKnownPosition'] != null
          ? LastKnownPosition.fromJson(json['lastKnownPosition'])
          : null,
      vehicleIcon: json['vehicleIcon'],
      vehicleIconColor: json['vehicleIconColor'],
      lastKnownEventUtcLastModified: json['lastKnownEventUtcLastModified'] != null
          ? DateTime.tryParse(json['lastKnownEventUtcLastModified'])
          : null,
      attributes: json['attributes'] as Map<String, dynamic>?,
      batteryLevel: (json['battery_level'] as num?)?.toInt(),
      tagType: json['tag_type'] as String?,
    );
  }
  
  Map<String, dynamic> toJson() {
    return {
      'id': id,
      'description': description,
      'registration': registration,
      'ignitionOn': ignitionOn,
      'lastKnownPosition': lastKnownPosition?.toJson(),
      'vehicleIcon': vehicleIcon,
      'vehicleIconColor': vehicleIconColor,
      'lastKnownEventUtcLastModified': lastKnownEventUtcLastModified?.toIso8601String(),
      'attributes': attributes,
      'battery_level': batteryLevel,
      'tag_type': tagType,
    };
  }
  
  bool get hasLocation => lastKnownPosition != null && lastKnownPosition!.hasValidCoordinates;
  
  /// Check if this is a newly added asset without location data yet
  bool get isNew => lastKnownPosition == null || !lastKnownPosition!.hasValidCoordinates;
  
  /// Get status string for display
  String get statusText {
    if (isNew) return 'NEW';
    if (lastKnownPosition!.isStale) return 'STALE';
    return 'ACTIVE';
  }
  
  /// Get attributes that should be shown on map
  Map<String, String> get visibleAttributes {
    if (attributes == null) return {};
    final Map<String, String> visible = {};
    
    attributes!.forEach((key, value) {
      if (value is Map && value['show_on_map'] == true) {
        final val = value['value']?.toString() ?? '';
        if (val.isNotEmpty) {
          visible[key] = val;
        }
      }
    });
    
    return visible;
  }
  
  /// Get attribute value by key
  String? getAttributeValue(String key) {
    if (attributes == null || !attributes!.containsKey(key)) return null;
    final attr = attributes![key];
    if (attr is Map && attr.containsKey('value')) {
      return attr['value']?.toString();
    }
    return null;
  }
  
  /// Check if attribute should be shown on map
  bool isAttributeVisible(String key) {
    if (attributes == null || !attributes!.containsKey(key)) return false;
    final attr = attributes![key];
    if (attr is Map && attr.containsKey('show_on_map')) {
      return attr['show_on_map'] == true;
    }
    return false;
  }
}

/// Last known position model
class LastKnownPosition {
  final double latitude;
  final double longitude;
  final DateTime? utcTimestamp;
  final int? eventTypeId;
  final double? speed;
  final String? locationDescription;
  
  LastKnownPosition({
    required this.latitude,
    required this.longitude,
    this.utcTimestamp,
    this.eventTypeId,
    this.speed,
    this.locationDescription,
  });
  
  factory LastKnownPosition.fromJson(Map<String, dynamic> json) {
    return LastKnownPosition(
      latitude: (json['latitude'] ?? 0.0).toDouble(),
      longitude: (json['longitude'] ?? 0.0).toDouble(),
      utcTimestamp: json['utcTimestamp'] != null
          ? DateTime.tryParse(json['utcTimestamp'])
          : null,
      eventTypeId: json['eventType_Id'],
      speed: json['speed']?.toDouble(),
      locationDescription: json['locationDescription'],
    );
  }
  
  Map<String, dynamic> toJson() {
    return {
      'latitude': latitude,
      'longitude': longitude,
      'utcTimestamp': utcTimestamp?.toIso8601String(),
      'eventType_Id': eventTypeId,
      'speed': speed,
      'locationDescription': locationDescription,
    };
  }
  
  bool get hasValidCoordinates {
    return latitude != 0.0 && longitude != 0.0 &&
        latitude >= -90 && latitude <= 90 &&
        longitude >= -180 && longitude <= 180;
  }
  
  String get timestampFormatted {
    if (utcTimestamp == null) return 'Unknown';
    
    final now = DateTime.now();
    final difference = now.difference(utcTimestamp!);
    
    if (difference.inMinutes < 1) return 'Just now';
    if (difference.inMinutes < 60) return '${difference.inMinutes}m ago';
    if (difference.inHours < 24) return '${difference.inHours}h ago';
    if (difference.inDays < 7) return '${difference.inDays}d ago';
    
    return '${utcTimestamp!.day}/${utcTimestamp!.month}/${utcTimestamp!.year}';
  }
  
  bool get isStale {
    if (utcTimestamp == null) return true;
    final now = DateTime.now();
    final difference = now.difference(utcTimestamp!);
    return difference.inHours >= 24;
  }
}

/// Tag model (local representation)
class BLETag {
  final String imei;
  final String description;
  final String? vehicleId;
  /// Vendor platform key, e.g. 'tracksolid' or 'scope'.
  final String tagType;
  
  BLETag({
    required this.imei,
    required this.description,
    this.vehicleId,
    this.tagType = 'series1',
  });
  
  factory BLETag.fromJson(Map<String, dynamic> json) {
    return BLETag(
      imei: json['imei'] ?? '',
      description: json['description'] ?? 'BLE Tag',
      vehicleId: json['vehicle_id'],
      tagType: json['tag_type'] ?? 'series1',
    );
  }
  
  Map<String, dynamic> toJson() {
    return {
      'imei': imei,
      'description': description,
      'vehicle_id': vehicleId,
      'tag_type': tagType,
    };
  }
}
