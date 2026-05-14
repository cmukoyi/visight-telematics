import 'package:flutter/foundation.dart';

/// Environment Configuration - Automatic Build Mode Detection
/// 
/// ✅ AUTOMATIC MODE SELECTION (No manual configuration needed!):
/// - `flutter run` → Debug mode → localhost:8001
/// - `flutter build web --release` → Release mode → https://beacontelematics.co.uk
/// - No flags needed, no manual changes, no confusion!
/// 
/// 🔒 DEPLOYMENT SAFETY:
/// - Production URL hardcoded and always used for release builds
/// - Development URL only active in debug mode (flutter run)
/// - Both URLs committed to repo (safe, no secrets)
/// - Git hooks provide extra protection
/// 
/// 📝 Usage:
///   final apiUrl = Environment.apiBaseUrl;
///   if (Environment.isDevelopment) { /* dev-only code */ }

class Environment {
  // 🔒 PRODUCTION URL - Safe to commit, used for all release builds
  static const String _productionUrl = 'https://beacontelematics.co.uk';
  
  // 🛠️ DEVELOPMENT URL - Safe to commit, only active in debug mode
  static const String _developmentUrl = 'http://localhost:8001';
  
  /// Get the API base URL based on Flutter's build mode
  /// 
  /// AUTOMATIC SELECTION:
  /// - Debug mode (flutter run): Returns localhost
  /// - Release mode (flutter build): Returns production URL
  /// - Profile mode: Returns production URL (for testing production config)
  /// 
  /// No manual configuration needed!
  static String get apiBaseUrl {
    if (kDebugMode) {
      // Running with: flutter run
      // OR: flutter run -d chrome (web debug)
      print('🛠️  DEBUG MODE: Using development server → $_developmentUrl');
      return _developmentUrl;
    } else {
      // Running with: flutter build web --release
      // OR: flutter build apk --release
      print('🚀 RELEASE MODE: Using production server → $_productionUrl');
      return _productionUrl;
    }
  }
  
  /// Check if running in development/debug mode
  /// Returns true for: flutter run
  static bool get isDevelopment => kDebugMode;
  
  /// Check if running in production/release mode
  /// Returns true for: flutter build web --release
  static bool get isProduction => kReleaseMode;
  
  /// Check if running in profile mode
  /// Returns true for: flutter run --profile
  static bool get isProfile => kProfileMode;
  
  /// Get current build mode as string
  static String get buildMode {
    if (kDebugMode) return 'debug';
    if (kReleaseMode) return 'release';
    if (kProfileMode) return 'profile';
    return 'unknown';
  }
  
  /// Get user-friendly environment description
  static String get environmentDescription {
    if (kDebugMode) {
      return 'Development (localhost:8001)';
    } else {
      return 'Production (beacontelematics.co.uk)';
    }
  }
}
