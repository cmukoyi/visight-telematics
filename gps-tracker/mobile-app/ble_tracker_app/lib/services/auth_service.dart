import 'dart:convert';
import 'package:flutter/foundation.dart';
import 'package:http/http.dart' as http;
import 'package:shared_preferences/shared_preferences.dart';
import 'package:ble_tracker_app/services/logger_service.dart';
import 'package:ble_tracker_app/config/environment.dart';

class AuthService {
  final _logger = LoggerService();
  // Singleton pattern
  static final AuthService _instance = AuthService._internal();
  factory AuthService() => _instance;
  AuthService._internal();
  
  // Backend URL from environment configuration (production by default)
  static String get baseUrl => Environment.apiBaseUrl;
  
  String? _token;
  
  // Get current token
  Future<String?> getToken() async {
    if (_token == null) {
      final prefs = await SharedPreferences.getInstance();
      _token = prefs.getString('auth_token');
    }
    return _token;
  }
  
  // Check if user is logged in
  Future<bool> isLoggedIn() async {
    final prefs = await SharedPreferences.getInstance();
    _token = prefs.getString('auth_token');
    return _token != null;
  }
  
  // Save token to persistent storage with timestamp
  Future<void> _saveToken(String token, {String? email}) async {
    _token = token;
    final prefs = await SharedPreferences.getInstance();
    await prefs.setString('auth_token', token);
    await prefs.setInt('token_saved_at', DateTime.now().millisecondsSinceEpoch);
    if (email != null) {
      await prefs.setString('user_email', email);
    }
    print('✅ Token saved to storage at ${DateTime.now().toIso8601String()}');
  }
  
  // Get current user's email
  Future<String?> getUserEmail() async {
    final prefs = await SharedPreferences.getInstance();
    return prefs.getString('user_email');
  }
  
  // Clear token from storage
  Future<void> logout() async {
    _token = null;
    final prefs = await SharedPreferences.getInstance();
    await prefs.remove('auth_token');
    await prefs.remove('user_email');
    await _clearCachedTags();
    print('🚪 User logged out and cache cleared');
  }

  // Get token age in minutes
  Future<int> getTokenAgeMinutes() async {
    try {
      final prefs = await SharedPreferences.getInstance();
      final savedAt = prefs.getInt('token_saved_at');
      if (savedAt == null) return 999; // Very old
      
      final now = DateTime.now().millisecondsSinceEpoch;
      final ageMs = now - savedAt;
      return (ageMs / 1000 / 60).round();
    } catch (e) {
      return 999; // Error = treat as very old
    }
  }

  // Check if token needs refresh (older than 20 minutes)
  Future<bool> shouldRefreshToken() async {
    final age = await getTokenAgeMinutes();
    return age >= 20; // Refresh if 20+ minutes old (expires at 30)
  }

  // Refresh the JWT token
  Future<bool> refreshToken() async {
    try {
      final currentToken = await getToken();
      if (currentToken == null) return false;

      _logger.info('🔄 Refreshing token...');
      
      final response = await http.post(
        Uri.parse('$baseUrl/api/v1/auth/refresh'),
        headers: {
          'Content-Type': 'application/json',
          'Authorization': 'Bearer $currentToken',
        },
      );

      if (response.statusCode == 200) {
        final data = json.decode(response.body);
        final newToken = data['access_token'];
        
        // Save new token
        await _saveToken(newToken);
        _logger.success('✅ Token refreshed successfully');
        return true;
      } else {
        _logger.error('❌ Token refresh failed: ${response.statusCode}');
        return false;
      }
    } catch (e) {
      _logger.error('❌ Token refresh error: $e');
      return false;
    }
  }
  
  // Check if user has any tags (checks cache first, then API)
  Future<bool> hasTags() async {
    try {
      // First check cache
      final prefs = await SharedPreferences.getInstance();
      final cachedTagsJson = prefs.getString('cached_tags');
      if (cachedTagsJson != null && cachedTagsJson.isNotEmpty && cachedTagsJson != '[]') {
        print('✅ Found cached tags');
        return true;
      }
      
      // If no cache, check API
      if (_token == null) {
        await isLoggedIn();
      }
      if (_token == null) return false;
      
      final tags = await getBLETags();
      return tags.isNotEmpty;
    } catch (e) {
      // Check cache on error
      try {
        final prefs = await SharedPreferences.getInstance();
        final cachedTagsJson = prefs.getString('cached_tags');
        return cachedTagsJson != null && cachedTagsJson.isNotEmpty && cachedTagsJson != '[]';
      } catch (_) {
        return false;
      }
    }
  }
  
