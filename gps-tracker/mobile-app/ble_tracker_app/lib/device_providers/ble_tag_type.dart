/// BLE tag device types supported by Pinplot.
///
/// Each value maps to a lowercase string key stored in the backend DB.
/// Add a new value here (and a matching provider) to support a new
/// device platform.
enum BleTagType {
  series2('series2', 'Series 2'),
  series1('series1', 'Series 1');

  const BleTagType(this.apiValue, this.displayName);

  /// Lowercase key sent to / received from the backend API.
  final String apiValue;

  /// User-facing label shown in dropdowns.
  final String displayName;

  static BleTagType fromApiValue(String value) {
    return BleTagType.values.firstWhere(
      (e) => e.apiValue == value.toLowerCase(),
      orElse: () => BleTagType.series1,
    );
  }
}
