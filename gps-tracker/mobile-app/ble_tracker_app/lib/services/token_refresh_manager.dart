import 'dart:async';
import 'package:flutter/widgets.dart';
import 'auth_service.dart';
import 'logger_service.dart';

/// Manages automatic token refresh based on user activity
/// - Monitors user interactions (taps, scrolls, etc.)
/// - Refreshes token before expiration when user is active
/// - Logs out user after 10 minutes of inactivity
class TokenRefreshManager {
  static final TokenRefreshManager _instance = TokenRefreshManager._internal();
  factory TokenRefreshManager() => _instance;
  TokenRefreshManager._internal();

  final AuthService _authService = AuthService();
  final LoggerService _logger = LoggerService();

  Timer? _refreshTimer;
  Timer? _idleLogoutTimer;
  DateTime _lastActivity = DateTime.now();
  bool _isInitialized = false;
  Function? _onIdleLogout;

  // Configuration
  static const Duration checkInterval = Duration(minutes: 1); // Check token refresh every 1 min
  static const Duration idleTimeout = Duration(minutes: 10); // Auto-logout after 10 min idle
  static const int tokenRefreshThreshold = 20; // Refresh when token is 20+ min old

  /// Initialize the token refresh manager with optional logout callback
  void initialize({Function? onIdleLogout}) {
    if (_isInitialized) return;
    
    _isInitialized = true;
    _lastActivity = DateTime.now();
    _onIdleLogout = onIdleLogout;
    
    // Start periodic token refresh check
    _refreshTimer = Timer.periodic(checkInterval, (_) => _checkAndRefresh());
    
    // Start idle timeout monitoring
    _idleLogoutTimer = Timer.periodic(Duration(seconds: 30), (_) => _checkIdleTimeout());
    
    _logger.info('🔄 Token refresh manager initialized with 10-minute idle timeout');
  }

  /// Record user activity
  void recordActivity() {
    _lastActivity = DateTime.now();
  }

  /// Check if user has been idle too long and logout if needed
  Future<void> _checkIdleTimeout() async {
    try {
      final isLoggedIn = await _authService.isLoggedIn();
      if (!isLoggedIn) return;

      final timeSinceActivity = DateTime.now().difference(_lastActivity);
      
      if (timeSinceActivity >= idleTimeout) {
        _logger.info('⏱️  User idle for ${timeSinceActivity.inMinutes} min - logging out...');
        await _authService.logout();
        
        // Trigger logout callback to navigate to login screen
        if (_onIdleLogout != null) {
          _onIdleLogout!();
        }
      }
    } catch (e) {
      _logger.error('❌ Idle timeout check error: $e');
    }
  }

  /// Check if token needs refresh and do it if user is active
  Future<void> _checkAndRefresh() async {
    try {
      // Check if user is still logged in
      final isLoggedIn = await _authService.isLoggedIn();
      if (!isLoggedIn) {
        return;
      }

      // Check if token is old enough to refresh
      final shouldRefresh = await _authService.shouldRefreshToken();
      if (!shouldRefresh) {
        return;
      }

      // Token is old - refresh it to keep session alive while user is active
      final tokenAge = await _authService.getTokenAgeMinutes();
      _logger.info('🔄 Token is $tokenAge min old, refreshing to keep session alive...');
      
      final success = await _authService.refreshToken();
      if (success) {
        _logger.success('✅ Auto-refreshed token - session extended');
      } else {
        _logger.error('❌ Auto-refresh failed - user may need to re-login');
      }
    } catch (e) {
      _logger.error('❌ Token refresh check error: $e');
    }
  }

  /// Manually trigger a token refresh
  Future<bool> refreshNow() async {
    _logger.info('🔄 Manual token refresh triggered');
    return await _authService.refreshToken();
  }

  /// Get minutes until idle logout
  int getMinutesUntilIdleLogout() {
    final timeSinceActivity = DateTime.now().difference(_lastActivity);
    final remainingMinutes = idleTimeout.inMinutes - timeSinceActivity.inMinutes;
    return remainingMinutes > 0 ? remainingMinutes : 0;
  }

  /// Dispose resources
  void dispose() {
    _refreshTimer?.cancel();
    _idleLogoutTimer?.cancel();
    _refreshTimer = null;
    _idleLogoutTimer = null;
    _isInitialized = false;
    _onIdleLogout = null;
    _logger.info('🛑 Token refresh manager disposed');
  }
}

/// Widget that monitors user activity for token refresh and idle timeout
class ActivityMonitor extends StatefulWidget {
  final Widget child;

  const ActivityMonitor({Key? key, required this.child}) : super(key: key);

  @override
  State<ActivityMonitor> createState() => _ActivityMonitorState();
}

class _ActivityMonitorState extends State<ActivityMonitor> {
  final TokenRefreshManager _refreshManager = TokenRefreshManager();

  @override
  void initState() {
    super.initState();
    
    // Initialize with logout callback to navigate to welcome screen
    _refreshManager.initialize(
      onIdleLogout: () {
        if (mounted && context.mounted) {
          Navigator.of(context).pushNamedAndRemoveUntil('/welcome', (route) => false);
        }
      },
    );
  }

  @override
  void dispose() {
    // Don't dispose the singleton, just stop tracking
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    return Listener(
      behavior: HitTestBehavior.translucent,
      onPointerDown: (_) => _refreshManager.recordActivity(),
      onPointerMove: (_) => _refreshManager.recordActivity(),
      child: widget.child,
    );
  }
}
