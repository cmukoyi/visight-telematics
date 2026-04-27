// Conditional export: real BLE on mobile/desktop, no-op stub on web.
export '_ble_platform_mobile.dart'
    if (dart.library.html) '_ble_platform_web.dart';
