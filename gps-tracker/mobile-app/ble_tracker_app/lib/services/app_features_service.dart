import 'dart:convert';
import 'package:http/http.dart' as http;
import 'package:shared_preferences/shared_preferences.dart';
import 'package:ble_tracker_app/config/environment.dart';

class AppFeatures {
  final bool showMap;
  final bool showJourney;
  final bool showAssets;
  final bool showScan;
  final bool showSettings;
  final bool showSolutions;

  const AppFeatures({
    required this.showMap,
    required this.showJourney,
    required this.showAssets,
    required this.showScan,
    required this.showSettings,
    required this.showSolutions,
  });

  /// All tabs visible — used as safe fallback if the server is unreachable.
  factory AppFeatures.defaults() => const AppFeatures(
        showMap: true,
        showJourney: true,
        showAssets: true,
        showScan: true,
        showSettings: true,
        showSolutions: false,
      );

  factory AppFeatures.fromJson(Map<String, dynamic> json) => AppFeatures(
        showMap: json['show_map'] as bool? ?? true,
        showJourney: json['show_journey'] as bool? ?? true,
        showAssets: json['show_assets'] as bool? ?? true,
        showScan: json['show_scan'] as bool? ?? true,
        showSettings: json['show_settings'] as bool? ?? true,
        showSolutions: json['show_solutions'] as bool? ?? false,
      );

  Map<String, dynamic> toJson() => {
        'show_map': showMap,
        'show_journey': showJourney,
        'show_assets': showAssets,
        'show_scan': showScan,
        'show_settings': showSettings,
        'show_solutions': showSolutions,
      };
}

class AppFeaturesService {
  static const _cacheKey = 'app_features_cache';
  static String get _url => '${Environment.apiBaseUrl}/api/v1/app-features';

  /// Fetch features from the server and cache them locally.
  /// Falls back to the cached value, then to [AppFeatures.defaults()].
  Future<AppFeatures> fetchFeatures() async {
    try {
      final response = await http.get(Uri.parse(_url)).timeout(
        const Duration(seconds: 10),
      );
      if (response.statusCode == 200) {
        final data = json.decode(response.body) as Map<String, dynamic>;
        final features = AppFeatures.fromJson(data);
        await _cache(features);
        return features;
      }
    } catch (_) {
      // Network error — fall through to cache
    }
    return await _fromCache() ?? AppFeatures.defaults();
  }

  Future<void> _cache(AppFeatures f) async {
    final prefs = await SharedPreferences.getInstance();
    await prefs.setString(_cacheKey, json.encode(f.toJson()));
  }

  Future<AppFeatures?> _fromCache() async {
    try {
      final prefs = await SharedPreferences.getInstance();
      final raw = prefs.getString(_cacheKey);
      if (raw != null) {
        return AppFeatures.fromJson(json.decode(raw) as Map<String, dynamic>);
      }
    } catch (_) {}
    return null;
  }
}
