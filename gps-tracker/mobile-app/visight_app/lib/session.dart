import 'dart:async';

import 'package:flutter/widgets.dart';
import 'package:flutter_secure_storage/flutter_secure_storage.dart';

import 'api/api_client.dart';
import 'api/models.dart';

/// The signed-in user, the vehicles their security group lets them see, and
/// which tab and vehicle the app is showing.
///
/// Users sign in with their customer-dashboard login; the backend scopes every
/// answer to their security group (administrators see every vehicle).
class Session extends ChangeNotifier {
  Session({ApiClient? api, FlutterSecureStorage? storage})
      : api = api ?? ApiClient(),
        _storage = storage ?? const FlutterSecureStorage() {
    // Only once signed in: a stored token rejected during restore() is cleaned up there.
    this.api.onUnauthorized = () {
      if (signedIn) signOut(expired: true);
    };
  }

  static const _tokenKey = 'access_token';
  static const tabHome = 0, tabMap = 1, tabTrips = 2, tabAssets = 3;

  final ApiClient api;
  final FlutterSecureStorage _storage;
  Timer? _poll;

  bool restoring = true;
  Me? me;
  List<Vehicle> vehicles = const [];
  Map<String, FleetStatus> fleet = const {};
  String? selectedImei;
  String? vehiclesError;
  String? signedOutMessage;

  /// The bottom-navigation tab, and the vehicle the Trips tab is filtered to (null = all).
  final tab = ValueNotifier<int>(tabHome);
  final tripsImei = ValueNotifier<String?>(null);

  /// Set to a vehicle's IMEI to have the Map tab follow it live.
  final follow = ValueNotifier<String?>(null);

  bool get signedIn => me != null;

  Vehicle? get selected {
    for (final v in vehicles) {
      if (v.imei == selectedImei) return v;
    }
    return vehicles.isEmpty ? null : vehicles.first;
  }

  Vehicle? vehicle(String imei) {
    for (final v in vehicles) {
      if (v.imei == imei) return v;
    }
    return null;
  }

  /// Sign back in with the stored token, if it's still valid.
  Future<void> restore() async {
    try {
      api.token = await _storage.read(key: _tokenKey);
      if (api.token != null) await _loadUser();
    } catch (_) {
      api.token = null;
      me = null;
      await _storage.delete(key: _tokenKey);
    }
    restoring = false;
    notifyListeners();
  }

  Future<void> signIn(String email, String password) async {
    final res = await api.post('/api/auth/login', {'email': email.trim(), 'password': password});
    api.token = res['access_token'];
    await _storage.write(key: _tokenKey, value: api.token);
    await _loadUser();
    signedOutMessage = null;
    tab.value = tabHome;
    notifyListeners();
  }

  Future<void> signOut({bool expired = false}) async {
    _poll?.cancel();
    api.token = null;
    me = null;
    vehicles = const [];
    fleet = const {};
    selectedImei = null;
    tripsImei.value = null;
    follow.value = null;
    signedOutMessage = expired ? 'Your session has ended. Please sign in again.' : null;
    await _storage.delete(key: _tokenKey);
    notifyListeners();
  }

  Future<void> _loadUser() async {
    me = Me.fromJson(await api.get('/api/v2/me'));
    await refreshVehicles();
    _poll?.cancel();
    _poll = Timer.periodic(const Duration(seconds: 30), (_) => refreshVehicles());
  }

  /// Vehicles and their latest addresses. Fleet status needs "Live map" or
  /// "Trips and routes"; without it the vehicles still show, without addresses.
  Future<void> refreshVehicles() async {
    if (api.token == null) return;
    try {
      final rows = await api.get('/api/v2/vehicles') as List;
      vehicles = [for (final r in rows) Vehicle.fromJson(r)]..sort((a, b) => a.name.compareTo(b.name));
      vehiclesError = null;
      if (selectedImei == null || vehicle(selectedImei!) == null) {
        selectedImei = vehicles.isEmpty ? null : vehicles.first.imei;
      }
    } on ApiException catch (e) {
      if (e.isUnauthorized) return;
      vehiclesError = e.message;
    }
    try {
      final rows = await api.get('/api/v2/fleet-status') as List;
      fleet = {for (final r in rows) r['imei'] as String: FleetStatus.fromJson(r)};
    } on ApiException catch (_) {
      fleet = const {};
    }
    notifyListeners();
  }

  void select(String imei) {
    if (selectedImei == imei) return;
    selectedImei = imei;
    notifyListeners();
  }

  /// Open the Map tab on this vehicle.
  void showOnMap(String imei) {
    select(imei);
    tab.value = tabMap;
  }

  /// Open the Map tab following this vehicle live.
  void followLive(String imei) {
    showOnMap(imei);
    follow.value = imei;
  }

  /// Open the Trips tab filtered to this vehicle.
  void showTrips(String imei) {
    tripsImei.value = imei;
    tab.value = tabTrips;
  }

  @override
  void dispose() {
    _poll?.cancel();
    tab.dispose();
    tripsImei.dispose();
    follow.dispose();
    super.dispose();
  }
}

/// Makes the [Session] available to the widget tree and rebuilds dependants when it changes.
class SessionScope extends InheritedNotifier<Session> {
  const SessionScope({super.key, required Session session, required super.child}) : super(notifier: session);

  static Session of(BuildContext context) => context.dependOnInheritedWidgetOfExactType<SessionScope>()!.notifier!;

  /// The session without subscribing to its changes (for callbacks).
  static Session read(BuildContext context) => context.getInheritedWidgetOfExactType<SessionScope>()!.notifier!;
}
