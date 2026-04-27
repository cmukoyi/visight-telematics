import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:flutter_animate/flutter_animate.dart';
import 'package:google_fonts/google_fonts.dart';
import 'package:permission_handler/permission_handler.dart';
import 'package:ble_tracker_app/theme/app_theme.dart';
import 'package:ble_tracker_app/services/auth_service.dart';
import 'package:ble_tracker_app/services/location_service.dart';
import 'package:ble_tracker_app/screens/qr_scanner_screen.dart';
import 'package:ble_tracker_app/device_providers/ble_tag_type.dart';
import 'package:ble_tracker_app/device_providers/ble_tag_provider_factory.dart';

/// Screen for adding a new BLE tag.
///
/// Design highlights:
/// - Tag-type dropdown (TrackSolid / Scope) backed by [BleTagProviderFactory].
/// - Validation is delegated to the selected [BleTagProvider] Strategy before
///   the tag is persisted — TrackSolid checks the vendor API, Scope validates
///   the IMEI format.
/// - On success the user is taken to the map.
class AddTagScreen extends StatefulWidget {
  /// True when arriving directly after registration (first ever tag).
  /// Hides the "Back" affordance and adapts the title copy.
  final bool isFirstTag;

  const AddTagScreen({Key? key, this.isFirstTag = false}) : super(key: key);

  @override
  State<AddTagScreen> createState() => _AddTagScreenState();
}

class _AddTagScreenState extends State<AddTagScreen> {
  final _authService = AuthService();
  final _locationService = LocationService();
  final _imeiController = TextEditingController();
  final _tagNameController = TextEditingController();

  BleTagType _selectedType = BleTagType.series1;
  bool _isLoading = false;
  String? _validationMessage; // feedback shown below IMEI field
  int? _validatedBatteryLevel; // battery level returned by TrackSolid validation

  @override
  void dispose() {
    _imeiController.dispose();
    _tagNameController.dispose();
    super.dispose();
  }

  // ── QR scanner ──────────────────────────────────────────────────────────────
  Future<void> _openQRScanner() async {
    final status = await Permission.camera.request();
    if (!status.isGranted) return;

    final result = await Navigator.push<String>(
      context,
      MaterialPageRoute(builder: (_) => const QRScannerScreen()),
    );
    if (result != null && mounted) {
      setState(() {
        _imeiController.text = result;
        _validationMessage = null;
      });
      ScaffoldMessenger.of(context).showSnackBar(
        SnackBar(
          content: Text('✅ IMEI scanned: $result'),
          backgroundColor: Colors.green,
          duration: const Duration(seconds: 2),
        ),
      );
    }
  }

  // ── Submit ───────────────────────────────────────────────────────────────────
  Future<void> _submit() async {
    final imei = _imeiController.text.trim();
    if (!_locationService.isValidIMEI(imei)) {
      setState(() => _validationMessage = 'Please enter a valid IMEI (15 digits or valid GUID).');
      return;
    }

    setState(() {
      _isLoading = true;
      _validationMessage = null;
    });

    try {
      // 1. Validate against the vendor platform (Strategy pattern)
      final provider = BleTagProviderFactory.getProvider(_selectedType, _authService);
      final validationResult = await provider.validateTag(imei);

      if (!validationResult.isValid) {
        setState(() => _validationMessage = validationResult.message);
        return;
      }

      // Capture battery level from TrackSolid validation
      _validatedBatteryLevel = validationResult.batteryLevel;

      // 2. Save locally
      final tagName = _tagNameController.text.trim();
      await _locationService.saveIMEI(imei, description: tagName.isEmpty ? null : tagName);

      // 3. Persist to backend (includes tag_type and battery_level)
      await _authService.addBLETag(
        imei: imei,
        name: tagName.isEmpty ? null : tagName,
        tagType: _selectedType.apiValue,
        batteryLevel: _validatedBatteryLevel,
      );

      if (!mounted) return;

      ScaffoldMessenger.of(context).showSnackBar(
        const SnackBar(
          content: Text('Tag added successfully'),
          backgroundColor: Colors.green,
        ),
      );

      await Future.delayed(const Duration(milliseconds: 400));
      if (mounted) {
        Navigator.pushNamedAndRemoveUntil(context, '/map', (_) => false);
      }
    } catch (e) {
      print('❌ AddTagScreen._submit error: $e');
      if (mounted) {
        String msg = e.toString().replaceAll('Exception: ', '');
        setState(() => _validationMessage = msg);
      }
    } finally {
      if (mounted) setState(() => _isLoading = false);
    }
  }