  // Save tags to cache
  Future<void> _saveTags(List<dynamic> tags) async {
    try {
      final prefs = await SharedPreferences.getInstance();
      await prefs.setString('cached_tags', json.encode(tags));
      print('✅ Cached ${tags.length} tags to storage');
    } catch (e) {
      print('⚠️ Failed to cache tags: $e');
    }
  }
  
  // Get cached tags
  Future<List<dynamic>> getCachedTags() async {
    try {
      final prefs = await SharedPreferences.getInstance();
      final cachedTagsJson = prefs.getString('cached_tags');
      if (cachedTagsJson != null && cachedTagsJson.isNotEmpty) {
        return json.decode(cachedTagsJson) as List<dynamic>;
      }
    } catch (e) {
      print('⚠️ Failed to get cached tags: $e');
    }
    return [];
  }
  
  // Clear cached tags
  Future<void> _clearCachedTags() async {
    try {
      final prefs = await SharedPreferences.getInstance();
      await prefs.remove('cached_tags');
      print('🗑️ Cleared cached tags');
    } catch (e) {
      print('⚠️ Failed to clear cached tags: $e');
    }
  }
  
  // Helper method to extract clean error messages from API responses
  String _extractErrorMessage(dynamic error, {String defaultMessage = 'An error occurred'}) {
    try {
      String errorStr = error.toString();
      
      // Try to extract JSON detail from error message
      if (errorStr.contains('{"detail":')) {
        int start = errorStr.indexOf('{"detail":');
        int end = errorStr.indexOf('}', start) + 1;
        if (end > start) {
          String jsonStr = errorStr.substring(start, end);
          var jsonData = json.decode(jsonStr);
          if (jsonData['detail'] != null) {
            return jsonData['detail'].toString();
          }
        }
      }
      
      // If error contains "Server returned" pattern, extract the detail
      if (errorStr.contains('Server returned')) {
        var match = RegExp(r'"detail":"([^"]+)"').firstMatch(errorStr);
        if (match != null && match.groupCount >= 1) {
          return match.group(1) ?? defaultMessage;
        }
      }
      
      // Clean up common error patterns
      errorStr = errorStr.replaceAll('Exception: ', '');
      errorStr = errorStr.replaceAll('Unexpected error: ', '');
      
      // If still too technical, return default
      if (errorStr.contains('Server returned') || errorStr.contains('Exception')) {
        return defaultMessage;
      }
      
      return errorStr;
    } catch (e) {
      return defaultMessage;
    }
  }
  
  Future<void> sendVerificationCode(String email) async {
    print('\n========== AUTH SERVICE START ==========');
    print('⏰ Timestamp: ${DateTime.now().toIso8601String()}');
    print('📧 Email: $email');
    print('🌐 Base URL: $baseUrl');
    
    try {
      final url = '$baseUrl/api/auth/send-pin';
      final uri = Uri.parse(url);
      print('📍 Full URL: $uri');
      print('🔗 Scheme: ${uri.scheme}, Host: ${uri.host}, Port: ${uri.port}');
      
      final requestBody = json.encode({'email': email});
      print('📦 Request body: $requestBody');
      print('📋 Request headers: Content-Type: application/json');
      
      print('🚀 Sending POST request...');
      final startTime = DateTime.now();
      
      final response = await http.post(
        uri,
        headers: {
          'Content-Type': 'application/json',
          'Accept': 'application/json',
        },
        body: requestBody,
      ).timeout(
        Duration(seconds: 10),
        onTimeout: () {
          print('⏱️ REQUEST TIMED OUT after 10 seconds!');
          throw Exception('Request timed out after 10 seconds');
        },
      );
      
      final endTime = DateTime.now();
      final duration = endTime.difference(startTime).inMilliseconds;
      
      print('✅ Response received in ${duration}ms');
      print('📊 Status code: ${response.statusCode}');
      print('📋 Response headers: ${response.headers}');
      print('📄 Response body: ${response.body}');
      print('📏 Response length: ${response.body.length} bytes');
      
      if (response.statusCode != 200) {
        print('❌ Non-200 status code received');
        // Extract clean error message from response
        try {
          final errorData = json.decode(response.body);
          final detail = errorData['detail'] ?? 'Failed to send verification code';
          throw Exception(detail);
        } catch (e) {
          if (e.toString().contains('detail')) {
            rethrow;
          }
          throw Exception('Failed to send verification code');
        }
      }
      
      // Try to parse response
      try {
        final jsonResponse = json.decode(response.body);
        print('✅ Response parsed successfully: $jsonResponse');
      } catch (parseError) {
        print('⚠️ Failed to parse JSON response: $parseError');
      }
      
      print('✅ Verification code sent successfully!');
      print('========== AUTH SERVICE END ==========\n');
    } on http.ClientException catch (e) {
      print('❌ HTTP Client Exception: $e');
      print('   This usually means: Network connection failed, DNS resolution failed, or server not reachable');
      print('========== AUTH SERVICE ERROR END ==========\n');
      throw Exception('Network error. Please check your connection.');
    } on FormatException catch (e) {
      print('❌ Format Exception: $e');
      print('   This usually means: Invalid response format from server');
      print('========== AUTH SERVICE ERROR END ==========\n');
      throw Exception('Server error. Please try again.');
    } catch (e, stackTrace) {
      print('❌ Unexpected error: $e');
      print('📚 Stack trace:');
      print(stackTrace.toString().split('\n').take(10).join('\n'));
      print('========== AUTH SERVICE ERROR END ==========\n');
      // Re-throw if it's already a user-friendly message
      if (!e.toString().contains('Exception:')) {
        rethrow;
      }
      throw Exception(_extractErrorMessage(e, defaultMessage: 'An error occurred. Please try again.'));
    }
  }
  
