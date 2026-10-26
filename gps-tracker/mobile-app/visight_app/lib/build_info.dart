import 'dart:io';

import 'package:package_info_plus/package_info_plus.dart';

/// This app build: version and build number (pubspec + CI run number) and the commit and branch it was
/// built from (--dart-define=GIT_SHA / GIT_BRANCH in .github/workflows/mobile-app.yml; "dev" locally).
/// Shown in the menu, written to the log, sent to the server as X-App-Version (Users page) and put in
/// problem reports, so it's clear whether someone runs a build with a fix.
class AppBuild {
  AppBuild._();

  static const commit = String.fromEnvironment('GIT_SHA', defaultValue: 'dev');
  static const branch = String.fromEnvironment('GIT_BRANCH');

  static String version = '?';
  static String buildNumber = '?';

  static Future<void> load() async {
    try {
      final p = await PackageInfo.fromPlatform();
      version = p.version;
      buildNumber = p.buildNumber;
    } catch (_) {
      // Tests and unsupported platforms keep "?"
    }
  }

  /// "0.1.0 · build 57 · 96c92b6 (feat/mobile-app)"
  static String get label => '$version · build $buildNumber · $commit${branch.isEmpty ? '' : ' ($branch)'}';

  /// "0.1.0+57 96c92b6 android" — the X-App-Version header.
  static String get header => '$version+$buildNumber $commit ${Platform.operatingSystem}';
}
