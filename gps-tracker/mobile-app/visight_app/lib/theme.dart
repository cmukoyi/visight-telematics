import 'package:flutter/material.dart';

/// Colours taken from the mobile designs (UIDesigns/Mobile).
class AppColors {
  static const navy = Color(0xFF1B1446);
  static const blue = Color(0xFF2D7FF9);
  static const text = Color(0xFF1B1446);
  static const muted = Color(0xFF6B6F80);
  static const surface = Color(0xFFF7F7F8);
  static const segment = Color(0xFFF1F1F3);
  static const panel = Color(0xFFCDD3DC);
  static const border = Color(0xFFE3E4E8);
  static const alert = Color(0xFFF57C00);

  // Vehicle avatar: moving, idle, offline.
  static const moving = Color(0xFF7DC383);
  static const idle = Color(0xFFA9CB91);
  static const offline = Color(0xFFC5C9D1);

  // Shortcut tiles: background, accent.
  static const pink = (Color(0xFFF4E6F5), Color(0xFFB27BC6));
  static const sky = (Color(0xFFE4F3FA), Color(0xFF5FB2D6));
  static const lavender = (Color(0xFFE9EBFB), Color(0xFF6C7BD9));
  static const mint = (Color(0xFFE5F4EA), Color(0xFF4FA36A));
}

ThemeData buildTheme() {
  final scheme = ColorScheme.fromSeed(seedColor: AppColors.navy, primary: AppColors.navy, secondary: AppColors.blue,
      surface: Colors.white);
  return ThemeData(
    colorScheme: scheme,
    scaffoldBackgroundColor: Colors.white,
    textTheme: Typography.blackMountainView.apply(bodyColor: AppColors.text, displayColor: AppColors.text),
    navigationBarTheme: NavigationBarThemeData(
      backgroundColor: Colors.white,
      surfaceTintColor: Colors.transparent,
      indicatorColor: AppColors.navy,
      iconTheme: WidgetStateProperty.resolveWith(
          (s) => IconThemeData(color: s.contains(WidgetState.selected) ? Colors.white : AppColors.navy)),
      labelTextStyle: const WidgetStatePropertyAll(
          TextStyle(fontSize: 13, fontWeight: FontWeight.w500, color: AppColors.navy)),
    ),
    inputDecorationTheme: InputDecorationTheme(
      filled: true,
      fillColor: AppColors.surface,
      border: OutlineInputBorder(borderRadius: BorderRadius.circular(12), borderSide: BorderSide.none),
      contentPadding: const EdgeInsets.symmetric(horizontal: 16, vertical: 14),
    ),
    filledButtonTheme: FilledButtonThemeData(
      style: FilledButton.styleFrom(
        backgroundColor: AppColors.navy,
        minimumSize: const Size.fromHeight(50),
        shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(12)),
      ),
    ),
    outlinedButtonTheme: OutlinedButtonThemeData(
      style: OutlinedButton.styleFrom(
        foregroundColor: AppColors.navy,
        side: const BorderSide(color: AppColors.muted),
        shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(8)),
      ),
    ),
  );
}