  Future<void> verifyPin(String email, String pin) async {
    try {
      print('\n========== VERIFY PIN START ==========');
      print('📧 Email: $email');
      print('🔢 PIN: $pin');
      print('🌐 Calling: POST $baseUrl/api/auth/verify-pin');
      
      final response = await http.post(
        Uri.parse('$baseUrl/api/auth/verify-pin'),
        headers: {'Content-Type': 'application/json'},
        body: json.encode({
          'email': email,
          'pin': pin,
        }),
      ).timeout(Duration(seconds: 10));
      
      print('📊 Response status: ${response.statusCode}');
      print('📄 Response body: ${response.body}');
      
      if (response.statusCode == 200) {
        // Email ownership confirmed. No token at this stage —
        // the account is not created until /register (final step).
        print('✅ PIN verified. Email confirmed, proceeding to registration.');
        print('========== VERIFY PIN END ==========\n');
      } else {
        try {
          final errorData = json.decode(response.body);
          final detail = errorData['detail'] ?? 'Invalid verification code';
          throw Exception(detail);
        } catch (e) {
          if (!e.toString().contains('Exception:')) {
            rethrow;
          }
          throw Exception('Invalid verification code');
        }
      }
    } catch (e) {
      // Clean up error message
      String errorMsg = _extractErrorMessage(e, defaultMessage: 'Verification failed');
      throw Exception(errorMsg);
    }
  }
  
  Future<void> register({
    required String email,
    required String password,
    required String firstName,
    required String lastName,
  }) async {
    print('\n========== REGISTER START ==========');
    print('⏰ Timestamp: ${DateTime.now().toIso8601String()}');
    print('📧 Email: $email');
    print('👤 Name: $firstName $lastName');
    
    try {
      final url = '$baseUrl/api/v1/auth/register';
      final uri = Uri.parse(url);
      print('📍 URL: $uri');
      
      final requestBody = json.encode({
        'email': email,
        'password': password,
        'first_name': firstName,
        'last_name': lastName,
      });
      print('📦 Request body: ${requestBody.replaceAll(password, "****")}');
      
      print('🚀 Sending POST request...');
      final startTime = DateTime.now();
      
      final response = await http.post(
        uri,
        headers: {
          'Content-Type': 'application/json',
          'Accept': 'application/json',
        },
        body: requestBody,
      ).timeout(
        Duration(seconds: 10),
        onTimeout: () {
          print('⏱️ REQUEST TIMED OUT after 10 seconds!');
          throw Exception('Request timed out after 10 seconds');
        },
      );
      
      final endTime = DateTime.now();
      final duration = endTime.difference(startTime).inMilliseconds;
      
      print('✅ Response received in ${duration}ms');
      print('📊 Status code: ${response.statusCode}');
      print('📄 Response body: ${response.body}');
      
      if (response.statusCode == 200 || response.statusCode == 201) {
        final data = json.decode(response.body);
        await _saveToken(data['access_token'], email: email);
        print('✅ Registration successful! Token received.');
        print('========== REGISTER END ==========\n');
      } else {
        print('❌ Non-200 status code received');
        try {
          final errorData = json.decode(response.body);
          final detail = errorData['detail'] ?? 'Registration failed';
          throw Exception(detail);
        } catch (e) {
          if (!e.toString().contains('Exception:')) {
            rethrow;
          }
          throw Exception('Registration failed');
        }
      }
    } on http.ClientException catch (e) {
      print('❌ HTTP Client Exception: $e');
      print('========== REGISTER ERROR END ==========\n');
      throw Exception('Network error. Please check your connection.');
    } catch (e, stackTrace) {
      print('❌ Unexpected error: $e');
      print('📚 Stack trace:');
      print(stackTrace.toString().split('\n').take(10).join('\n'));
      print('========== REGISTER ERROR END ==========\n');
      // Clean up error message
      String errorMsg = _extractErrorMessage(e, defaultMessage: 'Registration failed. Please try again.');
      throw Exception(errorMsg);
    }
  }
  
