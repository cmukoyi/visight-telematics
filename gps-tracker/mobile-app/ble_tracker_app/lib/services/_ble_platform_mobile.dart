import 'package:flutter_blue_plus/flutter_blue_plus.dart';
import '../models/beacon_sighting_model.dart';

/// Mobile (Android / iOS) BLE implementation backed by flutter_blue_plus.
///
/// All BLE interactions go through this class so that [BLEScanService]
/// never imports flutter_blue_plus directly — keeping the web build clean.
class BlePlatform {
  const BlePlatform();

  bool get isAvailable => true;

  Future<void> startScan({required Duration timeout}) =>
      FlutterBluePlus.startScan(
        timeout: timeout,
        androidUsesFineLocation: true,
      );

  Future<void> stopScan() => FlutterBluePlus.stopScan();

  /// Maps raw flutter_blue_plus ScanResults to our domain model.
  Stream<List<DiscoveredBeacon>> get scanResults =>
      FlutterBluePlus.scanResults.map(
        (results) => results
            .map(
              (r) => DiscoveredBeacon(
                id: r.device.remoteId.str,
                name: r.device.platformName.isNotEmpty
                    ? r.device.platformName
                    : null,
                rssi: r.rssi,
                lastSeen: DateTime.now(),
                manufacturerData: r.advertisementData.manufacturerData,
                serviceData: {
                  for (final e in r.advertisementData.serviceData.entries)
                    e.key.toString().toLowerCase(): e.value,
                },
              ),
            )
            .toList(),
      );
}
