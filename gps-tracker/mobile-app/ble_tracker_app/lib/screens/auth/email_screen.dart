import 'package:flutter/material.dart';
import 'package:flutter_animate/flutter_animate.dart';
import 'package:google_fonts/google_fonts.dart';
import 'package:ble_tracker_app/theme/app_theme.dart';
import 'package:ble_tracker_app/screens/auth/pin_screen.dart';
import 'package:ble_tracker_app/services/auth_service.dart';

class EmailScreen extends StatefulWidget {
  const EmailScreen({Key? key}) : super(key: key);

  @override
  State<EmailScreen> createState() => _EmailScreenState();
}

class _EmailScreenState extends State<EmailScreen> {
  final _emailController = TextEditingController();
  final _formKey = GlobalKey<FormState>();
  bool _isLoading = false;
  final _authService = AuthService();

  Future<void> _sendVerificationCode() async {
    print('\n🔘 ========== BUTTON CLICKED ==========');
    print('📱 Screen: EmailScreen');
    print('⏰ Time: ${DateTime.now().toIso8601String()}');
    print('📧 Email entered: "${_emailController.text.trim()}"');
    print('🔍 Email length: ${_emailController.text.trim().length}');
    
    if (!_formKey.currentState!.validate()) {
      print('❌ Form validation FAILED');
      print('========== BUTTON HANDLER END (validation failed) ==========\n');
      return;
    }

    print('✅ Form validation PASSED');
    print('🔄 Setting isLoading to true...');
    setState(() => _isLoading = true);
    print('✅ Loading state set');

    try {
      print('\n📞 Sending verification code and checking email...');
      final startTime = DateTime.now();
      
      final emailCheck = await _authService.checkEmailExists(_emailController.text.trim());
      
      final endTime = DateTime.now();
      final duration = endTime.difference(startTime).inMilliseconds;
      
      if (emailCheck['can_register'] == false) {
        print('⛔ Registration blocked: ${emailCheck['message']}');
        if (mounted) {
          final isAlreadyRegistered = emailCheck['exists'] == true;
          ScaffoldMessenger.of(context).showSnackBar(
            SnackBar(
              content: Text(emailCheck['message'] ?? 'Registration not available for this email.'),
              backgroundColor: isAlreadyRegistered ? Colors.orange : Colors.red,
              duration: Duration(seconds: 5),
              action: isAlreadyRegistered
                  ? SnackBarAction(
                      label: 'Sign In',
                      textColor: Colors.white,
                      onPressed: () {
                        ScaffoldMessenger.of(context).clearSnackBars();
                        Navigator.pop(context);
                      },
                    )
                  : null,
            ),
          );
        }
        return;
      }
      
      print('\n✅ SUCCESS! Verification code sent in ${duration}ms');
      print('🎉 PIN code has been sent to email!');
      
      if (mounted) {
        print('✅ Widget is still mounted, showing success snackbar');
        ScaffoldMessenger.of(context).showSnackBar(
          SnackBar(
            content: Text('✅ Verification code sent! Check your email.'),
            backgroundColor: Colors.green,
            duration: Duration(seconds: 2),
          ),
        );
        
        print('🧭 Navigating to PIN screen...');
        // Clear any SnackBars before navigation
        ScaffoldMessenger.of(context).clearSnackBars();
        await Navigator.push(
          context,
          MaterialPageRoute(
            builder: (context) => PinVerificationScreen(
              email: _emailController.text.trim(),
            ),
          ),
        );
        print('✅ Navigation completed');
      } else {
        print('⚠️ Widget is NOT mounted, skipping navigation');
      }
    } catch (e, stackTrace) {
      print('\n❌ ========== ERROR CAUGHT ==========');
      print('❌ Error type: ${e.runtimeType}');
      print('❌ Error message: $e');
      print('📚 Stack trace (first 10 lines):');
      print(stackTrace.toString().split('\n').take(10).join('\n'));
      
      if (mounted) {
        print('✅ Widget mounted, showing error snackbar');
        
        // Extract clean error message
        String errorMessage = e.toString()
            .replaceAll('Exception: ', '')
            .replaceAll('Unexpected error: ', '')
            .replaceAll('Server returned ', '')
            .trim();
        
        // Provide context-specific messages
        if (errorMessage.isEmpty || errorMessage == 'Failed to send verification code') {
          errorMessage = 'Failed to send verification code';
        } else if (errorMessage.contains('Network')) {
          errorMessage = 'Network error. Please check your connection.';
        } else if (errorMessage.contains('timeout')) {
          errorMessage = 'Request timed out. Please try again.';
        }
        
        ScaffoldMessenger.of(context).showSnackBar(
          SnackBar(
            content: Text(errorMessage),
            backgroundColor: Colors.red,
            duration: Duration(seconds: 3),
            action: SnackBarAction(
              label: 'Dismiss',
              textColor: Colors.white,
              onPressed: () {
                ScaffoldMessenger.of(context).clearSnackBars();
              },
            ),
          ),
        );
      } else {
        print('⚠️ Widget NOT mounted, skipping snackbar');
      }
      print('========== ERROR HANDLER END ==========\n');
    } finally {
      if (mounted) {
        print('🔄 Setting isLoading to false...');
        setState(() => _isLoading = false);
        print('✅ Loading state cleared');
      } else {
        print('⚠️ Widget NOT mounted, skipping setState');
      }
      print('========== BUTTON HANDLER COMPLETE ==========\n');
    }
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      body: Container(
        decoration: BoxDecoration(
          gradient: AppTheme.backgroundGradient,
        ),
        child: SafeArea(
          child: Center(
            child: SingleChildScrollView(
              padding: MediaQuery.of(context).size.width < 380
                  ? const EdgeInsets.all(16.0) // Smaller padding on very small screens
                  : const EdgeInsets.all(24.0),
              child: Container(
                constraints: BoxConstraints(
                  maxWidth: MediaQuery.of(context).size.width > 600 ? 400 : MediaQuery.of(context).size.width * 0.9,
                ),
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
                padding: MediaQuery.of(context).size.width < 380
                    ? const EdgeInsets.all(24.0)
                    : const EdgeInsets.all(40.0),
                child: Form(
                  key: _formKey,
                  child: Column(
                    mainAxisSize: MainAxisSize.min,
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      // Back Button
                      TextButton.icon(
                        onPressed: () => Navigator.pop(context),
                        icon: Icon(Icons.arrow_back_ios, size: 16),
                        label: Text(
                          'Back',
                          style: GoogleFonts.inter(
                            fontWeight: FontWeight.w600,
                          ),
                        ),
                        style: TextButton.styleFrom(
                          foregroundColor: Colors.grey.shade600,
                          padding: EdgeInsets.zero,
                        ),
                      ).animate()
                        .fadeIn(duration: 300.ms)
                        .slideX(begin: -0.1, end: 0, duration: 300.ms),
                      SizedBox(height: 24),
                      
                      // Icon with animation
                      Center(
                        child: Container(
                          width: 80,
                          height: 80,
                          decoration: BoxDecoration(
                            gradient: LinearGradient(
                              colors: [
                                AppTheme.brandPrimary,
                                AppTheme.brandPrimaryHover,
                              ],
                            ),
                            borderRadius: BorderRadius.circular(24),
                            boxShadow: [
                              BoxShadow(
                                color: AppTheme.brandPrimary.withValues(alpha: 0.4),
                                blurRadius: 20,
                                offset: Offset(0, 10),
                              ),
                            ],
                          ),
                          child: Icon(
                            Icons.mail_outline,
                            size: 40,
                            color: Colors.white,
                          ),
                        ),
                      ).animate()
                        .fadeIn(delay: 100.ms, duration: 600.ms)
                        .scale(delay: 100.ms, duration: 600.ms, curve: Curves.easeOutBack),
                      SizedBox(height: 32),
                      
                      // Title
                      Center(
                        child: Column(
                          children: [
                            Text(
                              'Get Started',
                              style: GoogleFonts.poppins(
                                fontSize: 32,
                                fontWeight: FontWeight.bold,
                                color: Colors.grey.shade800,
                                letterSpacing: -0.5,
                              ),
                            ).animate()
                              .fadeIn(delay: 200.ms, duration: 600.ms)
                              .slideY(begin: 0.2, end: 0, delay: 200.ms, duration: 600.ms),
                            SizedBox(height: 12),
                            Text(
                              'Enter your email to receive a verification code',
                              style: GoogleFonts.inter(
                                fontSize: 15,
                                color: Colors.grey.shade600,
                                fontWeight: FontWeight.w500,
                              ),
                              textAlign: TextAlign.center,
                            ).animate()
                              .fadeIn(delay: 300.ms, duration: 600.ms),
                          ],
                        ),
                      ),
                      SizedBox(height: 40),
                      
                      // Email Input with floating label
                      Column(
                        crossAxisAlignment: CrossAxisAlignment.start,
                        children: [
                          Text(
                            'Email Address',
                            style: GoogleFonts.inter(
                              fontSize: 14,
                              fontWeight: FontWeight.w600,
                              color: Colors.grey.shade700,
                            ),
                          ),
                          SizedBox(height: 8),
                          TextFormField(
                            controller: _emailController,
                            keyboardType: TextInputType.emailAddress,
                            style: GoogleFonts.inter(
                              fontSize: 16,
                              fontWeight: FontWeight.w500,
                            ),
                            maxLines: 1,
                            decoration: InputDecoration(
                              hintText: 'you@example.com',
                              hintMaxLines: 1,
                              hintStyle: GoogleFonts.inter(
                                color: Colors.grey.shade400,
                              ),
                              filled: true,
                              fillColor: Colors.grey.shade50,
                              prefixIcon: Icon(Icons.email_outlined, color: AppTheme.brandPrimary),
                              border: OutlineInputBorder(
                                borderRadius: BorderRadius.circular(16),
                                borderSide: BorderSide(color: Colors.grey.shade200),
                              ),
                              enabledBorder: OutlineInputBorder(
                                borderRadius: BorderRadius.circular(16),
                                borderSide: BorderSide(color: Colors.grey.shade200, width: 1.5),
                              ),
                              focusedBorder: OutlineInputBorder(
                                borderRadius: BorderRadius.circular(16),
                                borderSide: BorderSide(color: AppTheme.brandPrimary, width: 2),
                              ),
                              errorBorder: OutlineInputBorder(
                                borderRadius: BorderRadius.circular(16),
                                borderSide: BorderSide(color: Colors.red.shade300, width: 1.5),
                              ),
                              contentPadding: EdgeInsets.symmetric(horizontal: 20, vertical: 18),
                            ),
                            validator: (value) {
                              if (value == null || value.isEmpty) {
                                return 'Please enter your email';
                              }
                              // Comprehensive email validation regex
                              final emailRegex = RegExp(
                                r'^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$'
                              );
                              if (!emailRegex.hasMatch(value.trim())) {
                                return 'Please enter a valid email address';
                              }
                              return null;
                            },
                          ),
                        ],
                      ).animate()
                        .fadeIn(delay: 400.ms, duration: 600.ms)
                        .slideY(begin: 0.2, end: 0, delay: 400.ms, duration: 600.ms),
                      SizedBox(height: 32),
                      
                      // Send Button with animation - Responsive
                      SizedBox(
                        width: double.infinity,
                        height: 60,
                        child: ElevatedButton(
                          onPressed: _isLoading ? null : _sendVerificationCode,
                          style: ElevatedButton.styleFrom(
                            backgroundColor: AppTheme.brandPrimary,
                            foregroundColor: Colors.white,
                            elevation: 8,
                            shadowColor: AppTheme.brandPrimary.withValues(alpha: 0.5),
                            shape: RoundedRectangleBorder(
                              borderRadius: BorderRadius.circular(16),
                            ),
                            disabledBackgroundColor: Colors.grey.shade300,
                          ),
                          child: _isLoading
                              ? SizedBox(
                                  height: 24,
                                  width: 24,
                                  child: CircularProgressIndicator(
                                    color: Colors.white,
                                    strokeWidth: 3,
                                  ),
                                )
                              : SingleChildScrollView(
                                  scrollDirection: Axis.horizontal,
                                  child: Row(
                                    mainAxisAlignment: MainAxisAlignment.center,
                                    mainAxisSize: MainAxisSize.min,
                                    children: [
                                      Icon(Icons.send_rounded, size: 20),
                                      SizedBox(width: 8),
                                      Text(
                                        'Send Code',
                                        style: GoogleFonts.inter(
                                          fontSize: 15,
                                          fontWeight: FontWeight.w600,
                                          letterSpacing: 0.3,
                                        ),
                                        maxLines: 1,
                                        overflow: TextOverflow.ellipsis,
                                      ),
                                    ],
                                  ),
                                ),
                        ),
                      ).animate()
                        .fadeIn(delay: 500.ms, duration: 600.ms)
                        .slideY(begin: 0.2, end: 0, delay: 500.ms, duration: 600.ms)
                        .shimmer(delay: 1000.ms, duration: 2000.ms, color: Colors.white.withValues(alpha: 0.3)),
                      SizedBox(height: 24),
                      
                      // Footer
                      Center(
                        child: Row(
                          mainAxisAlignment: MainAxisAlignment.center,
                          children: [
                            Text(
                              'Already have a code? ',
                              style: GoogleFonts.inter(
                                fontSize: 14,
                                color: Colors.grey.shade600,
                              ),
                            ),
                            TextButton(
                              onPressed: () {
                                if (_emailController.text.trim().isEmpty) {
                                  ScaffoldMessenger.of(context).showSnackBar(
                                    SnackBar(
                                      content: Text('Please enter your email first'),
                                      backgroundColor: Colors.orange,
                                    ),
                                  );
                                  return;
                                }
                                Navigator.pushReplacement(
                                  context,
                                  MaterialPageRoute(
                                    builder: (context) => PinVerificationScreen(
                                      email: _emailController.text.trim(),
                                    ),
                                  ),
                                );
                              },
                              style: TextButton.styleFrom(
                                foregroundColor: AppTheme.brandPrimary,
                                padding: EdgeInsets.zero,
                              ),
                              child: Text(
                                'Verify Now',
                                style: GoogleFonts.inter(
                                  fontSize: 14,
                                  fontWeight: FontWeight.w700,
                                ),
                              ),
                            ),
                          ],
                        ),
                      ).animate()
                        .fadeIn(delay: 600.ms, duration: 600.ms),
                      SizedBox(height: 16),
                      
                      // Sign In Link
                      Center(
                        child: Row(
                          mainAxisAlignment: MainAxisAlignment.center,
                          children: [
                            Text(
                              'Already registered? ',
                              style: GoogleFonts.inter(
                                fontSize: 14,
                                color: Colors.grey.shade600,
                              ),
                            ),
                            TextButton(
                              onPressed: () {
                                Navigator.pop(context);
                              },
                              style: TextButton.styleFrom(
                                foregroundColor: AppTheme.brandPrimary,
                                padding: EdgeInsets.zero,
                              ),
                              child: Text(
                                'Sign In',
                                style: GoogleFonts.inter(
                                  fontSize: 14,
                                  fontWeight: FontWeight.w700,
                                ),
                              ),
                            ),
                          ],
                        ),
                      ).animate()
                        .fadeIn(delay: 700.ms, duration: 600.ms),
                    ],
                  ),
                ),
              ),
            ),
          ),
        ),
      ),
    );
  }

  @override
  void dispose() {
    _emailController.dispose();
    super.dispose();
  }
}
