import 'dart:convert';
import 'package:http/http.dart' as http;
import '../models/poi_model.dart';
import '../services/auth_service.dart';
import '../services/logger_service.dart';
import '../config/environment.dart';

class POIService {
  static String get baseUrl => '${Environment.apiBaseUrl}/api/v1';
  
  final AuthService _authService = AuthService();
  final LoggerService _logger = LoggerService();

  // Get authorization headers
  Future<Map<String, String>> _getHeaders() async {
    final token = await _authService.getToken();
    return {
      'Content-Type': 'application/json',
      'Authorization': 'Bearer $token',
    };
  }

  // Handle 401 Unauthorized responses (expired token)
  void _handle401(http.Response response) {
    if (response.statusCode == 401) {
      _logger.error('🔒 Token expired or invalid - logging out');
      _authService.logout();
      throw Exception('SESSION_EXPIRED');
    }
  }

  // ==================== POI Management ====================

  Future<POI> createPOI(POICreateRequest request) async {
    try {
      _logger.info('Creating POI: ${request.name}');
      
      final headers = await _getHeaders();
      final response = await http.post(
        Uri.parse('$baseUrl/pois'),
        headers: headers,
        body: jsonEncode(request.toJson()),
      );

      _handle401(response);

      if (response.statusCode == 200) {
        final poi = POI.fromJson(jsonDecode(response.body));
        _logger.success('POI created successfully: ${poi.id}');
        return poi;
      } else {
        _logger.error('Failed to create POI: ${response.statusCode}');
        throw Exception('Failed to create POI: ${response.body}');
      }
    } catch (e) {
      _logger.error('Error creating POI: $e');
      rethrow;
    }
  }

  Future<List<POI>> getPOIs() async {
    try {
      _logger.info('Fetching all POIs');
      
      final headers = await _getHeaders();
      final response = await http.get(
        Uri.parse('$baseUrl/pois'),
        headers: headers,
      );

      _handle401(response);

      if (response.statusCode == 200) {
        final List<dynamic> data = jsonDecode(response.body);
        final pois = data.map((json) => POI.fromJson(json)).toList();
        _logger.success('Fetched ${pois.length} POIs');
        return pois;
      } else {
        _logger.error('Failed to fetch POIs: ${response.statusCode}');
        throw Exception('Failed to fetch POIs');
      }
    } catch (e) {
      _logger.error('Error fetching POIs: $e');
      rethrow;
    }
  }

  Future<POI> getPOI(String poiId) async {
    try {
      _logger.info('Fetching POI: $poiId');
      
      final headers = await _getHeaders();
      final response = await http.get(
        Uri.parse('$baseUrl/pois/$poiId'),
        headers: headers,
      );

      _handle401(response);

      if (response.statusCode == 200) {
        return POI.fromJson(jsonDecode(response.body));
      } else {
        throw Exception('Failed to fetch POI');
      }
    } catch (e) {
      _logger.error('Error fetching POI: $e');
      rethrow;
    }
  }

  Future<POI> updatePOI(String poiId, Map<String, dynamic> updates) async {
    try {
      _logger.info('Updating POI: $poiId');
      
      final headers = await _getHeaders();
      final response = await http.put(
        Uri.parse('$baseUrl/pois/$poiId'),
        headers: headers,
        body: jsonEncode(updates),
      );

      _handle401(response);

      if (response.statusCode == 200) {
        final poi = POI.fromJson(jsonDecode(response.body));
        _logger.success('POI updated successfully');
        return poi;
      } else {
        throw Exception('Failed to update POI');
      }
    } catch (e) {
      _logger.error('Error updating POI: $e');
      rethrow;
    }
  }

  Future<void> deletePOI(String poiId) async {
    try {
      _logger.info('Deleting POI: $poiId');
      
      final headers = await _getHeaders();
      final response = await http.delete(
        Uri.parse('$baseUrl/pois/$poiId'),
        headers: headers,
      );

      _handle401(response);

      if (response.statusCode == 200) {
        _logger.success('POI deleted successfully');
      } else {
        throw Exception('Failed to delete POI');
      }
    } catch (e) {
      _logger.error('Error deleting POI: $e');
      rethrow;
    }
  }

