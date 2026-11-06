import 'package:flutter/services.dart';
import 'package:local_auth/local_auth.dart';

import 'app_log.dart';

/// The phone's own lock: its fingerprint or face, falling back to its PIN, pattern or password, so a
/// driver with dirty hands isn't locked out. A lock on the app, not on its tokens: the access token
/// still renews behind it, and the phone's encrypted storage is what protects them.
class DeviceLock {
  DeviceLock({LocalAuthentication? auth}) : _auth = auth ?? LocalAuthentication();

  final LocalAuthentication _auth;

  /// Whether this phone has a fingerprint, face or screen lock to ask for.
  Future<bool> available() async {
    try {
      return await _auth.isDeviceSupported();
    } on Exception catch (e) {
      AppLog.warn('Device lock unavailable: $e');
      return false;
    }
  }

  /// Ask the phone's owner to confirm. Returns why they couldn't, or null if they did.
  Future<String?> confirm(String reason) async {
    try {
      return await _auth.authenticate(localizedReason: reason) ? null : 'Not recognised. Try again.';
    } on LocalAuthException catch (e) {
      AppLog.warn('Device lock: ${e.code.name}');
      return switch (e.code) {
        LocalAuthExceptionCode.userCanceled ||
        LocalAuthExceptionCode.systemCanceled ||
        LocalAuthExceptionCode.timeout =>
          'Cancelled. Try again.',
        LocalAuthExceptionCode.temporaryLockout ||
        LocalAuthExceptionCode.biometricLockout =>
          'Too many tries. Wait a moment, then use your phone PIN.',
        LocalAuthExceptionCode.noCredentialsSet ||
        LocalAuthExceptionCode.noBiometricsEnrolled ||
        LocalAuthExceptionCode.noBiometricHardware =>
          'This phone has no fingerprint, face or screen lock set up.',
        _ => "Couldn't check that. Try again.",
      };
    } on PlatformException catch (e) {
      AppLog.warn('Device lock: ${e.code}');
      return "Couldn't check that. Try again.";
    }
  }
}
