import 'package:http/http.dart' as http;
import 'dart:convert';
import 'package:intl/intl.dart';
import 'package:ble_tracker_app/config/environment.dart';

/// Enhanced logger for Pinplot mobile app
/// Sends logs to backend admin portal with proper sanitization
class AdminPortalLogger {
  static const String _logEndpoint = '/api/admin/logs';
  
  final String backendUrl;
  final String? adminKey;
  late String _baseUrl;
  
  AdminPortalLogger({
    String? backendUrl,
    this.adminKey,
  }) : backendUrl = backendUrl ?? Environment.apiBaseUrl {
    _baseUrl = this.backendUrl.replaceAll(RegExp(r'/$'), '');
  }

  /// Sanitize sensitive data from logs
  Map<String, dynamic> _sanitizeContext(Map<String, dynamic>? context) {
    if (context == null) return {};
    
    const sensitiveKeys = {
      'password', 'token', 'secret', 'api_key', 'api_secret',
      'auth', 'authorization', 'bearer', 'credit_card', 'cvv',
      'ssn', 'pin', 'private_key', 'refresh_token', 'access_token'
    };
    
    final sanitized = <String, dynamic>{};
    
    context.forEach((key, value) {
      final lowerKey = key.toLowerCase();
      final isSensitive = sensitiveKeys.any((s) => lowerKey.contains(s));
      
      if (isSensitive) {
        sanitized[key] = '[REDACTED]';
      } else if (value is Map) {
        sanitized[key] = _sanitizeContext(value as Map<String, dynamic>);
      } else if (value is List) {
        sanitized[key] = value.map((item) {
          return item is Map ? _sanitizeContext(item as Map<String, dynamic>) : item;
        }).toList();
      } else {
        sanitized[key] = value;
      }
    });
    
    return sanitized;
  }

  /// Log a message to the admin portal
  Future<void> _sendLog({
    required String level,
    required String category,
    required String message,
    Map<String, dynamic>? context,
    String? stackTrace,
    String? source = 'flutter_app',
  }) async {
    try {
      final sanitizedContext = _sanitizeContext(context);
      
      final payload = {
        'level': level.toUpperCase(),
        'category': category,
        'message': message,
        'context': sanitizedContext,
        'stack_trace': stackTrace,
        'source': source,
      };
      
      final headers = {
        'Content-Type': 'application/json',
        if (adminKey != null) 'X-Admin-Key': adminKey!,
      };
      
      final response = await http.post(
        Uri.parse('$_baseUrl$_logEndpoint'),
        headers: headers,
        body: jsonEncode(payload),
      ).timeout(const Duration(seconds: 5));
      
      if (response.statusCode != 200 && response.statusCode != 201) {
        _logLocally(
          level: 'WARNING',
          category: 'logging',
          message: 'Failed to send log to admin portal: ${response.statusCode}',
        );
      }
    } catch (e) {
      // Fail silently - don't let logging errors crash the app
      _logLocally(
        level: 'WARNING',
        category: 'logging',
        message: 'Error sending log to admin portal: $e',
      );
    }
  }

  /// Log to local console only
  void _logLocally({
    required String level,
    required String category,
    required String message,
  }) {
    final timestamp = DateFormat('HH:mm:ss.SSS').format(DateTime.now());
    print('[$timestamp] [$level] [$category] $message');
  }

  /// Log debug message
  Future<void> debug(
    String category,
    String message, {
    Map<String, dynamic>? context,
  }) {
    _logLocally(level: 'DEBUG', category: category, message: message);
    return _sendLog(
      level: 'DEBUG',
      category: category,
      message: message,
      context: context,
    );
  }

  /// Log info message
  Future<void> info(
    String category,
    String message, {
    Map<String, dynamic>? context,
  }) {
    _logLocally(level: 'INFO', category: category, message: message);
    return _sendLog(
      level: 'INFO',
      category: category,
      message: message,
      context: context,
    );
  }

  /// Log warning message
  Future<void> warning(
    String category,
    String message, {
    Map<String, dynamic>? context,
  }) {
    _logLocally(level: 'WARNING', category: category, message: message);
    return _sendLog(
      level: 'WARNING',
      category: category,
      message: message,
      context: context,
    );
  }

