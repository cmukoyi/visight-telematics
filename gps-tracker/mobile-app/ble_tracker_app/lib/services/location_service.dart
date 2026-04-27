import 'dart:convert';
import 'package:flutter/foundation.dart';
import 'package:http/http.dart' as http;
import 'package:shared_preferences/shared_preferences.dart';
import 'package:ble_tracker_app/services/logger_service.dart';
import 'package:ble_tracker_app/config/environment.dart';
import 'package:ble_tracker_app/models/trip_model.dart';

/// Helper class for date range formatting
class DateRange {
  final DateTime startDate;
  final DateTime endDate;
  
  DateRange({required this.startDate, required this.endDate});
  
  /// Format start date for API (ISO without milliseconds, UTC)
  String get startDateFormatted {
    final utc = startDate.toUtc();
    return '${utc.year.toString().padLeft(4, '0')}-${utc.month.toString().padLeft(2, '0')}-${utc.day.toString().padLeft(2, '0')}T${utc.hour.toString().padLeft(2, '0')}:${utc.minute.toString().padLeft(2, '0')}:${utc.second.toString().padLeft(2, '0')}Z';
  }
  
  /// Format end date for API (ISO without milliseconds, UTC)
  String get endDateFormatted {
    final utc = endDate.toUtc();
    return '${utc.year.toString().padLeft(4, '0')}-${utc.month.toString().padLeft(2, '0')}-${utc.day.toString().padLeft(2, '0')}T${utc.hour.toString().padLeft(2, '0')}:${utc.minute.toString().padLeft(2, '0')}:${utc.second.toString().padLeft(2, '0')}Z';
  }
  
  /// Get date range for today (00:00 to 23:59:59)
  static DateRange today() {
    final now = DateTime.now();
    return DateRange(
      startDate: DateTime(now.year, now.month, now.day),
      endDate: DateTime(now.year, now.month, now.day, 23, 59, 59),
    );
  }
  
  /// Get date range for yesterday
  static DateRange yesterday() {
    final now = DateTime.now();
    final yesterday = now.subtract(const Duration(days: 1));
    return DateRange(
      startDate: DateTime(yesterday.year, yesterday.month, yesterday.day),
      endDate: DateTime(yesterday.year, yesterday.month, yesterday.day, 23, 59, 59),
    );
  }
  
  /// Get date range for this week (Monday to Sunday)
  static DateRange thisWeek() {
    final now = DateTime.now();
    final weekday = now.weekday; // 1=Monday, 7=Sunday
    final monday = now.subtract(Duration(days: weekday - 1));
    final sunday = monday.add(const Duration(days: 6));
    return DateRange(
      startDate: DateTime(monday.year, monday.month, monday.day),
      endDate: DateTime(sunday.year, sunday.month, sunday.day, 23, 59, 59),
    );
  }
  
  /// Get date range for previous week
  static DateRange previousWeek() {
    final now = DateTime.now();
    final weekday = now.weekday;
    final lastMonday = now.subtract(Duration(days: weekday + 6));
    final lastSunday = lastMonday.add(const Duration(days: 6));
    return DateRange(
      startDate: DateTime(lastMonday.year, lastMonday.month, lastMonday.day),
      endDate: DateTime(lastSunday.year, lastSunday.month, lastSunday.day, 23, 59, 59),
    );
  }
  
  /// Get date range for this month
  static DateRange thisMonth() {
    final now = DateTime.now();
    final firstDay = DateTime(now.year, now.month, 1);
    final lastDay = DateTime(now.year, now.month + 1, 0, 23, 59, 59);
    return DateRange(startDate: firstDay, endDate: lastDay);
  }
  
  /// Get date range for previous month
  static DateRange previousMonth() {
    final now = DateTime.now();
    final firstDay = DateTime(now.year, now.month - 1, 1);
    final lastDay = DateTime(now.year, now.month, 0, 23, 59, 59);
    return DateRange(startDate: firstDay, endDate: lastDay);
  }
}

/// Service for fetching vehicle locations from mzone API via backend
class LocationService {
  // Singleton pattern
  static final LocationService _instance = LocationService._internal();
  factory LocationService() => _instance;
  LocationService._internal();
  
  final _logger = LoggerService();
  
  // Backend URL from environment configuration (production by default)
  static String get backendUrl => Environment.apiBaseUrl;
  
  /// Get auth token from storage
  Future<String?> _getAuthToken() async {
    final prefs = await SharedPreferences.getInstance();
    return prefs.getString('auth_token');
  }
  
