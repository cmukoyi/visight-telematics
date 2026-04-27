import 'dart:async';
import 'package:flutter/material.dart';
import 'package:flutter/foundation.dart';
import 'package:google_maps_flutter/google_maps_flutter.dart' as gmaps;
import 'package:apple_maps_flutter/apple_maps_flutter.dart' as apple;
import 'package:flutter_map/flutter_map.dart' as fmap;
import 'package:latlong2/latlong.dart' as latlong;
import 'package:google_fonts/google_fonts.dart';
import 'package:share_plus/share_plus.dart';
import 'package:ble_tracker_app/theme/app_theme.dart';
import 'package:ble_tracker_app/services/auth_service.dart';
import 'package:ble_tracker_app/services/location_service.dart';
import 'package:ble_tracker_app/services/logger_service.dart';
import 'package:ble_tracker_app/services/poi_service.dart';
import 'package:ble_tracker_app/services/deployment_monitor_service.dart';
import 'package:ble_tracker_app/models/vehicle_model.dart';
import 'package:ble_tracker_app/models/poi_model.dart';
import 'package:ble_tracker_app/models/trip_model.dart';
import 'package:ble_tracker_app/screens/home_screen.dart';
import 'package:ble_tracker_app/screens/alerts_screen.dart';
import 'package:ble_tracker_app/screens/trip_detail_screen.dart';
import 'package:ble_tracker_app/screens/scan_screen.dart';
import 'package:ble_tracker_app/screens/solutions_screen.dart';
import 'package:ble_tracker_app/services/app_features_service.dart';

// App version
const String APP_VERSION = '1.0.0';

class MapScreen extends StatefulWidget {
  const MapScreen({Key? key}) : super(key: key);

  @override
  State<MapScreen> createState() => _MapScreenState();
}

class _MapScreenState extends State<MapScreen> {
  final _authService = AuthService();
  final _locationService = LocationService();
  final _logger = LoggerService();
  final _poiService = POIService();
  final _deploymentMonitor = DeploymentMonitorService();
  int _selectedIndex = 0;
  AppFeatures _features = AppFeatures.defaults();
  int _unreadAlertCount = 0;
  Timer? _locationRefreshTimer; // Auto-refresh timer
  String? _userEmail; // Store logged-in user's email
  
  // Platform-specific map controllers
  Completer<gmaps.GoogleMapController>? _googleMapController;
  apple.AppleMapController? _appleMapController;
  final fmap.MapController _flutterMapController = fmap.MapController(); // For web
  
  Set<gmaps.Marker> _googleMarkers = {};
  Set<apple.Annotation> _appleAnnotations = {};
  List<fmap.Marker> _flutterMapMarkers = []; // For web and Android
  
  bool _isLoading = true;
  bool _isFirstLoad = true; // Track if this is first load to prevent map jumping
  List<Vehicle> _vehicles = [];
  Map<String, String> _vehicleCustomNames = {}; // Store custom names for vehicles
  Vehicle? _selectedVehicle; // Track selected vehicle for popup
  bool _googleMapsFailed = false; // Track if Google Maps failed to load
  
  // POI/Geofence management
  List<dynamic> _pois = []; // Store POIs
  List<fmap.CircleMarker> _geofenceCircles = []; // Geofence circles for flutter_map
  bool _showPOIs = true; // Toggle to show/hide POIs on map
  
  // Trips/Journeys management
  List<Trip> _trips = []; // Store fetched trips
  bool _isLoadingTrips = false;
  bool _tripsInitiallyLoaded = false; // Track if trips have been loaded at least once
  String _selectedDateRange = 'Today'; // Current date filter
  DateTime? _customStartDate; // Custom date range start
  DateTime? _customEndDate; // Custom date range end
  Vehicle? _selectedTripVehicle; // Vehicle selected for trips view
  Trip? _selectedTrip; // Currently selected trip for route display
  List<TripEvent>? _selectedTripRoute; // Route waypoints for selected trip
  List<fmap.Polyline> _tripRoutePolylines = []; // Route polylines for flutter_map
  List<fmap.Marker> _tripRouteMarkers = []; // Start/end markers for route
  
  // Helper to determine which map to use
  bool get _useAppleMaps => !kIsWeb && defaultTargetPlatform == TargetPlatform.iOS;
  bool get _useGoogleMaps => false; // Disabled - using OpenStreetMap instead
  bool get _useFlutterMap => true; // Use OpenStreetMap for all platforms (free, no API key needed)

  @override
  void initState() {
    super.initState();
    // Check authentication before loading any data
    _checkAuthAndLoad();
  }
  
  Future<void> _checkAuthAndLoad() async {
    // Verify user is authenticated before proceeding
    final isLoggedIn = await _authService.isLoggedIn();
    if (!isLoggedIn) {
      // No auth token - redirect to login immediately
      print('❌ MapScreen: No authentication - redirecting to login');
      if (mounted) {
        Navigator.pushNamedAndRemoveUntil(
          context,
          '/welcome',
          (route) => false,
        );
      }
      return;
    }
    
    // Load user email
    final email = await _authService.getUserEmail();
    if (mounted) {
      setState(() {
        _userEmail = email;
      });
    }
    
    // User is authenticated - proceed with loading
    _loadCustomVehicleNames(); // Load saved custom names first
    _loadTags();
    _loadUnreadAlertCount();
    _loadPOIs();
    _loadAppFeatures();
    
    // Auto-refresh locations every 60 seconds for armed geofences
    _locationRefreshTimer = Timer.periodic(Duration(seconds: 60), (timer) {
      _logger.info('Auto-refreshing vehicle locations (60 sec interval)');
      _loadTags();
    });
  }
  
  /// Load app feature flags from backend (cached fallback on error)
  Future<void> _loadAppFeatures() async {
    try {
      final features = await AppFeaturesService().fetchFeatures();
      if (mounted) {
        setState(() {
          _features = features;
        });
      }
    } catch (e) {
      // Keep defaults — app stays fully functional
    }
  }

  /// Load all custom vehicle names from persistent storage
  Future<void> _loadCustomVehicleNames() async {
    try {
      final customNames = await _authService.getAllCustomVehicleNames();
      if (mounted) {
        setState(() {
          _vehicleCustomNames = customNames;
          print('✅ Loaded ${customNames.length} custom vehicle names');
        });
      }
    } catch (e) {
      _logger.error('Failed to load custom vehicle names: $e');
    }
  }
  
  @override
  void dispose() {
    _locationRefreshTimer?.cancel();
    _appleMapController = null;
    _googleMapController = null;
    super.dispose();
  }

  Future<void> _handleLogout() async {
    final confirm = await showDialog<bool>(
      context: context,
      builder: (BuildContext context) {
        return AlertDialog(
          title: Row(
            children: [
              Icon(Icons.logout, color: Colors.red.shade700),
              SizedBox(width: 12),
              Text('Logout'),
            ],
          ),
          content: Text('Are you sure you want to logout?'),
          actions: [
            TextButton(
              onPressed: () => Navigator.pop(context, false),
              child: Text('Cancel'),
            ),
            ElevatedButton(
              onPressed: () => Navigator.pop(context, true),
              style: ElevatedButton.styleFrom(
                backgroundColor: Colors.red.shade700,
                foregroundColor: Colors.white,
              ),
              child: Text('Logout'),
            ),
          ],
        );
      },
    );
    
    if (confirm == true) {
      await _authService.logout();
      if (mounted) {
        Navigator.pushNamedAndRemoveUntil(context, '/welcome', (route) => false);
      }
    }
  }

  Future<void> _loadTags() async {
    try {
      _logger.info('_loadTags: Starting to load vehicle locations');
      print('🔄 MapScreen: Starting to load vehicle locations...');
      setState(() => _isLoading = true);
      
      // Fetch vehicle locations from backend (backend uses user's stored IMEIs)
      // Note: Removed blocking health check - let the main API call handle connectivity
      _logger.network('GET /api/vehicles');
      print('📡 MapScreen: Fetching vehicles from backend...');
      final response = await _locationService.getVehicleLocations();
      
      // Parse vehicles from response
      List<dynamic> vehiclesData;
      if (response['vehicles'] is List) {
        vehiclesData = response['vehicles'];
      } else if (response['vehicles'] is Map && response['vehicles']['value'] is List) {
        vehiclesData = response['vehicles']['value'];
      } else {
        vehiclesData = [];
      }
      
      print('✅ MapScreen: Received ${vehiclesData.length} vehicles from API');
      
      // Parse vehicles
      final vehicles = vehiclesData.map((data) {
        final vehicle = Vehicle.fromJson(data);
        print('🚗 Vehicle parsed: ${vehicle.description}, Attributes: ${vehicle.attributes}');
        if (vehicle.attributes != null && vehicle.attributes!.isNotEmpty) {
          print('   📋 Attributes details:');
          vehicle.attributes!.forEach((key, value) {
            print('      - $key: ${value['value']} (show_on_map: ${value['show_on_map']})');
          });
          print('   👁️ Visible attributes: ${vehicle.visibleAttributes}');
        }
        return vehicle;
      }).toList();
      
      if (!mounted) return;
      
      setState(() {
        _vehicles = vehicles;
      });
      
      if (vehicles.isEmpty) {
        print('⚠️ MapScreen: No vehicles found - please add tags in the home screen');
        setState(() => _isLoading = false);
        return;
      }
      
      // Create markers for vehicles with valid locations
      Set<gmaps.Marker> newGoogleMarkers = {};
      Set<apple.Annotation> newAppleAnnotations = {};
      List<fmap.Marker> newFlutterMapMarkers = [];
      List<gmaps.LatLng> positions = [];
      
      print('📍 MapScreen: Processing ${vehicles.length} vehicles...');
      for (var vehicle in vehicles) {
        if (vehicle.hasLocation) {
          final position = gmaps.LatLng(
            vehicle.lastKnownPosition!.latitude,
            vehicle.lastKnownPosition!.longitude,
          );
          positions.add(position);
          
          print('✅ MapScreen: Adding marker for ${vehicle.description} at [${position.latitude}, ${position.longitude}]');
          
          // Determine marker color based on ignition state and data freshness
          final Color markerColor;
          if (vehicle.lastKnownPosition!.isStale) {
            markerColor = Colors.orange;
          } else if (vehicle.ignitionOn) {
            markerColor = Colors.green;
          } else {
            markerColor = Colors.red;
          }
          
          // Create Google Maps marker (for Android)
          if (_useGoogleMaps) {
            final gmaps.BitmapDescriptor markerIcon;
            if (vehicle.lastKnownPosition!.isStale) {
              markerIcon = gmaps.BitmapDescriptor.defaultMarkerWithHue(gmaps.BitmapDescriptor.hueOrange);
            } else if (vehicle.ignitionOn) {
              markerIcon = gmaps.BitmapDescriptor.defaultMarkerWithHue(gmaps.BitmapDescriptor.hueGreen);
            } else {
              markerIcon = gmaps.BitmapDescriptor.defaultMarkerWithHue(gmaps.BitmapDescriptor.hueRed);
            }
            
            // Prepare info window snippet with location description or coordinates
            final locationInfo = vehicle.lastKnownPosition?.locationDescription ?? 
                '${position.latitude.toStringAsFixed(5)}, ${position.longitude.toStringAsFixed(5)}';
            final visibleAttrs = vehicle.visibleAttributes ?? {};
            final visibleCount = visibleAttrs.length;
            final snippet = visibleCount > 0
                ? '$locationInfo • $visibleCount attribute${visibleCount > 1 ? 's' : ''}'
                : locationInfo;
            
            newGoogleMarkers.add(
              gmaps.Marker(
                markerId: gmaps.MarkerId(vehicle.id),
                position: position,
                icon: markerIcon,
                infoWindow: gmaps.InfoWindow(
                  title: vehicle.description,
                  snippet: snippet,
                ),
                onTap: () => _showVehicleDetails(vehicle),
              ),
            );
          }
          
          // Create Apple Maps annotation (for iOS)
          if (_useAppleMaps) {
            final locationInfo = vehicle.lastKnownPosition?.locationDescription ?? 
                '${position.latitude.toStringAsFixed(5)}, ${position.longitude.toStringAsFixed(5)}';
            final visibleAttrs = vehicle.visibleAttributes ?? {};
            final visibleCount = visibleAttrs.length;
            final snippet = visibleCount > 0
                ? '$locationInfo • $visibleCount attribute${visibleCount > 1 ? 's' : ''}'
                : locationInfo;
                
            newAppleAnnotations.add(
              apple.Annotation(
                annotationId: apple.AnnotationId(vehicle.id),
                position: apple.LatLng(position.latitude, position.longitude),
                infoWindow: apple.InfoWindow(
                  title: vehicle.description,
                  snippet: snippet,
                ),
                onTap: () => _showVehicleDetails(vehicle),
              ),
            );
          }
          
          // Create Flutter Map marker (for Web)
          if (_useFlutterMap) {
            newFlutterMapMarkers.add(
              fmap.Marker(
                point: latlong.LatLng(position.latitude, position.longitude),
                width: 80,
                height: 90,
                child: GestureDetector(
                  onTap: () => _showVehicleDetails(vehicle),
                  child: Column(
                    mainAxisSize: MainAxisSize.min,
                    mainAxisAlignment: MainAxisAlignment.center,
                    children: [
                      Container(
                        padding: EdgeInsets.all(8),
                        decoration: BoxDecoration(
                          color: markerColor,
                          shape: BoxShape.circle,
                          boxShadow: [
                            BoxShadow(
                              color: Colors.black.withOpacity(0.3),
                              blurRadius: 6,
                              offset: Offset(0, 3),
                            ),
                          ],
                        ),
                        child: Icon(
                          vehicle.ignitionOn ? Icons.inventory_2 : Icons.location_on,
                          color: Colors.white,
                          size: 28,
                        ),
                      ),
                    ],
                  ),
                ),
              ),
            );
          }
        } else {
          print('⚠️ MapScreen: Vehicle ${vehicle.description} has no valid location');
        }
      }
      
      if (!mounted) return;
      
      print('🗺️ MapScreen: Setting markers on map');
      setState(() {
        _googleMarkers = newGoogleMarkers;
        _appleAnnotations = newAppleAnnotations;
        _flutterMapMarkers = newFlutterMapMarkers;
        _isLoading = false;
      });
      
      // Filter positions to only include UK coordinates
      // UK bounds: Latitude 49.5 to 61.0, Longitude -8.5 to 2.0
      final ukPositions = positions.where((pos) {
        return pos.latitude >= 49.5 && pos.latitude <= 61.0 &&
               pos.longitude >= -8.5 && pos.longitude <= 2.0;
      }).toList();
      
      print('📐 MapScreen: Filtered ${ukPositions.length} UK vehicles from ${positions.length} total');
      
      // Auto-fit map to show UK markers only
      if (ukPositions.isNotEmpty) {
        print('📐 MapScreen: Auto-fitting map to ${ukPositions.length} UK vehicle(s)');
        
        // Mark as no longer first load
        _isFirstLoad = false;
        
        // Wait for next frame to ensure map is ready, then add a small delay for map initialization
        WidgetsBinding.instance.addPostFrameCallback((_) async {
          if (!mounted) return;
          
          // Small delay to ensure map controllers are fully initialized
          await Future.delayed(Duration(milliseconds: 500));
          if (!mounted) return;
          
          try {
            if (_useAppleMaps && _appleMapController != null) {
              // Apple Maps: animate to region
              if (ukPositions.length == 1) {
                await _appleMapController!.animateCamera(
                  apple.CameraUpdate.newLatLngZoom(
                    apple.LatLng(ukPositions[0].latitude, ukPositions[0].longitude),
                    15.0,
                  ),
                );
              } else {
                // Calculate bounds for multiple positions
                double minLat = ukPositions.map((p) => p.latitude).reduce((a, b) => a < b ? a : b);
                double maxLat = ukPositions.map((p) => p.latitude).reduce((a, b) => a > b ? a : b);
                double minLng = ukPositions.map((p) => p.longitude).reduce((a, b) => a < b ? a : b);
                double maxLng = ukPositions.map((p) => p.longitude).reduce((a, b) => a > b ? a : b);
                
                final bounds = apple.LatLngBounds(
                  southwest: apple.LatLng(minLat, minLng),
                  northeast: apple.LatLng(maxLat, maxLng),
                );
                
                await _appleMapController!.animateCamera(
                  apple.CameraUpdate.newLatLngBounds(bounds, 80),
                );
              }
              print('📍 MapScreen: Fitted Apple Map to show ${ukPositions.length} UK vehicles');
            } else if (_useGoogleMaps && _googleMapController != null) {
              // Google Maps: animate to bounds
              final controller = await _googleMapController!.future;
              
              if (ukPositions.length == 1) {
                await controller.animateCamera(
                  gmaps.CameraUpdate.newLatLngZoom(ukPositions[0], 15.0),
                );
              } else {
                // Calculate bounds for multiple positions
                double minLat = ukPositions.map((p) => p.latitude).reduce((a, b) => a < b ? a : b);
                double maxLat = ukPositions.map((p) => p.latitude).reduce((a, b) => a > b ? a : b);
                double minLng = ukPositions.map((p) => p.longitude).reduce((a, b) => a < b ? a : b);
                double maxLng = ukPositions.map((p) => p.longitude).reduce((a, b) => a > b ? a : b);
                
                final bounds = gmaps.LatLngBounds(
                  southwest: gmaps.LatLng(minLat, minLng),
                  northeast: gmaps.LatLng(maxLat, maxLng),
                );
                
                await controller.animateCamera(
                  gmaps.CameraUpdate.newLatLngBounds(bounds, 80),
                );
              }
              print('📍 MapScreen: Fitted Google Map to show ${ukPositions.length} UK vehicles');
            } else if (_useFlutterMap) {
            // Flutter Map (Web): fit bounds
            if (ukPositions.length == 1) {
              _flutterMapController.move(
                latlong.LatLng(ukPositions[0].latitude, ukPositions[0].longitude),
                15.0,
              );
            } else {
              // Calculate bounds for multiple positions
              double minLat = ukPositions.map((p) => p.latitude).reduce((a, b) => a < b ? a : b);
              double maxLat = ukPositions.map((p) => p.latitude).reduce((a, b) => a > b ? a : b);
              double minLng = ukPositions.map((p) => p.longitude).reduce((a, b) => a < b ? a : b);
              double maxLng = ukPositions.map((p) => p.longitude).reduce((a, b) => a > b ? a : b);
              
              final bounds = fmap.LatLngBounds(
                latlong.LatLng(minLat, minLng),
                latlong.LatLng(maxLat, maxLng),
              );
              
              _flutterMapController.fitCamera(
                fmap.CameraFit.bounds(
                  bounds: bounds,
                  padding: EdgeInsets.all(80),
                ),
              );
            }
            print('📍 MapScreen: Fitted Flutter Map to show ${ukPositions.length} UK vehicles');
          }
          } catch (e) {
            print('⚠️ MapScreen: Error auto-fitting map: $e');
            _logger.error('Auto-fit failed: $e');
            // Continue anyway - map will show with initial zoom
          }
        });
      }
      
      print('✅ MapScreen: Vehicle loading complete - ${_flutterMapMarkers.length} markers displayed');
      _logger.success('_loadTags: Vehicle loading complete - ${_vehicles.length} vehicles loaded');
    } catch (e, stackTrace) {
      _logger.error('_loadTags: Error loading vehicles: $e');
      _logger.debug('Stack trace: $stackTrace');
      print('❌ MapScreen: Error loading vehicles: $e');
      print('❌ Stack trace: $stackTrace');
      
      // Check if this is a deployment error (HTML response, syntax error, etc.)
      if (DeploymentMonitorService.isDeploymentError(e)) {
        print('🔄 Detected deployment in progress...');
        _deploymentMonitor.detectDeploymentInProgress();
        
        // Listen for deployment completion and retry
        _deploymentMonitor.deploymentStateChanged.where((isDeploying) => !isDeploying).listen((_) {
          if (mounted) {
            print('✅ Deployment complete, reloading vehicles...');
            _loadTags();
          }
        });
        
        if (mounted) {
          setState(() => _isLoading = false);
        }
        return;
      }
      
      // Check if it's a session expiration error
      final errorMessage = e.toString();
      final isSessionExpired = errorMessage.contains('Session expired') || 
                               errorMessage.contains('No authentication token') ||
                               errorMessage.contains('Authentication failed');
      
      if (mounted) {
        setState(() => _isLoading = false);
        
        if (isSessionExpired) {
          // Session expired - redirect to login immediately
          print('🔐 Session expired - redirecting to login...');
          ScaffoldMessenger.of(context).showSnackBar(
            SnackBar(
              content: Text('Your session has expired. Please login again.'),
              backgroundColor: Colors.orange,
              duration: Duration(seconds: 2),
            ),
          );
          
          // Navigate to login immediately
          Navigator.pushNamedAndRemoveUntil(
            context,
            '/welcome',
            (route) => false,
          );
        } else {
          // Other errors (e.g. network, no vehicles yet) — log only, no UI error shown
          print('⚠️ Failed to load vehicles (silent): ${e.toString()}');
        }
      }
    }
  }