  Future<void> signIn(String email, String password) async {
    _logger.info('signIn: Attempting login for $email');
    _logger.network('POST $baseUrl/api/v1/auth/login');
    try {
      final response = await http.post(
        Uri.parse('$baseUrl/api/v1/auth/login'),
        headers: {'Content-Type': 'application/json'},
        body: json.encode({
          'email': email,
          'password': password,
        }),
      ).timeout(Duration(seconds: 10));
      
      _logger.network('Response ${response.statusCode}');
      
      if (response.statusCode == 200) {
        final data = json.decode(response.body);
        await _saveToken(data['access_token'], email: email);
        _logger.success('signIn: Login successful for $email');
        print('✅ Login successful! Token saved.');
      } else {
        _logger.error('signIn: Invalid credentials - ${response.statusCode}');
        throw Exception('Invalid credentials');
      }
    } catch (e) {
      _logger.error('signIn: Failed', e);
      rethrow; // Re-throw without wrapping to avoid double-exception messages
    }
  }
  
  Future<List<dynamic>> getBLETags() async {
    _logger.info('getBLETags: Starting tag fetch');
    print('🔑 AuthService: getBLETags called');
    if (_token == null) {
      _logger.error('getBLETags: No authentication token available');
      print('❌ AuthService: No token available');
      throw Exception('Not authenticated');
    }
    
    try {
      _logger.network('GET $baseUrl/api/tags/list');
      print('📡 AuthService: Fetching tags from $baseUrl/api/tags/list');
      final response = await http.get(
        Uri.parse('$baseUrl/api/tags/list'),
        headers: {
          'Authorization': 'Bearer $_token',
        },
      ).timeout(Duration(seconds: 10));
      
      _logger.network('Response ${response.statusCode}: ${response.body}');
      print('📥 AuthService: Response status: ${response.statusCode}');
      print('📥 AuthService: Response body: ${response.body}');
      
      if (response.statusCode == 200) {
        final responseData = json.decode(response.body) as Map<String, dynamic>;
        final tags = responseData['tags'] as List<dynamic>;
        _logger.success('getBLETags: Found ${tags.length} tags');
        print('✅ AuthService: Parsed ${tags.length} tags from API');
        // Cache the tags
        await _saveTags(tags);
        return tags;
      } else {
        _logger.warning('getBLETags: API returned ${response.statusCode}');
        print('⚠️ AuthService: API returned ${response.statusCode}: ${response.body}');
        // Try to return cached tags on error
        print('⚠️ Failed to fetch tags from API, trying cache...');
        return await getCachedTags();
      }
    } catch (e) {
      _logger.error('getBLETags: Network error', e);
      print('❌ AuthService: Network error fetching tags: $e');
      print('⚠️ Network error fetching tags, trying cache...');
      return await getCachedTags();
    }
  }
  
  Future<List<dynamic>> getTags() async {
    if (_token == null) {
      throw Exception('Not authenticated');
    }
    
    try {
      final response = await http.get(
        Uri.parse('$baseUrl/api/tags/list'),
        headers: {
          'Authorization': 'Bearer $_token',
        },
      ).timeout(Duration(seconds: 10));
      
      if (response.statusCode == 200) {
        return json.decode(response.body);
      } else {
        throw Exception('Failed to load tags');
      }
    } catch (e) {
      throw Exception('Network error: ${e.toString()}');
    }
  }
  
  Future<Map<String, dynamic>> getTagLocation(String tagId) async {
    print('📍 AuthService: getTagLocation called for tagId: $tagId');
    if (_token == null) {
      print('❌ AuthService: No token available for getTagLocation');
      throw Exception('Not authenticated');
    }
    
    try {
      final url = '$baseUrl/tags/$tagId/location';
      print('📡 AuthService: Fetching location from $url');
      
      final response = await http.get(
        Uri.parse(url),
        headers: {
          'Authorization': 'Bearer $_token',
        },
      ).timeout(Duration(seconds: 10));
      
      print('📥 AuthService: Location response status: ${response.statusCode}');
      print('📥 AuthService: Location response body: ${response.body}');
      
      if (response.statusCode == 200) {
        final location = json.decode(response.body);
        print('✅ AuthService: Parsed location: $location');
        return location;
      } else {
        print('❌ AuthService: Failed to load location: ${response.statusCode} - ${response.body}');
        throw Exception('Failed to load location');
      }
    } catch (e) {
      print('❌ AuthService: Network error getting location: $e');
      throw Exception('Network error: ${e.toString()}');
    }
  }
  
