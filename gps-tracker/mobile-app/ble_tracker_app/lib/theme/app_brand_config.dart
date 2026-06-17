import 'package:flutter/material.dart';

/// White-label brand configuration.
///
/// Drop in a new [AppBrandConfig] at app startup to completely re-skin
/// the app for a different deployment — no UI code changes required.
///
/// Usage in main.dart:
/// ```dart
/// AppTheme.configure(AppBrandConfig.pinplot());
/// runApp(MyApp());
/// ```
class AppBrandConfig {
  /// The primary brand colour. All theme colours are derived from this.
  final Color primaryColor;

  /// App display name shown on the welcome screen and window title.
  final String appName;

  /// Path to the logo asset (e.g. 'assets/logo.png').
  /// Should be a transparent PNG or SVG, ideally at least 400px wide.
  final String logoAsset;

  /// Optional tagline shown beneath the app name on the welcome screen.
  final String? tagline;

  /// Override the font family used for headings. Defaults to 'Poppins'.
  final String displayFont;

  /// Override the font family used for body text. Defaults to 'Inter'.
  final String bodyFont;

  const AppBrandConfig({
    required this.primaryColor,
    required this.appName,
    required this.logoAsset,
    this.tagline,
    this.displayFont = 'Poppins',
    this.bodyFont = 'Inter',
  });

  // ─── Built-in brand presets ───────────────────────────────────────────────

  /// Default PinPlot deployment.
  factory AppBrandConfig.pinplot() => const AppBrandConfig(
        primaryColor: Color(0xFF2E7D32), // Forest green
        appName: 'PinPlot',
        logoAsset: 'assets/MainLogo.png',
        tagline: 'Track your assets with ease',
      );

  /// Example white-label deployment — replace with your client values.
  factory AppBrandConfig.custom({
    required Color primaryColor,
    required String appName,
    required String logoAsset,
    String? tagline,
  }) =>
      AppBrandConfig(
        primaryColor: primaryColor,
        appName: appName,
        logoAsset: logoAsset,
        tagline: tagline,
      );
}
