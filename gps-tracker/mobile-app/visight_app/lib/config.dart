/// Build-time settings. Point a debug build at a local backend with
/// `flutter run --dart-define=API_BASE_URL=http://10.0.2.2:8001`.
class Config {
  static const apiBaseUrl = String.fromEnvironment('API_BASE_URL', defaultValue: 'https://track.visighttelematics.co.za');

  /// Same OpenStreetMap tiles as the customer dashboard's default map.
  static const tileUrl = 'https://tile.openstreetmap.org/{z}/{x}/{y}.png';
  static const userAgentPackage = 'za.co.visighttelematics.visight_app';
}