  Future<Map<String, dynamic>> checkEmailExists(String email) async {
    print('\n========== CHECK EMAIL START ==========');
    print('📧 Email: $email');
    
    try {
      final response = await http.post(
        Uri.parse('$baseUrl/api/auth/send-pin'),
        headers: {
          'Content-Type': 'application/json',
          'Accept': 'application/json',
        },
        body: json.encode({'email': email}),
      ).timeout(Duration(seconds: 10));
      
      print('📊 Status: ${response.statusCode}');
      print('📄 Response: ${response.body}');
      
      if (response.statusCode == 200) {
        print('✅ Email available — code sent');
        return {'exists': false, 'can_register': true};
      } else if (response.statusCode == 400) {
        final data = json.decode(response.body);
        final detail = data['detail']?.toString() ?? '';
        if (detail.contains('already registered')) {
          print('⚠️ Email already fully registered');
          return {'exists': true, 'can_register': false, 'message': 'Email already registered. Please sign in.'};
        }
        // Domain not allowed or any other policy rejection
        print('🚫 Registration blocked by server: $detail');
        return {'exists': false, 'can_register': false, 'message': detail.isNotEmpty ? detail : 'Registration is not available for your email domain.'};
      }

      // Any other non-200 response — block to be safe
      print('⚠️ Unexpected status ${response.statusCode}');
      return {'exists': false, 'can_register': false, 'message': 'Unable to register at this time. Please try again.'};
    } catch (e) {
      print('❌ Check email error: $e');
      // If check fails, allow to continue (network issues shouldn't block)
      return {'exists': false, 'can_register': true};
    } finally {
      print('========== CHECK EMAIL END ==========\n');
    }
  }
  
  // Validate IMEI against MProfiler API via backend
  Future<Map<String, dynamic>> validateIMEI(String imei) async {
    print('\n========== VALIDATE IMEI START ==========');
    print('⏰ Timestamp: ${DateTime.now().toIso8601String()}');
    print('📍 IMEI: $imei');
    
    if (_token == null) {
      print('❌ Not authenticated - no token available');
      throw Exception('Not authenticated. Please login first.');
    }
    
    try {
      final url = '$baseUrl/api/v1/validate-imei/$imei';
      print('📍 GET to: $url');
      
      final response = await http.get(
        Uri.parse(url),
        headers: {
          'Content-Type': 'application/json',
          'Accept': 'application/json',
          'Authorization': 'Bearer $_token',
        },
      ).timeout(Duration(seconds: 15));
      
      print('📊 Status code: ${response.statusCode}');
      print('📄 Response body: ${response.body}');
      
      if (response.statusCode == 200) {
        final data = json.decode(response.body);
        print('✅ IMEI validated successfully!');
        return {
          'success': true,
          'message': data['message'] ?? 'IMEI is valid',
        };
      } else if (response.statusCode == 404) {
        final data = json.decode(response.body);
        print('❌ IMEI not found in system');
        return {
          'success': false,
          'message': data['error'] ?? 'IMEI not found in tracking system',
        };
      } else if (response.statusCode == 401 || response.statusCode == 403) {
        print('❌ Authentication error: ${response.statusCode}');
        print('⚠️ Token might be expired or invalid');
        // Clear the token and prompt re-login
        await logout();
        return {
          'success': false,
          'message': 'Session expired. Please login again.',
          'requiresLogin': true,
        };
      } else {
        try {
          final data = json.decode(response.body);
          print('❌ Validation failed with status ${response.statusCode}');
          return {
            'success': false,
            'message': data['error'] ?? data['detail'] ?? 'Validation failed',
          };
        } catch (e) {
          print('⚠️ Could not parse error response');
          return {
            'success': false,
            'message': 'Validation failed (status: ${response.statusCode})',
          };
        }
      }
    } catch (e) {
      print('❌ Validate IMEI error: $e');
      print('========== VALIDATE IMEI ERROR END ==========\n');
      return {
        'success': false,
        'message': _extractErrorMessage(e, defaultMessage: 'Network error. Please check your connection.'),
      };
    } finally {
      print('========== VALIDATE IMEI END ==========\n');
    }
  }
  
