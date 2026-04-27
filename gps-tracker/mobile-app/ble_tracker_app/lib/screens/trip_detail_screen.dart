import 'package:flutter/material.dart';
import 'package:google_fonts/google_fonts.dart';
import 'package:flutter_map/flutter_map.dart' as fmap;
import 'package:latlong2/latlong.dart' as latlong;
import 'package:intl/intl.dart';
import 'package:ble_tracker_app/theme/app_theme.dart';
import 'package:ble_tracker_app/services/location_service.dart';
import 'package:ble_tracker_app/services/logger_service.dart';
import 'package:ble_tracker_app/models/trip_model.dart';
import 'package:ble_tracker_app/widgets/map_bubble.dart';

class TripDetailScreen extends StatefulWidget {
  final Trip trip;
  final String? customAssetName;
  const TripDetailScreen({Key? key, required this.trip, this.customAssetName}) : super(key: key);

  @override
  State<TripDetailScreen> createState() => _TripDetailScreenState();
}

class _TripDetailScreenState extends State<TripDetailScreen> {
  final _locationService = LocationService();
  final _logger = LoggerService();

  List<TripEvent> _tripEvents = [];
  List<fmap.Polyline> _tripPolylines = [];
  List<fmap.Marker> _tripMarkers = [];
  bool _isLoading = true;
  fmap.LatLngBounds? _routeBounds;

  // Map controller for zoom controls
  late fmap.MapController _mapController;

  // For showing location bubbles on marker tap
  String? _selectedMarkerType; // 'start' or 'end'
  Offset? _selectedMarkerPosition;

  @override
  void initState() {
    super.initState();
    _mapController = fmap.MapController();
    _loadTripRoute();
  }

  @override
  void dispose() {
    _mapController.dispose();
    super.dispose();
  }