  // ── Build ────────────────────────────────────────────────────────────────────
  @override
  Widget build(BuildContext context) {
    return Scaffold(
      backgroundColor: Colors.white,
      appBar: AppBar(
        backgroundColor: AppTheme.brandPrimary,
        title: Text(
          widget.isFirstTag ? 'Add Your First Tag' : 'Add BLE Tag',
          style: GoogleFonts.poppins(
            color: Colors.white,
            fontWeight: FontWeight.bold,
          ),
        ),
        automaticallyImplyLeading: !widget.isFirstTag,
        iconTheme: const IconThemeData(color: Colors.white),
      ),
      body: SingleChildScrollView(
        padding: const EdgeInsets.all(24),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            if (widget.isFirstTag) ...[
              Text(
                'Welcome! Let\'s add your first asset.',
                style: GoogleFonts.poppins(
                  fontSize: 18,
                  fontWeight: FontWeight.w600,
                  color: AppTheme.brandPrimary,
                ),
              ),
              const SizedBox(height: 8),
              Text(
                'Select the tag type, enter the IMEI, and tap Add Tag.',
                style: GoogleFonts.inter(
                  fontSize: 14,
                  color: Colors.grey.shade600,
                ),
              ),
              const SizedBox(height: 32),
            ],

            // ── Tag Type Dropdown ──────────────────────────────────────────
            _SectionLabel('Tag Type'),
            const SizedBox(height: 8),
            DropdownButtonFormField<BleTagType>(
              value: _selectedType,
              decoration: _inputDecoration(
                hintText: 'Select tag type',
                prefixIcon: Icons.devices,
              ),
              items: BleTagProviderFactory.supportedTypes.map((type) {
                return DropdownMenuItem(
                  value: type,
                  child: Text(type.displayName),
                );
              }).toList(),
              onChanged: (value) {
                if (value != null) {
                  setState(() {
                    _selectedType = value;
                    _validationMessage = null;
                  });
                }
              },
            ).animate().fadeIn(duration: 400.ms),

            const SizedBox(height: 8),
            _TagTypeHint(type: _selectedType),

            const SizedBox(height: 24),

            // ── IMEI / Identifier ──────────────────────────────────────────
            _SectionLabel('IMEI Number'),
            const SizedBox(height: 8),
            Row(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Expanded(
                  child: TextFormField(
                    controller: _imeiController,
                    keyboardType: TextInputType.number,
                    maxLength: 20,
                    inputFormatters: [FilteringTextInputFormatter.digitsOnly],
                    decoration: _inputDecoration(
                      hintText: 'Enter 15-digit IMEI',
                      helperText: 'Example: 867747079036032',
                      prefixIcon: Icons.tag,
                    ),
                    onChanged: (_) => setState(() => _validationMessage = null),
                  ),
                ),
                const SizedBox(width: 8),
                Tooltip(
                  message: 'Scan QR code',
                  child: Container(
                    margin: const EdgeInsets.only(top: 3),
                    decoration: BoxDecoration(
                      color: AppTheme.brandPrimary,
                      borderRadius: BorderRadius.circular(12),
                    ),
                    child: IconButton(
                      icon: const Icon(Icons.qr_code_scanner, color: Colors.white),
                      onPressed: _openQRScanner,
                    ),
                  ),
                ),
              ],
            ).animate().fadeIn(duration: 400.ms, delay: 50.ms),

            // Validation feedback
            if (_validationMessage != null) ...[
              const SizedBox(height: 4),
              Row(
                children: [
                  Icon(
                    Icons.error_outline,
                    size: 16,
                    color: Colors.red.shade700,
                  ),
                  const SizedBox(width: 6),
                  Expanded(
                    child: Text(
                      _validationMessage!,
                      style: TextStyle(
                        color: Colors.red.shade700,
                        fontSize: 13,
                      ),
                    ),
                  ),
                ],
              ).animate().fadeIn(duration: 200.ms),
            ],

            const SizedBox(height: 24),

            // ── Asset Name ─────────────────────────────────────────────────
            _SectionLabel('Asset Description (Optional)'),
            const SizedBox(height: 8),
            TextFormField(
              controller: _tagNameController,
              decoration: _inputDecoration(
                hintText: 'e.g., My Car, Office Keys',
                prefixIcon: Icons.label_outline,
              ),
            ).animate().fadeIn(duration: 400.ms, delay: 100.ms),

            const SizedBox(height: 40),

            // ── Submit Button ──────────────────────────────────────────────
            SizedBox(
              width: double.infinity,
              child: ElevatedButton(
                onPressed: _isLoading ? null : _submit,
                style: ElevatedButton.styleFrom(
                  backgroundColor: AppTheme.brandPrimary,
                  foregroundColor: Colors.white,
                  padding: const EdgeInsets.symmetric(vertical: 16),
                  shape: RoundedRectangleBorder(
                    borderRadius: BorderRadius.circular(14),
                  ),
                  elevation: 4,
                ),
                child: _isLoading
                    ? const SizedBox(
                        height: 22,
                        width: 22,
                        child: CircularProgressIndicator(
                          strokeWidth: 2.5,
                          valueColor: AlwaysStoppedAnimation<Color>(Colors.white),
                        ),
                      )
                    : Row(
                        mainAxisSize: MainAxisSize.min,
                        children: [
                          const Icon(Icons.add_circle_outline, size: 22),
                          const SizedBox(width: 10),
                          Text(
                            'Add Tag',
                            style: GoogleFonts.inter(
                              fontSize: 17,
                              fontWeight: FontWeight.bold,
                            ),
                          ),
                        ],
                      ),
              ),
            ).animate().fadeIn(duration: 400.ms, delay: 150.ms),

            const SizedBox(height: 24),
          ],
        ),
      ),
    );
  }

  InputDecoration _inputDecoration({
    required String hintText,
    String? helperText,
    required IconData prefixIcon,
  }) {
    return InputDecoration(
      hintText: hintText,
      helperText: helperText,
      prefixIcon: Icon(prefixIcon, color: AppTheme.brandPrimary),
      border: OutlineInputBorder(borderRadius: BorderRadius.circular(12)),
      focusedBorder: OutlineInputBorder(
        borderRadius: BorderRadius.circular(12),
        borderSide: const BorderSide(color: AppTheme.brandPrimary, width: 2),
      ),
      contentPadding: const EdgeInsets.symmetric(horizontal: 16, vertical: 14),
    );
  }
}

