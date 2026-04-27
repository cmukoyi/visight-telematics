import 'dart:async';
import 'package:flutter/foundation.dart';
import 'package:http/http.dart' as http;
import 'package:ble_tracker_app/config/environment.dart';

class DeploymentMonitorService {
  static final DeploymentMonitorService _instance = DeploymentMonitorService._internal();

  factory DeploymentMonitorService() {
    return _instance;
  }

  DeploymentMonitorService._internal();

  bool _isDeploying = false;
  Timer? _healthCheckTimer;
  final Duration _checkInterval = Duration(seconds: 3);
  final Duration _maxWaitTime = Duration(minutes: 10);
  DateTime? _deploymentStartTime;

  final _deploymentStateChanged = StreamController<bool>.broadcast();

  bool get isDeploying => _isDeploying;
  Stream<bool> get deploymentStateChanged => _deploymentStateChanged.stream;

  /// Called when a deployment error is detected
  void detectDeploymentInProgress() {
    if (!_isDeploying) {
      _isDeploying = true;
      _deploymentStartTime = DateTime.now();
      _deploymentStateChanged.add(true);
      _startHealthChecks();
    }
  }

  /// Check if error indicates deployment in progress.
  /// Only returns true for HTTP gateway errors (502/503/504) where the server
  /// is genuinely being replaced. Common errors like connection timeouts,
  /// JSON parse failures, or 500s are NOT deployment indicators.
  static bool isDeploymentError(dynamic error) {
    final errorStr = error.toString();
    // Match only explicit HTTP 502/503/504 status codes in the error string.
    // These are the codes a reverse-proxy (nginx/Caddy) returns when the
    // upstream container is being restarted during a deployment.
    return RegExp(r'\b(502|503|504)\b').hasMatch(errorStr);
  }

  void _startHealthChecks() {
    _healthCheckTimer?.cancel();
    _healthCheckTimer = Timer.periodic(_checkInterval, (timer) async {
      final elapsed = DateTime.now().difference(_deploymentStartTime!);
      if (elapsed > _maxWaitTime) {
        stopMonitoring();
        return;
      }

      // Actually ping the backend health endpoint.
      // If it responds with 2xx the deployment is complete.
      try {
        final response = await http
            .get(Uri.parse('${Environment.apiBaseUrl}/health'))
            .timeout(const Duration(seconds: 5));
        if (response.statusCode >= 200 && response.statusCode < 300) {
          stopMonitoring();
        }
      } catch (_) {
        // Still down — keep waiting
      }
    });
  }

  void stopMonitoring() {
    _healthCheckTimer?.cancel();
    _healthCheckTimer = null;
    _isDeploying = false;
    _deploymentStartTime = null;
    _deploymentStateChanged.add(false);
  }

  void dispose() {
    _healthCheckTimer?.cancel();
    _deploymentStateChanged.close();
  }
}
