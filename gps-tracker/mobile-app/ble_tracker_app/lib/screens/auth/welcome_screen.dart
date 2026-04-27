import 'package:flutter/material.dart';
import 'package:flutter_animate/flutter_animate.dart';
import 'package:google_fonts/google_fonts.dart';
import 'package:ble_tracker_app/theme/app_theme.dart';
import 'package:ble_tracker_app/screens/auth/email_screen.dart';
import 'package:ble_tracker_app/screens/auth/signin_screen.dart';

class WelcomeScreen extends StatelessWidget {
  const WelcomeScreen({Key? key}) : super(key: key);

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      body: Container(
        decoration: BoxDecoration(
          color: AppTheme.brandPrimary,
        ),
        child: Stack(
          children: [
            // Animated background circles
            Positioned(
              top: -100,
              right: -100,
              child: Container(
                width: 300,
                height: 300,
                decoration: BoxDecoration(
                  shape: BoxShape.circle,
                  gradient: RadialGradient(
                    colors: [
                      Colors.white.withValues(alpha: 0.1),
                      Colors.transparent,
                    ],
                  ),
                ),
              ).animate(onPlay: (controller) => controller.repeat())
                .scale(duration: 4000.ms, curve: Curves.easeInOut)
                .then()
                .scale(begin: Offset(1.2, 1.2), end: Offset(1.0, 1.0), duration: 4000.ms),
            ),
            Positioned(
              bottom: -50,
              left: -50,
              child: Container(
                width: 250,
                height: 250,
                decoration: BoxDecoration(
                  shape: BoxShape.circle,
                  gradient: RadialGradient(
                    colors: [
                      AppTheme.brandPrimary.withValues(alpha: 0.15),
                      Colors.transparent,
                    ],
                  ),
                ),
              ).animate(onPlay: (controller) => controller.repeat())
                .scale(duration: 5000.ms, curve: Curves.easeInOut, begin: Offset(1.0, 1.0), end: Offset(1.1, 1.1))
                .then()
                .scale(begin: Offset(1.1, 1.1), end: Offset(1.0, 1.0), duration: 5000.ms),
            ),
            
            // Main content
            SafeArea(
              child: Center(
                child: SingleChildScrollView(
                  padding: const EdgeInsets.all(24.0),
                  child: Container(
                    constraints: BoxConstraints(maxWidth: 400),
                    decoration: BoxDecoration(
                      color: Colors.white.withValues(alpha: 0.95),
                      borderRadius: BorderRadius.circular(32),
                      boxShadow: [
                        BoxShadow(
                          color: Colors.black.withValues(alpha: 0.08),
                          blurRadius: 40,
                          offset: Offset(0, 20),
                        ),
                      ],
                      border: Border.all(
                        color: Colors.white.withValues(alpha: 0.3),
                        width: 1.5,
                      ),
                    ),
                    padding: const EdgeInsets.all(40.0),
                    child: Column(
                      mainAxisSize: MainAxisSize.min,
                      children: [
                        // Logo with animation
                        Hero(
                          tag: 'app_logo',
                          child: Container(
                            width: double.infinity,
                            height: 120,
                            alignment: Alignment.center,
                            child: Image.asset(
                              'assets/MainLogo.png',
                              fit: BoxFit.contain,
                            ),
                          ),
                        ).animate()
                          .fadeIn(duration: 600.ms)
                          .scale(delay: 200.ms, duration: 400.ms, curve: Curves.easeOutBack),
                        SizedBox(height: 32),
                        
                        // Title with gradient
                        ShaderMask(
                          shaderCallback: (bounds) => LinearGradient(
                            colors: [
                              AppTheme.brandPrimary,
                              AppTheme.brandPrimaryHover,
                            ],
                          ).createShader(bounds),
                          child: Text(
                            'Asset Tracker',
                            style: GoogleFonts.poppins(
                              fontSize: 36,
                              fontWeight: FontWeight.bold,
                              color: Colors.white,
                              letterSpacing: -0.5,
                            ),
                          ),
                        ).animate()
                          .fadeIn(delay: 400.ms, duration: 600.ms)
                          .slideY(begin: 0.3, end: 0, delay: 400.ms, duration: 600.ms, curve: Curves.easeOut),
                        SizedBox(height: 12),
                        
                        // Subtitle
                        Text(
                          'Track your assets with ease',
                          style: GoogleFonts.inter(
                            fontSize: 16,
                            color: Colors.grey.shade600,
                            fontWeight: FontWeight.w500,
                          ),
                        ).animate()
                          .fadeIn(delay: 600.ms, duration: 600.ms)
                          .slideY(begin: 0.3, end: 0, delay: 600.ms, duration: 600.ms),
                        SizedBox(height: 50),
                        
                        // Get Started Button with animations
                        SizedBox(
                          width: double.infinity,
                          height: 60,
                          child: ElevatedButton(
                            onPressed: () {
                              Navigator.push(
                                context,
                                PageRouteBuilder(
                                  pageBuilder: (context, animation, secondaryAnimation) => EmailScreen(),
                                  transitionsBuilder: (context, animation, secondaryAnimation, child) {
                                    return FadeTransition(opacity: animation, child: child);
                                  },
                                ),
                              );
                            },
                            style: ElevatedButton.styleFrom(
                              backgroundColor: AppTheme.brandPrimary,
                              foregroundColor: Colors.white,
                              elevation: 8,
                              shadowColor: AppTheme.brandPrimary.withValues(alpha: 0.5),
                              shape: RoundedRectangleBorder(
                                borderRadius: BorderRadius.circular(16),
                              ),
                            ),
                            child: Row(
                              mainAxisAlignment: MainAxisAlignment.center,
                              children: [
                                Icon(Icons.auto_awesome, size: 22),
                                SizedBox(width: 12),
                                Text(
                                  'Get Started',
                                  style: GoogleFonts.inter(
                                    fontSize: 17,
                                    fontWeight: FontWeight.w600,
                                    letterSpacing: 0.5,
                                  ),
                                ),
                              ],
                            ),
                          ),
                        ).animate()
                          .fadeIn(delay: 800.ms, duration: 600.ms)
                          .slideY(begin: 0.2, end: 0, delay: 800.ms, duration: 600.ms)
                          .shimmer(delay: 1500.ms, duration: 2000.ms, color: Colors.white.withValues(alpha: 0.5)),
                        SizedBox(height: 16),
                        
                        // Sign In Button with animations
                        SizedBox(
                          width: double.infinity,
                          height: 60,
                          child: OutlinedButton(
                            onPressed: () {
                              Navigator.push(
                                context,
                                PageRouteBuilder(
                                  pageBuilder: (context, animation, secondaryAnimation) => SignInScreen(),
                                  transitionsBuilder: (context, animation, secondaryAnimation, child) {
                                    return FadeTransition(opacity: animation, child: child);
                                  },
                                ),
                              );
                            },
                            style: OutlinedButton.styleFrom(
                              foregroundColor: AppTheme.brandPrimary,
                              side: BorderSide(color: AppTheme.brandPrimary, width: 2),
                              shape: RoundedRectangleBorder(
                                borderRadius: BorderRadius.circular(16),
                              ),
                            ),
                            child: Row(
                              mainAxisAlignment: MainAxisAlignment.center,
                              children: [
                                Icon(Icons.login, size: 22),
                                SizedBox(width: 12),
                                Text(
                                  'Sign In',
                                  style: GoogleFonts.inter(
                                    fontSize: 17,
                                    fontWeight: FontWeight.w600,
                                    letterSpacing: 0.5,
                                  ),
                                ),
                              ],
                            ),
                          ),
                        ).animate()
                          .fadeIn(delay: 1000.ms, duration: 600.ms)
                          .slideY(begin: 0.2, end: 0, delay: 1000.ms, duration: 600.ms),
                        SizedBox(height: 32),
                      ],
                    ),
                  ),
                ),
              ),
            ),
          ],
        ),
      ),
    );
  }
}