// ── Small helpers ────────────────────────────────────────────────────────────

class _SectionLabel extends StatelessWidget {
  final String text;
  const _SectionLabel(this.text);

  @override
  Widget build(BuildContext context) {
    return Text(
      text,
      style: GoogleFonts.inter(
        fontSize: 14,
        fontWeight: FontWeight.w600,
        color: AppTheme.brandPrimary,
      ),
    );
  }
}

/// Short contextual hint shown below the tag-type dropdown.
class _TagTypeHint extends StatelessWidget {
  final BleTagType type;
  const _TagTypeHint({required this.type});

  @override
  Widget build(BuildContext context) {
    final String hint;
    final IconData icon;

    switch (type) {
      case BleTagType.series2:
        hint = 'Series 2: For newer devices.';
        icon = Icons.verified_outlined;
        break;
      case BleTagType.series1:
        hint = 'Series 1: For legacy devices.';
        icon = Icons.info_outline;
        break;
    }

    return Row(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        Icon(icon, size: 15, color: Colors.grey.shade500),
        const SizedBox(width: 6),
        Expanded(
          child: Text(
            hint,
            style: GoogleFonts.inter(
              fontSize: 12,
              color: Colors.grey.shade600,
              height: 1.5,
            ),
          ),
        ),
      ],
    );
  }
}