  /// Fetch vehicles from backend with their locations
  /// Backend uses user's stored IMEIs (no need to send them)
  Future<Map<String, dynamic>> getVehicleLocations() async {
    try {
      _logger.info('getVehicleLocations: Starting fetch');
      print('\n========== LOCATION SERVICE START ==========');
      print('⏰ Timestamp: ${DateTime.now().toIso8601String()}');
      print('📍 Fetching vehicle locations from backend');
      print('🌐 Backend URL: $backendUrl');
      
      // Get auth token
      print('🔑 Getting auth token from storage...');
      final authToken = await _getAuthToken();
      
      if (authToken == null) {
        _logger.error('getVehicleLocations: No auth token found');
        print('❌ ERROR: No auth token found in storage!');
        print('📋 Checking SharedPreferences keys...');
        final prefs = await SharedPreferences.getInstance();
        final keys = prefs.getKeys();
        print('   Available keys: $keys');
        throw Exception('No authentication token found');
      }
      
      _logger.success('getVehicleLocations: Auth token found');
      print('✅ Auth token found: ${authToken.substring(0, 20)}...');
      
      // Call backend API (backend uses user's stored IMEIs)
      final url = Uri.parse('$backendUrl/api/vehicles');
      _logger.network('POST $url');
      print('📡 Calling: POST $url');
      print('📤 Headers: Authorization: Bearer ${authToken.substring(0, 20)}...');
      print('📦 Body: {}');
      
      final startTime = DateTime.now();
      final response = await http.post(
        url,
        headers: {
          'Content-Type': 'application/json',
          'Authorization': 'Bearer $authToken',
        },
        body: json.encode({}), // Empty payload - backend uses stored IMEIs
      ).timeout(const Duration(seconds: 30));
      
      final duration = DateTime.now().difference(startTime);
      _logger.network('Response ${response.statusCode} in ${duration.inMilliseconds}ms');
      print('⏱️  Response received in ${duration.inMilliseconds}ms');
      print('📊 Response status: ${response.statusCode}');
      print('📄 Response body: ${response.body}');
      
      if (response.statusCode == 200) {
        final data = json.decode(response.body);
        final vehicleCount = data['found_vehicles'] ?? data['vehicles']?.length ?? 0;
        _logger.success('getVehicleLocations: Found $vehicleCount vehicles');
        print('✅ SUCCESS: Found $vehicleCount vehicles');
        print('📋 Response data keys: ${data.keys.toList()}');
        print('========== LOCATION SERVICE END ==========\n');
        return data;
      } else if (response.statusCode == 401) {
        _logger.error('getVehicleLocations: 401 Unauthorized - Token expired');
        print('❌ ERROR: 401 Unauthorized - Token invalid or expired');
        print('   Token used: ${authToken.substring(0, 20)}...');
        print('🔄 Clearing expired token from storage...');
        
        // Clear expired token from storage
        final prefs = await SharedPreferences.getInstance();
        await prefs.remove('auth_token');
        print('✅ Expired token cleared');
        print('========== LOCATION SERVICE ERROR END ==========\n');
        
        throw Exception('Session expired. Please login again.');
      } else {
        _logger.error('getVehicleLocations: Non-200 status ${response.statusCode}');
        print('❌ ERROR: Non-200 status ${response.statusCode}');
        final errorData = json.decode(response.body);
        print('   Error data: $errorData');
        print('========== LOCATION SERVICE ERROR END ==========\n');
        throw Exception(errorData['error'] ?? 'Failed to fetch vehicles');
      }
    } catch (e, stackTrace) {
      _logger.error('getVehicleLocations: Exception - $e');
      _logger.debug('Stack trace: $stackTrace');
      print('❌ EXCEPTION in getVehicleLocations: $e');
      print('📚 Stack trace (first 5 lines):');
      print(stackTrace.toString().split('\n').take(5).join('\n'));
      print('========== LOCATION SERVICE ERROR END ==========\n');
      
      // Provide more user-friendly error messages for common issues
      if (e.toString().contains('TimeoutException') || e.toString().contains('timed out')) {
        throw Exception('Server is taking too long to respond. Please check your internet connection and try again.');
      } else if (e.toString().contains('SocketException') || e.toString().contains('Failed host lookup')) {
        throw Exception('Cannot reach server. Please check your internet connection.');
      } else if (e.toString().contains('Connection refused') || e.toString().contains('Connection closed')) {
        throw Exception('Server connection failed. The service may be temporarily unavailable.');
      }
      
      rethrow;
    }
  }
  