  Future<void> _loadUnreadAlertCount() async {
    try {
      final response = await _poiService.getAlerts(limit: 1, offset: 0);
      if (mounted) {
        setState(() {
          _unreadAlertCount = response.unreadCount;
        });
      }
    } catch (e) {
      _logger.error('Failed to load unread alert count: $e');
    }
  }

  Future<void> _navigateToAlerts() async {
    await Navigator.push(
      context,
      MaterialPageRoute(builder: (context) => const AlertsScreen()),
    );
    // Refresh alert count when returning
    _loadUnreadAlertCount();
  }

  Future<void> _loadPOIs() async {
    try {
      final pois = await _poiService.getPOIs();
      print('📍 Loaded ${pois.length} POIs');
      if (mounted) {
        setState(() {
          _pois = pois;
          _updateGeofenceCircles();
        });
      }
    } catch (e) {
      _logger.error('Failed to load POIs: $e');
    }
  }

  void _updateGeofenceCircles() {
    print('🔵 Updating geofence circles... _showPOIs: $_showPOIs, _pois.length: ${_pois.length}');
    
    if (!_showPOIs) {
      _geofenceCircles = [];
      print('🔵 Circles hidden (showPOIs is false)');
      return;
    }

    _geofenceCircles = [];
    
    for (var poi in _pois) {
      // Add origin circle (blue for single POI, blue for route origin)
      _geofenceCircles.add(
        fmap.CircleMarker(
          point: latlong.LatLng(poi.latitude, poi.longitude),
          radius: poi.radius,
          useRadiusInMeter: true,
          color: poi.isActive 
              ? (poi.isRoute ? Colors.blue.withOpacity(0.15) : Colors.blue.withOpacity(0.15))
              : Colors.grey.withOpacity(0.10),
          borderStrokeWidth: 2,
          borderColor: poi.isActive 
              ? (poi.isRoute ? Colors.blue.withOpacity(0.5) : Colors.blue.withOpacity(0.5))
              : Colors.grey.withOpacity(0.3),
        ),
      );
      
      // Add destination circle for routes (green)
      if (poi.isRoute && poi.hasDestination) {
        _geofenceCircles.add(
          fmap.CircleMarker(
            point: latlong.LatLng(poi.destinationLatitude!, poi.destinationLongitude!),
            radius: poi.destinationRadius ?? 150.0,
            useRadiusInMeter: true,
            color: poi.isActive ? Colors.green.withOpacity(0.15) : Colors.grey.withOpacity(0.10),
            borderStrokeWidth: 2,
            borderColor: poi.isActive ? Colors.green.withOpacity(0.5) : Colors.grey.withOpacity(0.3),
          ),
        );
      }
    }
    
    print('🔵 Created ${_geofenceCircles.length} geofence circles');
  }

