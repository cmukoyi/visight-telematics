import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:google_fonts/google_fonts.dart';
import 'app_brand_config.dart';

/// Central theme system for the app.
///
/// Call [AppTheme.configure] once at startup before [runApp], then read
/// [AppTheme.brandPrimary], [AppTheme.light], and [AppTheme.dark] anywhere.
///
/// All colours are derived from the active [AppBrandConfig] — no hardcoded
/// hex values should appear in screen files.
class AppTheme {
  AppTheme._();

  static AppBrandConfig _config = AppBrandConfig.pinplot();

  /// Configure the theme for this deployment.
  /// Call before [runApp] in main.dart.
  static void configure(AppBrandConfig config) {
    _config = config;
  }

  // ─── Brand colour accessors ───────────────────────────────────────────────

  /// The primary brand colour (e.g. PinPlot green).
  static Color get brandPrimary => _config.primaryColor;

  /// Slightly darker shade for pressed/hover states.
  static Color get brandPrimaryHover =>
      _darken(_config.primaryColor, 0.12);

  /// Very light tint, used for selected backgrounds.
  static Color get brandPrimaryLight =>
      _config.primaryColor.withOpacity(0.10);

  /// Surface tint for cards / containers in light mode.
  static Color get brandSurface =>
      _config.primaryColor.withOpacity(0.04);

  /// Background gradient for auth screens (light green gradient)
  static LinearGradient get backgroundGradient {
    return LinearGradient(
      begin: Alignment.topLeft,
      end: Alignment.bottomRight,
      colors: [
        Color(0xFFE8F5E8),  // Very light green
        Color(0xFF80C080),  // Light green
        Color(0xFF3D8B3D),  // Medium green
        Color(0xFF1C6B1C),  // Deeper green
        _config.primaryColor,  // Base brand color
      ],
    );
  }

  // ─── Semantic colour tokens ───────────────────────────────────────────────

  static const Color successGreen = Color(0xFF388E3C);
  static const Color warningAmber = Color(0xFFF59E0B);
  static const Color errorRed = Color(0xFFD32F2F);
  static const Color infoBlue = Color(0xFF1976D2);

  // ─── Spacing constants (4pt grid) ─────────────────────────────────────────

  static const double spaceXS = 4.0;
  static const double spaceS = 8.0;
  static const double spaceM = 12.0;
  static const double spaceL = 16.0;
  static const double spaceXL = 24.0;
  static const double spaceXXL = 32.0;
  static const double spaceXXXL = 48.0;

  // ─── Border radii ─────────────────────────────────────────────────────────

  static const double radiusS = 8.0;
  static const double radiusM = 12.0;
  static const double radiusL = 16.0;
  static const double radiusXL = 24.0;
  static const double radiusRound = 100.0;

  // ─── Typography ───────────────────────────────────────────────────────────

  static TextStyle displayLarge(BuildContext context) => GoogleFonts.getFont(
        _config.displayFont,
        fontSize: 32,
        fontWeight: FontWeight.bold,
        height: 1.2,
        color: Theme.of(context).colorScheme.onSurface,
      );

  static TextStyle displayMedium(BuildContext context) => GoogleFonts.getFont(
        _config.displayFont,
        fontSize: 24,
        fontWeight: FontWeight.bold,
        height: 1.3,
        color: Theme.of(context).colorScheme.onSurface,
      );

  static TextStyle titleLarge(BuildContext context) => GoogleFonts.getFont(
        _config.bodyFont,
        fontSize: 20,
        fontWeight: FontWeight.w600,
        height: 1.4,
        color: Theme.of(context).colorScheme.onSurface,
      );

  static TextStyle titleMedium(BuildContext context) => GoogleFonts.getFont(
        _config.bodyFont,
        fontSize: 16,
        fontWeight: FontWeight.w600,
        height: 1.4,
        color: Theme.of(context).colorScheme.onSurface,
      );

  static TextStyle bodyLarge(BuildContext context) => GoogleFonts.getFont(
        _config.bodyFont,
        fontSize: 16,
        fontWeight: FontWeight.w400,
        height: 1.5,
        color: Theme.of(context).colorScheme.onSurface,
      );

