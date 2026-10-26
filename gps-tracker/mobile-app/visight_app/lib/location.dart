import 'package:geolocator/geolocator.dart';

/// The phone's position for a breakdown record, or null when location is off,
/// not allowed or too slow (the breakdown is still logged, without it).
Future<Position?> currentPosition() async {
  try {
    if (!await Geolocator.isLocationServiceEnabled()) return null;
    var permission = await Geolocator.checkPermission();
    if (permission == LocationPermission.denied) permission = await Geolocator.requestPermission();
    if (permission == LocationPermission.denied || permission == LocationPermission.deniedForever) return null;
    return await Geolocator.getCurrentPosition(
        locationSettings: const LocationSettings(accuracy: LocationAccuracy.high, timeLimit: Duration(seconds: 12)));
  } catch (_) {
    return Geolocator.getLastKnownPosition().catchError((_) => null);
  }
}

/// {latitude, longitude, accuracy} for the API (empty without a position).
Map<String, Object> positionJson(Position? p) =>
    p == null ? {} : {'latitude': p.latitude, 'longitude': p.longitude, 'accuracy': p.accuracy};