  Future<void> addBLETag({required String imei, String? name, String tagType = 'scope', int? batteryLevel}) async {
    print('\n========== ADD BLE TAG START ==========');
    print('⏰ Timestamp: ${DateTime.now().toIso8601String()}');
    print('📍 IMEI: $imei');
    print('🏷️ Name: ${name ?? "(none)"} | Type: $tagType | Battery: ${batteryLevel ?? "N/A"}');
    
    if (_token == null) {
      print('❌ Not authenticated - no token available');
      throw Exception('Not authenticated. Please login first.');
    }
    
    try {
      final url = '$baseUrl/api/v1/ble-tags';
      print('📍 POST to: $url');
      
      final body = <String, dynamic>{
        'imei': imei,
        'device_name': name,
        'tag_type': tagType,
      };
      if (batteryLevel != null) body['battery_level'] = batteryLevel;
      final requestBody = json.encode(body);
      print('📦 Request body: $requestBody');
      
      final response = await http.post(
        Uri.parse(url),
        headers: {
          'Content-Type': 'application/json',
          'Accept': 'application/json',
          'Authorization': 'Bearer $_token',
        },
        body: requestBody,
      ).timeout(Duration(seconds: 15));
      
      print('📊 Status code: ${response.statusCode}');
      print('📄 Response body (first 200 chars): ${response.body.length > 200 ? response.body.substring(0, 200) : response.body}');
      
      if (response.statusCode == 200 || response.statusCode == 201) {
        print('✅ BLE Tag added successfully!');
        // Refresh the cache by fetching all tags
        try {
          await getBLETags();
          print('✅ Tag cache refreshed');
        } catch (e) {
          print('⚠️ Failed to refresh cache: $e');
        }
        print('========== ADD BLE TAG END ==========\n');
      } else {
        print('❌ Failed with status ${response.statusCode}');
        
        // Check if response is HTML (server error)
        if (response.body.trim().startsWith('<')) {
          print('⚠️ Server returned HTML error page');
          throw Exception('Server error. Please check backend logs.');
        }
        
        // Try to parse JSON error
        try {
          final errorData = json.decode(response.body);
          final detail = errorData['detail'] ?? 'Failed to add tag';
          throw Exception(detail);
        } catch (e) {
          if (e.toString().contains('Exception:')) {
            rethrow;
          }
          throw Exception('Failed to add tag: ${response.statusCode}');
        }
      }
    } catch (e) {
      print('❌ Add BLE Tag error: $e');
      print('========== ADD BLE TAG ERROR END ==========\n');
      
      // Clean up error message
      String errorMsg = e.toString().replaceAll('Exception: ', '');
      if (errorMsg.contains('FormatException')) {
        errorMsg = 'Server returned invalid response. Please check backend.';
      }
      throw Exception(errorMsg);
    }
  }

  /// Validate an IMEI against its vendor platform before adding.
  /// Calls POST /api/v1/ble-tags/validate and returns {is_valid, message}.
  Future<Map<String, dynamic>> validateTagByType(String imei, String tagType) async {
    print('\n========== VALIDATE TAG BY TYPE ==========');
    print('📍 IMEI: $imei  Type: $tagType');

    final token = await getToken();
    if (token == null) throw Exception('Not authenticated.');

    try {
      final response = await http.post(
        Uri.parse('$baseUrl/api/v1/ble-tags/validate'),
        headers: {
          'Content-Type': 'application/json',
          'Accept': 'application/json',
          'Authorization': 'Bearer $token',
        },
        body: json.encode({'imei': imei, 'tag_type': tagType}),
      ).timeout(const Duration(seconds: 30));

      print('📊 Status code: ${response.statusCode}');
      print('📄 Response: ${response.body}');

      if (response.statusCode == 200) {
        final data = json.decode(response.body) as Map<String, dynamic>;
        print('========== VALIDATE TAG BY TYPE END ==========\n');
        return data;
      } else {
        final errorData = json.decode(response.body);
        throw Exception(errorData['detail'] ?? 'Validation failed');
      }
    } on Exception {
      rethrow;
    } catch (e) {
      throw Exception('Validation error: $e');
    }
  }
  
  // Get current user information
  Future<Map<String, dynamic>?> getUserInfo() async {
    if (_token == null) {
      await isLoggedIn();
      if (_token == null) {
        throw Exception('Not authenticated');
      }
    }
    
    try {
      _logger.network('GET $baseUrl/api/v1/auth/me');
      final response = await http.get(
        Uri.parse('$baseUrl/api/v1/auth/me'),
        headers: {
          'Authorization': 'Bearer $_token',
          'Content-Type': 'application/json',
        },
      ).timeout(Duration(seconds: 10));
      
      _logger.network('Response ${response.statusCode}');
      
      if (response.statusCode == 200) {
        final userInfo = json.decode(response.body) as Map<String, dynamic>;
        _logger.success('getUserInfo: Loaded user preferences');
        return userInfo;
      } else {
        _logger.warning('getUserInfo: API returned ${response.statusCode}');
        return null;
      }
    } catch (e) {
      _logger.error('getUserInfo: Error', e);
      rethrow;
    }
  }
  
