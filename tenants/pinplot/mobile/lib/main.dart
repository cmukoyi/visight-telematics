import 'package:flutter/material.dart';
import 'package:provider/provider.dart';
import 'package:ble_tracker_app/theme/app_theme.dart';
import 'package:ble_tracker_app/theme/app_brand_config.dart';
import 'package:ble_tracker_app/screens/auth/welcome_screen.dart';
import 'package:ble_tracker_app/screens/auth/reset_password_screen.dart';
import 'package:ble_tracker_app/screens/map_screen.dart';
import 'package:ble_tracker_app/screens/poi_management_screen.dart';
import 'package:ble_tracker_app/screens/add_tag_screen.dart';
import 'package:ble_tracker_app/services/auth_service.dart';
import 'package:ble_tracker_app/services/token_refresh_manager.dart';

// ─── Brand configuration ──────────────────────────────────────────────────────
//
// To white-label this app for a different deployment, change ONLY this line.
// Everything else — themes, colours, fonts — is derived automatically.
//
// Examples:
//   AppBrandConfig.pinplot()                   ← default PinPlot green
//   AppBrandConfig.custom(                     ← any brand colour
//     primaryColor: Color(0xFF1565C0),
//     appName: 'Beacon Telematics',
//     logoAsset: 'assets/beacon_logo.png',
//     tagline: 'Track your assets',
//   )

const _brand = null; // Set to AppBrandConfig.custom(...) to override

void main() {
  WidgetsFlutterBinding.ensureInitialized();

  // Configure the theme — must happen before runApp
  AppTheme.configure(_brand ?? AppBrandConfig.pinplot());

  runApp(const MyApp());
}

class MyApp extends StatefulWidget {
  const MyApp({super.key});

  @override
  State<MyApp> createState() => _MyAppState();
}

class _MyAppState extends State<MyApp> {
  // Expose theme mode so any screen can toggle light/dark
  ThemeMode _themeMode = ThemeMode.system;

  void _setThemeMode(ThemeMode mode) {
    setState(() => _themeMode = mode);
  }

  @override
  Widget build(BuildContext context) {
    return Provider<void Function(ThemeMode)>.value(
      value: _setThemeMode,
      child: ActivityMonitor(
        child: MaterialApp(
          title: 'PinPlot',
          debugShowCheckedModeBanner: false,
          
          // ── Themes ──────────────────────────────────────────────────────────
          theme: AppTheme.light,
          darkTheme: AppTheme.dark,
          themeMode: _themeMode,
          
          // ── Routes ──────────────────────────────────────────────────────────
          home: const SplashScreen(),
          routes: {
            '/welcome': (context) => const WelcomeScreen(),
            '/map': (context) => const MapScreen(),
            '/poi-management': (context) => const POIManagementScreen(),
            '/add-tag': (context) => const AddTagScreen(),
          },
          builder: (context, child) => child!,
        ),
      ),
    );
  }
}

// Splash screen to check authentication
class SplashScreen extends StatefulWidget {
  const SplashScreen({Key? key}) : super(key: key);

  @override
  State<SplashScreen> createState() => _SplashScreenState();
}

class _SplashScreenState extends State<SplashScreen> {
  final _authService = AuthService();

  @override
  void initState() {
    super.initState();
    _checkAuthStatus();
  }

  Future<void> _checkAuthStatus() async {
    await Future.delayed(Duration(milliseconds: 500)); // Brief delay
    
    if (!mounted) return;
    
    // Check for password reset token in URL
    final uri = Uri.base;
    final impersonateToken = uri.queryParameters['impersonate'];
    final impersonateEmail = uri.queryParameters['email'];

    if (impersonateToken != null && impersonateToken.isNotEmpty) {
      print('🔑 Admin impersonation token detected in URL');
      await _authService.saveImpersonationToken(impersonateToken, email: impersonateEmail);
      if (mounted) {
        Navigator.pushReplacementNamed(context, '/map');
      }
      return;
    }

    final resetToken = uri.queryParameters['reset_token'];
    
    if (resetToken != null && resetToken.isNotEmpty) {
      print('🔑 Reset token detected in URL: ${resetToken.substring(0, 10)}...');
      // Navigate to reset password screen with token
      Navigator.pushReplacement(
        context,
        MaterialPageRoute(
          builder: (context) => ResetPasswordScreen(token: resetToken),
        ),
      );
      return;
    }
    
    try {
      final isLoggedIn = await _authService.isLoggedIn();
      
      if (!mounted) return;
      
      if (isLoggedIn) {
        // Check if user has tags
        final hasTags = await _authService.hasTags();
        
        if (!mounted) return;
        
        if (hasTags) {
          // User has tags, go directly to map
          Navigator.pushReplacementNamed(context, '/map');
        } else {
          // User logged in but no tags, go to map anyway
          Navigator.pushReplacementNamed(context, '/map');
        }
      } else {
        // Not logged in, go to welcome
        Navigator.pushReplacementNamed(context, '/welcome');
      }
    } catch (e) {
      print('Error checking auth: $e');
      if (mounted) {
        Navigator.pushReplacementNamed(context, '/welcome');
      }
    }
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      body: Container(
        decoration: BoxDecoration(
          gradient: LinearGradient(
            begin: Alignment.topLeft,
            end: Alignment.bottomRight,
            colors: [Color(0xFF173D64), Color(0xFF1f4f7e)],
          ),
        ),
        child: Center(
          child: Column(
            mainAxisAlignment: MainAxisAlignment.center,
            children: [
              Image.asset(
                'assets/MainLogo.png',
                height: 120,
                fit: BoxFit.contain,
              ),
              SizedBox(height: 24),
              Text(
                'Asset Tracker',
                style: TextStyle(
                  fontSize: 32,
                  fontWeight: FontWeight.bold,
                  color: Colors.white,
                ),
              ),
              SizedBox(height: 40),
              CircularProgressIndicator(
                valueColor: AlwaysStoppedAnimation<Color>(Colors.white),
              ),
            ],
          ),
        ),
      ),
    );
  }
}
// Test staging
