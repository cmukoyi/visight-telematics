/// BLE tag provider factory (Factory Pattern).
///
/// Maps [BleTagType] values to concrete [BleTagProvider] instances.
/// To add a new device type:
///   1. Add the value to [BleTagType].
///   2. Create a new provider class implementing [BleTagProvider].
///   3. Add one case here.
///   Nothing else in the app needs changing.
import 'ble_tag_type.dart';
import 'ble_tag_provider.dart';
import 'tracksolid_provider.dart';
import 'scope_provider.dart';
import '../services/auth_service.dart';

class BleTagProviderFactory {
  /// Returns the correct provider for [type].
  static BleTagProvider getProvider(BleTagType type, AuthService authService) {
    switch (type) {
      case BleTagType.series2:
        return TrackSolidTagProvider(authService);
      case BleTagType.series1:
        return ScopeTagProvider(authService);
    }
  }

  /// All supported tag types for display in dropdown menus.
  static List<BleTagType> get supportedTypes => BleTagType.values;
}
