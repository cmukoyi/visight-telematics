/// TrackSolid BLE tag provider.
///
/// Delegates validation to the Pinplot backend, which holds the TrackSolid
/// credentials server-side. The backend calls TrackSolid's EU API, reusing
/// its cached JWT (valid 1 hour) to avoid rate-limit bans.
import '../device_providers/ble_tag_type.dart';
import '../device_providers/ble_tag_provider.dart';
import '../services/auth_service.dart';

class TrackSolidTagProvider implements BleTagProvider {
  final AuthService _authService;

  TrackSolidTagProvider(this._authService);

  @override
  BleTagType get tagType => BleTagType.series2;

  @override
  String get displayName => 'Series 2';

  @override
  Future<TagValidationResult> validateTag(String imei) async {
    final result =
        await _authService.validateTagByType(imei, BleTagType.series2.apiValue);
    return TagValidationResult(
      isValid: result['is_valid'] as bool,
      message: result['message'] as String,
      batteryLevel: result['battery_level'] as int?,
    );
  }
}