  // Update user preferences (email alerts, etc.)
  Future<Map<String, dynamic>> updateUserPreferences({
    bool? emailAlertsEnabled,
  }) async {
    if (_token == null) {
      await isLoggedIn();
      if (_token == null) {
        throw Exception('Not authenticated');
      }
    }
    
    try {
      final body = <String, dynamic>{};
      if (emailAlertsEnabled != null) {
        body['email_alerts_enabled'] = emailAlertsEnabled;
      }
      
      _logger.network('PUT $baseUrl/api/v1/user/preferences');
      final response = await http.put(
        Uri.parse('$baseUrl/api/v1/user/preferences'),
        headers: {
          'Authorization': 'Bearer $_token',
          'Content-Type': 'application/json',
        },
        body: json.encode(body),
      ).timeout(Duration(seconds: 10));
      
      _logger.network('Response ${response.statusCode}');
      
      if (response.statusCode == 200) {
        _logger.success('updateUserPreferences: Preferences updated');
        return {'success': true};
      } else {
        _logger.warning('updateUserPreferences: API returned ${response.statusCode}');
        return {'success': false, 'error': response.body};
      }
    } catch (e) {
      _logger.error('updateUserPreferences: Error', e);
      return {'success': false, 'error': e.toString()};
    }
  }
  
  // Update user email
  Future<Map<String, dynamic>> updateUserEmail(String newEmail) async {
    if (_token == null) {
      await isLoggedIn();
      if (_token == null) {
        throw Exception('Not authenticated');
      }
    }
    
    try {
      _logger.network('PUT $baseUrl/api/v1/user/email');
      final response = await http.put(
        Uri.parse('$baseUrl/api/v1/user/email'),
        headers: {
          'Authorization': 'Bearer $_token',
          'Content-Type': 'application/json',
        },
        body: json.encode({'email': newEmail}),
      ).timeout(Duration(seconds: 10));
      
      _logger.network('Response ${response.statusCode}');
      
      if (response.statusCode == 200) {
        _logger.success('updateUserEmail: Email updated successfully');
        return {'success': true, 'user': json.decode(response.body)};
      } else {
        final error = json.decode(response.body);
        _logger.warning('updateUserEmail: API returned ${response.statusCode}');
        return {'success': false, 'error': error['detail'] ?? 'Failed to update email'};
      }
    } catch (e) {
      _logger.error('updateUserEmail: Error', e);
      return {'success': false, 'error': e.toString()};
    }
  }
  
  String? get token => _token;
  bool get isAuthenticated => _token != null;

  // Request password reset email
  Future<void> requestPasswordReset(String email) async {
    _logger.info('requestPasswordReset: Sending reset email to $email');
    print('\n========== REQUEST PASSWORD RESET START ==========');
    print('📧 Email: $email');
    print('🌐 Calling: POST $baseUrl/api/v1/auth/forgot-password');
    
    try {
      final response = await http.post(
        Uri.parse('$baseUrl/api/v1/auth/forgot-password'),
        headers: {
          'Content-Type': 'application/json',
          'Accept': 'application/json',
        },
        body: json.encode({'email': email}),
      ).timeout(
        Duration(seconds: 10),
        onTimeout: () {
          print('⏱️ REQUEST TIMED OUT after 10 seconds!');
          throw Exception('Request timed out. Please try again.');
        },
      );
      
      print('📊 Response status: ${response.statusCode}');
      print('📄 Response body: ${response.body}');
      
      if (response.statusCode == 200) {
        _logger.success('requestPasswordReset: Reset email sent successfully');
        print('✅ Password reset email sent successfully');
        print('========== REQUEST PASSWORD RESET END ==========\n');
      } else {
        print('❌ Non-200 status code received');
        try {
          final errorData = json.decode(response.body);
          final detail = errorData['detail'] ?? 'Failed to send reset email';
          throw Exception(detail);
        } catch (e) {
          if (e.toString().contains('detail')) {
            rethrow;
          }
          throw Exception('Failed to send reset email');
        }
      }
    } on http.ClientException catch (e) {
      _logger.error('requestPasswordReset: Network error', e);
      print('❌ HTTP Client Exception: $e');
      print('========== REQUEST PASSWORD RESET ERROR END ==========\n');
      throw Exception('Network error. Please check your connection.');
    } catch (e, stackTrace) {
      _logger.error('requestPasswordReset: Error', e);
      print('❌ Unexpected error: $e');
      print('📚 Stack trace:');
      print(stackTrace.toString().split('\n').take(10).join('\n'));
      print('========== REQUEST PASSWORD RESET ERROR END ==========\n');
      String errorMsg = _extractErrorMessage(e, defaultMessage: 'Failed to send reset email. Please try again.');
      throw Exception(errorMsg);
    }
  }