  /// Get saved IMEIs from storage
  Future<List<String>> getSavedIMEIs() async {
    try {
      final prefs = await SharedPreferences.getInstance();
      final savedTagsJson = prefs.getString('bleTracker_savedTags');
      
      if (savedTagsJson != null && savedTagsJson.isNotEmpty) {
        final List<dynamic> tags = json.decode(savedTagsJson);
        return tags.map((tag) {
          if (tag is String) {
            return tag;
          } else if (tag is Map) {
            return tag['imei']?.toString() ?? '';
          }
          return '';
        }).where((imei) => imei.isNotEmpty).toList();
      }
    } catch (e) {
      print('⚠️ Error loading saved IMEIs: $e');
    }
    return [];
  }
  
  /// Save IMEI to backend and local storage
  Future<void> saveIMEI(String imei, {String? description}) async {
    // NOTE: The backend save is handled by AuthService.addBLETag (POST /api/v1/ble-tags).
    // This method only saves to local storage for offline access.
    try {
      await _saveIMEILocally(imei, description: description);
      print('✅ IMEI saved locally: $imei');
    } catch (e) {
      print('❌ Error saving IMEI: $e');
      rethrow;
    }
  }
  
  /// Save IMEI to local storage only (for offline access)
  Future<void> _saveIMEILocally(String imei, {String? description}) async {
    try {
      final prefs = await SharedPreferences.getInstance();
      List<Map<String, dynamic>> tags = [];
      
      // Load existing tags
      final savedTagsJson = prefs.getString('bleTracker_savedTags');
      if (savedTagsJson != null && savedTagsJson.isNotEmpty) {
        final List<dynamic> existingTags = json.decode(savedTagsJson);
        tags = existingTags.map((tag) {
          if (tag is Map) {
            return Map<String, dynamic>.from(tag);
          } else if (tag is String) {
            return {'imei': tag, 'description': 'BLE Tag'};
          }
          return {'imei': '', 'description': 'BLE Tag'};
        }).where((tag) => tag['imei'].toString().isNotEmpty).toList();
      }
      
      // Check if IMEI already exists
      final exists = tags.any((tag) => tag['imei'] == imei);
      if (!exists) {
        tags.add({
          'imei': imei,
          'description': description ?? 'BLE Tag',
        });
        
        await prefs.setString('bleTracker_savedTags', json.encode(tags));
        print('✅ Saved IMEI locally: $imei');
      }
    } catch (e) {
      print('❌ Error saving IMEI locally: $e');
    }
  }
  
  /// Get IMEIs from backend (user's stored tags)
  Future<List<String>> getBackendIMEIs() async {
    try {
      final authToken = await _getAuthToken();
      if (authToken == null) {
        throw Exception('No authentication token found');
      }
      
      final url = Uri.parse('$backendUrl/api/tags/list');
      final response = await http.get(
        url,
        headers: {
          'Authorization': 'Bearer $authToken',
        },
      ).timeout(const Duration(seconds: 10));
      
      if (response.statusCode == 200) {
        final data = json.decode(response.body);
        if (data['success']) {
          final List<dynamic> tags = data['tags'] ?? [];
          return tags.map((tag) => tag['imei'].toString()).toList();
        }
      }
    } catch (e) {
      print('⚠️ Error fetching backend IMEIs: $e');
    }
    return [];
  }
  
  /// Remove IMEI from storage
  Future<void> removeIMEI(String imei) async {
    try {
      final prefs = await SharedPreferences.getInstance();
      final savedTagsJson = prefs.getString('bleTracker_savedTags');
      
      if (savedTagsJson != null && savedTagsJson.isNotEmpty) {
        final List<dynamic> existingTags = json.decode(savedTagsJson);
        final tags = existingTags
            .where((tag) {
              if (tag is String) return tag != imei;
              if (tag is Map) return tag['imei'] != imei;
              return true;
            })
            .toList();
        
        await prefs.setString('bleTracker_savedTags', json.encode(tags));
        print('🗑️ Removed IMEI: $imei');
      }
    } catch (e) {
      print('❌ Error removing IMEI: $e');
      rethrow;
    }
  }
  
  /// Clear all saved IMEIs
  Future<void> clearAllIMEIs() async {
    try {
      final prefs = await SharedPreferences.getInstance();
      await prefs.remove('bleTracker_savedTags');
      print('🗑️ Cleared all IMEIs');
    } catch (e) {
      print('❌ Error clearing IMEIs: $e');
      rethrow;
    }
  }
  
