import 'dart:convert';
import 'package:http/http.dart' as http;
import 'package:ble_tracker_app/config/environment.dart';

class ApiService {
  // Backend URL from environment configuration (production by default)
  static String get baseUrl => Environment.apiBaseUrl;
  
  Future<List<dynamic>> getTags() async {
    try {
      final response = await http.get(
        Uri.parse('$baseUrl/tags'),
        headers: {'Content-Type': 'application/json'},
      );
      
      if (response.statusCode == 200) {
        return json.decode(response.body);
      } else {
        throw Exception('Failed to load tags: ${response.statusCode}');
      }
    } catch (e) {
      print('Error fetching tags: $e');
      throw Exception('Failed to connect to server: $e');
    }
  }
  
  Future<Map<String, dynamic>> getTagLocation(String tagId) async {
    try {
      final response = await http.get(
        Uri.parse('$baseUrl/tags/$tagId/location'),
        headers: {'Content-Type': 'application/json'},
      );
      
      if (response.statusCode == 200) {
        return json.decode(response.body);
      } else {
        throw Exception('Failed to load location: ${response.statusCode}');
      }
    } catch (e) {
      print('Error fetching location: $e');
      throw Exception('Failed to connect to server: $e');
    }
  }
  
  Future<Map<String, dynamic>> getTagDetails(String tagId) async {
    try {
      final response = await http.get(
        Uri.parse('$baseUrl/tags/$tagId'),
        headers: {'Content-Type': 'application/json'},
      );
      
      if (response.statusCode == 200) {
        return json.decode(response.body);
      } else {
        throw Exception('Failed to load tag details: ${response.statusCode}');
      }
    } catch (e) {
      print('Error fetching tag details: $e');
      throw Exception('Failed to connect to server: $e');
    }
  }
  
  Future<bool> checkHealth() async {
    try {
      final response = await http.get(
        Uri.parse('$baseUrl/health'),
        headers: {'Content-Type': 'application/json'},
      ).timeout(const Duration(seconds: 5));
      
      return response.statusCode == 200;
    } catch (e) {
      print('Health check failed: $e');
      return false;
    }
  }
}
