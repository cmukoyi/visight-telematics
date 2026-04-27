enum POIType { single, route }

class POI {
  final String id;
  final String userId;
  final String name;
  final String? description;
  final POIType poiType;
  
  // Origin/FROM location
  final double latitude;
  final double longitude;
  final double radius;
  final String? address;
  
  // Destination/TO location (for routes)
  final double? destinationLatitude;
  final double? destinationLongitude;
  final double? destinationRadius;
  final String? destinationAddress;
  
  final bool isActive;
  final DateTime createdAt;
  final DateTime? updatedAt;
  final List<String> armedTrackers; // List of tracker IDs

  POI({
    required this.id,
    required this.userId,
    required this.name,
    this.description,
    this.poiType = POIType.single,
    required this.latitude,
    required this.longitude,
    this.radius = 150.0,
    this.address,
    this.destinationLatitude,
    this.destinationLongitude,
    this.destinationRadius,
    this.destinationAddress,
    this.isActive = true,
    required this.createdAt,
    this.updatedAt,
    this.armedTrackers = const [],
  });

  bool get isRoute => poiType == POIType.route;
  bool get hasDestination => destinationLatitude != null && destinationLongitude != null;

  factory POI.fromJson(Map<String, dynamic> json) {
    return POI(
      id: json['id'],
      userId: json['user_id'],
      name: json['name'],
      description: json['description'],
      poiType: json['poi_type'] == 'route' ? POIType.route : POIType.single,
      latitude: json['latitude'].toDouble(),
      longitude: json['longitude'].toDouble(),
      radius: json['radius']?.toDouble() ?? 150.0,
      address: json['address'],
      destinationLatitude: json['destination_latitude']?.toDouble(),
      destinationLongitude: json['destination_longitude']?.toDouble(),
      destinationRadius: json['destination_radius']?.toDouble(),
      destinationAddress: json['destination_address'],
      isActive: json['is_active'] ?? true,
      createdAt: DateTime.parse(json['created_at']),
      updatedAt: json['updated_at'] != null ? DateTime.parse(json['updated_at']) : null,
      armedTrackers: json['armed_trackers'] != null 
          ? List<String>.from(json['armed_trackers'])
          : [],
    );
  }

  Map<String, dynamic> toJson() {
    return {
      'id': id,
      'user_id': userId,
      'name': name,
      'description': description,
      'poi_type': poiType == POIType.route ? 'route' : 'single',
      'latitude': latitude,
      'longitude': longitude,
      'radius': radius,
      'address': address,
      'destination_latitude': destinationLatitude,
      'destination_longitude': destinationLongitude,
      'destination_radius': destinationRadius,
      'destination_address': destinationAddress,
      'is_active': isActive,
      'created_at': createdAt.toIso8601String(),
      'updated_at': updatedAt?.toIso8601String(),
      'armed_trackers': armedTrackers,
    };
  }

  bool isArmedTo(String trackerId) {
    return armedTrackers.contains(trackerId);
  }
}

class POICreateRequest {
  final String name;
  final String? description;
  final POIType poiType;
  
  // Origin/FROM location
  final double latitude;
  final double longitude;
  final double radius;
  final String? address;
  
  // Destination/TO location (for routes)
  final double? destinationLatitude;
  final double? destinationLongitude;
  final double? destinationRadius;
  final String? destinationAddress;

  POICreateRequest({
    required this.name,
    this.description,
    this.poiType = POIType.single,
    required this.latitude,
    required this.longitude,
    this.radius = 150.0,
    this.address,
    this.destinationLatitude,
    this.destinationLongitude,
    this.destinationRadius,
    this.destinationAddress,
  });

  Map<String, dynamic> toJson() {
    return {
      'name': name,
      'description': description,
      'poi_type': poiType == POIType.route ? 'route' : 'single',
      'latitude': latitude,
      'longitude': longitude,
      'radius': radius,
      'address': address,
      'destination_latitude': destinationLatitude,
      'destination_longitude': destinationLongitude,
      'destination_radius': destinationRadius,
      'destination_address': destinationAddress,
    };
  }
}

enum GeofenceEventType { entry, exit }

class GeofenceAlert {
  final String id;
  final String poiId;
  final String trackerId;
  final String userId;
  final GeofenceEventType eventType;
  final double latitude;
  final double longitude;
  final bool isRead;
  final DateTime createdAt;
  final String? poiName;
  final String? trackerName;

  GeofenceAlert({
    required this.id,
    required this.poiId,
    required this.trackerId,
    required this.userId,
    required this.eventType,
    required this.latitude,
    required this.longitude,
    this.isRead = false,
    required this.createdAt,
    this.poiName,
    this.trackerName,
  });

  factory GeofenceAlert.fromJson(Map<String, dynamic> json) {
    return GeofenceAlert(
      id: json['id'],
      poiId: json['poi_id'],
      trackerId: json['tracker_id'],
      userId: json['user_id'],
      eventType: json['event_type'] == 'entry' 
          ? GeofenceEventType.entry 
          : GeofenceEventType.exit,
      latitude: json['latitude'].toDouble(),
      longitude: json['longitude'].toDouble(),
      isRead: json['is_read'] ?? false,
      createdAt: DateTime.parse(json['created_at']),
      poiName: json['poi_name'],
      trackerName: json['tracker_name'],
    );
  }

  String get eventDescription {
    return eventType == GeofenceEventType.entry ? 'Entered' : 'Exited';
  }

  String get eventEmoji {
    return eventType == GeofenceEventType.entry ? '🟢' : '🔴';
  }
}

class AlertsResponse {
  final List<GeofenceAlert> alerts;
  final int total;
  final int unreadCount;

  AlertsResponse({
    required this.alerts,
    required this.total,
    required this.unreadCount,
  });

  factory AlertsResponse.fromJson(Map<String, dynamic> json) {
    return AlertsResponse(
      alerts: (json['alerts'] as List)
          .map((alert) => GeofenceAlert.fromJson(alert))
          .toList(),
      total: json['total'],
      unreadCount: json['unread_count'],
    );
  }
}

class PostcodeSearchResult {
  final double latitude;
  final double longitude;
  final String address;

  PostcodeSearchResult({
    required this.latitude,
    required this.longitude,
    required this.address,
  });

  factory PostcodeSearchResult.fromJson(Map<String, dynamic> json) {
    return PostcodeSearchResult(
      latitude: json['latitude'].toDouble(),
      longitude: json['longitude'].toDouble(),
      address: json['address'],
    );
  }
}
