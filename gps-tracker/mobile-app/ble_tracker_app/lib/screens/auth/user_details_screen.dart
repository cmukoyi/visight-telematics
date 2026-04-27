import 'package:flutter/material.dart';
import 'package:flutter_animate/flutter_animate.dart';
import 'package:google_fonts/google_fonts.dart';
import 'package:ble_tracker_app/theme/app_theme.dart';
import 'package:ble_tracker_app/screens/auth/password_screen.dart';

class UserDetailsScreen extends StatefulWidget {
  final String email;
  final String verifiedPin;

  const UserDetailsScreen({
    Key? key,
    required this.email,
    required this.verifiedPin,
  }) : super(key: key);

  @override
  State<UserDetailsScreen> createState() => _UserDetailsScreenState();
}

class _UserDetailsScreenState extends State<UserDetailsScreen> {
  final _formKey = GlobalKey<FormState>();
  final _firstNameController = TextEditingController();
  final _lastNameController = TextEditingController();

  @override
  void dispose() {
    _firstNameController.dispose();
    _lastNameController.dispose();
    super.dispose();
  }

  void _continue() {
    if (_formKey.currentState!.validate()) {
      Navigator.push(
        context,
        MaterialPageRoute(
          builder: (context) => PasswordScreen(
            email: widget.email,
            firstName: _firstNameController.text.trim(),
            lastName: _lastNameController.text.trim(),
          ),
        ),
      );
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
                          _ProgressDot(isActive: true, isCompleted: false),
                          _ProgressLine(isCompleted: false),
                          _ProgressDot(isActive: false, isCompleted: false),
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
                            Icons.person_outline,
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
                        'Your Details',
                        style: GoogleFonts.poppins(
                          fontSize: 32,
                          fontWeight: FontWeight.bold,
                          color: AppTheme.brandPrimary,
                          height: 1.2,
                        ),
                      ).animate()
                        .fadeIn(duration: 400.ms, delay: 100.ms)
                        .slideX(begin: -0.1, end: 0),
                      SizedBox(height: 12),

                      Text(
                        'Let\'s get to know you better',
                        style: GoogleFonts.inter(
                          fontSize: 16,
                          color: Colors.grey.shade600,
                          height: 1.5,
                        ),
                      ).animate()
                        .fadeIn(duration: 400.ms, delay: 200.ms)
                        .slideX(begin: -0.1, end: 0),
                      SizedBox(height: 40),

                      // First Name Field
                      Text(
                        'First Name',
                        style: GoogleFonts.inter(
                          fontSize: 14,
                          fontWeight: FontWeight.w600,
                          color: AppTheme.brandPrimary,
                        ),
                      ),
                      SizedBox(height: 8),
                      TextFormField(
                        controller: _firstNameController,
                        decoration: InputDecoration(
                          hintText: 'Enter your first name',
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
                            Icons.person,
                            color: AppTheme.brandPrimary,
                          ),
                        ),
                        validator: (value) {
                          if (value == null || value.trim().isEmpty) {
                            return 'Please enter your first name';
                          }
                          if (value.trim().length < 2) {
                            return 'First name must be at least 2 characters';
                          }
                          return null;
                        },
                        textCapitalization: TextCapitalization.words,
                      ).animate()
                        .fadeIn(duration: 400.ms, delay: 300.ms)
                        .slideY(begin: 0.2, end: 0),
                      SizedBox(height: 24),

                      // Last Name Field
                      Text(
                        'Last Name',
                        style: GoogleFonts.inter(
                          fontSize: 14,
                          fontWeight: FontWeight.w600,
                          color: AppTheme.brandPrimary,
                        ),
                      ),
                      SizedBox(height: 8),
                      TextFormField(
                        controller: _lastNameController,
                        decoration: InputDecoration(
                          hintText: 'Enter your last name',
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
                            Icons.person,
                            color: AppTheme.brandPrimary,
                          ),
                        ),
                        validator: (value) {
                          if (value == null || value.trim().isEmpty) {
                            return 'Please enter your last name';
                          }
                          if (value.trim().length < 2) {
                            return 'Last name must be at least 2 characters';
                          }
                          return null;
                        },
                        textCapitalization: TextCapitalization.words,
                      ).animate()
                        .fadeIn(duration: 400.ms, delay: 400.ms)
                        .slideY(begin: 0.2, end: 0),
                      SizedBox(height: 40),

                      // Next Button
                      SizedBox(
                        width: double.infinity,
                        height: 56,
                        child: ElevatedButton(
                          onPressed: _continue,
                          style: ElevatedButton.styleFrom(
                            backgroundColor: AppTheme.brandPrimary,
                            foregroundColor: Colors.white,
                            elevation: 0,
                            shape: RoundedRectangleBorder(
                              borderRadius: BorderRadius.circular(16),
                            ),
                          ),
                          child: Row(
                            mainAxisAlignment: MainAxisAlignment.center,
                            children: [
                              Text(
                                'Next',
                                style: GoogleFonts.inter(
                                  fontSize: 16,
                                  fontWeight: FontWeight.w600,
                                  letterSpacing: 0.5,
                                ),
                              ),
                              SizedBox(width: 8),
                              Icon(Icons.arrow_forward, size: 20),
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
