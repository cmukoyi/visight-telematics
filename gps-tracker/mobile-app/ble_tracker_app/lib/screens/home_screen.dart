import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:flutter/foundation.dart' show kIsWeb;
import 'package:flutter_animate/flutter_animate.dart';
import 'package:google_fonts/google_fonts.dart';
import 'package:ble_tracker_app/theme/app_theme.dart';
import 'package:ble_tracker_app/services/auth_service.dart';
import 'package:ble_tracker_app/services/location_service.dart';
import 'package:ble_tracker_app/screens/map_screen.dart';
import 'package:ble_tracker_app/screens/qr_scanner_screen.dart';
import 'package:ble_tracker_app/screens/add_tag_screen.dart';
import 'package:permission_handler/permission_handler.dart';

class HomeScreen extends StatefulWidget {
  final bool skipAutoNavigation;
  /// True when coming straight from registration — hides map shortcut until
  /// the user has added their first IMEI.
  final bool isFirstTimeUser;
  const HomeScreen({Key? key, this.skipAutoNavigation = false, this.isFirstTimeUser = false}) : super(key: key);

  @override
  State<HomeScreen> createState() => _HomeScreenState();
}

class _HomeScreenState extends State<HomeScreen> {
  final _authService = AuthService();
  final _locationService = LocationService();
  bool _showAddTagModal = false;
  bool _isLoading = false;
  bool _checkingTags = true;
  final _imeiController = TextEditingController();
  final _tagNameController = TextEditingController();
  String _selectedMethod = 'manual'; // 'manual' or 'qr'

  @override
  void initState() {
    super.initState();
    _checkUserTags();
  }

  Future<void> _checkUserTags() async {
    print('🏠 HomeScreen._checkUserTags: skipAutoNavigation=${widget.skipAutoNavigation}, isFirstTimeUser=${widget.isFirstTimeUser}');
    // Skip auto-navigation if explicitly told to, or for first-time users
    // (first-time users navigate to MapScreen only after adding their first tag)
    if (widget.skipAutoNavigation || widget.isFirstTimeUser) {
      print('🏠 HomeScreen._checkUserTags: skipping auto-nav, showing add-tag screen');
      if (mounted) {
        setState(() => _checkingTags = false);
      }
      return;
    }
    
    // Check if user already has tags
    try {
      print('🏠 HomeScreen._checkUserTags: fetching tags from backend...');
      final tags = await _authService.getBLETags();
      print('🏠 HomeScreen._checkUserTags: got ${tags?.length ?? 0} tags');
      if (tags != null && tags.isNotEmpty && mounted) {
        // User has tags - navigate to MapScreen
        print('🏠 HomeScreen._checkUserTags: has tags, pushing /map');
        Navigator.pushNamedAndRemoveUntil(context, '/map', (route) => false);
        return;
      }
    } catch (e) {
      print('🏠 HomeScreen._checkUserTags: error fetching tags: $e');
    }
    
    // User has no tags - show add tag screen
    print('🏠 HomeScreen._checkUserTags: no tags found, showing add-tag screen');
    if (mounted) {
      setState(() => _checkingTags = false);
    }
  }

  @override
  void dispose() {
    _imeiController.dispose();
    _tagNameController.dispose();
    super.dispose();
  }

  Future<void> _openQRScanner() async {
    // Request camera permission
    final status = await Permission.camera.request();
    
    if (status.isGranted) {
      // Open QR scanner
      final result = await Navigator.push<String>(
        context,
        MaterialPageRoute(
          builder: (context) => QRScannerScreen(),
        ),
      );

      if (result != null && mounted) {
        // IMEI scanned successfully
        setState(() {
          _imeiController.text = result;
          _selectedMethod = 'manual'; // Switch to manual view to show the scanned IMEI
        });

        ScaffoldMessenger.of(context).showSnackBar(
          SnackBar(
            content: Text('✅ IMEI scanned: $result'),
            backgroundColor: Colors.green,
            duration: Duration(seconds: 2),
          ),
        );
      }
    }
    // If permission is denied or permanently denied, do nothing —
    // the user stays on the screen and can type the IMEI manually
    // or tap the QR button again.
  }