  static TextStyle bodyMedium(BuildContext context) => GoogleFonts.getFont(
        _config.bodyFont,
        fontSize: 14,
        fontWeight: FontWeight.w400,
        height: 1.5,
        color: Theme.of(context).colorScheme.onSurface,
      );

  static TextStyle bodySmall(BuildContext context) => GoogleFonts.getFont(
        _config.bodyFont,
        fontSize: 12,
        fontWeight: FontWeight.w400,
        height: 1.5,
        color: Theme.of(context).colorScheme.onSurfaceVariant,
      );

  static TextStyle labelLarge(BuildContext context) => GoogleFonts.getFont(
        _config.bodyFont,
        fontSize: 14,
        fontWeight: FontWeight.w600,
        letterSpacing: 0.1,
        color: Theme.of(context).colorScheme.onSurface,
      );

  // ─── Theme builders ───────────────────────────────────────────────────────

  /// Warm professional light theme.
  static ThemeData get light {
    final cs = ColorScheme.fromSeed(
      seedColor: _config.primaryColor,
      brightness: Brightness.light,
      surface: const Color(0xFFFAF9F6),       // Warm off-white
      onSurface: const Color(0xFF1C1C1C),
      surfaceContainerHighest: const Color(0xFFF0EDE8), // Warm light grey
      surfaceContainerLow: const Color(0xFFFFFFFF),
      outline: const Color(0xFFE0DBD4),
    ).copyWith(
      primary: _config.primaryColor,
      onPrimary: Colors.white,
      secondary: _darken(_config.primaryColor, 0.08),
      onSecondary: Colors.white,
      error: errorRed,
    );

    return _buildTheme(cs, Brightness.light);
  }

  /// Rich dark theme — deep neutrals with brand accent.
  static ThemeData get dark {
    final cs = ColorScheme.fromSeed(
      seedColor: _config.primaryColor,
      brightness: Brightness.dark,
      surface: const Color(0xFF121212),
      onSurface: const Color(0xFFE8E8E8),
      surfaceContainerHighest: const Color(0xFF2A2A2A),
      surfaceContainerLow: const Color(0xFF1E1E1E),
      outline: const Color(0xFF333333),
    ).copyWith(
      primary: _lighten(_config.primaryColor, 0.15),
      onPrimary: Colors.black,
      secondary: _lighten(_config.primaryColor, 0.08),
      onSecondary: Colors.black,
      error: const Color(0xFFEF9A9A),
    );

    return _buildTheme(cs, Brightness.dark);
  }

  // ─── Shared theme builder ─────────────────────────────────────────────────