  /// Validate IMEI format (15 digits or GUID)
  bool isValidIMEI(String imei) {
    // Check for 15-digit IMEI
    if (RegExp(r'^\d{15}$').hasMatch(imei)) {
      return true;
    }
    
    // Check for GUID format
    if (RegExp(r'^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$', 
        caseSensitive: false).hasMatch(imei)) {
      return true;
    }
    
    return false;
  }
  
  /// Update asset attributes
  Future<void> updateAssetAttributes(String imei, Map<String, dynamic> attributes, {String? deviceName}) async {
    try {
      _logger.info('updateAssetAttributes: Updating attributes for IMEI $imei');
      print('\n========== UPDATE ATTRIBUTES ==========');
      print('📝 Updating attributes for IMEI: $imei');
      if (deviceName != null) print('🏷️  Updating device name to: $deviceName');
      
      // Get auth token
      final authToken = await _getAuthToken();
      if (authToken == null) {
        _logger.error('updateAssetAttributes: No auth token found');
        throw Exception('No authentication token found');
      }
      
      // Call backend API
      final url = Uri.parse('$backendUrl/api/tags/$imei/attributes');
      _logger.network('PUT $url');
      print('📡 Calling: PUT $url');
      print('📦 Attributes: $attributes');
      
      final body = <String, dynamic>{'attributes': attributes};
      if (deviceName != null) body['device_name'] = deviceName;
      
      final response = await http.put(
        url,
        headers: {
          'Content-Type': 'application/json',
          'Authorization': 'Bearer $authToken',
        },
        body: json.encode(body),
      ).timeout(const Duration(seconds: 30));
      
      print('📊 Response status: ${response.statusCode}');
      print('📄 Response body: ${response.body}');
      
      if (response.statusCode == 200) {
        _logger.success('updateAssetAttributes: Attributes updated successfully');
        print('✅ Attributes updated successfully');
        print('========== UPDATE END ==========\n');
      } else if (response.statusCode == 401) {
        _logger.error('updateAssetAttributes: 401 Unauthorized');
        throw Exception('Session expired. Please login again.');
      } else {
        _logger.error('updateAssetAttributes: Non-200 status ${response.statusCode}');
        final errorData = json.decode(response.body);
        throw Exception(errorData['detail'] ?? 'Failed to update attributes');
      }
    } catch (e) {
      _logger.error('updateAssetAttributes: Error - $e');
      print('❌ Error updating attributes: $e');
      print('========== UPDATE ERROR END ==========\n');
      rethrow;
    }
  }
  
  /// Check backend health
  Future<bool> checkBackendHealth() async {
    try {
      _logger.info('checkBackendHealth: Checking $backendUrl/health');
      final url = Uri.parse('$backendUrl/health');
      final response = await http.get(url).timeout(const Duration(seconds: 5));
      final isHealthy = response.statusCode == 200;
      if (isHealthy) {
        _logger.success('checkBackendHealth: Backend is healthy');
      } else {
        _logger.error('checkBackendHealth: Backend unhealthy (status ${response.statusCode})');
      }
      return isHealthy;
    } catch (e) {
      _logger.error('checkBackendHealth: Failed - $e');
      print('❌ Backend health check failed: $e');
      return false;
    }
  }
  
