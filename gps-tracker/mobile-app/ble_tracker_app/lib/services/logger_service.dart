import 'dart:io';
import 'package:flutter/foundation.dart';
import 'package:path_provider/path_provider.dart';
import 'package:intl/intl.dart';

class LoggerService {
  static final LoggerService _instance = LoggerService._internal();
  factory LoggerService() => _instance;
  LoggerService._internal();

  final List<String> _logs = [];
  final int _maxLogs = 1000; // Keep last 1000 log entries
  
  // Log levels
  static const String INFO = '📘 INFO';
  static const String SUCCESS = '✅ SUCCESS';
  static const String WARNING = '⚠️ WARNING';
  static const String ERROR = '❌ ERROR';
  static const String DEBUG = '🔍 DEBUG';
  static const String NETWORK = '📡 NETWORK';

  void log(String level, String message, [dynamic error]) {
    final timestamp = DateFormat('yyyy-MM-dd HH:mm:ss.SSS').format(DateTime.now());
    final logEntry = '[$timestamp] $level: $message${error != null ? '\nError: $error' : ''}';
    
    // Add to in-memory logs
    _logs.add(logEntry);
    if (_logs.length > _maxLogs) {
      _logs.removeAt(0); // Remove oldest log
    }
    
    // Print to console (for Flutter debug console)
    if (kDebugMode) {
      print(logEntry);
    }
  }

  void info(String message) => log(INFO, message);
  void success(String message) => log(SUCCESS, message);
  void warning(String message) => log(WARNING, message);
  void error(String message, [dynamic error]) => log(ERROR, message, error);
  void debug(String message) => log(DEBUG, message);
  void network(String message) => log(NETWORK, message);

  // Get all logs as a string
  String getAllLogs() {
    return _logs.join('\n');
  }

  // Get logs count
  int getLogsCount() => _logs.length;

  // Clear all logs
  void clearLogs() {
    _logs.clear();
    log(INFO, 'Logs cleared');
  }

  // Export logs to file
  Future<File> exportLogsToFile() async {
    try {
      final directory = await getApplicationDocumentsDirectory();
      final timestamp = DateFormat('yyyyMMdd_HHmmss').format(DateTime.now());
      final file = File('${directory.path}/ble_tracker_logs_$timestamp.txt');
      
      // Device info header
      final header = '''
================================================================================
BLE Tracker - Debug Logs
Generated: ${DateFormat('yyyy-MM-dd HH:mm:ss').format(DateTime.now())}
Platform: ${Platform.operatingSystem} ${Platform.operatingSystemVersion}
================================================================================

''';
      
      final content = header + getAllLogs();
      await file.writeAsString(content);
      
      log(SUCCESS, 'Logs exported to: ${file.path}');
      return file;
    } catch (e) {
      log(ERROR, 'Failed to export logs', e);
      rethrow;
    }
  }

  // Get recent logs (last N entries)
  String getRecentLogs(int count) {
    final recentLogs = _logs.length > count 
        ? _logs.sublist(_logs.length - count) 
        : _logs;
    return recentLogs.join('\n');
  }
}