  Future<void> _addTag() async {
    final imei = _imeiController.text.trim();
    
    if (!_locationService.isValidIMEI(imei)) {
      ScaffoldMessenger.of(context).showSnackBar(
        SnackBar(
          content: Text('Please enter a valid IMEI (15 digits or valid GUID)'),
          backgroundColor: Colors.red,
        ),
      );
      return;
    }

    setState(() => _isLoading = true);

    try {
      // Save IMEI to local storage using LocationService
      final tagName = _tagNameController.text.trim();
      await _locationService.saveIMEI(imei, description: tagName.isEmpty ? null : tagName);
      print('✅ HomeScreen: IMEI saved to local storage: $imei');
      
      // Optional: Also try to save to backend for user's account (legacy API)
      try {
        final validationResult = await _authService.validateIMEI(imei);
        
        if (validationResult['requiresLogin'] == true) {
          // Authentication failed - redirect to login
          print('🔒 HomeScreen: Session expired, redirecting to login');
          if (mounted) {
            ScaffoldMessenger.of(context).showSnackBar(
              SnackBar(
                content: Text('${validationResult['message']}'),
                backgroundColor: Colors.orange,
                duration: Duration(seconds: 3),
              ),
            );
            await Future.delayed(Duration(milliseconds: 500));
            Navigator.pushReplacementNamed(context, '/');
          }
          return;
        }
        
        if (validationResult['success']) {
          await _authService.addBLETag(
            imei: imei,
            name: _tagNameController.text.trim().isEmpty 
                ? null 
                : _tagNameController.text.trim(),
          );
          print('✅ HomeScreen: IMEI also saved to backend');
        } else {
          print('ℹ️ HomeScreen: IMEI not validated by backend (${validationResult['message']}), but saved locally');
        }
      } catch (e) {
        print('⚠️ HomeScreen: Backend save failed: $e (IMEI still saved locally)');
      }

      if (mounted) {
        ScaffoldMessenger.of(context).showSnackBar(
          SnackBar(
            content: Text('IMEI added successfully'),
            backgroundColor: Colors.green,
          ),
        );

        setState(() {
          _showAddTagModal = false;
          _imeiController.clear();
          _tagNameController.clear();
        });
        
        // After successful add, navigate to MapScreen — use named route so URL updates correctly
        await Future.delayed(Duration(milliseconds: 500));
        if (mounted) {
          print('✅ HomeScreen: Navigating to /map after adding first tag');
          Navigator.pushNamedAndRemoveUntil(context, '/map', (route) => false);
        }
      }
    } catch (e) {
      print('❌ HomeScreen: Error adding IMEI: $e');
      if (mounted) {
        // Extract error message - prefer simple messages
        String errorMsg = e.toString();
        if (errorMsg.contains('IMEI not recognised')) {
          errorMsg = 'IMEI not recognised';
        } else if (errorMsg.contains('Exception: ')) {
          errorMsg = errorMsg.replaceAll('Exception: ', '');
        }
        ScaffoldMessenger.of(context).showSnackBar(
          SnackBar(
            content: Text(errorMsg),
            backgroundColor: Colors.red,
          ),
        );
      }
    } finally {
      if (mounted) {
        setState(() => _isLoading = false);
      }
    }
  }
    