  // Reset password with token
  Future<void> resetPassword(String token, String newPassword) async {
    _logger.info('resetPassword: Attempting password reset with token');
    print('\n========== RESET PASSWORD START ==========');
    print('🔑 Token: ${token.substring(0, 10)}...');
    print('🌐 Calling: POST $baseUrl/api/v1/auth/reset-password');
    
    try {
      final response = await http.post(
        Uri.parse('$baseUrl/api/v1/auth/reset-password'),
        headers: {
          'Content-Type': 'application/json',
          'Accept': 'application/json',
        },
        body: json.encode({
          'token': token,
          'new_password': newPassword,
        }),
      ).timeout(
        Duration(seconds: 10),
        onTimeout: () {
          print('⏱️ REQUEST TIMED OUT after 10 seconds!');
          throw Exception('Request timed out. Please try again.');
        },
      );
      
      print('📊 Response status: ${response.statusCode}');
      print('📄 Response body: ${response.body}');
      
      if (response.statusCode == 200) {
        _logger.success('resetPassword: Password reset successfully');
        print('✅ Password reset successfully');
        print('========== RESET PASSWORD END ==========\n');
      } else {
        print('❌ Non-200 status code received');
        try {
          final errorData = json.decode(response.body);
          final detail = errorData['detail'] ?? 'Failed to reset password';
          throw Exception(detail);
        } catch (e) {
          if (e.toString().contains('detail')) {
            rethrow;
          }
          throw Exception('Failed to reset password');
        }
      }
    } on http.ClientException catch (e) {
      _logger.error('resetPassword: Network error', e);
      print('❌ HTTP Client Exception: $e');
      print('========== RESET PASSWORD ERROR END ==========\n');
      throw Exception('Network error. Please check your connection.');
    } catch (e, stackTrace) {
      _logger.error('resetPassword: Error', e);
      print('❌ Unexpected error: $e');
      print('📚 Stack trace:');
      print(stackTrace.toString().split('\n').take(10).join('\n'));
      print('========== RESET PASSWORD ERROR END ==========\n');
      String errorMsg = _extractErrorMessage(e, defaultMessage: 'Failed to reset password. Please try again.');
      throw Exception(errorMsg);
    }
  }

  // ============= CUSTOM VEHICLE NAME PERSISTENCE =============
  /// Save a custom name for a vehicle/tag (persisted across sessions)
  Future<void> saveCustomVehicleName(String vehicleId, String customName) async {
    try {
      final prefs = await SharedPreferences.getInstance();
      await prefs.setString('custom_vehicle_name_$vehicleId', customName);
      print('✅ Saved custom name for $vehicleId: $customName');
    } catch (e) {
      print('❌ Failed to save custom vehicle name: $e');
      rethrow;
    }
  }

  /// Retrieve custom name for a vehicle (returns null if no custom name set)
  Future<String?> getCustomVehicleName(String vehicleId) async {
    try {
      final prefs = await SharedPreferences.getInstance();
      return prefs.getString('custom_vehicle_name_$vehicleId');
    } catch (e) {
      print('❌ Failed to get custom vehicle name: $e');
      return null;
    }
  }

  /// Delete custom name for a vehicle (revert to showing IMEI)
  Future<void> deleteCustomVehicleName(String vehicleId) async {
    try {
      final prefs = await SharedPreferences.getInstance();
      await prefs.remove('custom_vehicle_name_$vehicleId');
      print('✅ Deleted custom name for $vehicleId');
    } catch (e) {
      print('❌ Failed to delete custom vehicle name: $e');
    }
  }

  /// Get all custom vehicle names as a map {vehicleId: customName}
  Future<Map<String, String>> getAllCustomVehicleNames() async {
    try {
      final prefs = await SharedPreferences.getInstance();
      final customNames = <String, String>{};
      
      prefs.getKeys().forEach((key) {
        if (key.startsWith('custom_vehicle_name_')) {
          final vehicleId = key.replaceFirst('custom_vehicle_name_', '');
          final customName = prefs.getString(key);
          if (customName != null) {
            customNames[vehicleId] = customName;
          }
        }
      });
      
      return customNames;
    } catch (e) {
      print('❌ Failed to get all custom vehicle names: $e');
      return {};
    }
  }
}