  Future<void> _loadTripRoute() async {
    try {
      final events = await _locationService.getTripEvents(widget.trip.id);

      if (mounted) {
        setState(() {
          _tripEvents = events;
          _isLoading = false;
        });

        // Draw route on map
        _drawRoute(events);
      }
    } catch (e) {
      _logger.error('Failed to load trip route: $e');
      if (mounted) {
        setState(() {
          _isLoading = false;
        });
        ScaffoldMessenger.of(context).showSnackBar(
          SnackBar(
            content: Row(
              children: [
                Icon(Icons.error, color: Colors.white),
                SizedBox(width: 12),
                Expanded(child: Text('Failed to load route: $e')),
              ],
            ),
            backgroundColor: Colors.red,
            behavior: SnackBarBehavior.floating,
            shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(12)),
          ),
        );
      }
    }
  }

  void _drawRoute(List<TripEvent> events) {
    if (events.isEmpty) return;

    // Create polyline
    final points = events.map((e) => latlong.LatLng(e.latitude, e.longitude)).toList();

    final polyline = fmap.Polyline(
      points: points,
      color: AppTheme.brandPrimary,
      strokeWidth: 4.0,
      isDotted: false,
    );

    // Create start marker
    final startEvent = events.first;
    final startMarker = fmap.Marker(
      point: latlong.LatLng(startEvent.latitude, startEvent.longitude),
      width: 40,
      height: 40,
      child: GestureDetector(
        onTap: () {
          setState(() {
            _selectedMarkerType = 'start';
            _selectedMarkerPosition = Offset(20, 20);
          });
        },
        child: Container(
          decoration: BoxDecoration(
            color: Colors.green,
            shape: BoxShape.circle,
            boxShadow: [
              BoxShadow(
                color: Colors.black.withOpacity(0.3),
                blurRadius: 4,
                offset: Offset(0, 2),
              ),
            ],
          ),
          child: Icon(
            Icons.trip_origin,
            color: Colors.white,
            size: 24,
          ),
        ),
      ),
    );

    // Create end marker
    final endEvent = events.last;
    final endMarker = fmap.Marker(
      point: latlong.LatLng(endEvent.latitude, endEvent.longitude),
      width: 40,
      height: 40,
      child: GestureDetector(
        onTap: () {
          setState(() {
            _selectedMarkerType = 'end';
            _selectedMarkerPosition = Offset(20, 20);
          });
        },
        child: Container(
          decoration: BoxDecoration(
            color: Colors.red,
            shape: BoxShape.circle,
            boxShadow: [
              BoxShadow(
                color: Colors.black.withOpacity(0.3),
                blurRadius: 4,
                offset: Offset(0, 2),
              ),
            ],
          ),
          child: Icon(
            Icons.place,
            color: Colors.white,
            size: 24,
          ),
        ),
      ),
    );

    setState(() {
      _tripPolylines = [polyline];
      _tripMarkers = [startMarker, endMarker];
    });

    // Zoom map to show full route
    _zoomToRoute(points);
  }

  void _zoomToRoute(List<latlong.LatLng> points) {
    if (points.isEmpty) return;

    double minLat = points.first.latitude;
    double maxLat = points.first.latitude;
    double minLng = points.first.longitude;
    double maxLng = points.first.longitude;

    for (var point in points) {
      if (point.latitude < minLat) minLat = point.latitude;
      if (point.latitude > maxLat) maxLat = point.latitude;
      if (point.longitude < minLng) minLng = point.longitude;
      if (point.longitude > maxLng) maxLng = point.longitude;
    }

    final latPadding = (maxLat - minLat) * 0.15;
    final lngPadding = (maxLng - minLng) * 0.15;

    final bounds = fmap.LatLngBounds(
      latlong.LatLng(minLat - latPadding, minLng - lngPadding),
      latlong.LatLng(maxLat + latPadding, maxLng + lngPadding),
    );

    setState(() {
      _routeBounds = bounds;
    });
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      backgroundColor: Colors.grey.shade50,
      body: SafeArea(
        child: Column(
          children: [
            // Header
            Container(
              color: Colors.white,
              padding: EdgeInsets.all(16),
              child: Row(
                children: [
                  IconButton(
                    onPressed: Navigator.of(context).pop,
                    icon: Icon(Icons.arrow_back, color: AppTheme.brandPrimary),
                    tooltip: 'Back',
                  ),
                  Expanded(
                    child: Text(
                      'Journey Details',
                      style: GoogleFonts.poppins(
                        fontSize: 20,
                        fontWeight: FontWeight.w700,
                        color: AppTheme.brandPrimary,
                      ),
                    ),
                  ),
                ],
              ),
            ),
            // Map view
            Expanded(
              flex: 7,
              child: Container(
                margin: EdgeInsets.all(12),
                decoration: BoxDecoration(
                  border: Border.all(
                    color: AppTheme.brandPrimary.withOpacity(0.3),
                    width: 2,
                  ),
                  borderRadius: BorderRadius.circular(16),
                  boxShadow: [
                    BoxShadow(
                      color: Colors.black.withOpacity(0.08),
                      blurRadius: 12,
                      offset: Offset(0, 4),
                    ),
                  ],
                ),
                child: ClipRRect(
                  borderRadius: BorderRadius.circular(14),
                  child: _isLoading
                      ? Center(
                          child: CircularProgressIndicator(
                            valueColor: AlwaysStoppedAnimation<Color>(AppTheme.brandPrimary),
                          ),
                        )
                      : Stack(
                          children: [
                            fmap.FlutterMap(
                              mapController: _mapController,
                              options: fmap.MapOptions(
                                initialCenter: _routeBounds != null
                                    ? latlong.LatLng(
                                        (_routeBounds!.south + _routeBounds!.north) / 2,
                                        (_routeBounds!.west + _routeBounds!.east) / 2,
                                      )
                                    : (_tripEvents.isNotEmpty
                                        ? latlong.LatLng(_tripEvents.first.latitude, _tripEvents.first.longitude)
                                        : latlong.LatLng(0, 0)),
                                initialZoom: _routeBounds != null ? 12.0 : 13.0,
                              ),
                              children: [
                                fmap.TileLayer(
                                  urlTemplate: 'https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png',
                                  subdomains: const ['a', 'b', 'c'],
                                  userAgentPackageName: 'com.beacontelematics.tracker',
                                  keepBuffer: 2,
                                  panBuffer: 1,
                                ),
                                fmap.PolylineLayer(polylines: _tripPolylines),
                                fmap.MarkerLayer(markers: _tripMarkers),
                              ],
                            ),
                            if (_selectedMarkerType != null && _selectedMarkerPosition != null)
                              _buildLocationBubble(),
                            Positioned(
                              right: 12,
                              bottom: 12,
                              child: Column(
                                children: [
                                  FloatingActionButton(
                                    mini: true,
                                    heroTag: 'zoom_in',
                                    backgroundColor: Colors.white,
                                    elevation: 2,
                                    onPressed: () {
                                      _mapController.move(
                                        _mapController.camera.center,
                                        _mapController.camera.zoom + 1,
                                      );
                                    },
                                    child: Icon(Icons.add, color: AppTheme.brandPrimary),
                                  ),
                                  SizedBox(height: 8),
                                  FloatingActionButton(
                                    mini: true,
                                    heroTag: 'zoom_out',
                                    backgroundColor: Colors.white,
                                    elevation: 2,
                                    onPressed: () {
                                      _mapController.move(
                                        _mapController.camera.center,
                                        _mapController.camera.zoom - 1,
                                      );
                                    },
                                    child: Icon(Icons.remove, color: AppTheme.brandPrimary),
                                  ),
                                ],
                              ),
                            ),
                          ],
                        ),
                ),
              ),
            ),
            // Trip info box
            Container(
              color: Colors.white,
              child: SingleChildScrollView(
                child: Padding(
                  padding: EdgeInsets.symmetric(horizontal: 16, vertical: 12),
                  child: Column(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      // Date
                      Row(
                        children: [
                          Icon(Icons.calendar_today, size: 16, color: Colors.grey.shade600),
                          SizedBox(width: 8),
                          Text(
                            widget.trip.dateFormatted,
                            style: GoogleFonts.inter(
                              fontSize: 14,
                              fontWeight: FontWeight.w600,
                              color: Colors.grey.shade900,
                            ),
                          ),
                        ],
                      ),
                      SizedBox(height: 6),
                      // Time
                      Row(
                        children: [
                          Icon(Icons.access_time, size: 16, color: Colors.grey.shade600),
                          SizedBox(width: 8),
                          Text(
                            '${widget.trip.startTimeFormatted} - ${widget.trip.endTimeFormatted}',
                            style: GoogleFonts.inter(
                              fontSize: 13,
                              fontWeight: FontWeight.w500,
                              color: Colors.grey.shade900,
                            ),
                          ),
                        ],
                      ),
                      SizedBox(height: 8),
                      Divider(color: Colors.grey.shade300, height: 1),
                      SizedBox(height: 8),
                      // Vehicle
                      Row(
                        children: [
                          Container(
                            padding: EdgeInsets.all(8),
                            decoration: BoxDecoration(
                              color: AppTheme.brandPrimary.withOpacity(0.1),
                              borderRadius: BorderRadius.circular(8),
                            ),
                            child: Icon(Icons.inventory_2, size: 18, color: AppTheme.brandPrimary),
                          ),
                          SizedBox(width: 12),
                          Expanded(
                            child: Column(
                              crossAxisAlignment: CrossAxisAlignment.start,
                              children: [
                                Text(
                                  'Asset',
                                  style: GoogleFonts.inter(
                                    fontSize: 12,
                                    color: Colors.grey.shade600,
                                  ),
                                ),
                                Text(
                                  widget.customAssetName ?? widget.trip.vehicleDescription,
                                  style: GoogleFonts.inter(
                                    fontSize: 14,
                                    fontWeight: FontWeight.w600,
                                    color: Colors.grey.shade900,
                                  ),
                                ),
                              ],
                            ),
                          ),
                        ],
                      ),
                      SizedBox(height: 8),
                      // Distance and Duration
                      Row(
                        children: [
                          Expanded(
                            child: Row(
                              children: [
                                Container(
                                  padding: EdgeInsets.all(6),
                                  decoration: BoxDecoration(
                                    color: Colors.blue.shade50,
                                    borderRadius: BorderRadius.circular(6),
                                  ),
                                  child: Icon(Icons.straighten, size: 16, color: Colors.blue.shade700),
                                ),
                                SizedBox(width: 8),
                                Expanded(
                                  child: Column(
                                    crossAxisAlignment: CrossAxisAlignment.start,
                                    children: [
                                      Text(
                                        'Distance',
                                        style: GoogleFonts.inter(
                                          fontSize: 11,
                                          color: Colors.grey.shade600,
                                        ),
                                      ),
                                      Text(
                                        widget.trip.formattedDistance,
                                        style: GoogleFonts.inter(
                                          fontSize: 13,
                                          fontWeight: FontWeight.w600,
                                          color: Colors.blue.shade700,
                                        ),
                                      ),
                                    ],
                                  ),
                                ),
                              ],
                            ),
                          ),
                          SizedBox(width: 12),
                          Expanded(
                            child: Row(
                              children: [
                                Container(
                                  padding: EdgeInsets.all(6),
                                  decoration: BoxDecoration(
                                    color: Colors.orange.shade50,
                                    borderRadius: BorderRadius.circular(6),
                                  ),
                                  child: Icon(Icons.timer, size: 16, color: Colors.orange.shade700),
                                ),
                                SizedBox(width: 8),
                                Expanded(
                                  child: Column(
                                    crossAxisAlignment: CrossAxisAlignment.start,
                                    children: [
                                      Text(
                                        'Duration',
                                        style: GoogleFonts.inter(
                                          fontSize: 11,
                                          color: Colors.grey.shade600,
                                        ),
                                      ),
                                      Text(
                                        widget.trip.formattedDuration,
                                        style: GoogleFonts.inter(
                                          fontSize: 13,
                                          fontWeight: FontWeight.w600,
                                          color: Colors.orange.shade700,
                                        ),
                                      ),
                                    ],
                                  ),
                                ),
                              ],
                            ),
                          ),
                        ],
                      ),
                      SizedBox(height: 12),
                      // Start location
                      if (widget.trip.startLocationDescription != null) ...[
                        Row(
                          crossAxisAlignment: CrossAxisAlignment.start,
                          children: [
                            Container(
                              padding: EdgeInsets.all(8),
                              decoration: BoxDecoration(
                                color: Colors.green.shade50,
                                borderRadius: BorderRadius.circular(8),
                              ),
                              child: Icon(Icons.trip_origin, size: 18, color: Colors.green.shade700),
                            ),
                            SizedBox(width: 12),
                            Expanded(
                              child: Column(
                                crossAxisAlignment: CrossAxisAlignment.start,
                                children: [
                                  Text(
                                    'Start Location',
                                    style: GoogleFonts.inter(
                                      fontSize: 12,
                                      color: Colors.grey.shade600,
                                    ),
                                  ),
                                  Text(
                                    widget.trip.startLocationDescription!,
                                    style: GoogleFonts.inter(
                                      fontSize: 13,
                                      color: Colors.grey.shade900,
                                    ),
                                    maxLines: 2,
                                    overflow: TextOverflow.ellipsis,
                                  ),
                                ],
                              ),
                            ),
                          ],
                        ),
                        SizedBox(height: 12),
                      ],
                      // End location
                      if (widget.trip.endLocationDescription != null) ...[
                        Row(
                          crossAxisAlignment: CrossAxisAlignment.start,
                          children: [
                            Container(
                              padding: EdgeInsets.all(8),
                              decoration: BoxDecoration(
                                color: Colors.red.shade50,
                                borderRadius: BorderRadius.circular(8),
                              ),
                              child: Icon(Icons.place, size: 18, color: Colors.red.shade700),
                            ),
                            SizedBox(width: 12),
                            Expanded(
                              child: Column(
                                crossAxisAlignment: CrossAxisAlignment.start,
                                children: [
                                  Text(
                                    'End Location',
                                    style: GoogleFonts.inter(
                                      fontSize: 12,
                                      color: Colors.grey.shade600,
                                    ),
                                  ),
                                  Text(
                                    widget.trip.endLocationDescription!,
                                    style: GoogleFonts.inter(
                                      fontSize: 13,
                                      color: Colors.grey.shade900,
                                    ),
                                    maxLines: 2,
                                    overflow: TextOverflow.ellipsis,
                                  ),
                                ],
                              ),
                            ),
                          ],
                        ),
                        SizedBox(height: 12),
                      ],
                      // Driver info
                      if (widget.trip.driverDescription != null) ...[
                        Row(
                          children: [
                            Container(
                              padding: EdgeInsets.all(8),
                              decoration: BoxDecoration(
                                color: Colors.purple.shade50,
                                borderRadius: BorderRadius.circular(8),
                              ),
                              child: Icon(Icons.person, size: 18, color: Colors.purple.shade700),
                            ),
                            SizedBox(width: 12),
                            Expanded(
                              child: Column(
                                crossAxisAlignment: CrossAxisAlignment.start,
                                children: [
                                  Text(
                                    'Driver',
                                    style: GoogleFonts.inter(
                                      fontSize: 12,
                                      color: Colors.grey.shade600,
                                    ),
                                  ),
                                  Text(
                                    widget.trip.driverDescription!,
                                    style: GoogleFonts.inter(
                                      fontSize: 13,
                                      color: Colors.grey.shade900,
                                    ),
                                    maxLines: 2,
                                    overflow: TextOverflow.ellipsis,
                                  ),
                                ],
                              ),
                            ),
                          ],
                        ),
                      ],
                    ],       // closes Column children
                  ),         // closes Column
                ),           // closes Padding
              ),             // closes SingleChildScrollView
            ),               // closes Container (trip info box)
          ],                 // closes outer Column children
        ),                   // closes Column
      ),                     // closes SafeArea
    );                       // closes Scaffold
  }

  Widget _buildLocationBubble() {
    String title = '';
    String? description;
    String? subtitle;

    if (_selectedMarkerType == 'start' && _tripEvents.isNotEmpty) {
      final event = _tripEvents.first;
      title = 'Trip Start';
      subtitle = DateFormat('MMM dd, yyyy HH:mm').format(event.utcTimestamp.toLocal());
      description = 'Location: ${event.latitude.toStringAsFixed(3)}, ${event.longitude.toStringAsFixed(3)}';
    } else if (_selectedMarkerType == 'end' && _tripEvents.isNotEmpty) {
      final event = _tripEvents.last;
      title = 'Trip End';
      subtitle = DateFormat('MMM dd, yyyy HH:mm').format(event.utcTimestamp.toLocal());
      description = 'Location: ${event.latitude.toStringAsFixed(3)}, ${event.longitude.toStringAsFixed(3)}';
    }

    final screenWidth = MediaQuery.of(context).size.width;
    final maxBubbleWidth = screenWidth < 360 ? screenWidth * 0.7 : 250.0;

    return Positioned(
      left: 16,
      top: 16,
      child: GestureDetector(
        onTap: () {},
        child: Container(
          constraints: BoxConstraints(maxWidth: maxBubbleWidth),
          decoration: BoxDecoration(
            color: Colors.white,
            borderRadius: BorderRadius.circular(12),
            boxShadow: [
              BoxShadow(
                color: Colors.black.withOpacity(0.15),
                blurRadius: 12,
                offset: Offset(0, 4),
              ),
            ],
            border: Border.all(
              color: AppTheme.brandPrimary.withOpacity(0.2),
              width: 1,
            ),
          ),
          child: Stack(
            children: [
              Padding(
                padding: EdgeInsets.all(12),
                child: Column(
                  mainAxisSize: MainAxisSize.min,
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Text(
                      title,
                      style: GoogleFonts.inter(
                        fontSize: 13,
                        fontWeight: FontWeight.w700,
                        color: AppTheme.brandPrimary,
                      ),
                    ),
                    if (subtitle != null) ...[
                      SizedBox(height: 4),
                      Text(
                        subtitle,
                        style: GoogleFonts.inter(
                          fontSize: 11,
                          color: Colors.grey.shade600,
                        ),
                      ),
                    ],
                    if (description != null && description.isNotEmpty) ...[
                      SizedBox(height: 8),
                      Container(
                        padding: EdgeInsets.symmetric(horizontal: 8, vertical: 6),
                        decoration: BoxDecoration(
                          color: Colors.grey.shade50,
                          borderRadius: BorderRadius.circular(6),
                        ),
                        child: Text(
                          description,
                          style: GoogleFonts.inter(
                            fontSize: 11,
                            color: Colors.grey.shade800,
                          ),
                          maxLines: 2,
                          overflow: TextOverflow.ellipsis,
                        ),
                      ),
                    ],
                  ],
                ),
              ),
              Positioned(
                top: 4,
                right: 4,
                child: GestureDetector(
                  onTap: () {
                    setState(() {
                      _selectedMarkerType = null;
                      _selectedMarkerPosition = null;
                    });
                  },
                  child: Container(
                    padding: EdgeInsets.all(4),
                    decoration: BoxDecoration(
                      color: Colors.grey.shade200,
                      shape: BoxShape.circle,
                    ),
                    child: Icon(
                      Icons.close,
                      size: 14,
                      color: Colors.grey.shade700,
                    ),
                  ),
                ),
              ),
            ],
          ),
        ),
      ),
    );
  }
}