  @override
  Widget build(BuildContext context) {
    // Show loading while checking tags
    if (_checkingTags) {
      return Scaffold(
        body: Center(
          child: Column(
            mainAxisAlignment: MainAxisAlignment.center,
            children: [
              CircularProgressIndicator(color: AppTheme.brandPrimary),
              SizedBox(height: 16),
              Text(
                'Loading...',
                style: GoogleFonts.inter(
                  fontSize: 16,
                  color: Colors.grey.shade600,
                ),
              ),
            ],
          ),
        ),
      );
    }
    
    return Scaffold(
      body: Stack(
        children: [
          // Gradient Background
          Container(
            decoration: BoxDecoration(
              gradient: LinearGradient(
                begin: Alignment.topLeft,
                end: Alignment.bottomRight,
                colors: [
                  Color(0xFFf0f9ff),
                  Color(0xFFe0f2fe),
                  Color(0xFFbae6fd),
                  Color(0xFF7dd3fc),
                  Color(0xFF38bdf8),
                ],
              ),
            ),
          ),
          
          // Floating circles animation
          Positioned(
            top: -100,
            right: -50,
            child: Container(
              width: 300,
              height: 300,
              decoration: BoxDecoration(
                shape: BoxShape.circle,
                gradient: RadialGradient(
                  colors: [
                    AppTheme.brandPrimary.withOpacity(0.08),
                    Colors.transparent,
                  ],
                ),
              ),
            ).animate(onPlay: (controller) => controller.repeat())
              .move(
                duration: 6000.ms,
                begin: Offset(0, 0),
                end: Offset(20, 20),
              ),
          ),
          
          Positioned(
            bottom: -80,
            left: -50,
            child: Container(
              width: 250,
              height: 250,
              decoration: BoxDecoration(
                shape: BoxShape.circle,
                gradient: RadialGradient(
                  colors: [
                    Color(0xFF38bdf8).withOpacity(0.1),
                    Colors.transparent,
                  ],
                ),
              ),
            ).animate(onPlay: (controller) => controller.repeat())
              .move(
                duration: 8000.ms,
                begin: Offset(0, 0),
                end: Offset(-20, -20),
              ),
          ),

          // Main Content
          SafeArea(
            child: Center(
              child: SingleChildScrollView(
                padding: const EdgeInsets.all(24.0),
                child: Column(
                  mainAxisAlignment: MainAxisAlignment.center,
                  children: [
                    // BLE Icon
                    Container(
                      padding: EdgeInsets.all(24),
                      decoration: BoxDecoration(
                        gradient: LinearGradient(
                          colors: [Colors.white, Color(0xFFe0f2fe)],
                        ),
                        shape: BoxShape.circle,
                        boxShadow: [
                          BoxShadow(
                            color: AppTheme.brandPrimary.withOpacity(0.15),
                            blurRadius: 40,
                            offset: Offset(0, 20),
                          ),
                        ],
                        border: Border.all(
                          color: Colors.white.withOpacity(0.8),
                          width: 2,
                        ),
                      ),
                      child: Icon(
                        Icons.bluetooth,
                        size: 80,
                        color: AppTheme.brandPrimary,
                      ),
                    ).animate()
                      .fadeIn(duration: 600.ms)
                      .scale(begin: Offset(0.8, 0.8), end: Offset(1, 1)),
                    
                    SizedBox(height: 32),

                    // Title with gradient
                    ShaderMask(
                      shaderCallback: (bounds) => LinearGradient(
                        colors: [AppTheme.brandPrimary, Color(0xFF2563eb)],
                      ).createShader(bounds),
                      child: Text(
                        'BLE Tag Tracker',
                        style: GoogleFonts.poppins(
                          fontSize: 36,
                          fontWeight: FontWeight.bold,
                          color: Colors.white,
                          height: 1.2,
                        ),
                        textAlign: TextAlign.center,
                      ),
                    ).animate()
                      .fadeIn(duration: 600.ms, delay: 100.ms)
                      .slideX(begin: -0.1, end: 0),
                    
                    SizedBox(height: 16),

                    // Subtitle
                    Text(
                      'Track your assets in real-time with\nour advanced BLE technology',
                      style: GoogleFonts.inter(
                        fontSize: 16,
                        color: Colors.grey.shade800,
                        fontWeight: FontWeight.w500,
                        height: 1.5,
                      ),
                      textAlign: TextAlign.center,
                    ).animate()
                      .fadeIn(duration: 600.ms, delay: 200.ms)
                      .slideX(begin: -0.1, end: 0),
                    
                    SizedBox(height: 48),

                    // Add BLE Tag Button
                    Container(
                      decoration: BoxDecoration(
                        gradient: LinearGradient(
                          colors: [
                            AppTheme.brandPrimary,
                            Color(0xFF2563eb),
                          ],
                        ),
                        borderRadius: BorderRadius.circular(16),
                        boxShadow: [
                          BoxShadow(
                            color: AppTheme.brandPrimary.withOpacity(0.3),
                            blurRadius: 30,
                            offset: Offset(0, 10),
                          ),
                          BoxShadow(
                            color: AppTheme.brandPrimary.withOpacity(0.2),
                            blurRadius: 12,
                            offset: Offset(0, 4),
                          ),
                        ],
                      ),
                      child: ElevatedButton(
                        onPressed: () {
                          Navigator.push(
                            context,
                            MaterialPageRoute(
                              builder: (_) => AddTagScreen(
                                isFirstTag: widget.isFirstTimeUser,
                              ),
                            ),
                          );
                        },
                        style: ElevatedButton.styleFrom(
                          backgroundColor: Colors.transparent,
                          foregroundColor: Colors.white,
                          elevation: 0,
                          padding: EdgeInsets.symmetric(horizontal: 40, vertical: 18),
                          shape: RoundedRectangleBorder(
                            borderRadius: BorderRadius.circular(16),
                          ),
                        ),
                        child: Row(
                          mainAxisSize: MainAxisSize.min,
                          children: [
                            Icon(Icons.add, size: 24),
                            SizedBox(width: 12),
                            Text(
                              'Add BLE Tag',
                              style: GoogleFonts.inter(
                                fontSize: 18,
                                fontWeight: FontWeight.bold,
                              ),
                            ),
                          ],
                        ),
                      ),
                    ).animate()
                      .fadeIn(duration: 600.ms, delay: 300.ms)
                      .slideY(begin: 0.2, end: 0),
                    
                    SizedBox(height: 16),

                    // Back to Map Button — hidden for first-time users (they have
                    // no tags yet, so the map would be a blank white screen).
                    if (!widget.isFirstTimeUser)
                      TextButton(
                        onPressed: () {
                          print('🗺️ HomeScreen: Back to Map tapped, navigating to /map');
                          // Use named route so Flutter Web updates URL to #/map correctly
                          Navigator.pushNamedAndRemoveUntil(context, '/map', (route) => false);
                        },
                        style: TextButton.styleFrom(
                          backgroundColor: Colors.white.withOpacity(0.6),
                          foregroundColor: AppTheme.brandPrimary,
                          padding: EdgeInsets.symmetric(horizontal: 32, vertical: 14),
                          shape: RoundedRectangleBorder(
                            borderRadius: BorderRadius.circular(12),
                          ),
                        ),
                        child: Row(
                          mainAxisSize: MainAxisSize.min,
                          children: [
                            Icon(Icons.map, size: 20),
                            SizedBox(width: 8),
                            Text(
                              'Back to Map',
                              style: GoogleFonts.inter(
                                fontSize: 15,
                                fontWeight: FontWeight.w600,
                              ),
                            ),
                          ],
                        ),
                      ).animate()
                        .fadeIn(duration: 600.ms, delay: 400.ms)
                        .slideY(begin: 0.2, end: 0),

                    // First-time hint — shown instead of the map button
                    if (widget.isFirstTimeUser)
                      Padding(
                        padding: const EdgeInsets.symmetric(horizontal: 8.0),
                        child: Text(
                          'Add your first asset to get started. You can access the map once a tag has been registered.',
                          style: GoogleFonts.inter(
                            fontSize: 13,
                            color: Colors.grey.shade700,
                            height: 1.5,
                          ),
                          textAlign: TextAlign.center,
                        ),
                      ).animate()
                        .fadeIn(duration: 600.ms, delay: 400.ms),
                    
                    SizedBox(height: 48),

                    // Feature Highlights — only shown for returning users
                    if (!widget.isFirstTimeUser)
                      Row(
                        mainAxisAlignment: MainAxisAlignment.center,
                        children: [
                          _FeatureCard(
                            icon: Icons.location_on,
                            label: 'Real-time\nTracking',
                          ),
                          SizedBox(width: 16),
                          _FeatureCard(
                            icon: Icons.shield,
                            label: 'Secure &\nPrivate',
                          ),
                          SizedBox(width: 16),
                          _FeatureCard(
                            icon: Icons.bolt,
                            label: 'Instant\nAlerts',
                          ),
                        ],
                      ).animate()
                        .fadeIn(duration: 600.ms, delay: 500.ms),
                  ],
                ),
              ),
            ),
          ),

          // Add Tag Modal
          if (_showAddTagModal)
            Container(
              color: Colors.black.withOpacity(0.5),
              child: Center(
                child: Container(
                  margin: EdgeInsets.all(24),
                  constraints: BoxConstraints(maxWidth: 500),
                  decoration: BoxDecoration(
                    color: Colors.white,
                    borderRadius: BorderRadius.circular(24),
                    boxShadow: [
                      BoxShadow(
                        color: Colors.black.withOpacity(0.2),
                        blurRadius: 20,
                      ),
                    ],
                  ),
                  child: Column(
                    mainAxisSize: MainAxisSize.min,
                    children: [
                      // Modal Header
                      Container(
                        padding: EdgeInsets.all(24),
                        decoration: BoxDecoration(
                          color: AppTheme.brandPrimary,
                          borderRadius: BorderRadius.only(
                            topLeft: Radius.circular(24),
                            topRight: Radius.circular(24),
                          ),
                        ),
                        child: Row(
                          children: [
                            Expanded(
                              child: Text(
                                'Add BLE Tag',
                                style: GoogleFonts.poppins(
                                  fontSize: 20,
                                  fontWeight: FontWeight.bold,
                                  color: Colors.white,
                                ),
                              ),
                            ),
                            IconButton(
                              icon: Icon(Icons.close, color: Colors.white),
                              onPressed: () {
                                setState(() => _showAddTagModal = false);
                              },
                            ),
                          ],
                        ),
                      ),

                      // Modal Content
                      Padding(
                        padding: EdgeInsets.all(24),
                        child: Column(
                          crossAxisAlignment: CrossAxisAlignment.start,
                          children: [
                            // Method Selection Buttons
                            Row(
                              children: [
                                Expanded(
                                  child: _MethodButton(
                                    icon: Icons.qr_code_scanner,
                                    label: 'Scan QR Code',
                                    isSelected: _selectedMethod == 'qr',
                                    onTap: () {
                                      _openQRScanner();
                                    },
                                  ),
                                ),
                                SizedBox(width: 12),
                                Expanded(
                                  child: _MethodButton(
                                    icon: Icons.edit,
                                    label: 'Manual Entry',
                                    isSelected: _selectedMethod == 'manual',
                                    onTap: () {
                                      setState(() {
                                        _selectedMethod = 'manual';
                                      });
                                    },
                                  ),
                                ),
                              ],
                            ),
                            SizedBox(height: 24),

                            // IMEI Input
                            Text(
                              'IMEI Number',
                              style: GoogleFonts.inter(
                                fontSize: 14,
                                fontWeight: FontWeight.w600,
                                color: AppTheme.brandPrimary,
                              ),
                            ),
                            SizedBox(height: 8),
                            TextField(
                              controller: _imeiController,
                              keyboardType: TextInputType.number,
                              maxLength: 15,
                              inputFormatters: [
                                FilteringTextInputFormatter.digitsOnly,
                              ],
                              decoration: InputDecoration(
                                hintText: 'Enter 15-digit IMEI',
                                helperText: 'Example: 867747079036032',
                                prefixIcon: Icon(Icons.tag, color: AppTheme.brandPrimary),
                                border: OutlineInputBorder(
                                  borderRadius: BorderRadius.circular(12),
                                ),
                                focusedBorder: OutlineInputBorder(
                                  borderRadius: BorderRadius.circular(12),
                                  borderSide: BorderSide(
                                    color: AppTheme.brandPrimary,
                                    width: 2,
                                  ),
                                ),
                              ),
                            ),
                            SizedBox(height: 20),

                            // Tag Name Input
                            Text(
                              'Asset Description (Optional)',
                              style: GoogleFonts.inter(
                                fontSize: 14,
                                fontWeight: FontWeight.w600,
                                color: AppTheme.brandPrimary,
                              ),
                            ),
                            SizedBox(height: 8),
                            TextField(
                              controller: _tagNameController,
                              decoration: InputDecoration(
                                hintText: 'e.g., My Car, Office Keys',
                                prefixIcon: Icon(Icons.label, color: AppTheme.brandPrimary),
                                border: OutlineInputBorder(
                                  borderRadius: BorderRadius.circular(12),
                                ),
                                focusedBorder: OutlineInputBorder(
                                  borderRadius: BorderRadius.circular(12),
                                  borderSide: BorderSide(
                                    color: AppTheme.brandPrimary,
                                    width: 2,
                                  ),
                                ),
                              ),
                            ),
                            SizedBox(height: 24),

                            // Save Button
                            SizedBox(
                              width: double.infinity,
                              child: ElevatedButton(
                                onPressed: _isLoading ? null : _addTag,
                                style: ElevatedButton.styleFrom(
                                  backgroundColor: AppTheme.brandPrimary,
                                  foregroundColor: Colors.white,
                                  padding: const EdgeInsets.symmetric(vertical: 14, horizontal: 16),
                                  shape: RoundedRectangleBorder(
                                    borderRadius: BorderRadius.circular(12),
                                  ),
                                  disabledBackgroundColor: Colors.grey.shade300,
                                ),
                                child: _isLoading
                                    ? const SizedBox(
                                        height: 20,
                                        width: 20,
                                        child: CircularProgressIndicator(
                                          strokeWidth: 2,
                                          valueColor: AlwaysStoppedAnimation<Color>(Colors.white),
                                        ),
                                      )
                                    : Row(
                                        mainAxisSize: MainAxisSize.min,
                                        mainAxisAlignment: MainAxisAlignment.center,
                                        children: [
                                          const Icon(Icons.save, size: 20),
                                          const SizedBox(width: 8),
                                          Flexible(
                                            child: Text(
                                              'Save Tag',
                                              style: GoogleFonts.inter(
                                                fontSize: 16,
                                                fontWeight: FontWeight.w600,
                                              ),
                                              overflow: TextOverflow.ellipsis,
                                            ),
                                          ),
                                        ],
                                      ),
                              ),
                            ),
                          ],
                        ),
                      ),
                    ],
                  ),
                ).animate()
                  .fadeIn(duration: 200.ms)
                  .scale(begin: Offset(0.9, 0.9), end: Offset(1, 1)),
              ),
            ),
        ],
      ),
    );
  }
}

