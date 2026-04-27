import 'package:flutter/material.dart';
import 'package:flutter_animate/flutter_animate.dart';
import 'package:google_fonts/google_fonts.dart';
import 'package:ble_tracker_app/theme/app_theme.dart';
import 'package:ble_tracker_app/services/auth_service.dart';
import 'package:ble_tracker_app/screens/home_screen.dart';

class PasswordScreen extends StatefulWidget {
  final String email;
  final String firstName;
  final String lastName;

  const PasswordScreen({
    Key? key,
    required this.email,
    required this.firstName,
    required this.lastName,
  }) : super(key: key);

  @override
  State<PasswordScreen> createState() => _PasswordScreenState();
}

class _PasswordScreenState extends State<PasswordScreen> {
  final _formKey = GlobalKey<FormState>();
  final _passwordController = TextEditingController();
  final _confirmPasswordController = TextEditingController();
  final _authService = AuthService();
  bool _isLoading = false;
  bool _obscurePassword = true;
  bool _obscureConfirmPassword = true;

  @override
  void dispose() {
    _passwordController.dispose();
    _confirmPasswordController.dispose();
    super.dispose();
  }

  String? _validatePassword(String? value) {
    if (value == null || value.isEmpty) {
      return 'Please enter a password';
    }
    if (value.length < 8) {
      return 'Password must be at least 8 characters';
    }
    if (!value.contains(RegExp(r'[A-Z]'))) {
      return 'Password must contain at least one uppercase letter';
    }
    if (!value.contains(RegExp(r'[a-z]'))) {
      return 'Password must contain at least one lowercase letter';
    }
    if (!value.contains(RegExp(r'[0-9]'))) {
      return 'Password must contain at least one number';
    }
    return null;
  }