  /// Fetch trips for a vehicle within date range
  Future<List<Trip>> getTrips({
    required String vehicleId,
    required DateTime startDate,
    required DateTime endDate,
  }) async {
    try {
      _logger.info('getTrips: Fetching trips for vehicle $vehicleId');
      print('\n========== TRIPS SERVICE START ==========');
      print('⏰ Timestamp: ${DateTime.now().toIso8601String()}');
      print('📍 Fetching trips for vehicle: $vehicleId');
      print('📅 Date range: ${startDate.toLocal()} to ${endDate.toLocal()}');
      
      // Get auth token
      final authToken = await _getAuthToken();
      if (authToken == null) {
        _logger.error('getTrips: No auth token found');
        throw Exception('No authentication token found');
      }
      
      // Format dates for API (ISO without milliseconds)
      final dateRange = DateRange(startDate: startDate, endDate: endDate);
      
      // Call backend API
      final url = Uri.parse('$backendUrl/api/trips');
      _logger.network('POST $url');
      print('📡 Calling: POST $url');
      
      final requestBody = {
        'vehicleId': vehicleId,
        'startDate': dateRange.startDateFormatted,
        'endDate': dateRange.endDateFormatted,
      };
      print('📤 Request body: $requestBody');
      
      final startTime = DateTime.now();
      final response = await http.post(
        url,
        headers: {
          'Content-Type': 'application/json',
          'Authorization': 'Bearer $authToken',
        },
        body: json.encode(requestBody),
      ).timeout(const Duration(seconds: 30));
      
      final duration = DateTime.now().difference(startTime);
      _logger.network('Response ${response.statusCode} in ${duration.inMilliseconds}ms');
      print('⏱️  Response received in ${duration.inMilliseconds}ms');
      print('📊 Response status: ${response.statusCode}');
      
      if (response.statusCode == 200) {
        final data = json.decode(response.body);
        final tripsData = data['trips'] as List? ?? [];
        final trips = tripsData.map((tripJson) => Trip.fromJson(tripJson)).toList();
        _logger.success('getTrips: Found ${trips.length} trips');
        print('✅ SUCCESS: Found ${trips.length} trips');
        print('========== TRIPS SERVICE END ==========\n');
        return trips;
      } else if (response.statusCode == 401) {
        _logger.error('getTrips: 401 Unauthorized');
        throw Exception('Session expired. Please login again.');
      } else {
        _logger.error('getTrips: Non-200 status ${response.statusCode}');
        print('❌ ERROR: ${response.body}');
        print('========== TRIPS SERVICE ERROR END ==========\n');
        throw Exception('Failed to fetch trips');
      }
    } catch (e, stackTrace) {
      _logger.error('getTrips: Exception - $e');
      print('❌ EXCEPTION in getTrips: $e');
      print('========== TRIPS SERVICE ERROR END ==========\n');
      
      // Provide user-friendly error messages
      if (e.toString().contains('TimeoutException') || e.toString().contains('timed out')) {
        throw Exception('Server is taking too long to respond. Please try again.');
      } else if (e.toString().contains('SocketException') || e.toString().contains('Failed host lookup')) {
        throw Exception('Cannot reach server. Please check your internet connection.');
      }
      
      rethrow;
    }
  }
  
  /// Fetch trip events/waypoints for route plotting
  Future<List<TripEvent>> getTripEvents(String tripId) async {
    try {
      _logger.info('getTripEvents: Fetching events for trip $tripId');
      print('\n========== TRIP EVENTS SERVICE START ==========');
      print('🗺️ Fetching route for trip: $tripId');
      
      // Get auth token
      final authToken = await _getAuthToken();
      if (authToken == null) {
        _logger.error('getTripEvents: No auth token found');
        throw Exception('No authentication token found');
      }
      
      // Call backend API
      final url = Uri.parse('$backendUrl/api/trips/$tripId/events');
      _logger.network('GET $url');
      print('📡 Calling: GET $url');
      
      final startTime = DateTime.now();
      final response = await http.get(
        url,
        headers: {
          'Content-Type': 'application/json',
          'Authorization': 'Bearer $authToken',
        },
      ).timeout(const Duration(seconds: 30));
      
      final duration = DateTime.now().difference(startTime);
      _logger.network('Response ${response.statusCode} in ${duration.inMilliseconds}ms');
      print('⏱️  Response received in ${duration.inMilliseconds}ms');
      print('📊 Response status: ${response.statusCode}');
      
      if (response.statusCode == 200) {
        final data = json.decode(response.body);
        final eventsData = data['events'] as List? ?? [];
        final events = eventsData.map((eventJson) => TripEvent.fromJson(eventJson)).toList();
        _logger.success('getTripEvents: Found ${events.length} waypoints');
        print('✅ SUCCESS: Found ${events.length} waypoints');
        print('========== TRIP EVENTS SERVICE END ==========\n');
        return events;
      } else if (response.statusCode == 401) {
        _logger.error('getTripEvents: 401 Unauthorized');
        throw Exception('Session expired. Please login again.');
      } else {
        _logger.error('getTripEvents: Non-200 status ${response.statusCode}');
        print('❌ ERROR: ${response.body}');
        print('========== TRIP EVENTS SERVICE ERROR END ==========\n');
        throw Exception('Failed to fetch trip route');
      }
    } catch (e) {
      _logger.error('getTripEvents: Exception - $e');
      print('❌ EXCEPTION in getTripEvents: $e');
      print('========== TRIP EVENTS SERVICE ERROR END ==========\n');
      
      // Provide user-friendly error messages
      if (e.toString().contains('TimeoutException') || e.toString().contains('timed out')) {
        throw Exception('Server is taking too long to respond. Please try again.');
      } else if (e.toString().contains('SocketException') || e.toString().contains('Failed host lookup')) {
        throw Exception('Cannot reach server. Please check your internet connection.');
      }
      
      rethrow;
    }
  }
}