class _FeatureCard extends StatelessWidget {
  final IconData icon;
  final String label;

  const _FeatureCard({required this.icon, required this.label});

  @override
  Widget build(BuildContext context) {
    return Container(
      width: 90,
      child: Column(
        children: [
          Container(
            padding: EdgeInsets.all(12),
            decoration: BoxDecoration(
              color: Colors.white.withOpacity(0.7),
              borderRadius: BorderRadius.circular(12),
              boxShadow: [
                BoxShadow(
                  color: Colors.black.withOpacity(0.05),
                  blurRadius: 8,
                ),
              ],
            ),
            child: Icon(
              icon,
              size: 28,
              color: AppTheme.brandPrimary,
            ),
          ),
          SizedBox(height: 8),
          Text(
            label,
            style: GoogleFonts.inter(
              fontSize: 10,
              fontWeight: FontWeight.w600,
              color: Colors.grey.shade800,
              height: 1.2,
            ),
            textAlign: TextAlign.center,
          ),
        ],
      ),
    );
  }
}

class _MethodButton extends StatelessWidget {
  final IconData icon;
  final String label;
  final bool isSelected;
  final VoidCallback onTap;

  const _MethodButton({
    required this.icon,
    required this.label,
    required this.isSelected,
    required this.onTap,
  });

  @override
  Widget build(BuildContext context) {
    return InkWell(
      onTap: onTap,
      borderRadius: BorderRadius.circular(12),
      child: Container(
        padding: EdgeInsets.symmetric(vertical: 16, horizontal: 12),
        decoration: BoxDecoration(
          color: isSelected ? AppTheme.brandPrimary.withOpacity(0.1) : Colors.grey.shade100,
          border: Border.all(
            color: isSelected ? AppTheme.brandPrimary : Colors.grey.shade300,
            width: 2,
          ),
          borderRadius: BorderRadius.circular(12),
        ),
        child: Column(
          children: [
            Icon(
              icon,
              color: isSelected ? AppTheme.brandPrimary : Colors.grey.shade600,
              size: 32,
            ),
            SizedBox(height: 8),
            Text(
              label,
              style: GoogleFonts.inter(
                fontSize: 13,
                fontWeight: isSelected ? FontWeight.w600 : FontWeight.w500,
                color: isSelected ? AppTheme.brandPrimary : Colors.grey.shade700,
              ),
              textAlign: TextAlign.center,
            ),
          ],
        ),
      ),
    );
  }
}
