/// Strategy interface for BLE tag provider implementations.
///
/// Each supported vendor (TrackSolid, Scope, …) implements this abstract
/// class. The rest of the app only depends on this interface — never on
/// concrete providers — keeping the Add-Tag screen and auth service
/// completely decoupled from vendor-specific logic.
import 'ble_tag_type.dart';

/// Result returned by [BleTagProvider.validateTag].
class TagValidationResult {
  final bool isValid;
  final String message;
  /// Battery level 0–100 returned by TrackSolid on successful validation, null for other providers.
  final int? batteryLevel;

  const TagValidationResult({
    required this.isValid,
    required this.message,
    this.batteryLevel,
  });
}

/// Abstract Strategy: one implementation per supported tag/device type.
abstract class BleTagProvider {
  BleTagType get tagType;
  String get displayName;

  /// Validate *imei* on the vendor platform.  
  /// Returns [TagValidationResult] with a user-facing message.
  Future<TagValidationResult> validateTag(String imei);
}
