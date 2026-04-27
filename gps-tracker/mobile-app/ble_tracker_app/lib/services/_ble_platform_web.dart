import '../models/beacon_sighting_model.dart';

/// Web stub — BLE scanning is not supported in browsers.
/// All methods are safe no-ops so the web build compiles cleanly.
class BlePlatform {
  const BlePlatform();

  bool get isAvailable => false;

  Future<void> startScan({required Duration timeout}) =>
      Future.error(UnsupportedError('BLE scanning is not available on web.'));

  Future<void> stopScan() async {}

  Stream<List<DiscoveredBeacon>> get scanResults => const Stream.empty();
}