  static ThemeData _buildTheme(ColorScheme cs, Brightness brightness) {
    final isLight = brightness == Brightness.light;

    final textTheme = GoogleFonts.getTextTheme(
      _config.bodyFont,
      isLight ? ThemeData.light().textTheme : ThemeData.dark().textTheme,
    ).copyWith(
      displayLarge: GoogleFonts.getFont(_config.displayFont,
          fontSize: 32, fontWeight: FontWeight.bold, height: 1.2),
      displayMedium: GoogleFonts.getFont(_config.displayFont,
          fontSize: 24, fontWeight: FontWeight.bold, height: 1.3),
      displaySmall: GoogleFonts.getFont(_config.displayFont,
          fontSize: 20, fontWeight: FontWeight.w700, height: 1.3),
      headlineMedium: GoogleFonts.getFont(_config.bodyFont,
          fontSize: 18, fontWeight: FontWeight.w600),
      titleLarge: GoogleFonts.getFont(_config.bodyFont,
          fontSize: 20, fontWeight: FontWeight.w600, height: 1.4),
      titleMedium: GoogleFonts.getFont(_config.bodyFont,
          fontSize: 16, fontWeight: FontWeight.w600, height: 1.4),
      titleSmall: GoogleFonts.getFont(_config.bodyFont,
          fontSize: 14, fontWeight: FontWeight.w600),
      bodyLarge: GoogleFonts.getFont(_config.bodyFont,
          fontSize: 16, fontWeight: FontWeight.w400, height: 1.5),
      bodyMedium: GoogleFonts.getFont(_config.bodyFont,
          fontSize: 14, fontWeight: FontWeight.w400, height: 1.5),
      bodySmall: GoogleFonts.getFont(_config.bodyFont,
          fontSize: 12, fontWeight: FontWeight.w400, height: 1.5),
      labelLarge: GoogleFonts.getFont(_config.bodyFont,
          fontSize: 14, fontWeight: FontWeight.w600, letterSpacing: 0.1),
      labelMedium: GoogleFonts.getFont(_config.bodyFont,
          fontSize: 12, fontWeight: FontWeight.w500),
    );

    return ThemeData(
      useMaterial3: true,
      colorScheme: cs,
      brightness: brightness,
      textTheme: textTheme,

      // ── Scaffold ──────────────────────────────────────────────────────────
      scaffoldBackgroundColor: cs.surface,

      // ── AppBar ────────────────────────────────────────────────────────────
      appBarTheme: AppBarTheme(
        backgroundColor: cs.surface,
        foregroundColor: cs.onSurface,
        elevation: 0,
        scrolledUnderElevation: 1,
        shadowColor: cs.outline.withOpacity(0.5),
        titleTextStyle: GoogleFonts.getFont(
          _config.bodyFont,
          fontSize: 18,
          fontWeight: FontWeight.w600,
          color: cs.onSurface,
        ),
        systemOverlayStyle: isLight
            ? SystemUiOverlayStyle.dark
            : SystemUiOverlayStyle.light,
        surfaceTintColor: Colors.transparent,
      ),

      // ── Bottom Navigation ─────────────────────────────────────────────────
      bottomNavigationBarTheme: BottomNavigationBarThemeData(
        backgroundColor: isLight ? Colors.white : const Color(0xFF1A1A1A),
        selectedItemColor: cs.primary,
        unselectedItemColor: cs.onSurfaceVariant,
        showSelectedLabels: true,
        showUnselectedLabels: true,
        type: BottomNavigationBarType.fixed,
        elevation: 8,
        selectedLabelStyle: GoogleFonts.getFont(_config.bodyFont,
            fontSize: 11, fontWeight: FontWeight.w600),
        unselectedLabelStyle: GoogleFonts.getFont(_config.bodyFont,
            fontSize: 11, fontWeight: FontWeight.w400),
      ),

      // ── Navigation Rail (tablet) ───────────────────────────────────────────
      navigationRailTheme: NavigationRailThemeData(
        backgroundColor: isLight ? Colors.white : const Color(0xFF1A1A1A),
        selectedIconTheme: IconThemeData(color: cs.primary),
        unselectedIconTheme: IconThemeData(color: cs.onSurfaceVariant),
        selectedLabelTextStyle:
            GoogleFonts.getFont(_config.bodyFont, fontSize: 12, fontWeight: FontWeight.w600, color: cs.primary),
        unselectedLabelTextStyle:
            GoogleFonts.getFont(_config.bodyFont, fontSize: 12, color: cs.onSurfaceVariant),
        indicatorColor: cs.primary.withOpacity(0.12),
        elevation: 0,
        useIndicator: true,
      ),

      // ── Cards ─────────────────────────────────────────────────────────────
      cardTheme: CardThemeData(
        color: isLight ? Colors.white : const Color(0xFF1E1E1E),
        elevation: 0,
        shape: RoundedRectangleBorder(
          borderRadius: BorderRadius.circular(radiusL),
          side: BorderSide(color: cs.outline.withOpacity(0.6), width: 1),
        ),
        margin: const EdgeInsets.symmetric(horizontal: spaceL, vertical: spaceS),
        surfaceTintColor: Colors.transparent,
      ),

      // ── Elevated Button ───────────────────────────────────────────────────
      elevatedButtonTheme: ElevatedButtonThemeData(
        style: ElevatedButton.styleFrom(
          backgroundColor: cs.primary,
          foregroundColor: cs.onPrimary,
          elevation: 0,
          padding: const EdgeInsets.symmetric(
              horizontal: spaceXL, vertical: spaceM + 2),
          shape: RoundedRectangleBorder(
            borderRadius: BorderRadius.circular(radiusM),
          ),
          textStyle: GoogleFonts.getFont(_config.bodyFont,
              fontSize: 15, fontWeight: FontWeight.w600),
          minimumSize: const Size(0, 48),
        ),
      ),

      // ── Outlined Button ───────────────────────────────────────────────────
      outlinedButtonTheme: OutlinedButtonThemeData(
        style: OutlinedButton.styleFrom(
          foregroundColor: cs.primary,
          side: BorderSide(color: cs.primary, width: 1.5),
          padding: const EdgeInsets.symmetric(
              horizontal: spaceXL, vertical: spaceM + 2),
          shape: RoundedRectangleBorder(
            borderRadius: BorderRadius.circular(radiusM),
          ),
          textStyle: GoogleFonts.getFont(_config.bodyFont,
              fontSize: 15, fontWeight: FontWeight.w600),
          minimumSize: const Size(0, 48),
        ),
      ),

      // ── Text Button ───────────────────────────────────────────────────────
      textButtonTheme: TextButtonThemeData(
        style: TextButton.styleFrom(
          foregroundColor: cs.primary,
          padding: const EdgeInsets.symmetric(
              horizontal: spaceL, vertical: spaceS + 2),
          textStyle: GoogleFonts.getFont(_config.bodyFont,
              fontSize: 14, fontWeight: FontWeight.w600),
          minimumSize: const Size(0, 40),
        ),
      ),

      // ── Input Fields ──────────────────────────────────────────────────────
      inputDecorationTheme: InputDecorationTheme(
        filled: true,
        fillColor: isLight
            ? const Color(0xFFF5F3F0)
            : const Color(0xFF252525),
        border: OutlineInputBorder(
          borderRadius: BorderRadius.circular(radiusM),
          borderSide: BorderSide(color: cs.outline, width: 1),
        ),
        enabledBorder: OutlineInputBorder(
          borderRadius: BorderRadius.circular(radiusM),
          borderSide: BorderSide(color: cs.outline, width: 1),
        ),
        focusedBorder: OutlineInputBorder(
          borderRadius: BorderRadius.circular(radiusM),
          borderSide: BorderSide(color: cs.primary, width: 2),
        ),
        errorBorder: OutlineInputBorder(
          borderRadius: BorderRadius.circular(radiusM),
          borderSide: BorderSide(color: cs.error, width: 1),
        ),
        focusedErrorBorder: OutlineInputBorder(
          borderRadius: BorderRadius.circular(radiusM),
          borderSide: BorderSide(color: cs.error, width: 2),
        ),
        contentPadding: const EdgeInsets.symmetric(
            horizontal: spaceL, vertical: spaceM),
        hintStyle: GoogleFonts.getFont(_config.bodyFont,
            fontSize: 14,
            color: isLight
                ? const Color(0xFF9E9E9E)
                : const Color(0xFF757575)),
        labelStyle: GoogleFonts.getFont(_config.bodyFont,
            fontSize: 14, fontWeight: FontWeight.w500, color: cs.onSurface),
        floatingLabelStyle: GoogleFonts.getFont(_config.bodyFont,
            fontSize: 12, fontWeight: FontWeight.w600, color: cs.primary),
        prefixIconColor: cs.primary,
        suffixIconColor: cs.onSurfaceVariant,
      ),

      // ── Divider ───────────────────────────────────────────────────────────
      dividerTheme: DividerThemeData(
        color: cs.outline.withOpacity(0.5),
        thickness: 1,
        space: 1,
      ),

      // ── List Tile ─────────────────────────────────────────────────────────
      listTileTheme: ListTileThemeData(
        contentPadding: const EdgeInsets.symmetric(
            horizontal: spaceL, vertical: spaceXS),
        titleTextStyle: GoogleFonts.getFont(_config.bodyFont,
            fontSize: 15, fontWeight: FontWeight.w500, color: cs.onSurface),
        subtitleTextStyle: GoogleFonts.getFont(_config.bodyFont,
            fontSize: 13, color: cs.onSurfaceVariant),
        iconColor: cs.onSurfaceVariant,
        shape: RoundedRectangleBorder(
          borderRadius: BorderRadius.circular(radiusM),
        ),
      ),

      // ── Switch / Checkbox ─────────────────────────────────────────────────
      switchTheme: SwitchThemeData(
        thumbColor: WidgetStateProperty.resolveWith((states) =>
            states.contains(WidgetState.selected) ? cs.primary : null),
        trackColor: WidgetStateProperty.resolveWith((states) =>
            states.contains(WidgetState.selected)
                ? cs.primary.withOpacity(0.4)
                : null),
      ),

      checkboxTheme: CheckboxThemeData(
        fillColor: WidgetStateProperty.resolveWith((states) =>
            states.contains(WidgetState.selected) ? cs.primary : null),
        shape: RoundedRectangleBorder(
          borderRadius: BorderRadius.circular(4),
        ),
      ),

      // ── Chip ─────────────────────────────────────────────────────────────
      chipTheme: ChipThemeData(
        backgroundColor: cs.surfaceContainerHighest,
        selectedColor: cs.primary.withOpacity(0.15),
        labelStyle: GoogleFonts.getFont(_config.bodyFont,
            fontSize: 13, fontWeight: FontWeight.w500),
        shape: RoundedRectangleBorder(
          borderRadius: BorderRadius.circular(radiusRound),
          side: BorderSide(color: cs.outline.withOpacity(0.5)),
        ),
        padding: const EdgeInsets.symmetric(
            horizontal: spaceM, vertical: spaceXS),
      ),

      // ── SnackBar ──────────────────────────────────────────────────────────
      snackBarTheme: SnackBarThemeData(
        behavior: SnackBarBehavior.floating,
        shape: RoundedRectangleBorder(
          borderRadius: BorderRadius.circular(radiusM),
        ),
        contentTextStyle: GoogleFonts.getFont(_config.bodyFont,
            fontSize: 14, fontWeight: FontWeight.w500, color: Colors.white),
      ),

      // ── Dialog ────────────────────────────────────────────────────────────
      dialogTheme: DialogThemeData(
        backgroundColor: isLight ? Colors.white : const Color(0xFF1E1E1E),
        shape: RoundedRectangleBorder(
          borderRadius: BorderRadius.circular(radiusXL),
        ),
        elevation: 8,
        titleTextStyle: GoogleFonts.getFont(_config.bodyFont,
            fontSize: 18, fontWeight: FontWeight.w600, color: cs.onSurface),
        contentTextStyle: GoogleFonts.getFont(_config.bodyFont,
            fontSize: 14, color: cs.onSurfaceVariant),
      ),

      // ── FAB ───────────────────────────────────────────────────────────────
      floatingActionButtonTheme: FloatingActionButtonThemeData(
        backgroundColor: cs.primary,
        foregroundColor: cs.onPrimary,
        elevation: 4,
        shape: RoundedRectangleBorder(
          borderRadius: BorderRadius.circular(radiusL),
        ),
      ),

      // ── Progress Indicator ────────────────────────────────────────────────
      progressIndicatorTheme: ProgressIndicatorThemeData(
        color: cs.primary,
      ),
    );
  }

  // ─── Colour utilities ─────────────────────────────────────────────────────

  static Color _darken(Color color, double amount) {
    final hsl = HSLColor.fromColor(color);
    return hsl
        .withLightness((hsl.lightness - amount).clamp(0.0, 1.0))
        .toColor();
  }

  static Color _lighten(Color color, double amount) {
    final hsl = HSLColor.fromColor(color);
    return hsl
        .withLightness((hsl.lightness + amount).clamp(0.0, 1.0))
        .toColor();
  }
}