  // ==================== ARM/DISARM ====================

  Future<void> armPOI(String poiId, String trackerId) async {
    try {
      _logger.info('Arming POI $poiId to tracker $trackerId');
      
      final headers = await _getHeaders();
      final response = await http.post(
        Uri.parse('$baseUrl/pois/$poiId/arm/$trackerId'),
        headers: headers,
      );

      _handle401(response);

      if (response.statusCode == 200) {
        _logger.success('POI armed successfully');
      } else {
        throw Exception('Failed to arm POI');
      }
    } catch (e) {
      _logger.error('Error arming POI: $e');
      rethrow;
    }
  }

  Future<void> disarmPOI(String poiId, String trackerId) async {
    try {
      _logger.info('Disarming POI $poiId from tracker $trackerId');
      
      final headers = await _getHeaders();
      final response = await http.post(
        Uri.parse('$baseUrl/pois/$poiId/disarm/$trackerId'),
        headers: headers,
      );

      _handle401(response);

      if (response.statusCode == 200) {
        _logger.success('POI disarmed successfully');
      } else {
        throw Exception('Failed to disarm POI');
      }
    } catch (e) {
      _logger.error('Error disarming POI: $e');
      rethrow;
    }
  }

  // ==================== Alerts ====================

  Future<AlertsResponse> getAlerts({
    int limit = 50,
    int offset = 0,
    bool unreadOnly = false,
  }) async {
    try {
      _logger.info('Fetching alerts (limit: $limit, offset: $offset, unread: $unreadOnly)');
      
      final headers = await _getHeaders();
      final queryParams = {
        'limit': limit.toString(),
        'offset': offset.toString(),
        'unread_only': unreadOnly.toString(),
      };
      
      final uri = Uri.parse('$baseUrl/alerts').replace(queryParameters: queryParams);
      final response = await http.get(uri, headers: headers);

      _handle401(response);

      if (response.statusCode == 200) {
        final alertsResponse = AlertsResponse.fromJson(jsonDecode(response.body));
        _logger.success('Fetched ${alertsResponse.alerts.length} alerts (${alertsResponse.unreadCount} unread)');
        return alertsResponse;
      } else {
        throw Exception('Failed to fetch alerts');
      }
    } catch (e) {
      _logger.error('Error fetching alerts: $e');
      rethrow;
    }
  }

  Future<void> markAlertRead(String alertId) async {
    try {
      _logger.info('Marking alert as read: $alertId');
      
      final headers = await _getHeaders();
      final response = await http.post(
        Uri.parse('$baseUrl/alerts/$alertId/mark-read'),
        headers: headers,
      );

      _handle401(response);

      if (response.statusCode == 200) {
        _logger.success('Alert marked as read');
      } else {
        throw Exception('Failed to mark alert as read');
      }
    } catch (e) {
      _logger.error('Error marking alert as read: $e');
      rethrow;
    }
  }

  Future<void> markAllAlertsRead() async {
    try {
      _logger.info('Marking all alerts as read');
      
      final headers = await _getHeaders();
      final response = await http.post(
        Uri.parse('$baseUrl/alerts/mark-all-read'),
        headers: headers,
      );

      _handle401(response);

      if (response.statusCode == 200) {
        _logger.success('All alerts marked as read');
      } else {
        throw Exception('Failed to mark all alerts as read');
      }
    } catch (e) {
      _logger.error('Error marking all alerts as read: $e');
      rethrow;
    }
  }

  // ==================== Postcode Search ====================

  Future<PostcodeSearchResult> searchPostcode(String postcode) async {
    try {
      _logger.info('Searching for postcode: $postcode');
      
      final headers = await _getHeaders();
      final response = await http.post(
        Uri.parse('$baseUrl/search/postcode'),
        headers: headers,
        body: jsonEncode({'postcode': postcode}),
      );

      if (response.statusCode == 200) {
        final result = PostcodeSearchResult.fromJson(jsonDecode(response.body));
        _logger.success('Postcode found: ${result.address}');
        return result;
      } else {
        throw Exception('Postcode not found');
      }
    } catch (e) {
      _logger.error('Error searching postcode: $e');
      rethrow;
    }
  }
}