  Future<void> _showCreatePOIDialog({double? latitude, double? longitude, String? address}) async {
    final nameController = TextEditingController();
    final descriptionController = TextEditingController();
    final originPostcodeController = TextEditingController();
    final destinationPostcodeController = TextEditingController();
    final originRadiusController = TextEditingController(text: '150');
    final destinationRadiusController = TextEditingController(text: '150');
    
    POIType poiType = POIType.single;
    
    // Origin location
    double? originLat = latitude;
    double? originLng = longitude;
    String? originAddress = address;
    bool isSearchingOrigin = false;
    
    // Destination location
    double? destLat;
    double? destLng;
    String? destAddress;
    bool isSearchingDest = false;
    
    bool hasName = false;
    
    // Tracker selection
    String? selectedTrackerId;
    List<dynamic> availableTags = [];
    bool showImei = false; // Toggle to show IMEI instead of description
    
    // Load available tags/trackers AND ensure custom names are fresh
    try {
      final results = await Future.wait([
        _authService.getBLETags(),
        _authService.getAllCustomVehicleNames(),
      ]);
      availableTags = results[0] as List<dynamic>;
      final freshCustomNames = results[1] as Map<String, String>;
      if (mounted) {
        setState(() {
          _vehicleCustomNames = freshCustomNames;
        });
      }
      if (availableTags.isNotEmpty) {
        selectedTrackerId = availableTags[0]['id']?.toString() ?? availableTags[0]['imei']?.toString();
      }
    } catch (e) {
      print('Failed to load tags: $e');
    }

    await showDialog(
      context: context,
      builder: (context) => StatefulBuilder(
        builder: (context, setDialogState) {
          // Add listener to name controller if not already added
          if (!nameController.hasListeners) {
            nameController.addListener(() {
              setDialogState(() {
                hasName = nameController.text.isNotEmpty;
              });
            });
          }
          
          bool canCreate = hasName && originLat != null && originLng != null && selectedTrackerId != null;
          if (poiType == POIType.route) {
            canCreate = canCreate && destLat != null && destLng != null;
          }
          
          return AlertDialog(
          title: Text('Create Location'),
          content: SingleChildScrollView(
            child: Column(
              mainAxisSize: MainAxisSize.min,
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                TextField(
                  controller: nameController,
                  decoration: InputDecoration(
                    labelText: 'Name *',
                    hintText: 'e.g., Home Delivery, Office Route',
                  ),
                ),
                SizedBox(height: 12),
                TextField(
                  controller: descriptionController,
                  decoration: InputDecoration(
                    labelText: 'Description',
                    hintText: 'Optional description',
                  ),
                  maxLines: 2,
                ),
                SizedBox(height: 16),
                Divider(),
                SizedBox(height: 8),
                
                // Type selector
                Text('Type', style: TextStyle(fontWeight: FontWeight.bold)),
                SizedBox(height: 8),
                Row(
                  children: [
                    Expanded(
                      child: ChoiceChip(
                        label: Text('Single Location'),
                        selected: poiType == POIType.single,
                        onSelected: (selected) {
                          if (selected) {
                            setDialogState(() => poiType = POIType.single);
                          }
                        },
                      ),
                    ),
                    SizedBox(width: 8),
                    Expanded(
                      child: ChoiceChip(
                        label: Text('From | To'),
                        selected: poiType == POIType.route,
                        onSelected: (selected) {
                          if (selected) {
                            setDialogState(() => poiType = POIType.route);
                          }
                        },
                      ),
                    ),
                  ],
                ),
                SizedBox(height: 16),
                Divider(),
                SizedBox(height: 8),
                
                // Tracker selection
                Text('📡 Selected Tracker *', style: TextStyle(fontWeight: FontWeight.bold)),
                SizedBox(height: 8),
                // IMEI display toggle
                Row(
                  children: [
                    Checkbox(
                      value: showImei,
                      onChanged: (value) {
                        setDialogState(() {
                          showImei = value ?? false;
                        });
                      },
                    ),
                    Text('Display IMEI', style: TextStyle(fontSize: 13)),
                  ],
                ),
                SizedBox(height: 8),
                if (availableTags.isEmpty)
                  Container(
                    padding: EdgeInsets.all(12),
                    decoration: BoxDecoration(
                      color: Colors.orange.withOpacity(0.1),
                      borderRadius: BorderRadius.circular(8),
                      border: Border.all(color: Colors.orange.withOpacity(0.3)),
                    ),
                    child: Text(
                      '⚠️ No trackers found. Add a tracker first.',
                      style: TextStyle(color: Colors.orange[800], fontSize: 13),
                    ),
                  )
                else
                  Container(
                    padding: EdgeInsets.symmetric(horizontal: 12, vertical: 4),
                    decoration: BoxDecoration(
                      border: Border.all(color: Colors.grey[400]!),
                      borderRadius: BorderRadius.circular(8),
                    ),
                    child: DropdownButton<String>(
                      isExpanded: true,
                      underline: SizedBox.shrink(),
                      value: selectedTrackerId,
                      hint: Text('Select tracker to monitor'),
                      items: availableTags.map((tag) {
                        final tagId = tag['id']?.toString() ?? tag['imei']?.toString();
                        final description = tag['description'];
                        final deviceName = tag['device_name'];
                        final imei = tag['imei'];
                        final customName = tagId != null ? _vehicleCustomNames[tagId] : null;
                        // Show IMEI when toggle is on, otherwise prioritize custom name > description > device_name > IMEI
                        final displayName = showImei 
                          ? (imei ?? 'Unknown Tracker')
                          : (customName ?? description ?? deviceName ?? imei ?? 'Unknown Tracker');
                        return DropdownMenuItem<String>(
                          value: tagId,
                          child: Text(displayName),
                        );
                      }).toList(),
                      onChanged: (value) {
                        setDialogState(() {
                          selectedTrackerId = value;
                        });
                      },
                    ),
                  ),
                SizedBox(height: 12),
                Text(
                  'This location will only trigger alerts for the selected tracker',
                  style: TextStyle(fontSize: 12, color: Colors.grey[600], fontStyle: FontStyle.italic),
                ),
                SizedBox(height: 16),
                Divider(),
                SizedBox(height: 8),
                
                // Origin/START location
                Text(
                  poiType == POIType.route ? '📍 START (Origin)' : '📍 Location', 
                  style: TextStyle(fontWeight: FontWeight.bold)
                ),
                SizedBox(height: 8),
                if (originLat != null && originLng != null) ...[
                  Text('${originAddress ?? "${originLat?.toStringAsFixed(4)}, ${originLng?.toStringAsFixed(4)}"}'),
                  SizedBox(height: 8),
                ],
                Row(
                  children: [
                    Expanded(
                      child: TextField(
                        controller: originPostcodeController,
                        decoration: InputDecoration(
                          labelText: 'Postcode',
                          hintText: 'Enter full postcode',
                          isDense: true,
                        ),
                      ),
                    ),
                    SizedBox(width: 8),
                    ElevatedButton(
                      onPressed: isSearchingOrigin ? null : () async {
                        if (originPostcodeController.text.isEmpty) return;
                        
                        setDialogState(() => isSearchingOrigin = true);
                        try {
                          final result = await _poiService.searchPostcode(originPostcodeController.text);
                          setDialogState(() {
                            originLat = result.latitude;
                            originLng = result.longitude;
                            originAddress = result.address;
                            isSearchingOrigin = false;
                          });
                        } catch (e) {
                          setDialogState(() => isSearchingOrigin = false);
                          ScaffoldMessenger.of(context).showSnackBar(
                            SnackBar(content: Text('Postcode not found: $e')),
                          );
                        }
                      },
                      child: isSearchingOrigin 
                          ? SizedBox(width: 16, height: 16, child: CircularProgressIndicator(strokeWidth: 2))
                          : Text('Search'),
                    ),
                  ],
                ),
                SizedBox(height: 8),
                TextField(
                  controller: originRadiusController,
                  keyboardType: TextInputType.number,
                  decoration: InputDecoration(
                    labelText: 'Radius (meters)',
                    isDense: true,
                  ),
                ),
                
                // Destination/TO location (only for routes)
                if (poiType == POIType.route) ...[
                  SizedBox(height: 16),
                  Divider(),
                  SizedBox(height: 8),
                  Text('📍 END (Destination)', style: TextStyle(fontWeight: FontWeight.bold)),
                  SizedBox(height: 8),
                  if (destLat != null && destLng != null) ...[
                    Text('${destAddress ?? "${destLat?.toStringAsFixed(4)}, ${destLng?.toStringAsFixed(4)}"}'),
                    SizedBox(height: 8),
                  ],
                  Row(
                    children: [
                      Expanded(
                        child: TextField(
                          controller: destinationPostcodeController,
                          decoration: InputDecoration(
                            labelText: 'Postcode',
                            hintText: 'Enter full postcode',
                            isDense: true,
                          ),
                        ),
                      ),
                      SizedBox(width: 8),
                      ElevatedButton(
                        onPressed: isSearchingDest ? null : () async {
                          if (destinationPostcodeController.text.isEmpty) return;
                          
                          setDialogState(() => isSearchingDest = true);
                          try {
                            final result = await _poiService.searchPostcode(destinationPostcodeController.text);
                            setDialogState(() {
                              destLat = result.latitude;
                              destLng = result.longitude;
                              destAddress = result.address;
                              isSearchingDest = false;
                            });
                          } catch (e) {
                            setDialogState(() => isSearchingDest = false);
                            ScaffoldMessenger.of(context).showSnackBar(
                              SnackBar(content: Text('Postcode not found: $e')),
                            );
                          }
                        },
                        child: isSearchingDest 
                            ? SizedBox(width: 16, height: 16, child: CircularProgressIndicator(strokeWidth: 2))
                            : Text('Search'),
                      ),
                    ],
                  ),
                  SizedBox(height: 8),
                  TextField(
                    controller: destinationRadiusController,
                    keyboardType: TextInputType.number,
                    decoration: InputDecoration(
                      labelText: 'Radius (meters)',
                      isDense: true,
                    ),
                  ),
                ],
              ],
            ),
          ),
          actions: [
            TextButton(
              onPressed: () => Navigator.pop(context),
              child: Text('Cancel'),
            ),
            ElevatedButton(
              onPressed: !canCreate
                  ? null
                  : () async {
                      try {
                        final request = POICreateRequest(
                          name: nameController.text,
                          description: descriptionController.text.isEmpty ? null : descriptionController.text,
                          poiType: poiType,
                          latitude: originLat!,
                          longitude: originLng!,
                          radius: double.tryParse(originRadiusController.text) ?? 150.0,
                          address: originAddress,
                          destinationLatitude: destLat,
                          destinationLongitude: destLng,
                          destinationRadius: poiType == POIType.route 
                              ? (double.tryParse(destinationRadiusController.text) ?? 150.0)
                              : null,
                          destinationAddress: destAddress,
                        );
                        
                        // Create the POI
                        final createdPOI = await _poiService.createPOI(request);
                        
                        // Automatically ARM the POI to the selected tracker
                        if (selectedTrackerId != null) {
                          await _poiService.armPOI(createdPOI.id, selectedTrackerId!);
                        }
                        
                        Navigator.pop(context);
                        
                        // Get tracker name for success message
                        final selectedTag = availableTags.firstWhere(
                          (tag) => (tag['id']?.toString() ?? tag['imei']?.toString()) == selectedTrackerId,
                          orElse: () => {'device_name': 'Unknown'},
                        );
                        final trackerName = selectedTag['device_name'] ?? selectedTag['imei'] ?? 'tracker';
                        
                        ScaffoldMessenger.of(context).showSnackBar(
                          SnackBar(
                            content: Text('✅ ${poiType == POIType.route ? "Start/End location" : "Location"} created and armed to $trackerName'),
                            duration: Duration(seconds: 3),
                          ),
                        );
                        
                        _loadPOIs(); // Reload POIs
                      } catch (e) {
                        ScaffoldMessenger.of(context).showSnackBar(
                          SnackBar(content: Text('Failed to create: $e')),
                        );
                      }
                    },
              style: ElevatedButton.styleFrom(
                backgroundColor: AppTheme.brandPrimary,
                foregroundColor: Colors.white,
              ),
              child: Text('Create'),
            ),
          ],
        );
        },
      ),
    );
  }

  Future<void> _exportLogs() async {
    _logger.info('User initiated problem report from MapScreen');
    
    try {
      // Show loading indicator
      if (!mounted) return;
      ScaffoldMessenger.of(context).showSnackBar(
        const SnackBar(
          content: Text('📝 Preparing debug logs...'),
          duration: Duration(seconds: 2),
        ),
      );

      // Export logs to file
      final file = await _logger.exportLogsToFile();
      
      // Share the file via email, WhatsApp, etc.
      final result = await Share.shareXFiles(
        [XFile(file.path)],
        subject: 'BLE Tracker - Problem Report',
        text: '''Hi Support Team,

I'm experiencing an issue with the BLE Tracker app. Debug logs are attached.

Issue Description:
[Please describe your issue here]

Device: ${defaultTargetPlatform.toString()}
Timestamp: ${DateTime.now()}

Best regards''',
      );

      if (result.status == ShareResultStatus.success) {
        _logger.success('Logs shared successfully');
        if (mounted) {
          ScaffoldMessenger.of(context).showSnackBar(
            const SnackBar(
              content: Text('✅ Logs exported successfully!'),
              backgroundColor: Colors.green,
              duration: Duration(seconds: 2),
            ),
          );
        }
      }
    } catch (e) {
      _logger.error('Failed to export logs', e);
      if (mounted) {
        ScaffoldMessenger.of(context).showSnackBar(
          SnackBar(
            content: Text('❌ Failed to export logs: ${e.toString()}'),
            backgroundColor: Colors.red,
            duration: const Duration(seconds: 5),
          ),
        );
      }
    }
  }
  
  void _showVehicleDetails(Vehicle vehicle) {
    setState(() {
      _selectedVehicle = vehicle;
    });
  }

  /// Share vehicle location via Share dialog
  void _shareVehicleLocation(Vehicle vehicle) async {
    final location = vehicle.lastKnownPosition;
    if (location == null) {
      ScaffoldMessenger.of(context).showSnackBar(
        SnackBar(
          content: Text('No location available to share'),
          backgroundColor: Colors.orange,
        ),
      );
      return;
    }

    final vehicleName = _vehicleCustomNames[vehicle.id] ??
        vehicle.description ??
        vehicle.registration ??
        'Unknown Asset';

    final lat = location.latitude;
    final lng = location.longitude;

    String mapsUrl;
    String mapProvider;

    if (!kIsWeb && defaultTargetPlatform == TargetPlatform.iOS) {
      mapsUrl = 'https://maps.apple.com/?q=$lat,$lng';
      mapProvider = 'Apple Maps';
    } else {
      mapsUrl = 'https://www.google.com/maps?q=$lat,$lng';
      mapProvider = 'Google Maps';
    }

    final shareText = '''$vehicleName
Location: $mapsUrl

View on $mapProvider to see the vehicle location.''';

    await Share.share(shareText, subject: 'Location of $vehicleName');
  }

  void _hideVehicleDetails() {
    setState(() {
      _selectedVehicle = null;
    });
  }

  // Map control methods
  void _zoomIn() {
    final currentZoom = _flutterMapController.camera.zoom;
    _flutterMapController.move(
      _flutterMapController.camera.center,
      currentZoom + 1,
    );
  }

  void _zoomOut() {
    final currentZoom = _flutterMapController.camera.zoom;
    _flutterMapController.move(
      _flutterMapController.camera.center,
      currentZoom - 1,
    );
  }

  void _panMap(double latDelta, double lngDelta) {
    final center = _flutterMapController.camera.center;
    _flutterMapController.move(
      latlong.LatLng(center.latitude + latDelta, center.longitude + lngDelta),
      _flutterMapController.camera.zoom,
    );
  }

  void _resetMapView() {
    // Reset to London, UK at street level
    _flutterMapController.move(
      latlong.LatLng(51.5074, -0.1278),
      15.0, // Street-level zoom
    );
  }

  // Keep the old method for reference but not used
  void _showVehicleDetailsOld(Vehicle vehicle) {
    final location = vehicle.lastKnownPosition;
    showModalBottomSheet(
      context: context,
      backgroundColor: Colors.transparent,
      builder: (context) => Container(
        decoration: BoxDecoration(
          color: Colors.white,
          borderRadius: BorderRadius.vertical(top: Radius.circular(20)),
        ),
        padding: EdgeInsets.all(24),
        child: Column(
          mainAxisSize: MainAxisSize.min,
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Row(
              children: [
                Container(
                  width: 48,
                  height: 48,
                  decoration: BoxDecoration(
                    color: vehicle.ignitionOn 
                        ? Colors.green.withOpacity(0.1)
                        : Colors.red.withOpacity(0.1),
                    borderRadius: BorderRadius.circular(12),
                  ),
                  child: Icon(
                    vehicle.ignitionOn ? Icons.inventory_2 : Icons.location_on,
                    color: vehicle.ignitionOn ? Colors.green : Colors.red,
                    size: 28,
                  ),
                ),
                SizedBox(width: 16),
                Expanded(
                  child: Column(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      Text(
                        _vehicleCustomNames[vehicle.id] ?? vehicle.description,
                        style: GoogleFonts.poppins(
                          fontSize: 18,
                          fontWeight: FontWeight.w600,
                        ),
                      ),
                      Text(
                        'Registration: ${vehicle.registration ?? 'N/A'}',

                        style: GoogleFonts.inter(
                          fontSize: 12,
                          color: Colors.grey[600],
                        ),
                      ),
                    ],
                  ),
                ),
              ],
            ),
            SizedBox(height: 24),
            _buildInfoRow(
              icon: vehicle.ignitionOn ? Icons.power : Icons.power_off,
              label: 'Status',
              value: vehicle.ignitionOn ? 'Running' : 'Stopped',
            ),
            if (location != null) ...[
              SizedBox(height: 12),
              _buildInfoRow(
                icon: Icons.gps_fixed,
                label: 'Location',
                value: '${location.latitude.toStringAsFixed(6)}, ${location.longitude.toStringAsFixed(6)}',
              ),
              SizedBox(height: 12),
              _buildInfoRow(
                icon: Icons.access_time,
                label: 'Last Updated',
                value: location.timestampFormatted,
              ),
              if (location.speed != null)
                Padding(
                  padding: EdgeInsets.only(top: 12),
                  child: _buildInfoRow(
                    icon: Icons.speed,
                    label: 'Speed',
                    value: '${location.speed!.toStringAsFixed(1)} km/h',
                  ),
                ),
              if (location.isStale)
                Padding(
                  padding: EdgeInsets.only(top: 16),
                  child: Container(
                    padding: EdgeInsets.all(12),
                    decoration: BoxDecoration(
                      color: Colors.orange.withOpacity(0.1),
                      borderRadius: BorderRadius.circular(8),
                    ),
                    child: Row(
                      children: [
                        Icon(Icons.warning, color: Colors.orange, size: 20),
                        SizedBox(width: 8),
                        Expanded(
                          child: Text(
                            'Location data is more than 24 hours old',
                            style: GoogleFonts.inter(
                              fontSize: 12,
                              color: Colors.orange[800],
                            ),
                          ),
                        ),
                      ],
                    ),
                  ),
                ),
            ],
          ],
        ),
      ),
    );
  }

  Widget _buildVehiclePopup(Vehicle vehicle) {
    final location = vehicle.lastKnownPosition;
    return Container(
      margin: EdgeInsets.all(8),
      constraints: BoxConstraints(maxWidth: 260, maxHeight: 220),
      decoration: BoxDecoration(
        color: Colors.white,
        borderRadius: BorderRadius.circular(12),
        boxShadow: [
          BoxShadow(
            color: Colors.black.withOpacity(0.15),
            blurRadius: 12,
            offset: Offset(0, 2),
          ),
        ],
      ),
      child: Column(
        mainAxisSize: MainAxisSize.min,
        children: [
          // Header with close button
          Container(
            padding: EdgeInsets.symmetric(horizontal: 10, vertical: 6),
            decoration: BoxDecoration(
              color: AppTheme.brandPrimary.withOpacity(0.08),
              borderRadius: BorderRadius.vertical(top: Radius.circular(12)),
            ),
            child: Row(
              children: [
                Container(
                  width: 28,
                  height: 28,
                  decoration: BoxDecoration(
                    color: AppTheme.brandPrimary,
                    borderRadius: BorderRadius.circular(6),
                  ),
                  child: Icon(
                    Icons.location_on,
                    color: Colors.white,
                    size: 16,
                  ),
                ),
                SizedBox(width: 8),
                Expanded(
                  child: Text(
                    _vehicleCustomNames[vehicle.id] ?? vehicle.description,
                    style: GoogleFonts.poppins(
                      fontSize: 13,
                      fontWeight: FontWeight.w600,
                    ),
                    overflow: TextOverflow.ellipsis,
                  ),
                ),
                SizedBox(width: 2),
                GestureDetector(
                  onTap: _hideVehicleDetails,
                  child: Icon(Icons.close, size: 18, color: Colors.grey.shade600),
                ),
              ],
            ),
          ),
          // Content - Scrollable
          Expanded(
            child: SingleChildScrollView(
              child: Container(
                padding: EdgeInsets.all(8),
                child: Column(
                  mainAxisSize: MainAxisSize.min,
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    if (location != null) ...[
                      if (location.locationDescription != null && location.locationDescription!.isNotEmpty)
                        _buildCompactInfoRow(
                          icon: Icons.place,
                          value: location.locationDescription!,
                        )
                      else
                        _buildCompactInfoRow(
                          icon: Icons.gps_fixed,
                          value: '${location.latitude.toStringAsFixed(4)}, ${location.longitude.toStringAsFixed(4)}',
                        ),
                      SizedBox(height: 6),
                      _buildCompactInfoRow(
                        icon: Icons.access_time,
                        value: location.timestampFormatted,
                      ),
                      if (location.speed != null)
                        Padding(
                          padding: EdgeInsets.only(top: 6),
                          child: _buildCompactInfoRow(
                            icon: Icons.speed,
                            value: '${location.speed!.toStringAsFixed(1)} km/h',
                          ),
                        ),
                    ],
                    if (vehicle.batteryLevel != null)
                      Padding(
                        padding: EdgeInsets.only(top: 6),
                        child: _buildBatteryInfoRow(vehicle.batteryLevel!),
                      ),
                  ],
                ),
              ),
            ),
          ),
          // Action buttons - Fixed at bottom
          Container(
            padding: EdgeInsets.symmetric(horizontal: 6, vertical: 6),
            decoration: BoxDecoration(
              border: Border(top: BorderSide(color: Colors.grey.shade200)),
            ),
            child: Row(
              children: [
                // View Attributes button (eye icon - if attributes exist)
                if ((vehicle.visibleAttributes ?? {}).isNotEmpty)
                  Expanded(
                    child: Container(
                      height: 32,
                      child: OutlinedButton.icon(
                        onPressed: () {
                          _hideVehicleDetails();
                          _showAttributesBottomSheet(vehicle);
                        },
                        icon: Icon(Icons.remove_red_eye, size: 13),
                        label: Text('View', style: GoogleFonts.inter(fontSize: 10, fontWeight: FontWeight.w500)),
                        style: OutlinedButton.styleFrom(
                          padding: EdgeInsets.symmetric(horizontal: 6),
                        ),
                      ),
                    ),
                  ),
                if ((vehicle.visibleAttributes ?? {}).isNotEmpty) SizedBox(width: 4),
                Expanded(
                  child: Container(
                    height: 32,
                    child: OutlinedButton.icon(
                      onPressed: () {
                        _hideVehicleDetails();
                        _shareVehicleLocation(vehicle);
                      },
                      icon: Icon(Icons.share, size: 13),
                      label: Text('Share', style: GoogleFonts.inter(fontSize: 10, fontWeight: FontWeight.w500)),
                      style: OutlinedButton.styleFrom(
                        padding: EdgeInsets.symmetric(horizontal: 6),
                      ),
                    ),
                  ),
                ),
              ],
            ),
          ),
        ],
      ),
    );
  }

  /// Battery row with colour-coded icon (green/orange/red)
  Widget _buildBatteryInfoRow(int battery) {
    final Color color;
    final IconData icon;
    if (battery > 60) {
      color = Colors.green.shade600;
      icon = Icons.battery_full;
    } else if (battery > 20) {
      color = Colors.orange.shade700;
      icon = Icons.battery_4_bar;
    } else {
      color = Colors.red.shade600;
      icon = Icons.battery_alert;
    }
    return Row(
      crossAxisAlignment: CrossAxisAlignment.center,
      children: [
        Icon(icon, size: 16, color: color),
        SizedBox(width: 8),
        Text(
          'Battery: $battery%',
          style: GoogleFonts.inter(
            fontSize: 11,
            fontWeight: FontWeight.w600,
            color: color,
          ),
        ),
      ],
    );
  }

  /// Compact info row for vehicle popup - shows icon and value only
  Widget _buildCompactInfoRow({
    required IconData icon,
    required String value,
  }) {
    return Row(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        Icon(icon, size: 16, color: Colors.grey.shade600),
        SizedBox(width: 8),
        Expanded(
          child: Text(
            value,
            style: GoogleFonts.inter(
              fontSize: 11,
              fontWeight: FontWeight.w500,
              color: Colors.grey.shade800,
            ),
            overflow: TextOverflow.ellipsis,
            maxLines: 2,
          ),
        ),
      ],
    );
  }

  /// Standard info row for different contexts - shows icon, label, and value
  Widget _buildInfoRow({
    required IconData icon,
    required String label,
    required String value,
  }) {
    return Row(
      children: [
        Icon(icon, size: 20, color: Colors.grey[600]),
        SizedBox(width: 12),
        Expanded(
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Text(
                label,
                style: GoogleFonts.inter(
                  fontSize: 12,
                  color: Colors.grey[600],
                ),
              ),
              Text(
                value,
                style: GoogleFonts.inter(
                  fontSize: 14,
                  fontWeight: FontWeight.w500,
                ),
                overflow: TextOverflow.ellipsis,
                maxLines: 2,
              ),
            ],
          ),
        ),
      ],
    );
  }

  void _focusOnAsset(Vehicle vehicle) {
    if (!vehicle.hasLocation) return;

    // Switch to map view
    setState(() {
      _selectedIndex = 0;
    });

    // Focus on the asset on the map
    final position = gmaps.LatLng(
      vehicle.lastKnownPosition!.latitude,
      vehicle.lastKnownPosition!.longitude,
    );
    
    // Move map to vehicle location (platform-specific)
    if (_useAppleMaps && _appleMapController != null) {
      _appleMapController!.animateCamera(
        apple.CameraUpdate.newLatLng(apple.LatLng(position.latitude, position.longitude)),
      );
    } else if (_useGoogleMaps && _googleMapController != null) {
      _googleMapController!.future.then((controller) {
        controller.animateCamera(gmaps.CameraUpdate.newLatLngZoom(position, 15.0));
      });
    } else if (_useFlutterMap) {
      _flutterMapController.move(
        latlong.LatLng(position.latitude, position.longitude),
        15.0,
      );
    }
    
    // Show vehicle details after a short delay
    Future.delayed(const Duration(milliseconds: 500), () {
      if (mounted) {
        _showVehicleDetails(vehicle);
      }
    });
  }
  @override
  Widget build(BuildContext context) {
    return Scaffold(
      body: Stack(
        children: [
         // Keep all views in the widget tree but hide inactive ones to preserve state
          Offstage(
            offstage: _selectedIndex != 0,
            child: _buildMapView(),
          ),
          Offstage(
            offstage: _selectedIndex != 1,
            child: _buildJourneysView(),
          ),
          Offstage(
            offstage: _selectedIndex != 2,
            child: _buildAssetsView(),
          ),
          Offstage(
            offstage: _selectedIndex != 3,
            child: const ScanScreen(),
          ),
          Offstage(
            offstage: _selectedIndex != 4,
            child: _buildSettingsView(),
          ),
          Offstage(
            offstage: _selectedIndex != 5,
            child: const SolutionsScreen(),
          ),
          
          // Top Navigation Bar
          Positioned(
            top: 0,
            left: 0,
            right: 0,
            child: SafeArea(
              child: Container(
                decoration: BoxDecoration(
                  gradient: LinearGradient(
                    colors: [AppTheme.brandPrimary, Color(0xFF007A00)],
                  ),
                  boxShadow: [
                    BoxShadow(
                      color: Colors.black.withOpacity(0.2),
                      blurRadius: 8,
                    ),
                  ],
                ),
                child: Padding(
                  padding: EdgeInsets.symmetric(horizontal: 16, vertical: 12),
                  child: Row(
                    children: [
                      Image.asset(
                        'assets/FullLogowhite.png',
                        height: 36,
                        fit: BoxFit.contain,
                      ),
                      Spacer(),
                      // Alerts button with badge
                      Stack(
                        children: [
                          IconButton(
                            icon: Icon(Icons.notifications_outlined, color: Colors.white, size: 28),
                            onPressed: _navigateToAlerts,
                          ),
                          if (_unreadAlertCount > 0)
                            Positioned(
                              right: 8,
                              top: 8,
                              child: IgnorePointer(
                                child: Container(
                                  padding: EdgeInsets.all(4),
                                  decoration: BoxDecoration(
                                    color: Colors.red,
                                    shape: BoxShape.circle,
                                  ),
                                  constraints: BoxConstraints(
                                    minWidth: 18,
                                    minHeight: 18,
                                  ),
                                  child: Text(
                                    _unreadAlertCount > 99 ? '99+' : _unreadAlertCount.toString(),
                                    style: TextStyle(
                                      color: Colors.white,
                                      fontSize: 10,
                                      fontWeight: FontWeight.bold,
                                    ),
                                    textAlign: TextAlign.center,
                                  ),
                                ),
                              ),
                            ),
                        ],
                      ),
                      PopupMenuButton<String>(
                        offset: Offset(0, 50),
                        child: CircleAvatar(
                          backgroundColor: Colors.white,
                          radius: 20,
                          child: Icon(Icons.person, color: AppTheme.brandPrimary),
                        ),
                        itemBuilder: (BuildContext context) => <PopupMenuEntry<String>>[
                          if (_userEmail != null)
                            PopupMenuItem<String>(
                              enabled: false,
                              child: Row(
                                children: [
                                  Icon(Icons.email, size: 18, color: Colors.grey[600]),
                                  SizedBox(width: 8),
                                  Flexible(
                                    child: Text(
                                      _userEmail!,
                                      style: TextStyle(
                                        fontSize: 12,
                                        color: Colors.grey[800],
                                        fontWeight: FontWeight.w500,
                                      ),
                                      overflow: TextOverflow.ellipsis,
                                    ),
                                  ),
                                ],
                              ),
                            ),
                          PopupMenuItem<String>(
                            enabled: false,
                            child: Row(
                              children: [
                                Icon(Icons.info_outline, size: 18, color: Colors.grey[600]),
                                SizedBox(width: 8),
                                Text(
                                  'Version: $APP_VERSION',
                                  style: TextStyle(
                                    fontSize: 12,
                                    color: Colors.grey[600],
                                  ),
                                ),
                              ],
                            ),
                          ),
                          PopupMenuDivider(),
                          PopupMenuItem<String>(
                            value: 'logout',
                            child: Row(
                              children: [
                                Icon(Icons.logout, size: 18, color: Colors.red.shade700),
                                SizedBox(width: 8),
                                Text(
                                  'Logout',
                                  style: TextStyle(color: Colors.red.shade700),
                                ),
                              ],
                            ),
                          ),
                        ],
                        onSelected: (String value) {
                          if (value == 'logout') {
                            _handleLogout();
                          }
                        },
                      ),
                    ],
                  ),
                ),
              ),
            ),
          ),
        ],
      ),
      
      // Bottom Navigation Bar
      bottomNavigationBar: Container(
        decoration: BoxDecoration(
          gradient: LinearGradient(
            colors: [AppTheme.brandPrimary, Color(0xFF007A00)],
          ),
          boxShadow: [
            BoxShadow(
              color: Colors.black.withOpacity(0.3),
              blurRadius: 20,
              offset: Offset(0, -5),
            ),
          ],
        ),
        child: SafeArea(
          child: Container(
            height: 65,
            child: Row(
              children: _buildNavItems(),
            ),
          ),
        ),
      ),
    );
  }

  /// Build the list of bottom-nav items, filtering by feature flags.
  /// The physical index stored in [_selectedIndex] always matches the
  /// position of the tab in the [Offstage] stack (0-5), so we keep a
  /// mapping from physical index → visibility.
  List<Widget> _buildNavItems() {
    final specs = [
      if (_features.showMap)
        _NavSpec(icon: Icons.map_outlined,        label: 'MAP',      index: 0),
      if (_features.showJourney)
        _NavSpec(icon: Icons.route,               label: 'JOURNEYS', index: 1),
      if (_features.showAssets)
        _NavSpec(icon: Icons.widgets,             label: 'ASSETS',   index: 2),
      if (_features.showScan)
        _NavSpec(icon: Icons.bluetooth_searching, label: 'SCAN',     index: 3),
      if (_features.showSettings)
        _NavSpec(icon: Icons.settings,            label: 'SETTINGS', index: 4),
      if (_features.showSolutions)
        _NavSpec(icon: Icons.lightbulb_outline,   label: 'SOLUTIONS',index: 5),
    ];
    return specs.map((s) => _buildNavItem(icon: s.icon, label: s.label, index: s.index)).toList();
  }

  Widget _buildNavItem({
    required IconData icon,
    required String label,
    required int index,
  }) {
    // Log navbar icon for ASSETS
    if (label == 'ASSETS') {
      print('🎨 NAVBAR: Building $label tab with icon: $icon (Icons.inventory_2 = ${Icons.inventory_2})');
      print('   Icon match: ${icon == Icons.inventory_2}');
    }
    
    final isSelected = _selectedIndex == index;
    
    return Expanded(
      child: InkWell(
        onTap: () {
          setState(() {
            _selectedIndex = index;
          });
        },
        child: Container(
          decoration: BoxDecoration(
            border: isSelected ? Border(
              top: BorderSide(color: Colors.white, width: 3),
            ) : null,
          ),
          child: Column(
            mainAxisAlignment: MainAxisAlignment.center,
            children: [
              Icon(
                icon,
                color: Colors.white,
                size: 26,
              ),
              SizedBox(height: 4),
              Text(
                label,
                style: GoogleFonts.inter(
                  fontSize: 11,
                  fontWeight: isSelected ? FontWeight.w700 : FontWeight.w500,
                  color: Colors.white,
                  letterSpacing: 0.5,
                ),
              ),
            ],
          ),
        ),
      ),
    );
  }

  Widget _buildMapView() {
    return Stack(
      children: [
        // Platform-specific map widget
        if (_useAppleMaps)
          apple.AppleMap(
            onMapCreated: (controller) {
              _appleMapController = controller;
            },
            initialCameraPosition: apple.CameraPosition(
              target: apple.LatLng(51.5074, -0.1278), // London, UK
              zoom: 12.0,
            ),
            annotations: _appleAnnotations,
            myLocationEnabled: true,
            myLocationButtonEnabled: true,
            mapType: apple.MapType.standard,
          )
        else if (_useGoogleMaps)
          gmaps.GoogleMap(
            onMapCreated: (controller) {
              if (_googleMapController == null) {
                _googleMapController = Completer<gmaps.GoogleMapController>();
              }
              _googleMapController!.complete(controller);
              _logger.success('Google Maps loaded successfully');
              print('✅ Google Maps initialized');
            },
            initialCameraPosition: gmaps.CameraPosition(
              target: gmaps.LatLng(51.5074, -0.1278), // London, UK
              zoom: 12.0,
            ),
            markers: _googleMarkers,
            myLocationEnabled: true,
            myLocationButtonEnabled: true,
            mapType: gmaps.MapType.normal,
          )
        else
          // Flutter Map for Web (OpenStreetMap)
          fmap.FlutterMap(
            mapController: _flutterMapController,
            options: fmap.MapOptions(
              initialCenter: latlong.LatLng(51.5074, -0.1278), // London, UK
              initialZoom: 15.0, // Street-level zoom
              minZoom: 3.0,
              maxZoom: 18.0,
              interactionOptions: fmap.InteractionOptions(
                enableMultiFingerGestureRace: true,
              ),
            ),
            children: [
              fmap.TileLayer(
                urlTemplate: 'https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png',
                subdomains: const ['a', 'b', 'c'],
                userAgentPackageName: 'com.beacontelematics.tracker',
                maxZoom: 18,
                keepBuffer: 2,
                panBuffer: 1,
                maxNativeZoom: 18,
                retinaMode: false,
                tileSize: 256,
                tileDisplay: fmap.TileDisplay.fadeIn(
                  duration: Duration(milliseconds: 50),
                ),
                evictErrorTileStrategy: fmap.EvictErrorTileStrategy.notVisibleRespectMargin,
                additionalOptions: {
                  'attribution': '© OpenStreetMap contributors',
                },
              ),
              // Geofence circles layer
              if (_showPOIs && _geofenceCircles.isNotEmpty)
                fmap.CircleLayer(circles: _geofenceCircles),
              // Trip route polyline layer
              if (_tripRoutePolylines.isNotEmpty)
                fmap.PolylineLayer(polylines: _tripRoutePolylines),
              // Trip route markers layer (start/end points)
              if (_tripRouteMarkers.isNotEmpty)
                fmap.MarkerLayer(markers: _tripRouteMarkers),
              // Vehicle markers layer (always on top)
              fmap.MarkerLayer(markers: _flutterMapMarkers),
            ],
          ),
        // Popup bubble for selected vehicle
        if (_selectedVehicle != null)
          Positioned.fill(
            child: GestureDetector(
              onTap: _hideVehicleDetails,
              child: Container(
                color: Colors.transparent,
                alignment: Alignment.center,
                child: GestureDetector(
                  onTap: () {}, // Prevent tap from closing popup
                  child: _buildVehiclePopup(_selectedVehicle!),
                ),
              ),
            ),
          ),
        if (_isLoading)
          Container(
            color: Colors.white.withOpacity(0.8),
            child: Center(
              child: Column(
                mainAxisSize: MainAxisSize.min,
                children: [
                  CircularProgressIndicator(
                    valueColor: AlwaysStoppedAnimation<Color>(AppTheme.brandPrimary),
                  ),
                  SizedBox(height: 16),
                  Text(
                    'Loading asset locations...',
                    style: GoogleFonts.inter(
                      fontSize: 14,
                      fontWeight: FontWeight.w500,
                      color: Colors.grey[700],
                    ),
                  ),
                  SizedBox(height: 4),
                  Text(
                    'Map tiles are cached for faster loading',
                    style: GoogleFonts.inter(
                      fontSize: 12,
                      color: Colors.grey[500],
                    ),
                  ),
                ],
              ),
            ),
          ),
        // Show empty state with Add Tag button when no vehicles
        if (!_isLoading && _vehicles.isEmpty)
          Container(
            color: Colors.white.withOpacity(0.95),
            child: Center(
              child: Column(
                mainAxisAlignment: MainAxisAlignment.center,
                children: [
                  Icon(
                    Icons.bluetooth_searching,
                    size: 100,
                    color: AppTheme.brandPrimary.withOpacity(0.5),
                  ),
                  SizedBox(height: 24),
                  Text(
                    'No Tags Yet',
                    style: GoogleFonts.poppins(
                      fontSize: 28,
                      fontWeight: FontWeight.bold,
                      color: AppTheme.brandPrimary,
                    ),
                  ),
                  SizedBox(height: 12),
                  Padding(
                    padding: EdgeInsets.symmetric(horizontal: 40),
                    child: Text(
                      'Add your first BLE tag to start tracking your assets',
                      textAlign: TextAlign.center,
                      style: GoogleFonts.inter(
                        fontSize: 16,
                        color: Colors.grey[600],
                      ),
                    ),
                  ),
                  SizedBox(height: 32),
                  ElevatedButton.icon(
                    onPressed: () async {
                      // Navigate to add tag screen
                      final result = await Navigator.push(
                        context,
                        MaterialPageRoute(builder: (context) => HomeScreen(skipAutoNavigation: true)),
                      );
                      // Reload tags after returning
                      if (result == true) {
                        _loadTags();
                      }
                    },
                    icon: Icon(Icons.add, size: 24),
                    label: Text(
                      'Add Your First Tag',
                      style: GoogleFonts.inter(
                        fontSize: 18,
                        fontWeight: FontWeight.w600,
                      ),
                    ),
                    style: ElevatedButton.styleFrom(
                      backgroundColor: AppTheme.brandPrimary,
                      foregroundColor: Colors.white,
                      padding: EdgeInsets.symmetric(horizontal: 32, vertical: 16),
                      shape: RoundedRectangleBorder(
                        borderRadius: BorderRadius.circular(16),
                      ),
                      elevation: 4,
                    ),
                  ),
                ],
              ),
            ),
          ),
        // POI management buttons (only show when there are vehicles)
        if (!_isLoading && _vehicles.isNotEmpty)
          Positioned(
            bottom: 88, // Above the refresh button
            right: 16,
            child: FloatingActionButton(
              heroTag: 'add_tracker',
              onPressed: () async {
                final result = await Navigator.push(
                  context,
                  MaterialPageRoute(builder: (context) => HomeScreen(skipAutoNavigation: true)),
                );
                if (result == true) {
                  _loadTags();
                }
              },
              backgroundColor: Colors.green,
              child: Icon(Icons.add, color: Colors.white),
              tooltip: 'Add New Tracker',
            ),
          ),
        // Map zoom controls only - Web only - Minimal compact design
        if (!_isLoading && _useFlutterMap && kIsWeb)
          Positioned(
            right: 16,
            top: 80,
            child: Material(
              elevation: 4,
              borderRadius: BorderRadius.circular(8),
              shadowColor: Colors.black.withOpacity(0.15),
              child: Container(
                decoration: BoxDecoration(
                  color: Colors.white,
                  borderRadius: BorderRadius.circular(8),
                  border: Border.all(
                    color: Colors.grey.shade200,
                    width: 0.5,
                  ),
                ),
                child: Column(
                  mainAxisSize: MainAxisSize.min,
                  children: [
                    // Zoom In button
                    SizedBox(
                      width: 32,
                      height: 32,
                      child: IconButton(
                        padding: EdgeInsets.zero,
                        icon: Icon(Icons.add_rounded, size: 16),
                        onPressed: _zoomIn,
                        tooltip: 'Zoom In',
                      ),
                    ),
                    Container(
                      height: 1,
                      width: 28,
                      color: Colors.grey.shade200,
                    ),
                    // Zoom Out button
                    SizedBox(
                      width: 32,
                      height: 32,
                      child: IconButton(
                        padding: EdgeInsets.zero,
                        icon: Icon(Icons.remove_rounded, size: 16),
                        onPressed: _zoomOut,
                        tooltip: 'Zoom Out',
                      ),
                    ),
                  ],
                ),
              ),
            ),
          ),
        // Refresh button (only show when there are vehicles)
        if (!_isLoading && _vehicles.isNotEmpty)
          Positioned(
            bottom: 16,
            right: 16,
            child: FloatingActionButton(
              heroTag: 'refresh',
              onPressed: _loadTags,
              backgroundColor: AppTheme.brandPrimary,
              child: Icon(Icons.refresh, color: Colors.white),
            ),
          ),
      ],
    );
  }

  Widget _buildMapControlButton({
    required IconData icon,
    required VoidCallback onPressed,
    required String tooltip,
    bool isPrimary = false,
  }) {
    return Tooltip(
      message: tooltip,
      child: Material(
        color: Colors.transparent,
        child: InkWell(
          onTap: onPressed,
          borderRadius: BorderRadius.circular(8),
          hoverColor: isPrimary 
              ? AppTheme.brandPrimary.withOpacity(0.08)
              : Colors.grey.shade100,
          child: Container(
            width: 36,
            height: 36,
            alignment: Alignment.center,
            child: Icon(
              icon, 
              size: 18, 
              color: isPrimary 
                  ? AppTheme.brandPrimary
                  : Colors.grey.shade700,
            ),
          ),
        ),
      ),
    );
  }

  Widget _buildJourneysView() {
    // Auto-load trips on first display if vehicles are available
    if (!_tripsInitiallyLoaded && _vehicles.isNotEmpty && !_isLoadingTrips) {
      WidgetsBinding.instance.addPostFrameCallback((_) {
        if (mounted && !_tripsInitiallyLoaded) {
          _tripsInitiallyLoaded = true;
          _loadTrips();
        }
      });
    }
    
    return Container(
      color: Colors.grey.shade50,
      child: Column(
        children: [
          // Header with vehicle selector and date filter
          Container(
            padding: EdgeInsets.only(top: 96, left: 16, right: 16, bottom: 12),
            decoration: BoxDecoration(
              color: Colors.white,
              boxShadow: [
                BoxShadow(
                  color: Colors.black.withOpacity(0.05),
                  blurRadius: 8,
                  offset: Offset(0, 2),
                ),
              ],
            ),
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                // Vehicle selector
                if (_vehicles.isEmpty)
                  Text(
                    'No assets being tracked',
                    style: GoogleFonts.inter(
                      fontSize: 14,
                      color: Colors.grey.shade600,
                    ),
                  )
                else
                  Container(
                    padding: EdgeInsets.symmetric(horizontal: 12, vertical: 4),
                    decoration: BoxDecoration(
                      color: Colors.grey.shade100,
                      borderRadius: BorderRadius.circular(8),
                    ),
                    child: DropdownButtonHideUnderline(
                      child: DropdownButton<String>(
                        value: _selectedTripVehicle?.id ?? _vehicles.first.id,
                        isExpanded: true,
                        icon: Icon(Icons.arrow_drop_down, color: AppTheme.brandPrimary),
                        items: _vehicles.map((vehicle) {
                          return DropdownMenuItem<String>(
                            value: vehicle.id,
                            child: Row(
                              children: [
                                Icon(Icons.directions_car, size: 18, color: AppTheme.brandPrimary),
                                SizedBox(width: 8),
                                Text(
                                  _vehicleCustomNames[vehicle.id] ?? vehicle.description,
                                  style: GoogleFonts.inter(
                                    fontSize: 15,
                                    fontWeight: FontWeight.w500,
                                  ),
                                ),
                              ],
                            ),
                          );
                        }).toList(),
                        onChanged: (value) {
                          if (value != null) {
                            final vehicle = _vehicles.firstWhere((v) => v.id == value);
                            setState(() {
                              _selectedTripVehicle = vehicle;
                            });
                            _loadTrips();
                          }
                        },
                      ),
                    ),
                  ),
                SizedBox(height: 12),
                // Date range selector - simplified to 3 options for mobile
                SingleChildScrollView(
                  scrollDirection: Axis.horizontal,
                  child: Row(
                    children: [
                      _buildDateChip('Custom'),
                      SizedBox(width: 8),
                      _buildDateChip('Today'),
                      SizedBox(width: 8),
                      _buildDateChip('Yesterday'),
                    ],
                  ),
                ),
              ],
            ),
          ),
          // Trips list
          Expanded(
            child: _vehicles.isEmpty
                ? Center(
                    child: Column(
                      mainAxisAlignment: MainAxisAlignment.center,
                      children: [
                        Icon(Icons.location_on_outlined, size: 64, color: Colors.grey.shade400),
                        SizedBox(height: 16),
                        Text(
                          'No assets being tracked',
                          style: GoogleFonts.inter(
                            fontSize: 16,
                            color: Colors.grey.shade600,
                          ),
                        ),
                      ],
                    ),
                  )
                : _isLoadingTrips
                    ? Center(child: CircularProgressIndicator())
                    : _getFilteredTrips().isEmpty
                        ? Center(
                            child: Column(
                              mainAxisAlignment: MainAxisAlignment.center,
                              children: [
                                Icon(Icons.route, size: 64, color: Colors.grey.shade400),
                                SizedBox(height: 16),
                                Text(
                                  'No Journeys found',
                                  style: GoogleFonts.inter(
                                    fontSize: 16,
                                    fontWeight: FontWeight.w500,
                                    color: Colors.grey.shade700,
                                  ),
                                ),
                                SizedBox(height: 8),
                                Text(
                                  'Try selecting a different date range',
                                  style: GoogleFonts.inter(
                                    fontSize: 14,
                                    color: Colors.grey.shade600,
                                  ),
                                ),
                              ],
                            ),
                          )
                        : RefreshIndicator(
                            onRefresh: _loadTrips,
                            child: ListView.builder(
                              padding: EdgeInsets.all(16),
                              itemCount: _getFilteredTrips().length,
                              itemBuilder: (context, index) {
                                final filteredTrips = _getFilteredTrips();
                                return _buildTripCard(filteredTrips[index]);
                              },
                            ),
                          ),
          ),
        ],
      ),
    );
  }

  Widget _buildAssetsView() {
    return Container(
      color: Colors.grey.shade50,
      padding: EdgeInsets.only(top: 80),
      child: _isLoading
          ? Center(
              child: Column(
                mainAxisAlignment: MainAxisAlignment.center,
                children: [
                  CircularProgressIndicator(
                    valueColor: AlwaysStoppedAnimation<Color>(AppTheme.brandPrimary),
                  ),
                  SizedBox(height: 16),
                  Text(
                    'Loading assets...',
                    style: GoogleFonts.inter(
                      fontSize: 14,
                      color: Colors.grey.shade600,
                    ),
                  ),
                ],
              ),
            )
          : _vehicles.isEmpty
              ? Center(
                  child: Column(
                    mainAxisAlignment: MainAxisAlignment.center,
                    children: [
                      Icon(
                        Icons.bluetooth_searching,
                        size: 100,
                        color: AppTheme.brandPrimary.withOpacity(0.5),
                      ),
                      SizedBox(height: 24),
                      Text(
                        'No Tags Yet',
                        style: GoogleFonts.poppins(
                          fontSize: 28,
                          fontWeight: FontWeight.bold,
                          color: AppTheme.brandPrimary,
                        ),
                      ),
                      SizedBox(height: 12),
                      Padding(
                        padding: EdgeInsets.symmetric(horizontal: 40),
                        child: Text(
                          'Add your first BLE tag to start tracking your assets',
                          textAlign: TextAlign.center,
                          style: GoogleFonts.inter(
                            fontSize: 16,
                            color: Colors.grey[600],
                          ),
                        ),
                      ),
                      SizedBox(height: 32),
                      ElevatedButton.icon(
                        onPressed: () async {
                          final result = await Navigator.push(
                            context,
                            MaterialPageRoute(builder: (context) => HomeScreen(skipAutoNavigation: true)),
                          );
                          if (result == true) {
                            _loadTags();
                          }
                        },
                        icon: Icon(Icons.add, size: 24),
                        label: Text(
                          'Add Your First Tag',
                          style: GoogleFonts.inter(
                            fontSize: 18,
                            fontWeight: FontWeight.w600,
                          ),
                        ),
                        style: ElevatedButton.styleFrom(
                          backgroundColor: AppTheme.brandPrimary,
                          foregroundColor: Colors.white,
                          padding: EdgeInsets.symmetric(horizontal: 32, vertical: 16),
                          shape: RoundedRectangleBorder(
                            borderRadius: BorderRadius.circular(16),
                          ),
                          elevation: 4,
                        ),
                      ),
                    ],
                  ),
                )
              : RefreshIndicator(
                  onRefresh: _loadTags,
                  child: ListView(
                    padding: EdgeInsets.all(16),
                    children: [
                      // Header
                      Padding(
                        padding: EdgeInsets.symmetric(vertical: 16),
                        child: Row(
                          mainAxisAlignment: MainAxisAlignment.spaceBetween,
                          children: [
                            Column(
                              crossAxisAlignment: CrossAxisAlignment.start,
                              children: [
                                Text(
                                  'Assets',
                                  style: GoogleFonts.poppins(
                                    fontSize: 28,
                                    fontWeight: FontWeight.w700,
                                    color: AppTheme.brandPrimary,
                                  ),
                                ),
                                Text(
                                  'Total: ${_vehicles.length}',
                                  style: GoogleFonts.inter(
                                    fontSize: 14,
                                    color: Colors.grey.shade600,
                                  ),
                                ),
                              ],
                            ),
                            IconButton(
                              onPressed: _loadTags,
                              icon: Icon(Icons.refresh),
                              color: AppTheme.brandPrimary,
                              iconSize: 28,
                            ),
                          ],
                        ),
                      ),
                      // Vehicle List
                      ..._vehicles.map((vehicle) => _buildAssetCard(vehicle)).toList(),
                    ],
                  ),
                ),
    );
  }

  Widget _buildAssetCard(Vehicle vehicle) {
    final hasLocation = vehicle.hasLocation;
    final isNew = vehicle.isNew;
    final isStale = hasLocation && vehicle.lastKnownPosition!.isStale;
    final displayName = _vehicleCustomNames[vehicle.id] ?? 
                       vehicle.description ?? 
                       vehicle.registration ?? 
                       'Unknown Asset';
    
    return Container(
      margin: EdgeInsets.only(bottom: 16),
      decoration: BoxDecoration(
        color: Colors.white,
        borderRadius: BorderRadius.circular(16),
        boxShadow: [
          BoxShadow(
            color: Colors.black.withOpacity(0.08),
            blurRadius: 12,
            offset: Offset(0, 4),
          ),
        ],
      ),
      child: Material(
        color: Colors.transparent,
        child: InkWell(
          onTap: hasLocation ? () => _focusOnAsset(vehicle) : null,
          borderRadius: BorderRadius.circular(16),
          child: Padding(
            padding: EdgeInsets.all(16),
            child: Row(
              children: [
                // Status Indicator
                Container(
                  width: 48,
                  height: 48,
                  decoration: BoxDecoration(
                    gradient: LinearGradient(
                      colors: isNew
                          ? [Colors.blue.shade400, Colors.blue.shade600]
                          : isStale
                              ? [Colors.grey.shade300, Colors.grey.shade400]
                              : vehicle.ignitionOn
                                  ? [Colors.green.shade400, Colors.green.shade600]
                                  : [Colors.orange.shade400, Colors.orange.shade600],
                    ),
                    borderRadius: BorderRadius.circular(12),
                    boxShadow: [
                      BoxShadow(
                        color: (isNew
                                ? Colors.blue
                                : isStale
                                    ? Colors.grey.shade400
                                    : vehicle.ignitionOn
                                        ? Colors.green
                                        : Colors.orange)
                            .withOpacity(0.3),
                        blurRadius: 8,
                        offset: Offset(0, 2),
                      ),
                    ],
                  ),
                  child: Icon(
                    isNew
                        ? Icons.new_releases
                        : isStale
                            ? Icons.signal_wifi_off
                            : vehicle.ignitionOn
                                ? Icons.inventory_2
                                : Icons.inventory,
                    color: Colors.white,
                    size: 24,
                  ),
                ),
                SizedBox(width: 16),
                // Asset Info
                Expanded(
                  child: Column(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      Row(
                        children: [
                          Expanded(
                            child: Text(
                              displayName,
                              maxLines: 2,
                              overflow: TextOverflow.ellipsis,
                              style: GoogleFonts.poppins(
                                fontSize: 16,
                                fontWeight: FontWeight.w600,
                                color: Colors.grey.shade800,
                              ),
                            ),
                          ),
                          if (isNew)
                            Container(
                              padding: EdgeInsets.symmetric(horizontal: 8, vertical: 4),
                              decoration: BoxDecoration(
                                color: Colors.blue.shade50,
                                borderRadius: BorderRadius.circular(8),
                                border: Border.all(color: Colors.blue.shade300, width: 1),
                              ),
                              child: Text(
                                'NEW',
                                style: GoogleFonts.inter(
                                  fontSize: 10,
                                  fontWeight: FontWeight.w700,
                                  color: Colors.blue.shade700,
                                  letterSpacing: 1.2,
                                ),
                              ),
                            ),
                        ],
                      ),
                      if (vehicle.registration != null)
                        Text(
                          vehicle.registration!,
                          style: GoogleFonts.inter(
                            fontSize: 12,
                            color: Colors.grey.shade600,
                            letterSpacing: 1.2,
                          ),
                        ),
                      if (vehicle.batteryLevel != null)
                        Padding(
                          padding: EdgeInsets.only(top: 4),
                          child: _buildBatteryIndicator(vehicle.batteryLevel!),
                        ),
                      if (isNew)
                        Padding(
                          padding: EdgeInsets.only(top: 4),
                          child: Text(
                            'Location data pending...',
                            style: GoogleFonts.inter(
                              fontSize: 11,
                              color: Colors.grey.shade500,
                              fontStyle: FontStyle.italic,
                            ),
                          ),
                        ),
                    ],
                  ),
                ),
                // Arm/Disarm Button
                IconButton(
                  icon: Icon(
                    _isTrackerArmedToAnyPOI(vehicle.id) 
                      ? Icons.security 
                      : Icons.security,
                    color: _isTrackerArmedToAnyPOI(vehicle.id) 
                      ? Colors.green.shade700 
                      : Colors.red.shade700,
                    size: 18,
                  ),
                  padding: EdgeInsets.all(4),
                  constraints: BoxConstraints(minWidth: 32, minHeight: 32),
                  onPressed: () => _showArmDisarmDialog(vehicle),
                  tooltip: _isTrackerArmedToAnyPOI(vehicle.id) ? 'Armed' : 'Disarmed',
                ),
                // Share Location Button (disabled for NEW assets)
                if (hasLocation)
                  IconButton(
                    icon: Icon(Icons.share, color: Colors.green.shade700, size: 18),
                    padding: EdgeInsets.all(4),
                    constraints: BoxConstraints(minWidth: 32, minHeight: 32),
                    onPressed: () => _showShareLocationOptions(vehicle),
                    tooltip: 'Share location',
                  ),
                // Edit Button
                IconButton(
                  icon: Icon(Icons.edit, color: AppTheme.brandPrimary, size: 18),
                  padding: EdgeInsets.all(4),
                  constraints: BoxConstraints(minWidth: 32, minHeight: 32),
                  onPressed: () => _showEditNameDialog(vehicle),
                  tooltip: 'Edit name',
                ),
                // Chevron (only for assets with location)
                if (hasLocation)
                  Icon(
                    Icons.chevron_right,
                    color: Colors.grey.shade400,
                    size: 24,
                  ),
              ],
            ),
          ),
        ),
      ),
    );
  }
  
  /// Compact battery level row: icon + percentage + colour-coded bar.
  Widget _buildBatteryIndicator(int level) {
    final Color barColor = level > 50
        ? Colors.green.shade600
        : level > 20
            ? Colors.orange.shade600
            : Colors.red.shade600;
    final IconData icon = level > 50
        ? Icons.battery_full
        : level > 20
            ? Icons.battery_3_bar
            : Icons.battery_alert;

    return Row(
      mainAxisSize: MainAxisSize.min,
      children: [
        Icon(icon, size: 14, color: barColor),
        SizedBox(width: 3),
        Text(
          'Battery: $level%',
          style: GoogleFonts.inter(
            fontSize: 11,
            fontWeight: FontWeight.w500,
            color: barColor,
          ),
        ),
        SizedBox(width: 6),
        // tiny progress bar
        ClipRRect(
          borderRadius: BorderRadius.circular(3),
          child: SizedBox(
            width: 48,
            height: 6,
            child: LinearProgressIndicator(
              value: level / 100.0,
              backgroundColor: Colors.grey.shade200,
              valueColor: AlwaysStoppedAnimation<Color>(barColor),
            ),
          ),
        ),
      ],
    );
  }

  List<Widget> _buildAttributeChips(Vehicle vehicle) {    print('🏷️ Building attribute chips for ${vehicle.description}');
    print('   Attributes data: ${vehicle.attributes}');
    final chips = <Widget>[];
    
    if (vehicle.attributes != null) {
      vehicle.attributes!.forEach((key, value) {
        print('   🔑 Processing attribute: $key = $value');
        if (value is Map && value['value'] != null && value['value'].toString().trim().isNotEmpty) {
          final displayKey = key.replaceAll('_', ' ').toUpperCase();
          final showOnMap = value['show_on_map'] == true;
          print('      ✅ Adding chip: $displayKey (visible: $showOnMap)');
          
          chips.add(
            Padding(
              padding: EdgeInsets.only(top: 4, right: 4),
              child: Container(
                padding: EdgeInsets.symmetric(horizontal: 8, vertical: 4),
                decoration: BoxDecoration(
                  color: showOnMap ? Colors.green.shade50 : Colors.grey.shade100,
                  borderRadius: BorderRadius.circular(6),
                  border: Border.all(
                    color: showOnMap ? Colors.green.shade300 : Colors.grey.shade300,
                    width: 1,
                  ),
                ),
                child: Row(
                  mainAxisSize: MainAxisSize.min,
                  children: [
                    if (showOnMap)
                      Padding(
                        padding: EdgeInsets.only(right: 4),
                        child: Icon(
                          Icons.visibility,
                          size: 12,
                          color: Colors.green.shade700,
                        ),
                      ),
                    Text(
                      '$displayKey: ${value['value']}',
                      style: GoogleFonts.inter(
                        fontSize: 11,
                        color: showOnMap ? Colors.green.shade800 : Colors.grey.shade700,
                        fontWeight: showOnMap ? FontWeight.w500 : FontWeight.normal,
                      ),
                    ),
                  ],
                ),
              ),
            ),
          );
        }
      });
    }
    
    if (chips.isEmpty) {
      print('   ⚠️ No attribute chips created');
      chips.add(
        Padding(
          padding: EdgeInsets.only(top: 4),
          child: Text(
            'No attributes set. Click edit to add.',
            style: GoogleFonts.inter(
              fontSize: 10,
              color: Colors.grey.shade500,
              fontStyle: FontStyle.italic,
            ),
          ),
        ),
      );
    }
    
    return chips;
  }

  
  void _showAttributesBottomSheet(Vehicle vehicle) {
    final visibleAttrs = vehicle.visibleAttributes ?? {};
    
    showModalBottomSheet(
      context: context,
      isScrollControlled: true,
      backgroundColor: Colors.transparent,
      builder: (context) => Container(
        decoration: BoxDecoration(
          color: Colors.white,
          borderRadius: BorderRadius.vertical(top: Radius.circular(20)),
        ),
        constraints: BoxConstraints(
          maxHeight: MediaQuery.of(context).size.height * 0.8,
        ),
        child: Column(
          mainAxisSize: MainAxisSize.min,
          children: [
            // Drag handle
            Padding(
              padding: EdgeInsets.only(top: 8),
              child: Container(
                width: 40,
                height: 4,
                decoration: BoxDecoration(
                  color: Colors.grey.shade300,
                  borderRadius: BorderRadius.circular(2),
                ),
              ),
            ),
            // Header
            Container(
              padding: EdgeInsets.all(16),
              decoration: BoxDecoration(
                border: Border(bottom: BorderSide(color: Colors.grey.shade200)),
              ),
              child: Row(
                children: [
                  Icon(Icons.description, color: AppTheme.brandPrimary, size: 24),
                  SizedBox(width: 12),
                  Expanded(
                    child: Column(
                      crossAxisAlignment: CrossAxisAlignment.start,
                      children: [
                        Text(
                          'Attributes',
                          style: GoogleFonts.poppins(
                            fontSize: 18,
                            fontWeight: FontWeight.w600,
                          ),
                        ),
                        Text(
                          _vehicleCustomNames[vehicle.id] ?? vehicle.description,
                          style: GoogleFonts.inter(
                            fontSize: 12,
                            color: Colors.grey.shade600,
                          ),
                          overflow: TextOverflow.ellipsis,
                        ),
                      ],
                    ),
                  ),
                  IconButton(
                    icon: Icon(Icons.close, size: 20),
                    onPressed: () => Navigator.pop(context),
                    padding: EdgeInsets.zero,
                    constraints: BoxConstraints(minWidth: 32, minHeight: 32),
                  ),
                ],
              ),
            ),
            // Content - Scrollable attributes list
            Expanded(
              child: SingleChildScrollView(
                child: Container(
                  padding: EdgeInsets.all(16),
                  child: visibleAttrs.isEmpty
                      ? Center(
                          child: Padding(
                            padding: EdgeInsets.symmetric(vertical: 32),
                            child: Column(
                              mainAxisSize: MainAxisSize.min,
                              children: [
                                Icon(
                                  Icons.label_off,
                                  size: 48,
                                  color: Colors.grey.shade400,
                                ),
                                SizedBox(height: 16),
                                Text(
                                  'No attributes to display',
                                  style: GoogleFonts.inter(
                                    fontSize: 14,
                                    color: Colors.grey.shade600,
                                  ),
                                ),
                              ],
                            ),
                          ),
                        )
                      : Column(
                          children: visibleAttrs.entries.map((entry) {
                            final displayKey = entry.key.replaceAll('_', ' ');
                            return Padding(
                              padding: EdgeInsets.only(bottom: 16),
                              child: Container(
                                padding: EdgeInsets.all(16),
                                decoration: BoxDecoration(
                                  color: Colors.grey.shade50,
                                  borderRadius: BorderRadius.circular(12),
                                  border: Border.all(color: Colors.grey.shade200),
                                ),
                                child: Column(
                                  crossAxisAlignment: CrossAxisAlignment.start,
                                  children: [
                                    Row(
                                      mainAxisAlignment: MainAxisAlignment.spaceBetween,
                                      children: [
                                        Text(
                                          displayKey.toUpperCase(),
                                          style: GoogleFonts.inter(
                                            fontSize: 12,
                                            fontWeight: FontWeight.w600,
                                            color: Colors.grey.shade700,
                                            letterSpacing: 0.5,
                                          ),
                                        ),
                                        Container(
                                          padding: EdgeInsets.symmetric(
                                            horizontal: 8,
                                            vertical: 4,
                                          ),
                                          decoration: BoxDecoration(
                                            color: Colors.green.shade100,
                                            borderRadius: BorderRadius.circular(6),
                                          ),
                                          child: Row(
                                            mainAxisSize: MainAxisSize.min,
                                            children: [
                                              Icon(
                                                Icons.visibility,
                                                size: 12,
                                                color: Colors.green.shade700,
                                              ),
                                              SizedBox(width: 4),
                                              Text(
                                                'Visible',
                                                style: GoogleFonts.inter(
                                                  fontSize: 10,
                                                  color: Colors.green.shade700,
                                                  fontWeight: FontWeight.w600,
                                                ),
                                              ),
                                            ],
                                          ),
                                        ),
                                      ],
                                    ),
                                    SizedBox(height: 12),
                                    Text(
                                      entry.value.toString(),
                                      style: GoogleFonts.inter(
                                        fontSize: 16,
                                        fontWeight: FontWeight.w500,
                                        color: Colors.grey.shade800,
                                      ),
                                    ),
                                  ],
                                ),
                              ),
                            );
                          }).toList(),
                        ),
                ),
              ),
            ),
            // Footer
            Container(
              padding: EdgeInsets.all(16),
              decoration: BoxDecoration(
                border: Border(top: BorderSide(color: Colors.grey.shade200)),
              ),
              child: Row(
                children: [
                  Expanded(
                    child: ElevatedButton.icon(
                      onPressed: () {
                        Navigator.pop(context);
                        _showEditNameDialog(vehicle);
                      },
                      icon: Icon(Icons.edit, size: 16),
                      label: Text('Edit Attributes'),
                      style: ElevatedButton.styleFrom(
                        backgroundColor: AppTheme.brandPrimary,
                        foregroundColor: Colors.white,
                        padding: EdgeInsets.symmetric(vertical: 12),
                      ),
                    ),
                  ),
                  SizedBox(width: 12),
                  Expanded(
                    child: OutlinedButton.icon(
                      onPressed: () => Navigator.pop(context),
                      icon: Icon(Icons.close, size: 16),
                      label: Text('Close'),
                      style: OutlinedButton.styleFrom(
                        padding: EdgeInsets.symmetric(vertical: 12),
                      ),
                    ),
                  ),
                ],
              ),
            ),
          ],
        ),
      ),
    );
  }

  void _showEditNameDialog(Vehicle vehicle) {
    print('✏️ Opening attributes editor for ${vehicle.description}');
    print('   Current attributes: ${vehicle.attributes}');
    final currentName = _vehicleCustomNames[vehicle.id] ?? 
                       vehicle.description ?? 
                       vehicle.registration ?? 
                       'Unknown Asset';
    
    // Controllers for all attribute fields
    final nameController = TextEditingController(text: currentName);
    final descriptionController = TextEditingController(
      text: vehicle.getAttributeValue('description') ?? '',
    );
    final jobAccessoriesController = TextEditingController(
      text: vehicle.getAttributeValue('job_accessories') ?? '',
    );
    final notesController = TextEditingController(
      text: vehicle.getAttributeValue('notes') ?? '',
    );
    final referenceController = TextEditingController(
      text: vehicle.getAttributeValue('reference_number') ?? '',
    );
    
    // Checkboxes state for map visibility
    final showDescription = ValueNotifier<bool>(
      vehicle.isAttributeVisible('description'),
    );
    final showJobAccessories = ValueNotifier<bool>(
      vehicle.isAttributeVisible('job_accessories'),
    );
    final showNotes = ValueNotifier<bool>(
      vehicle.isAttributeVisible('notes'),
    );
    final showReference = ValueNotifier<bool>(
      vehicle.isAttributeVisible('reference_number'),
    );
    
    final isSaving = ValueNotifier<bool>(false);

    showDialog(
      context: context,
      builder: (context) => AlertDialog(
        title: Text(
          'Edit Asset Details',
          style: GoogleFonts.poppins(
            fontWeight: FontWeight.w600,
          ),
        ),
        content: SingleChildScrollView(
          child: Container(
            width: 500,
            child: Column(
              mainAxisSize: MainAxisSize.min,
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                // Asset Name
                TextField(
                  controller: nameController,
                  decoration: InputDecoration(
                    labelText: 'Asset Name',
                    border: OutlineInputBorder(
                      borderRadius: BorderRadius.circular(8),
                    ),
                    focusedBorder: OutlineInputBorder(
                      borderRadius: BorderRadius.circular(8),
                      borderSide: BorderSide(color: AppTheme.brandPrimary, width: 2),
                    ),
                  ),
                ),
                SizedBox(height: 16),
                
                // IMEI (read-only display)
                Container(
                  padding: EdgeInsets.all(12),
                  decoration: BoxDecoration(
                    color: Colors.grey.shade100,
                    borderRadius: BorderRadius.circular(8),
                    border: Border.all(color: Colors.grey.shade300),
                  ),
                  child: Row(
                    children: [
                      Icon(Icons.info_outline, size: 18, color: Colors.grey.shade600),
                      SizedBox(width: 8),
                      Text(
                        'IMEI: ${vehicle.registration ?? "N/A"}',
                        style: GoogleFonts.inter(
                          fontSize: 13,
                          color: Colors.grey.shade700,
                        ),
                      ),
                    ],
                  ),
                ),
                SizedBox(height: 20),
                
                // Section header
                Text(
                  'Additional Attributes',
                  style: GoogleFonts.poppins(
                    fontSize: 14,
                    fontWeight: FontWeight.w600,
                    color: Colors.grey.shade700,
                  ),
                ),
                SizedBox(height: 8),
                Text(
                  'Check "Show on Map" to display the attribute in map marker popups',
                  style: GoogleFonts.inter(
                    fontSize: 11,
                    color: Colors.grey.shade600,
                  ),
                ),
                SizedBox(height: 12),
                
                // Description
                _buildAttributeField(
                  controller: descriptionController,
                  label: 'Description',
                  showOnMap: showDescription,
                ),
                SizedBox(height: 16),
                
                // Job Accessories
                _buildAttributeField(
                  controller: jobAccessoriesController,
                  label: 'Job Accessories',
                  showOnMap: showJobAccessories,
                ),
                SizedBox(height: 16),
                
                // Notes
                _buildAttributeField(
                  controller: notesController,
                  label: 'Notes',
                  showOnMap: showNotes,
                  maxLines: 3,
                ),
                SizedBox(height: 16),
                
                // Reference Number
                _buildAttributeField(
                  controller: referenceController,
                  label: 'Reference Number',
                  showOnMap: showReference,
                ),
              ],
            ),
          ),
        ),
        actions: [
          TextButton(
            onPressed: () => Navigator.pop(context),
            child: Text('Cancel'),
          ),
          ValueListenableBuilder<bool>(
            valueListenable: isSaving,
            builder: (context, saving, child) {
              return ElevatedButton(
                onPressed: saving ? null : () async {
                  isSaving.value = true;
                  
                  // Update local name
                  setState(() {
                    _vehicleCustomNames[vehicle.id] = nameController.text.trim();
                  });
                  
                  // Prepare attributes for API
                  final attributes = {
                    'description': {
                      'value': descriptionController.text.trim(),
                      'show_on_map': showDescription.value,
                    },
                    'job_accessories': {
                      'value': jobAccessoriesController.text.trim(),
                      'show_on_map': showJobAccessories.value,
                    },
                    'notes': {
                      'value': notesController.text.trim(),
                      'show_on_map': showNotes.value,
                    },
                    'reference_number': {
                      'value': referenceController.text.trim(),
                      'show_on_map': showReference.value,
                    },
                  };
                  
                  try {
                    // Call API to save attributes and device name
                    final imei = vehicle.registration ?? '';
                    print('💾 Saving attributes for IMEI: $imei');
                    print('   Attributes to save: $attributes');
                    print('   Device name: ${nameController.text.trim()}');
                    if (imei.isNotEmpty) {
                      await _locationService.updateAssetAttributes(
                        imei,
                        attributes,
                        deviceName: nameController.text.trim().isEmpty ? null : nameController.text.trim(),
                      );
                      print('✅ Attributes saved successfully');
                      
                      // Reload vehicles to reflect changes
                      await _loadTags();
                      
                      if (mounted) {
                        ScaffoldMessenger.of(context).showSnackBar(
                          SnackBar(
                            content: Text('Asset attributes saved successfully'),
                            backgroundColor: Colors.green,
                            duration: Duration(seconds: 2),
                          ),
                        );
                      }
                    }
                  } catch (e) {
                    if (mounted) {
                      ScaffoldMessenger.of(context).showSnackBar(
                        SnackBar(
                          content: Text('Failed to save attributes: $e'),
                          backgroundColor: Colors.red,
                          duration: Duration(seconds: 3),
                        ),
                      );
                    }
                  }
                  
                  isSaving.value = false;
                  if (mounted) {
                    Navigator.pop(context);
                  }
                },
                style: ElevatedButton.styleFrom(
                  backgroundColor: AppTheme.brandPrimary,
                  foregroundColor: Colors.white,
                ),
                child: saving
                    ? SizedBox(
                        width: 16,
                        height: 16,
                        child: CircularProgressIndicator(
                          strokeWidth: 2,
                          valueColor: AlwaysStoppedAnimation(Colors.white),
                        ),
                      )
                    : Text('Save'),
              );
            },
          ),
        ],
      ),
    );
  }
  
  Widget _buildAttributeField({
    required TextEditingController controller,
    required String label,
    required ValueNotifier<bool> showOnMap,
    int maxLines = 1,
  }) {
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        TextField(
          controller: controller,
          maxLines: maxLines,
          decoration: InputDecoration(
            labelText: label,
            border: OutlineInputBorder(
              borderRadius: BorderRadius.circular(8),
            ),
            focusedBorder: OutlineInputBorder(
              borderRadius: BorderRadius.circular(8),
              borderSide: BorderSide(color: AppTheme.brandPrimary, width: 2),
            ),
          ),
        ),
        SizedBox(height: 4),
        ValueListenableBuilder<bool>(
          valueListenable: showOnMap,
          builder: (context, checked, child) {
            return InkWell(
              onTap: () => showOnMap.value = !showOnMap.value,
              borderRadius: BorderRadius.circular(4),
              child: Padding(
                padding: EdgeInsets.symmetric(vertical: 4),
                child: Row(
                  mainAxisSize: MainAxisSize.min,
                  children: [
                    SizedBox(
                      width: 20,
                      height: 20,
                      child: Checkbox(
                        value: checked,
                        onChanged: (value) => showOnMap.value = value ?? false,
                        materialTapTargetSize: MaterialTapTargetSize.shrinkWrap,
                      ),
                    ),
                    SizedBox(width: 8),
                    Text(
                      'Show on Map',
                      style: GoogleFonts.inter(
                        fontSize: 12,
                        color: Colors.grey.shade700,
                      ),
                    ),
                  ],
                ),
              ),
            );
          },
        ),
      ],
    );
  }

  /// Check if a tracker is armed to any POI
  bool _isTrackerArmedToAnyPOI(String trackerId) {
    if (_pois.isEmpty) return false;
    
    for (var poi in _pois) {
      if (poi is POI && poi.isArmedTo(trackerId)) {
        return true;
      }
    }
    return false;
  }

  /// Show arm/disarm dialog with location list
  void _showArmDisarmDialog(Vehicle vehicle) {
    final displayName = _vehicleCustomNames[vehicle.id] ?? 
                       vehicle.description ?? 
                       vehicle.registration ?? 
                       'Unknown Asset';
    
    // Create a stateful dialog to manage checkbox states
    showDialog(
      context: context,
      builder: (context) => _ArmDisarmDialog(
        vehicle: vehicle,
        displayName: displayName,
        pois: _pois.whereType<POI>().toList(),
        poiService: _poiService,
        onComplete: () {
          // Reload POIs to get updated armed status
          _loadPOIs();
        },
      ),
    );
  }

  void _showShareLocationOptions(Vehicle vehicle) {
    if (!vehicle.hasLocation) return;

    final displayName = _vehicleCustomNames[vehicle.id] ?? 
                       vehicle.description ?? 
                       vehicle.registration ?? 
                       'Unknown Vehicle';
    
    final lat = vehicle.lastKnownPosition!.latitude;
    final lng = vehicle.lastKnownPosition!.longitude;
    
    // Use platform-specific map URLs
    String mapsUrl;
    String mapProvider;
    
    if (!kIsWeb && defaultTargetPlatform == TargetPlatform.iOS) {
      // iOS: Use Apple Maps
      mapsUrl = 'https://maps.apple.com/?q=$lat,$lng';
      mapProvider = 'Apple Maps';
    } else {
      // Android and Web: Use Google Maps
      mapsUrl = 'https://www.google.com/maps?q=$lat,$lng';
      mapProvider = 'Google Maps';
    }
    
    final message = '''$displayName
Location: $mapsUrl

View on $mapProvider to see the vehicle location.''';

    // Open native share sheet - shows all available apps (WhatsApp, Email, SMS, etc.)
    Share.share(
      message,
      subject: 'Location of $displayName',
    );
  }

  Widget _buildSettingsView() {
    return FutureBuilder<Map<String, dynamic>?>(
      future: _authService.getUserInfo(),
      builder: (context, snapshot) {
        final userInfo = snapshot.data;
        final userEmail = userInfo?['email'] ?? 'Loading...';
        final emailAlertsEnabled = userInfo?['email_alerts_enabled'] ?? true;
        final hasLoaded = snapshot.connectionState == ConnectionState.done;
        
        return Container(
          decoration: BoxDecoration(
            gradient: LinearGradient(
              begin: Alignment.topCenter,
              end: Alignment.bottomCenter,
              colors: [Colors.grey.shade100, Colors.white],
            ),
          ),
          padding: EdgeInsets.only(top: 80, left: 16, right: 16, bottom: 16),
          child: ListView(
            children: [
              SizedBox(height: 24),
              
              // Profile Section
              Container(
                padding: EdgeInsets.all(24),
                decoration: BoxDecoration(
                  gradient: LinearGradient(
                    colors: [AppTheme.brandPrimary, Color(0xFF007A00)],
                  ),
                  borderRadius: BorderRadius.circular(20),
                  boxShadow: [
                    BoxShadow(
                      color: AppTheme.brandPrimary.withOpacity(0.3),
                      blurRadius: 15,
                      offset: Offset(0, 5),
                    ),
                  ],
                ),
                child: Row(
                  children: [
                    Container(
                      padding: EdgeInsets.all(16),
                      decoration: BoxDecoration(
                        color: Colors.white,
                        shape: BoxShape.circle,
                      ),
                      child: Icon(Icons.person, size: 32, color: AppTheme.brandPrimary),
                    ),
                    SizedBox(width: 20),
                    Expanded(
                      child: Column(
                        crossAxisAlignment: CrossAxisAlignment.start,
                        children: [
                          Text(
                            'Welcome Back',
                            style: GoogleFonts.poppins(
                              fontSize: 22,
                              fontWeight: FontWeight.bold,
                              color: Colors.white,
                            ),
                          ),
                          SizedBox(height: 4),
                          Text(
                            '${_vehicles.length} ${_vehicles.length == 1 ? 'tracker' : 'trackers'} active',
                            style: GoogleFonts.inter(
                              fontSize: 14,
                              color: Colors.white.withOpacity(0.9),
                            ),
                          ),
                        ],
                      ),
                    ),
                  ],
                ),
              ),
              
              SizedBox(height: 32),
              
              // Email Notifications Section
              _buildSectionTitle('Email Notifications'),
              SizedBox(height: 12),
              
              Container(
                decoration: BoxDecoration(
                  color: Colors.white,
                  borderRadius: BorderRadius.circular(16),
                  boxShadow: [
                    BoxShadow(
                      color: Colors.black.withOpacity(0.08),
                      blurRadius: 12,
                      offset: Offset(0, 3),
                    ),
                  ],
                ),
                child: Column(
                  children: [
                    // Email Address Row
                    InkWell(
                      onTap: hasLoaded ? () => _showEditEmailDialog(userEmail) : null,
                      borderRadius: BorderRadius.vertical(top: Radius.circular(16)),
                      child: Padding(
                        padding: EdgeInsets.all(20),
                        child: Row(
                          children: [
                            Container(
                              width: 48,
                              height: 48,
                              decoration: BoxDecoration(
                                color: Colors.blue.shade50,
                                borderRadius: BorderRadius.circular(12),
                              ),
                              child: Icon(Icons.email_outlined, color: Colors.blue.shade600, size: 24),
                            ),
                            SizedBox(width: 16),
                            Expanded(
                              child: Column(
                                crossAxisAlignment: CrossAxisAlignment.start,
                                children: [
                                  Text(
                                    'Email Address',
                                    style: GoogleFonts.inter(
                                      fontSize: 16,
                                      fontWeight: FontWeight.w600,
                                      color: Colors.grey.shade900,
                                    ),
                                  ),
                                  SizedBox(height: 4),
                                  Text(
                                    userEmail,
                                    style: GoogleFonts.inter(
                                      fontSize: 14,
                                      color: Colors.grey.shade600,
                                    ),
                                  ),
                                ],
                              ),
                            ),
                            Icon(Icons.edit, color: AppTheme.brandPrimary, size: 20),
                          ],
                        ),
                      ),
                    ),
                    
                    Divider(height: 1, thickness: 1, color: Colors.grey.shade200),
                    
                    // Email Alerts Toggle
                    Padding(
                      padding: EdgeInsets.all(20),
                      child: Row(
                        children: [
                          Container(
                            width: 48,
                            height: 48,
                            decoration: BoxDecoration(
                              color: Colors.orange.shade50,
                              borderRadius: BorderRadius.circular(12),
                            ),
                            child: Icon(Icons.notifications_active, color: Colors.orange.shade600, size: 24),
                          ),
                          SizedBox(width: 16),
                          Expanded(
                            child: Column(
                              crossAxisAlignment: CrossAxisAlignment.start,
                              children: [
                                Text(
                                  'Location Alerts',
                                  style: GoogleFonts.inter(
                                    fontSize: 16,
                                    fontWeight: FontWeight.w600,
                                    color: Colors.grey.shade900,
                                  ),
                                ),
                                SizedBox(height: 4),
                                Text(
                                  emailAlertsEnabled 
                                      ? 'Receiving alerts via email' 
                                      : 'Email alerts disabled',
                                  style: GoogleFonts.inter(
                                    fontSize: 14,
                                    color: Colors.grey.shade600,
                                  ),
                                ),
                              ],
                            ),
                          ),
                          Switch(
                            value: emailAlertsEnabled,
                            onChanged: hasLoaded ? (value) => _toggleEmailAlerts(value) : null,
                            activeColor: Colors.green,
                          ),
                        ],
                      ),
                    ),
                  ],
                ),
              ),
              
              SizedBox(height: 32),
              
              // Quick Actions Section
              _buildSectionTitle('Quick Actions'),
              SizedBox(height: 12),
              
              _buildModernActionTile(
                icon: Icons.add_location_alt,
                iconColor: Colors.green.shade600,
                iconBg: Colors.green.shade50,
                title: 'Add New Tracker',
                subtitle: 'Register a new BLE tag',
                onTap: () async {
                  final result = await Navigator.push(
                    context,
                    MaterialPageRoute(builder: (context) => HomeScreen(skipAutoNavigation: true)),
                  );
                  setState(() {
                    _selectedIndex = 0;
                  });
                  if (result == true) {
                    _loadTags();
                  }
                },
              ),
              
              SizedBox(height: 12),
              
              _buildModernActionTile(
                icon: Icons.refresh_rounded,
                iconColor: Colors.purple.shade600,
                iconBg: Colors.purple.shade50,
                title: 'Refresh GPS Positions',
                subtitle: 'Update all tracker positions',
                onTap: _loadTags,
              ),
              
              SizedBox(height: 12),
              
              _buildModernActionTile(
                icon: Icons.fence,
                iconColor: Colors.blue.shade600,
                iconBg: Colors.blue.shade50,
                title: 'Manage Locations',
                subtitle: 'Create and manage location alerts',
                onTap: () async {
                  final result = await Navigator.pushNamed(context, '/poi-management');
                  _loadPOIs();
                  if (result == 'create') {
                    _showCreatePOIDialog();
                  }
                },
              ),
              
              SizedBox(height: 12),
              
              _buildModernActionTile(
                icon: Icons.add_location,
                iconColor: Colors.green.shade600,
                iconBg: Colors.green.shade50,
                title: 'Create Location',
                subtitle: 'Add a new location alert zone',
                onTap: () => _showCreatePOIDialog(),
              ),
              
              SizedBox(height: 32),
              
              // Logout Button
              Container(
                decoration: BoxDecoration(
                  color: Colors.white,
                  borderRadius: BorderRadius.circular(16),
                  border: Border.all(color: Colors.red.shade200, width: 2),
                  boxShadow: [
                    BoxShadow(
                      color: Colors.red.withOpacity(0.1),
                      blurRadius: 12,
                      offset: Offset(0, 3),
                    ),
                  ],
                ),
                child: InkWell(
                  onTap: () async {
                    final confirm = await showDialog<bool>(
                      context: context,
                      builder: (context) => AlertDialog(
                        shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(16)),
                        title: Row(
                          children: [
                            Icon(Icons.logout, color: Colors.red.shade700),
                            SizedBox(width: 12),
                            Text('Logout'),
                          ],
                        ),
                        content: Text('Are you sure you want to logout?'),
                        actions: [
                          TextButton(
                            onPressed: () => Navigator.pop(context, false),
                            child: Text('Cancel'),
                          ),
                          ElevatedButton(
                            onPressed: () => Navigator.pop(context, true),
                            style: ElevatedButton.styleFrom(
                              backgroundColor: Colors.red.shade700,
                              foregroundColor: Colors.white,
                            ),
                            child: Text('Logout'),
                          ),
                        ],
                      ),
                    );
                    
                    if (confirm == true) {
                      await _authService.logout();
                      if (mounted) {
                        Navigator.pushNamedAndRemoveUntil(context, '/welcome', (route) => false);
                      }
                    }
                  },
                  borderRadius: BorderRadius.circular(16),
                  child: Padding(
                    padding: EdgeInsets.all(20),
                    child: Row(
                      mainAxisAlignment: MainAxisAlignment.center,
                      children: [
                        Icon(Icons.logout, color: Colors.red.shade700, size: 24),
                        SizedBox(width: 12),
                        Text(
                          'Logout',
                          style: GoogleFonts.inter(
                            fontSize: 18,
                            fontWeight: FontWeight.w600,
                            color: Colors.red.shade700,
                          ),
                        ),
                      ],
                    ),
                  ),
                ),
              ),
              
              SizedBox(height: 24),
            ],
          ),
        );
      },
    );
  }
  
  Widget _buildSectionTitle(String title) {
    return Text(
      title,
      style: GoogleFonts.poppins(
        fontSize: 18,
        fontWeight: FontWeight.w700,
        color: Colors.grey.shade800,
        letterSpacing: 0.5,
      ),
    );
  }
  
  Widget _buildModernActionTile({
    required IconData icon,
    required Color iconColor,
    required Color iconBg,
    required String title,
    required String subtitle,
    required VoidCallback onTap,
  }) {
    return Container(
      decoration: BoxDecoration(
        color: Colors.white,
        borderRadius: BorderRadius.circular(16),
        boxShadow: [
          BoxShadow(
            color: Colors.black.withOpacity(0.08),
            blurRadius: 12,
            offset: Offset(0, 3),
          ),
        ],
      ),
      child: InkWell(
        onTap: onTap,
        borderRadius: BorderRadius.circular(16),
        child: Padding(
          padding: EdgeInsets.all(20),
          child: Row(
            children: [
              Container(
                width: 48,
                height: 48,
                decoration: BoxDecoration(
                  color: iconBg,
                  borderRadius: BorderRadius.circular(12),
                ),
                child: Icon(icon, color: iconColor, size: 24),
              ),
              SizedBox(width: 16),
              Expanded(
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Text(
                      title,
                      style: GoogleFonts.inter(
                        fontSize: 16,
                        fontWeight: FontWeight.w600,
                        color: Colors.grey.shade900,
                      ),
                    ),
                    SizedBox(height: 4),
                    Text(
                      subtitle,
                      style: GoogleFonts.inter(
                        fontSize: 14,
                        color: Colors.grey.shade600,
                      ),
                    ),
                  ],
                ),
              ),
              Icon(Icons.chevron_right, color: Colors.grey.shade400, size: 24),
            ],
          ),
        ),
      ),
    );
  }
  
  Future<void> _showEditEmailDialog(String currentEmail) async {
    final emailController = TextEditingController(text: currentEmail);
    
    final result = await showDialog<String>(
      context: context,
      builder: (context) => AlertDialog(
        shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(16)),
        title: Row(
          children: [
            Icon(Icons.email, color: AppTheme.brandPrimary),
            SizedBox(width: 12),
            Text('Update Email'),
          ],
        ),
        content: Column(
          mainAxisSize: MainAxisSize.min,
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Text(
              'Enter your new email address',
              style: TextStyle(fontSize: 14, color: Colors.grey[600]),
            ),
            SizedBox(height: 16),
            TextField(
              controller: emailController,
              keyboardType: TextInputType.emailAddress,
              decoration: InputDecoration(
                labelText: 'Email Address',
                hintText: 'your@email.com',
                prefixIcon: Icon(Icons.email_outlined),
                border: OutlineInputBorder(
                  borderRadius: BorderRadius.circular(12),
                ),
                focusedBorder: OutlineInputBorder(
                  borderRadius: BorderRadius.circular(12),
                  borderSide: BorderSide(color: AppTheme.brandPrimary, width: 2),
                ),
              ),
            ),
          ],
        ),
        actions: [
          TextButton(
            onPressed: () => Navigator.pop(context),
            child: Text('Cancel'),
          ),
          ElevatedButton(
            onPressed: () {
              final newEmail = emailController.text.trim();
              if (newEmail.isEmpty || !newEmail.contains('@')) {
                ScaffoldMessenger.of(context).showSnackBar(
                  SnackBar(
                    content: Text('Please enter a valid email address'),
                    backgroundColor: Colors.red,
                  ),
                );
                return;
              }
              Navigator.pop(context, newEmail);
            },
            style: ElevatedButton.styleFrom(
              backgroundColor: AppTheme.brandPrimary,
              foregroundColor: Colors.white,
              shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(12)),
            ),
            child: Text('Update'),
          ),
        ],
      ),
    );
    
    if (result != null && result.isNotEmpty && result != currentEmail) {
      await _updateUserEmail(result);
    }
  }
  
  Future<void> _updateUserEmail(String newEmail) async {
    try {
      final response = await _authService.updateUserEmail(newEmail);
      
      if (response['success'] == true) {
        if (mounted) {
          setState(() {});
          ScaffoldMessenger.of(context).showSnackBar(
            SnackBar(
              content: Row(
                children: [
                  Icon(Icons.check_circle, color: Colors.white),
                  SizedBox(width: 12),
                  Text('Email updated successfully'),
                ],
              ),
              backgroundColor: Colors.green,
              behavior: SnackBarBehavior.floating,
              shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(12)),
            ),
          );
        }
      } else {
        throw Exception(response['error'] ?? 'Failed to update email');
      }
    } catch (e) {
      if (mounted) {
        ScaffoldMessenger.of(context).showSnackBar(
          SnackBar(
            content: Row(
              children: [
                Icon(Icons.error, color: Colors.white),
                SizedBox(width: 12),
                Expanded(child: Text('Failed to update email: $e')),
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
  
  Future<void> _toggleEmailAlerts(bool value) async {
    try {
      final response = await _authService.updateUserPreferences(
        emailAlertsEnabled: value,
      );
      
      if (response['success'] == true) {
        if (mounted) {
          setState(() {});
          ScaffoldMessenger.of(context).showSnackBar(
            SnackBar(
              content: Row(
                children: [
                  Icon(
                    value ? Icons.notifications_active : Icons.notifications_off, 
                    color: Colors.white,
                  ),
                  SizedBox(width: 12),
                  Text(value ? 'Email alerts enabled' : 'Email alerts disabled'),
                ],
              ),
              backgroundColor: value ? Colors.green : Colors.orange,
              behavior: SnackBarBehavior.floating,
              shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(12)),
            ),
          );
        }
      } else {
        throw Exception('Failed to update preferences');
      }
    } catch (e) {
      if (mounted) {
        ScaffoldMessenger.of(context).showSnackBar(
          SnackBar(
            content: Row(
              children: [
                Icon(Icons.error, color: Colors.white),
                SizedBox(width: 12),
                Expanded(child: Text('Failed to update: $e')),
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
  
  // ==================== Trips/Journeys Helper Methods ====================
  
  Widget _buildDateChip(String label) {
    final isSelected = _selectedDateRange == label;
    return GestureDetector(
      onTap: () {
        if (label == 'Custom') {
          _showCustomDateRangePicker();
        } else {
          setState(() {
            _selectedDateRange = label;
            _customStartDate = null;
            _customEndDate = null;
          });
          _loadTrips();
        }
      },
      child: Container(
        padding: EdgeInsets.symmetric(horizontal: 16, vertical: 8),
        decoration: BoxDecoration(
          color: isSelected ? AppTheme.brandPrimary : Colors.white,
          borderRadius: BorderRadius.circular(20),
          border: Border.all(
            color: isSelected ? AppTheme.brandPrimary : Colors.grey.shade300,
          ),
        ),
        child: Text(
          label,
          style: GoogleFonts.inter(
            fontSize: 13,
            fontWeight: isSelected ? FontWeight.w600 : FontWeight.w400,
            color: isSelected ? Colors.white : Colors.grey.shade700,
          ),
        ),
      ),
    );
  }
  
  Future<void> _showCustomDateRangePicker() async {
    final now = DateTime.now();
    final initialStart = _customStartDate ?? now.subtract(Duration(days: 7));
    final initialEnd = _customEndDate ?? now;

    showDialog(
      context: context,
      builder: (context) => _CustomDateRangeDialog(
        initialStartDate: initialStart,
        initialEndDate: initialEnd,
        onDateRangeSelected: (startDate, endDate) {
          setState(() {
            _selectedDateRange = 'Custom';
            _customStartDate = startDate;
            _customEndDate = endDate;
          });
          _loadTrips();
        },
      ),
    );
  }
  
  Widget _buildTripCard(Trip trip) {
    final isSelected = _selectedTrip?.id == trip.id;
    return Container(
      margin: EdgeInsets.only(bottom: 12),
      decoration: BoxDecoration(
        color: Colors.white,
        borderRadius: BorderRadius.circular(12),
        border: Border.all(
          color: isSelected ? AppTheme.brandPrimary : Colors.transparent,
          width: 2,
        ),
        boxShadow: [
          BoxShadow(
            color: Colors.black.withOpacity(0.05),
            blurRadius: 8,
            offset: Offset(0, 2),
          ),
        ],
      ),
      child: Material(
        color: Colors.transparent,
        child: InkWell(
          borderRadius: BorderRadius.circular(12),
          onTap: () => _showTripRoute(trip),
          child: Padding(
            padding: EdgeInsets.all(16),
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                // Date
                Row(
                  children: [
                    Icon(Icons.calendar_today, size: 16, color: Colors.grey.shade600),
                    SizedBox(width: 6),
                    Text(
                      trip.dateFormatted,
                      style: GoogleFonts.inter(
                        fontSize: 14,
                        fontWeight: FontWeight.w600,
                        color: Colors.grey.shade800,
                      ),
                    ),
                  ],
                ),
                SizedBox(height: 8),
                // Time range
                Row(
                  children: [
                    Icon(Icons.access_time, size: 16, color: Colors.grey.shade600),
                    SizedBox(width: 6),
                    Text(
                      '${trip.startTimeFormatted} - ${trip.endTimeFormatted}',
                      style: GoogleFonts.inter(
                        fontSize: 15,
                        fontWeight: FontWeight.w600,
                        color: Colors.grey.shade900,
                      ),
                    ),
                    Spacer(),
                    // Distance badge
                    Container(
                      padding: EdgeInsets.symmetric(horizontal: 8, vertical: 4),
                      decoration: BoxDecoration(
                        color: Colors.blue.shade50,
                        borderRadius: BorderRadius.circular(6),
                      ),
                      child: Row(
                        mainAxisSize: MainAxisSize.min,
                        children: [
                          Icon(Icons.straighten, size: 12, color: Colors.blue.shade700),
                          SizedBox(width: 4),
                          Text(
                            trip.formattedDistance,
                            style: GoogleFonts.inter(
                              fontSize: 12,
                              fontWeight: FontWeight.w600,
                              color: Colors.blue.shade700,
                            ),
                          ),
                        ],
                      ),
                    ),
                    SizedBox(width: 6),
                    // Duration badge
                    Container(
                      padding: EdgeInsets.symmetric(horizontal: 8, vertical: 4),
                      decoration: BoxDecoration(
                        color: Colors.orange.shade50,
                        borderRadius: BorderRadius.circular(6),
                      ),
                      child: Row(
                        mainAxisSize: MainAxisSize.min,
                        children: [
                          Icon(Icons.timer, size: 12, color: Colors.orange.shade700),
                          SizedBox(width: 4),
                          Text(
                            trip.formattedDuration,
                            style: GoogleFonts.inter(
                              fontSize: 12,
                              fontWeight: FontWeight.w600,
                              color: Colors.orange.shade700,
                            ),
                          ),
                        ],
                      ),
                    ),
                  ],
                ),
                SizedBox(height: 12),
                // Start location
                Row(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Container(
                      padding: EdgeInsets.all(6),
                      decoration: BoxDecoration(
                        color: Colors.green.shade50,
                        shape: BoxShape.circle,
                      ),
                      child: Icon(Icons.trip_origin, size: 14, color: Colors.green.shade700),
                    ),
                    SizedBox(width: 10),
                    Expanded(
                      child: Text(
                        trip.startLocationDescription ?? 'Start location',
                        style: GoogleFonts.inter(
                          fontSize: 13,
                          color: Colors.grey.shade700,
                        ),
                        maxLines: 2,
                        overflow: TextOverflow.ellipsis,
                      ),
                    ),
                  ],
                ),
                SizedBox(height: 8),
                // End location
                Row(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Container(
                      padding: EdgeInsets.all(6),
                      decoration: BoxDecoration(
                        color: Colors.red.shade50,
                        shape: BoxShape.circle,
                      ),
                      child: Icon(Icons.place, size: 14, color: Colors.red.shade700),
                    ),
                    SizedBox(width: 10),
                    Expanded(
                      child: Text(
                        trip.endLocationDescription ?? 'End location',
                        style: GoogleFonts.inter(
                          fontSize: 13,
                          color: Colors.grey.shade700,
                        ),
                        maxLines: 2,
                        overflow: TextOverflow.ellipsis,
                      ),
                    ),
                  ],
                ),
                // Driver info
                if (trip.driverDescription != null) ...[
                  SizedBox(height: 8),
                  Row(
                    children: [
                      Icon(Icons.person, size: 14, color: Colors.grey.shade500),
                      SizedBox(width: 6),
                      Text(
                        trip.driverDescription!,
                        style: GoogleFonts.inter(
                          fontSize: 12,
                          color: Colors.grey.shade600,
                        ),
                      ),
                    ],
                  ),
                ],
                // View route button
                SizedBox(height: 12),
                Row(
                  mainAxisAlignment: MainAxisAlignment.end,
                  children: [
                    Text(
                      'Tap to view route',
                      style: GoogleFonts.inter(
                        fontSize: 12,
                        fontWeight: FontWeight.w500,
                        color: AppTheme.brandPrimary,
                      ),
                    ),
                    SizedBox(width: 4),
                    Icon(
                      Icons.map,
                      size: 14,
                      color: AppTheme.brandPrimary,
                    ),
                  ],
                ),
              ],
            ),
          ),
        ),
      ),
    );
  }
  
  /// Filter out trips with distance 0km or no distance data
  List<Trip> _getFilteredTrips() {
    return _trips.where((trip) {
      return trip.distance != null && trip.distance! >= 0.1;
    }).toList();
  }
  
  Future<void> _loadTrips() async {
    if (_vehicles.isEmpty) return;
    
    // Set selected vehicle if not set
    _selectedTripVehicle ??= _vehicles.first;
    
    if (_selectedTripVehicle == null) return;
    
    setState(() {
      _isLoadingTrips = true;
    });
    
    try {
      // Get date range based on selection
      DateRange dateRange;
      switch (_selectedDateRange) {
        case 'Yesterday':
          dateRange = DateRange.yesterday();
          break;
        case 'Custom':
          if (_customStartDate != null && _customEndDate != null) {
            dateRange = DateRange(
              startDate: _customStartDate!,
              endDate: _customEndDate!,
            );
          } else {
            dateRange = DateRange.today();
          }
          break;
        default: // 'Today'
          dateRange = DateRange.today();
      }
      
      final allTrips = await _locationService.getTrips(
        vehicleId: _selectedTripVehicle!.id,
        startDate: dateRange.startDate,
        endDate: dateRange.endDate,
      );
      
      // Filter out trips with 0km distance (including very short trips < 0.1km)
      final filteredTrips = allTrips.where((trip) {
        return trip.distance != null && trip.distance! >= 0.1;
      }).toList();
      
      if (mounted) {
        setState(() {
          _trips = filteredTrips;
          _isLoadingTrips = false;
          // Clear selected trip if it's not in the new list
          if (_selectedTrip != null && !filteredTrips.any((t) => t.id == _selectedTrip!.id)) {
            _selectedTrip = null;
            _selectedTripRoute = null;
            _clearTripRoute();
          }
        });
      }
    } catch (e) {
      _logger.error('Failed to load trips: $e');
      
      // Check if this is a deployment error (HTML response, syntax error, etc.)
      if (DeploymentMonitorService.isDeploymentError(e)) {
        print('🔄 Detected deployment in progress...');
        _deploymentMonitor.detectDeploymentInProgress();
        
        // Listen for deployment completion and retry
        _deploymentMonitor.deploymentStateChanged.where((isDeploying) => !isDeploying).listen((_) {
          if (mounted) {
            print('✅ Deployment complete, reloading trips...');
            _loadTrips();
          }
        });
        
        if (mounted) {
          setState(() {
            _isLoadingTrips = false;
            _trips = [];
          });
        }
        return;
      }
      
      if (mounted) {
        setState(() {
          _isLoadingTrips = false;
          _trips = [];
        });
        ScaffoldMessenger.of(context).showSnackBar(
          SnackBar(
            content: Row(
              children: [
                Icon(Icons.error, color: Colors.white),
                SizedBox(width: 12),
                Expanded(child: Text('Failed to load trips: $e')),
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
  
  Future<void> _showTripRoute(Trip trip) async {
    // The custom name is stored in vehicle.description (set as device_name by user).
    // _vehicleCustomNames map may be empty; use vehicle.description as the authoritative name.
    final effectiveVehicle = _selectedTripVehicle ?? (_vehicles.isNotEmpty ? _vehicles.first : null);
    final customName = effectiveVehicle != null
        ? (_vehicleCustomNames[effectiveVehicle.id] ?? effectiveVehicle.description)
        : null;
    Navigator.push(
      context,
      MaterialPageRoute(
        builder: (context) => TripDetailScreen(trip: trip, customAssetName: customName),
      ),
    );
  }
  
  void _drawTripRoute(List<TripEvent> events) {
    if (events.isEmpty) return;
    
    // Create polyline for flutter_map
    final points = events.map((e) => latlong.LatLng(e.latitude, e.longitude)).toList();
    
    final polyline = fmap.Polyline(
      points: points,
      color: Colors.blue,
      strokeWidth: 4.0,
    );
    
    // Create start marker
    final startEvent = events.first;
    final startMarker = fmap.Marker(
      point: latlong.LatLng(startEvent.latitude, startEvent.longitude),
      width: 40,
      height: 40,
      child: Icon(
        Icons.trip_origin,
        color: Colors.green,
        size: 30,
      ),
    );
    
    // Create end marker
    final endEvent = events.last;
    final endMarker = fmap.Marker(
      point: latlong.LatLng(endEvent.latitude, endEvent.longitude),
      width: 40,
      height: 40,
      child: Icon(
        Icons.place,
        color: Colors.red,
        size: 30,
      ),
    );
    
    setState(() {
      _tripRoutePolylines = [polyline];
      _tripRouteMarkers = [startMarker, endMarker];
    });
    
    // Zoom map to show full route
    _zoomToRoute(points);
  }
  
  void _clearTripRoute() {
    setState(() {
      _tripRoutePolylines = [];
      _tripRouteMarkers = [];
    });
  }
  
  void _zoomToRoute(List<latlong.LatLng> points) {
    if (points.isEmpty) return;
    
    // Calculate bounds
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
    
    // Calculate center and zoom
    final centerLat = (minLat + maxLat) / 2;
    final centerLng = (minLng + maxLng) / 2;
    
    // Fit bounds with padding
    _flutterMapController.move(
      latlong.LatLng(centerLat, centerLng),
      13.0, // Default zoom level
    );
  }
}

/// Stateful dialog for arm/disarm with location checkboxes
class _ArmDisarmDialog extends StatefulWidget {
  final Vehicle vehicle;
  final String displayName;
  final List<POI> pois;
  final POIService poiService;
  final VoidCallback onComplete;

  const _ArmDisarmDialog({
    required this.vehicle,
    required this.displayName,
    required this.pois,
    required this.poiService,
    required this.onComplete,
  });

  @override
  State<_ArmDisarmDialog> createState() => _ArmDisarmDialogState();
}

class _ArmDisarmDialogState extends State<_ArmDisarmDialog> {
  late Map<String, bool> _armedStatus;
  bool _isSaving = false;

  @override
  void initState() {
    super.initState();
    // Initialize armed status for each POI
    _armedStatus = {};
    for (var poi in widget.pois) {
      _armedStatus[poi.id] = poi.isArmedTo(widget.vehicle.id);
    }
  }

  Future<void> _saveChanges() async {
    setState(() => _isSaving = true);
    
    try {
      // Process each POI and update its armed status
      for (var poi in widget.pois) {
        final currentlyArmed = poi.isArmedTo(widget.vehicle.id);
        final shouldBeArmed = _armedStatus[poi.id] ?? false;
        
        // Only make API call if status changed
        if (currentlyArmed != shouldBeArmed) {
          if (shouldBeArmed) {
            await widget.poiService.armPOI(poi.id, widget.vehicle.id);
          } else {
            await widget.poiService.disarmPOI(poi.id, widget.vehicle.id);
          }
        }
      }
      
      if (mounted) {
        Navigator.of(context).pop();
        ScaffoldMessenger.of(context).showSnackBar(
          SnackBar(
            content: Text('✅ Armed status updated'),
            backgroundColor: Colors.green,
          ),
        );
        // Call onComplete to reload POIs
        widget.onComplete();
      }
    } catch (e) {
      if (mounted) {
        setState(() => _isSaving = false);
        ScaffoldMessenger.of(context).showSnackBar(
          SnackBar(
            content: Text('❌ Failed to update: $e'),
            backgroundColor: Colors.red,
          ),
        );
      }
    }
  }

  @override
  Widget build(BuildContext context) {
    final isArmedToAny = _armedStatus.values.any((armed) => armed);
    
    return AlertDialog(
      title: Row(
        children: [
          Icon(
            Icons.security,
            color: isArmedToAny ? Colors.green.shade700 : Colors.red.shade700,
          ),
          SizedBox(width: 8),
          Expanded(
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Text(
                  'Arm/Disarm Locations',
                  style: GoogleFonts.poppins(
                    fontWeight: FontWeight.w600,
                    fontSize: 18,
                  ),
                ),
                Text(
                  widget.displayName,
                  style: GoogleFonts.inter(
                    fontSize: 12,
                    color: Colors.grey.shade600,
                    fontWeight: FontWeight.normal,
                  ),
                ),
              ],
            ),
          ),
        ],
      ),
      content: Container(
        width: 400,
        child: widget.pois.isEmpty
          ? Padding(
              padding: EdgeInsets.all(24),
              child: Column(
                mainAxisSize: MainAxisSize.min,
                children: [
                  Icon(Icons.location_off, size: 48, color: Colors.grey),
                  SizedBox(height: 16),
                  Text(
                    'No locations created yet',
                    style: GoogleFonts.inter(color: Colors.grey.shade600),
                  ),
                  SizedBox(height: 8),
                  Text(
                    'Create a location to enable arming',
                    style: GoogleFonts.inter(
                      fontSize: 12,
                      color: Colors.grey.shade500,
                    ),
                    textAlign: TextAlign.center,
                  ),
                ],
              ),
            )
          : SingleChildScrollView(
              child: Column(
                mainAxisSize: MainAxisSize.min,
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Text(
                    'Select locations to monitor for this asset:',
                    style: GoogleFonts.inter(
                      fontSize: 13,
                      color: Colors.grey.shade700,
                    ),
                  ),
                  SizedBox(height: 12),
                  ...widget.pois.map((poi) {
                    final isArmed = _armedStatus[poi.id] ?? false;
                    return CheckboxListTile(
                      value: isArmed,
                      onChanged: _isSaving ? null : (value) {
                        setState(() {
                          _armedStatus[poi.id] = value ?? false;
                        });
                      },
                      title: Text(
                        poi.name,
                        style: GoogleFonts.poppins(
                          fontWeight: FontWeight.w500,
                          fontSize: 14,
                        ),
                      ),
                      subtitle: poi.description != null
                        ? Text(
                            poi.description!,
                            style: GoogleFonts.inter(fontSize: 11),
                          )
                        : null,
                      secondary: Icon(
                        poi.poiType == POIType.route
                          ? Icons.route
                          : Icons.location_on,
                        color: isArmed ? Colors.green.shade700 : Colors.grey,
                      ),
                      activeColor: Colors.green.shade700,
                    );
                  }).toList(),
                ],
              ),
            ),
      ),
      actions: [
        TextButton(
          onPressed: _isSaving ? null : () => Navigator.of(context).pop(),
          child: Text('Cancel'),
        ),
        if (widget.pois.isNotEmpty)
          ElevatedButton(
            onPressed: _isSaving ? null : _saveChanges,
            style: ElevatedButton.styleFrom(
              backgroundColor: AppTheme.brandPrimary,
              foregroundColor: Colors.white,
            ),
            child: _isSaving
              ? SizedBox(
                  width: 16,
                  height: 16,
                  child: CircularProgressIndicator(
                    strokeWidth: 2,
                    valueColor: AlwaysStoppedAnimation<Color>(Colors.white),
                  ),
                )
              : Text('Save'),
          ),
      ],
    );
  }
}

class _CustomDateRangeDialog extends StatefulWidget {
  final DateTime initialStartDate;
  final DateTime initialEndDate;
  final Function(DateTime, DateTime) onDateRangeSelected;

  const _CustomDateRangeDialog({
    Key? key,
    required this.initialStartDate,
    required this.initialEndDate,
    required this.onDateRangeSelected,
  }) : super(key: key);

  @override
  State<_CustomDateRangeDialog> createState() => _CustomDateRangeDialogState();
}

class _CustomDateRangeDialogState extends State<_CustomDateRangeDialog> {
  late DateTime _startDate;
  late DateTime _endDate;

  @override
  void initState() {
    super.initState();
    _startDate = widget.initialStartDate;
    _endDate = widget.initialEndDate;
  }

  Future<void> _selectStartDate() async {
    final picked = await showDatePicker(
      context: context,
      initialDate: _startDate,
      firstDate: DateTime(2020),
      lastDate: _endDate,
    );
    if (picked != null) {
      setState(() {
        _startDate = picked;
      });
    }
  }

  Future<void> _selectEndDate() async {
    final picked = await showDatePicker(
      context: context,
      initialDate: _endDate,
      firstDate: _startDate,
      lastDate: DateTime.now(),
    );
    if (picked != null) {
      setState(() {
        _endDate = picked;
      });
    }
  }

  @override
  Widget build(BuildContext context) {
    return Dialog(
      shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(16)),
      child: Container(
        padding: EdgeInsets.all(24),
        child: Column(
          mainAxisSize: MainAxisSize.min,
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Text(
              'Select Date Range',
              style: GoogleFonts.poppins(
                fontSize: 18,
                fontWeight: FontWeight.w700,
                color: AppTheme.brandPrimary,
              ),
            ),
            SizedBox(height: 24),
            // Start Date
            Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Text(
                  'Start Date',
                  style: GoogleFonts.inter(
                    fontSize: 13,
                    fontWeight: FontWeight.w600,
                    color: Colors.grey.shade700,
                  ),
                ),
                SizedBox(height: 8),
                InkWell(
                  onTap: _selectStartDate,
                  borderRadius: BorderRadius.circular(12),
                  child: Container(
                    padding: EdgeInsets.all(12),
                    decoration: BoxDecoration(
                      border: Border.all(color: Colors.grey.shade300),
                      borderRadius: BorderRadius.circular(12),
                      color: Colors.grey.shade50,
                    ),
                    child: Row(
                      mainAxisAlignment: MainAxisAlignment.spaceBetween,
                      children: [
                        Text(
                          _formatDate(_startDate),
                          style: GoogleFonts.inter(
                            fontSize: 14,
                            fontWeight: FontWeight.w500,
                            color: AppTheme.brandPrimary,
                          ),
                        ),
                        Icon(Icons.calendar_today, color: AppTheme.brandPrimary, size: 20),
                      ],
                    ),
                  ),
                ),
              ],
            ),
            SizedBox(height: 16),
            // End Date
            Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Text(
                  'End Date',
                  style: GoogleFonts.inter(
                    fontSize: 13,
                    fontWeight: FontWeight.w600,
                    color: Colors.grey.shade700,
                  ),
                ),
                SizedBox(height: 8),
                InkWell(
                  onTap: _selectEndDate,
                  borderRadius: BorderRadius.circular(12),
                  child: Container(
                    padding: EdgeInsets.all(12),
                    decoration: BoxDecoration(
                      border: Border.all(color: Colors.grey.shade300),
                      borderRadius: BorderRadius.circular(12),
                      color: Colors.grey.shade50,
                    ),
                    child: Row(
                      mainAxisAlignment: MainAxisAlignment.spaceBetween,
                      children: [
                        Text(
                          _formatDate(_endDate),
                          style: GoogleFonts.inter(
                            fontSize: 14,
                            fontWeight: FontWeight.w500,
                            color: AppTheme.brandPrimary,
                          ),
                        ),
                        Icon(Icons.calendar_today, color: AppTheme.brandPrimary, size: 20),
                      ],
                    ),
                  ),
                ),
              ],
            ),
            SizedBox(height: 24),
            // Date range display
            Container(
              padding: EdgeInsets.all(12),
              decoration: BoxDecoration(
                color: AppTheme.brandPrimary.withOpacity(0.1),
                borderRadius: BorderRadius.circular(12),
              ),
              child: Row(
                children: [
                  Icon(Icons.info_outline, size: 18, color: AppTheme.brandPrimary),
                  SizedBox(width: 12),
                  Expanded(
                    child: Text(
                      '${_getDayCount()} days selected',
                      style: GoogleFonts.inter(
                        fontSize: 13,
                        color: AppTheme.brandPrimary,
                      ),
                    ),
                  ),
                ],
              ),
            ),
            SizedBox(height: 24),
            // Action buttons
            Row(
              mainAxisAlignment: MainAxisAlignment.end,
              children: [
                TextButton(
                  onPressed: () => Navigator.pop(context),
                  child: Text(
                    'Cancel',
                    style: GoogleFonts.inter(
                      fontSize: 14,
                      fontWeight: FontWeight.w600,
                      color: Colors.grey.shade700,
                    ),
                  ),
                ),
                SizedBox(width: 12),
                ElevatedButton(
                  onPressed: () {
                    widget.onDateRangeSelected(_startDate, _endDate);
                    Navigator.pop(context);
                  },
                  style: ElevatedButton.styleFrom(
                    backgroundColor: AppTheme.brandPrimary,
                    foregroundColor: Colors.white,
                    padding: EdgeInsets.symmetric(horizontal: 24, vertical: 12),
                    shape: RoundedRectangleBorder(
                      borderRadius: BorderRadius.circular(8),
                    ),
                  ),
                  child: Text(
                    'Apply',
                    style: GoogleFonts.inter(
                      fontSize: 14,
                      fontWeight: FontWeight.w600,
                    ),
                  ),
                ),
              ],
            ),
          ],
        ),
      ),
    );
  }

  String _formatDate(DateTime date) {
    final months = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'];
    return '${months[date.month - 1]} ${date.day}, ${date.year}';
  }

  int _getDayCount() {
    return _endDate.difference(_startDate).inDays + 1;
  }
}

/// Simple data holder used by [_MapScreenState._buildNavItems].
class _NavSpec {
  final IconData icon;
  final String label;
  final int index;
  const _NavSpec({required this.icon, required this.label, required this.index});
}