  /// Log error message
  Future<void> error(
    String category,
    String message, {
    Map<String, dynamic>? context,
    String? stackTrace,
  }) {
    _logLocally(level: 'ERROR', category: category, message: message);
    return _sendLog(
      level: 'ERROR',
      category: category,
      message: message,
      context: context,
      stackTrace: stackTrace,
    );
  }

  /// Log critical message
  Future<void> critical(
    String category,
    String message, {
    Map<String, dynamic>? context,
    String? stackTrace,
  }) {
    _logLocally(level: 'CRITICAL', category: category, message: message);
    return _sendLog(
      level: 'CRITICAL',
      category: category,
      message: message,
      context: context,
      stackTrace: stackTrace,
    );
  }

  /// Log authentication event
  Future<void> logAuth(String event, {String? details, bool success = true}) {
    return info(
      'auth',
      'Authentication: $event',
      context: {
        'event': event,
        'success': success,
        'details': details,
        'timestamp': DateTime.now().toIso8601String(),
      },
    );
  }

  /// Log location update
  Future<void> logLocation(
    double latitude,
    double longitude, {
    String? description,
    Map<String, dynamic>? additionalData,
  }) {
    return info(
      'location',
      'Location updated: $latitude, $longitude',
      context: {
        'latitude': latitude,
        'longitude': longitude,
        'description': description,
        ...?additionalData,
        'timestamp': DateTime.now().toIso8601String(),
      },
    );
  }

  /// Log API call
  Future<void> logApiCall(
    String method,
    String endpoint, {
    int? statusCode,
    String? errorMessage,
    Map<String, dynamic>? additionalData,
  }) {
    final message = errorMessage != null
        ? '$method $endpoint - Error: $errorMessage'
        : '$method $endpoint - Status: $statusCode';
    
    final level = (statusCode ?? 500) >= 400 ? 'WARNING' : 'DEBUG';
    
    return level == 'WARNING'
        ? warning(
            'api',
            message,
            context: {
              'method': method,
              'endpoint': endpoint,
              'status_code': statusCode,
              ...?additionalData,
            },
          )
        : debug(
            'api',
            message,
            context: {
              'method': method,
              'endpoint': endpoint,
              'status_code': statusCode,
              ...?additionalData,
            },
          );
  }

  /// Log UI event
  Future<void> logUIEvent(String screen, String action, {Map<String, dynamic>? data}) {
    return debug(
      'ui',
      'Screen: $screen, Action: $action',
      context: {
        'screen': screen,
        'action': action,
        ...?data,
      },
    );
  }

  /// Log device event
  Future<void> logDeviceEvent(
    String event, {
    String? deviceId,
    String? imei,
    Map<String, dynamic>? deviceInfo,
  }) {
    return info(
      'device',
      'Device event: $event',
      context: {
        'event': event,
        'device_id': deviceId,
        'imei': imei,
        ...?deviceInfo,
      },
    );
  }
}

/// Global logger instance
AdminPortalLogger? _loggerInstance;

/// Initialize global logger instance
AdminPortalLogger initializeLogger({
  String? backendUrl,
  String? adminKey,
}) {
  _loggerInstance = AdminPortalLogger(
    backendUrl: backendUrl,
    adminKey: adminKey,
  );
  return _loggerInstance!;
}

/// Get global logger instance
AdminPortalLogger getLogger() {
  return _loggerInstance ??= AdminPortalLogger();
}

// Usage examples in Flutter app:
// 
// // In main.dart - initialize logger
// void main() {
//   initializeLogger();
//   runApp(const MyApp());
// }
//
// // In various screens
// final logger = getLogger();
//
// // Log authentication
// await logger.logAuth('login_attempt', success: true);
//
// // Log location
// await logger.logLocation(51.5074, -0.1278, description: 'Office location');
//
// // Log API calls
// try {
//   final response = await api.getTags();
//   await logger.logApiCall('GET', '/api/tags', statusCode: response.statusCode);
// } catch (e) {
//   await logger.logApiCall('GET', '/api/tags', errorMessage: e.toString());
// }
//
// // Log UI events
// await logger.logUIEvent('trip_detail_screen', 'map_marker_tapped', data: {'marker_type': 'start'});
//
// // Log errors with stack trace
// try {
//   // some operation
// } catch (e, stackTrace) {
//   await logger.error('auth', 'Login failed: $e', stackTrace: stackTrace.toString());
// }