  Future<void> _register() async {
    print('\n🔘 ========== REGISTER BUTTON CLICKED ==========');
    print('📝 Form validation...');
    
    if (!_formKey.currentState!.validate()) {
      print('❌ Form validation FAILED');
      return;
    }

    if (_passwordController.text != _confirmPasswordController.text) {
      print('❌ Passwords do not match');
      ScaffoldMessenger.of(context).showSnackBar(
        SnackBar(
          content: Text('Passwords do not match'),
          backgroundColor: Colors.red,
          duration: Duration(seconds: 3),
        ),
      );
      return;
    }

    print('✅ Form validation PASSED');
    print('📧 Email: ${widget.email}');
    print('👤 Name: ${widget.firstName} ${widget.lastName}');
    print('🔒 Password length: ${_passwordController.text.length}');

    setState(() => _isLoading = true);

    try {
      print('📤 Calling authService.register...');
      await _authService.register(
        email: widget.email,
        password: _passwordController.text,
        firstName: widget.firstName,
        lastName: widget.lastName,
      );

      print('✅ Registration successful!');

      if (mounted) {
        // Clear any error messages before showing success
        ScaffoldMessenger.of(context).clearSnackBars();
        ScaffoldMessenger.of(context).showSnackBar(
          SnackBar(
            content: Text('✅ Registration successful! Welcome!'),
            backgroundColor: Colors.green,
            duration: Duration(seconds: 2),
          ),
        );

        print('🗺️ Navigating to home screen...');
        // Small delay to show success message
        await Future.delayed(Duration(milliseconds: 500));
        ScaffoldMessenger.of(context).clearSnackBars();
        Navigator.pushAndRemoveUntil(
          context,
          MaterialPageRoute(builder: (context) => HomeScreen(isFirstTimeUser: true)),
          (route) => false,
        );
      }
    } catch (e) {
      print('❌ Registration error: $e');
      if (mounted) {
        // Extract clean error message
        String errorMessage = e.toString()
            .replaceAll('Exception: ', '')
            .replaceAll('Unexpected error: ', '')
            .replaceAll('Server returned ', '')
            .trim();
        
        Color errorColor = Colors.red;
        SnackBarAction? action;
        
        // Provide context-specific messages and actions
        if (errorMessage.contains('already registered')) {
          errorColor = Colors.orange;
          action = SnackBarAction(
            label: 'Sign In',
            textColor: Colors.white,
            onPressed: () {
              Navigator.popUntil(context, (route) => route.isFirst);
            },
          );
        } else if (errorMessage.contains('Network') || errorMessage.contains('connection')) {
          errorMessage = 'Network error. Please check your connection and try again.';
        } else if (errorMessage.contains('timeout')) {
          errorMessage = 'Request timed out. Please try again.';
        } else if (errorMessage.contains('invalid')) {
          errorMessage = 'Invalid information. Please check your details.';
        } else if (errorMessage.isEmpty || errorMessage == 'Registration failed. Please try again.') {
          errorMessage = 'Registration failed. Please try again.';
        }
        
        ScaffoldMessenger.of(context).showSnackBar(
          SnackBar(
            content: Text(errorMessage),
            backgroundColor: errorColor,
            duration: Duration(seconds: 3),
            action: action ?? SnackBarAction(
              label: 'Dismiss',
              textColor: Colors.white,
              onPressed: () {
                ScaffoldMessenger.of(context).clearSnackBars();
              },
            ),
          ),
        );
      }
    } finally {
      if (mounted) {
        setState(() => _isLoading = false);
      }
      print('========== REGISTER HANDLER COMPLETE ==========\n');
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
              padding: const EdgeInsets.all(24.0),
              child: Container(
                constraints: BoxConstraints(
                  maxWidth: MediaQuery.of(context).size.width > 600 ? 400 : MediaQuery.of(context).size.width * 0.95,
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
                padding: EdgeInsets.symmetric(
                  horizontal: MediaQuery.of(context).size.width < 420 ? 20.0 : 40.0,
                  vertical: 40.0,
                ),
                child: Form(
                  key: _formKey,
                  child: Column(
                    mainAxisSize: MainAxisSize.min,
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      // Back Button
                      Row(
                        children: [
                          TextButton.icon(
                            onPressed: () => Navigator.pop(context),
                            icon: Icon(Icons.arrow_back, size: 18),
                            label: Text('Back'),
                            style: TextButton.styleFrom(
                              foregroundColor: Colors.grey.shade600,
                              padding: EdgeInsets.symmetric(horizontal: 8),
                            ),
                          ),
                          Spacer(),
                        ],
                      ),
                      SizedBox(height: 16),
                      
                      // Progress Indicator
                      Row(
                        children: [
                          _ProgressDot(isActive: true, isCompleted: true),
                          _ProgressLine(isCompleted: true),
                          _ProgressDot(isActive: true, isCompleted: true),
                          _ProgressLine(isCompleted: true),
                          _ProgressDot(isActive: true, isCompleted: false),
                        ],
                      ),
                      SizedBox(height: 32),

                      // Icon
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
                            borderRadius: BorderRadius.circular(20),
                            boxShadow: [
                              BoxShadow(
                                color: AppTheme.brandPrimary.withValues(alpha: 0.3),
                                blurRadius: 20,
                                offset: Offset(0, 10),
                              ),
                            ],
                          ),
                          child: Icon(
                            Icons.lock_outline,
                            size: 40,
                            color: Colors.white,
                          ),
                        ),
                      ).animate()
                        .fadeIn(duration: 400.ms)
                        .scale(begin: Offset(0.8, 0.8), end: Offset(1, 1)),
                      SizedBox(height: 32),

                      // Title
                      Text(
                        'Secure Your Account',
                        style: GoogleFonts.poppins(
                          fontSize: 28,
                          fontWeight: FontWeight.bold,
                          color: AppTheme.brandPrimary,
                          height: 1.2,
                        ),
                      ).animate()
                        .fadeIn(duration: 400.ms, delay: 100.ms)
                        .slideX(begin: -0.1, end: 0),
                      SizedBox(height: 12),

                      Text(
                        'Create a strong password for ${widget.firstName}',
                        style: GoogleFonts.inter(
                          fontSize: 16,
                          color: Colors.grey.shade600,
                          height: 1.5,
                        ),
                      ).animate()
                        .fadeIn(duration: 400.ms, delay: 200.ms)
                        .slideX(begin: -0.1, end: 0),
                      SizedBox(height: 40),

                      // Password Field
                      Text(
                        'Password',
                        style: GoogleFonts.inter(
                          fontSize: 14,
                          fontWeight: FontWeight.w600,
                          color: AppTheme.brandPrimary,
                        ),
                      ),
                      SizedBox(height: 8),
                      TextFormField(
                        controller: _passwordController,
                        obscureText: _obscurePassword,
                        decoration: InputDecoration(
                          hintText: 'Enter your password',
                          hintStyle: GoogleFonts.inter(
                            color: Colors.grey.shade400,
                          ),
                          filled: true,
                          fillColor: Colors.grey.shade50,
                          border: OutlineInputBorder(
                            borderRadius: BorderRadius.circular(16),
                            borderSide: BorderSide.none,
                          ),
                          enabledBorder: OutlineInputBorder(
                            borderRadius: BorderRadius.circular(16),
                            borderSide: BorderSide(
                              color: Colors.grey.shade200,
                              width: 1,
                            ),
                          ),
                          focusedBorder: OutlineInputBorder(
                            borderRadius: BorderRadius.circular(16),
                            borderSide: BorderSide(
                              color: AppTheme.brandPrimary,
                              width: 2,
                            ),
                          ),
                          errorBorder: OutlineInputBorder(
                            borderRadius: BorderRadius.circular(16),
                            borderSide: BorderSide(
                              color: Colors.red.shade300,
                              width: 1,
                            ),
                          ),
                          prefixIcon: Icon(
                            Icons.lock,
                            color: AppTheme.brandPrimary,
                          ),
                          suffixIcon: IconButton(
                            icon: Icon(
                              _obscurePassword
                                  ? Icons.visibility_off
                                  : Icons.visibility,
                              color: Colors.grey.shade600,
                            ),
                            onPressed: () {
                              setState(() {
                                _obscurePassword = !_obscurePassword;
                              });
                            },
                          ),
                        ),
                        validator: _validatePassword,
                      ).animate()
                        .fadeIn(duration: 400.ms, delay: 300.ms)
                        .slideY(begin: 0.2, end: 0),
                      SizedBox(height: 16),

                      // Password Requirements
                      Container(
                        padding: EdgeInsets.all(16),
                        decoration: BoxDecoration(
                          color: AppTheme.brandPrimary.withValues(alpha: 0.05),
                          borderRadius: BorderRadius.circular(12),
                          border: Border.all(
                            color: AppTheme.brandPrimary.withValues(alpha: 0.1),
                          ),
                        ),
                        child: Column(
                          crossAxisAlignment: CrossAxisAlignment.start,
                          children: [
                            Text(
                              'Password must contain:',
                              style: GoogleFonts.inter(
                                fontSize: 12,
                                fontWeight: FontWeight.w600,
                                color: AppTheme.brandPrimary,
                              ),
                            ),
                            SizedBox(height: 8),
                            _RequirementItem('At least 8 characters'),
                            _RequirementItem('One uppercase letter'),
                            _RequirementItem('One lowercase letter'),
                            _RequirementItem('One number'),
                          ],
                        ),
                      ).animate()
                        .fadeIn(duration: 400.ms, delay: 350.ms),
                      SizedBox(height: 24),

                      // Confirm Password Field
                      Text(
                        'Confirm Password',
                        style: GoogleFonts.inter(
                          fontSize: 14,
                          fontWeight: FontWeight.w600,
                          color: AppTheme.brandPrimary,
                        ),
                      ),
                      SizedBox(height: 8),
                      TextFormField(
                        controller: _confirmPasswordController,
                        obscureText: _obscureConfirmPassword,
                        decoration: InputDecoration(
                          hintText: 'Re-enter your password',
                          hintStyle: GoogleFonts.inter(
                            color: Colors.grey.shade400,
                          ),
                          filled: true,
                          fillColor: Colors.grey.shade50,
                          border: OutlineInputBorder(
                            borderRadius: BorderRadius.circular(16),
                            borderSide: BorderSide.none,
                          ),
                          enabledBorder: OutlineInputBorder(
                            borderRadius: BorderRadius.circular(16),
                            borderSide: BorderSide(
                              color: Colors.grey.shade200,
                              width: 1,
                            ),
                          ),
                          focusedBorder: OutlineInputBorder(
                            borderRadius: BorderRadius.circular(16),
                            borderSide: BorderSide(
                              color: AppTheme.brandPrimary,
                              width: 2,
                            ),
                          ),
                          errorBorder: OutlineInputBorder(
                            borderRadius: BorderRadius.circular(16),
                            borderSide: BorderSide(
                              color: Colors.red.shade300,
                              width: 1,
                            ),
                          ),
                          prefixIcon: Icon(
                            Icons.lock,
                            color: AppTheme.brandPrimary,
                          ),
                          suffixIcon: IconButton(
                            icon: Icon(
                              _obscureConfirmPassword
                                  ? Icons.visibility_off
                                  : Icons.visibility,
                              color: Colors.grey.shade600,
                            ),
                            onPressed: () {
                              setState(() {
                                _obscureConfirmPassword = !_obscureConfirmPassword;
                              });
                            },
                          ),
                        ),
                        validator: (value) {
                          if (value == null || value.isEmpty) {
                            return 'Please confirm your password';
                          }
                          return null;
                        },
                      ).animate()
                        .fadeIn(duration: 400.ms, delay: 400.ms)
                        .slideY(begin: 0.2, end: 0),
                      SizedBox(height: 40),

                      // Save Button
                      SizedBox(
                        width: double.infinity,
                        height: 56,
                        child: ElevatedButton(
                          onPressed: _isLoading ? null : _register,
                          style: ElevatedButton.styleFrom(
                            backgroundColor: AppTheme.brandPrimary,
                            foregroundColor: Colors.white,
                            elevation: 0,
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
                                    strokeWidth: 2,
                                    valueColor: AlwaysStoppedAnimation<Color>(Colors.white),
                                  ),
                                )
                              : Row(
                                  mainAxisAlignment: MainAxisAlignment.center,
                                  children: [
                                    Icon(Icons.check_circle_outline, size: 24),
                                    SizedBox(width: 12),
                                    Text(
                                      'Complete Registration',
                                      style: GoogleFonts.inter(
                                        fontSize: 16,
                                        fontWeight: FontWeight.w600,
                                        letterSpacing: 0.5,
                                      ),
                                    ),
                                  ],
                                ),
                        ),
                      ).animate()
                        .fadeIn(duration: 400.ms, delay: 500.ms)
                        .slideY(begin: 0.2, end: 0),
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
}

class _RequirementItem extends StatelessWidget {
  final String text;

  const _RequirementItem(this.text);

  @override
  Widget build(BuildContext context) {
    return Padding(
      padding: const EdgeInsets.only(bottom: 4),
      child: Row(
        children: [
          Icon(
            Icons.check_circle_outline,
            size: 16,
            color: AppTheme.brandPrimary,
          ),
          SizedBox(width: 8),
          Text(
            text,
            style: GoogleFonts.inter(
              fontSize: 12,
              color: Colors.grey.shade700,
            ),
          ),
        ],
      ),
    );
  }
}

class _ProgressDot extends StatelessWidget {
  final bool isActive;
  final bool isCompleted;

  const _ProgressDot({required this.isActive, required this.isCompleted});

  @override
  Widget build(BuildContext context) {
    return Container(
      width: 32,
      height: 32,
      decoration: BoxDecoration(
        color: isCompleted
            ? AppTheme.brandPrimary
            : isActive
                ? AppTheme.brandPrimary
                : Colors.grey.shade300,
        shape: BoxShape.circle,
        border: Border.all(
          color: isActive
              ? AppTheme.brandPrimary
              : Colors.grey.shade400,
          width: 2,
        ),
      ),
      child: isCompleted
          ? Icon(Icons.check, color: Colors.white, size: 18)
          : null,
    );
  }
}

class _ProgressLine extends StatelessWidget {
  final bool isCompleted;

  const _ProgressLine({required this.isCompleted});

  @override
  Widget build(BuildContext context) {
    return Expanded(
      child: Container(
        height: 2,
        color: isCompleted ? AppTheme.brandPrimary : Colors.grey.shade300,
      ),
    );
  }
}
