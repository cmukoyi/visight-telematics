/// Decodes Pareto Anywhere–supported BLE advertisement formats.
///
/// Supported formats:
///   – iBeacon      (Apple company ID 0x004C, subtype 0x02 0x15)
///   – Eddystone UID / URL / TLM  (service UUID 0xFEAA)
///   – AltBeacon    (magic bytes 0xBE 0xAC at manufacturer data offset 2)
///
/// All decoding is purely local — no network required.
library;

import '../models/beacon_sighting_model.dart';

/// The advertisement format detected for a discovered BLE device.
enum ParetoDeviceType {
  iBeacon,
  eddystoneUid,
  eddystoneUrl,
  eddystoneTlm,
  altBeacon,
  none,
}

/// Decoded information from a Pareto Anywhere–supported advertisement.
class ParetoInfo {
  /// The detected format. [ParetoDeviceType.none] means not recognised.
  final ParetoDeviceType type;

  /// iBeacon UUID or Eddystone UID namespace (hex string).
  final String? beaconId;

  /// iBeacon major value.
  final int? major;

  /// iBeacon minor value.
  final int? minor;

  /// Eddystone URL decoded value.
  final String? url;

  /// Eddystone UID instance ID (hex string, 6 bytes).
  final String? instanceId;

  /// Calibrated TX power at 0 m (dBm).
  final int? txPower;

  /// Eddystone TLM battery voltage in millivolts (null if not TLM or not parsed).
  final int? batteryMv;

  const ParetoInfo({
    required this.type,
    this.beaconId,
    this.major,
    this.minor,
    this.url,
    this.instanceId,
    this.txPower,
    this.batteryMv,
  });

  bool get isPareto => type != ParetoDeviceType.none;

  String get typeLabel {
    switch (type) {
      case ParetoDeviceType.iBeacon:
        return 'iBeacon';
      case ParetoDeviceType.eddystoneUid:
        return 'Eddystone UID';
      case ParetoDeviceType.eddystoneUrl:
        return 'Eddystone URL';
      case ParetoDeviceType.eddystoneTlm:
        return 'Eddystone TLM';
      case ParetoDeviceType.altBeacon:
        return 'AltBeacon';
      case ParetoDeviceType.none:
        return 'Unknown';
    }
  }

  static const ParetoInfo unknown = ParetoInfo(type: ParetoDeviceType.none);
}

/// Stateless decoder — call [ParetoDecoder.decode] with a [DiscoveredBeacon].
class ParetoDecoder {
  const ParetoDecoder._();

  static const int _appleCompanyId = 0x004C;

  // Eddystone service UUID — lowercase to match how we store serviceData keys.
  static const String _eddystoneUuid =
      '0000feaa-0000-1000-8000-00805f9b34fb';

  /// Attempts to decode the advertisement data of [beacon] into a known
  /// Pareto Anywhere–supported format.
  ///
  /// Returns [ParetoInfo.unknown] if no known format is matched.
  static ParetoInfo decode(DiscoveredBeacon beacon) {
    // 1 ─ iBeacon (Apple company ID 0x004C)
    final appleData = beacon.manufacturerData[_appleCompanyId];
    if (appleData != null && appleData.length >= 23) {
      if (appleData[0] == 0x02 && appleData[1] == 0x15) {
        return _decodeIBeacon(appleData);
      }
    }

    // 2 ─ Eddystone (service UUID 0xFEAA)
    final eddystoneData = beacon.serviceData[_eddystoneUuid];
    if (eddystoneData != null && eddystoneData.isNotEmpty) {
      return _decodeEddystone(eddystoneData);
    }

    // 3 ─ AltBeacon: magic bytes 0xBE 0xAC at offset 2 inside manufacturer data.
    for (final data in beacon.manufacturerData.values) {
      if (data.length >= 4 && data[2] == 0xBE && data[3] == 0xAC) {
        return const ParetoInfo(type: ParetoDeviceType.altBeacon);
      }
    }

    return ParetoInfo.unknown;
  }

  // ── Private helpers ──────────────────────────────────────────────────────

  static ParetoInfo _decodeIBeacon(List<int> data) {
    // Layout after company ID:
    //   [0]     = 0x02  (iBeacon subtype)
    //   [1]     = 0x15  (length = 21)
    //   [2..17] = 16-byte UUID  (big-endian)
    //   [18..19]= major          (big-endian)
    //   [20..21]= minor          (big-endian)
    //   [22]    = TX power       (signed int8, dBm at 1 m)
    final uuid = _formatUuid(data.sublist(2, 18));
    final major = (data[18] << 8) | data[19];
    final minor = (data[20] << 8) | data[21];
    final txPower = data[22].toSigned(8);
    return ParetoInfo(
      type: ParetoDeviceType.iBeacon,
      beaconId: uuid,
      major: major,
      minor: minor,
      txPower: txPower,
    );
  }

  static ParetoInfo _decodeEddystone(List<int> data) {
    if (data.isEmpty) return ParetoInfo.unknown;
    final frameType = data[0];

    switch (frameType) {
      case 0x00: // Eddystone-UID
        if (data.length < 18) return ParetoInfo.unknown;
        return ParetoInfo(
          type: ParetoDeviceType.eddystoneUid,
          txPower: data[1].toSigned(8),
          beaconId: _bytesToHex(data.sublist(2, 12)),   // 10-byte namespace
          instanceId: _bytesToHex(data.sublist(12, 18)), // 6-byte instance
        );

      case 0x10: // Eddystone-URL
        if (data.length < 4) return ParetoInfo.unknown;
        return ParetoInfo(
          type: ParetoDeviceType.eddystoneUrl,
          txPower: data[1].toSigned(8),
          url: _decodeEddystoneUrl(data[2], data.sublist(3)),
        );

      case 0x20: // Eddystone-TLM
        // Layout: [0]=0x20 [1]=version [2-3]=battery mV (uint16 BE) [4-5]=temp [6-9]=adv count
        final batt = data.length >= 4 ? ((data[2] << 8) | data[3]) : null;
        return ParetoInfo(type: ParetoDeviceType.eddystoneTlm, batteryMv: batt);

      default:
        return ParetoInfo.unknown;
    }
  }

  /// Formats 16 raw bytes as a standard UUID string (8-4-4-4-12).
  static String _formatUuid(List<int> bytes) {
    final h = _bytesToHex(bytes);
    return '${h.substring(0, 8)}-${h.substring(8, 12)}'
        '-${h.substring(12, 16)}-${h.substring(16, 20)}-${h.substring(20)}';
  }

  static String _bytesToHex(List<int> bytes) =>
      bytes.map((b) => b.toRadixString(16).padLeft(2, '0')).join();

  static String _decodeEddystoneUrl(int scheme, List<int> encoded) {
    const prefixes = [
      'http://www.',
      'https://www.',
      'http://',
      'https://',
    ];
    const expansions = {
      0x00: '.com/', 0x01: '.org/', 0x02: '.edu/', 0x03: '.net/',
      0x04: '.info/', 0x05: '.biz/', 0x06: '.gov/',
      0x07: '.com', 0x08: '.org', 0x09: '.edu', 0x0A: '.net',
      0x0B: '.info', 0x0C: '.biz', 0x0D: '.gov',
    };

    final prefix = scheme < prefixes.length ? prefixes[scheme] : '';
    final sb = StringBuffer(prefix);
    for (final byte in encoded) {
      if (expansions.containsKey(byte)) {
        sb.write(expansions[byte]);
      } else {
        sb.writeCharCode(byte);
      }
    }
    return sb.toString();
  }
}
