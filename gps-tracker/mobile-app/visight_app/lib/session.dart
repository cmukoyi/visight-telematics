import 'dart:async';

import 'package:flutter/widgets.dart';
import 'package:flutter_secure_storage/flutter_secure_storage.dart';

import 'api/api_client.dart';
import 'app_log.dart';
import 'api/models.dart';
import 'device_lock.dart';

/// The signed-in user, the vehicles their security group lets them see, and
/// which tab and vehicle the app is showing.
///
/// Users sign in with their customer-dashboard login; the backend scopes every
/// answer to their security group (administrators see every vehicle).
class Session extends ChangeNotifier {
  Session({ApiClient? api, FlutterSecureStorage? storage, DeviceLock? deviceLock})
      : api = api ?? ApiClient(),
        deviceLock = deviceLock ?? DeviceLock(),
        _storage = storage ?? const FlutterSecureStorage() {
    // Only once signed in: a stored token rejected during restore() is cleaned up there.
    this.api.onUnauthorized = () {
      if (signedIn) signOut(expired: true);
    };
    this.api.onTokenRenewed = () => _storage.write(key: _tokenKey, value: this.api.token);
  }

  static const _tokenKey = 'access_token', _refreshKey = 'refresh_token', _lockKey = 'device_lock';
  static const tabHome = 0, tabMap = 1, tabTrips = 2, tabAssets = 3;

  /// How long the app can be in the background before it asks to be unlocked again.
  static const lockAfter = Duration(minutes: 5);

  final ApiClient api;
  final DeviceLock deviceLock;
  final FlutterSecureStorage _storage;
  Timer? _poll;
  DateTime? _backgroundedAt;
  bool _confirming = false;

  bool restoring = true;
  Me? me;
  List<Vehicle> vehicles = const [];
  Map<String, FleetStatus> fleet = const {};
  String? selectedImei;
  String? vehiclesError;
  String? signedOutMessage;

  /// Couldn't check the stored sign-in because the server wasn't reachable; it's kept for another try.
  String? restoreError;

  /// The user chose to open the app with their fingerprint, face or phone PIN.
  bool lockEnabled = false;

  /// The app is covered until the phone's owner unlocks it.
  bool locked = false;

  /// Just signed in on a phone that could use the lock: suggest it once.
  bool offerLock = false;

  /// Called when the user is signed out, to close any screens open on top of the login.
  void Function()? onSignedOut;

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
    restoring = true;
    restoreError = null;
    notifyListeners();
    try {
      api.token = await _storage.read(key: _tokenKey);
      api.refreshToken = await _storage.read(key: _refreshKey);
      lockEnabled = await _storage.read(key: _lockKey) == '1';
      if (api.token != null) await _loadUser();
      locked = lockEnabled && signedIn;
    } on ApiException catch (e) {
      if (e.status == 0 || e.status >= 500) {
        restoreError = e.message; // no answer about the token, so keep it: no signal is no reason to sign out
      } else {
        await _forget();
      }
    } catch (_) {
      await _forget();
    }
    restoring = false;
    notifyListeners();
  }

  Future<void> _forget() async {
    api.token = api.refreshToken = null;
    me = null;
    lockEnabled = locked = offerLock = false;
    await _storage.delete(key: _tokenKey);
    await _storage.delete(key: _refreshKey);
    await _storage.delete(key: _lockKey);
  }

  Future<void> signIn(String email, String password) async {
    final res = await api.post('/api/auth/login', {'email': email.trim(), 'password': password, 'remember_device': true});
    api.token = res['access_token'];
    api.refreshToken = res['refresh_token'];
    await _storage.write(key: _tokenKey, value: api.token);
    await _storage.write(key: _refreshKey, value: api.refreshToken);
    await _loadUser();
    signedOutMessage = null;
    restoreError = null;
    offerLock = await deviceLock.available();
    tab.value = tabHome;
    notifyListeners();
  }

  Future<void> signOut({bool expired = false}) async {
    AppLog.info(expired ? 'Session ended (token rejected)' : 'Signed out');
    _poll?.cancel();
    final device = api.refreshToken;
    await _forget();
    onSignedOut?.call();
    // Best effort: a phone with no signal just leaves the token to expire
    if (device != null && !expired) {
      unawaited(api.post('/api/auth/logout', {'refresh_token': device}).then<void>((_) {}, onError: (_) {}));
    }
    restoreError = null;
    vehicles = const [];
    fleet = const {};
    selectedImei = null;
    tripsImei.value = null;
    follow.value = null;
    signedOutMessage = expired ? 'Your session has ended. Please sign in again.' : null;
    notifyListeners();
  }

  /// Ask for the fingerprint, face or phone PIN. Returns why it didn't unlock, or null if it did.
  Future<String?> unlock() async {
    if (_confirming) return null;
    _confirming = true;
    try {
      final problem = await deviceLock.confirm('Unlock ViSight Track');
      if (problem == null) {
        locked = false;
        notifyListeners();
      }
      return problem;
    } finally {
      _confirming = false;
    }
  }

  /// Turn the lock on (once the user has proved it works on this phone) or off. Returns why not, or null.
  Future<String?> setLockEnabled(bool on) async {
    if (on) {
      if (_confirming) return null;
      _confirming = true;
      try {
        final problem = await deviceLock.confirm('Confirm it is you to turn on the lock');
        if (problem != null) return problem;
      } finally {
        _confirming = false;
      }
    }
    lockEnabled = on;
    await _storage.write(key: _lockKey, value: on ? '1' : null);
    AppLog.info('Device lock ${on ? 'on' : 'off'}');
    notifyListeners();
    return null;
  }

  /// Lock again when the app comes back after [lockAfter] in the background. The system's own
  /// fingerprint prompt can pause the app too; that doesn't count.
  void appStateChanged(AppLifecycleState state, {DateTime? now}) {
    if (_confirming) return;
    final at = now ?? DateTime.now();
    if (state == AppLifecycleState.paused) {
      _backgroundedAt ??= at;
    } else if (state == AppLifecycleState.resumed) {
      final since = _backgroundedAt;
      _backgroundedAt = null;
      if (lockEnabled && signedIn && since != null && at.difference(since) >= lockAfter) {
        locked = true;
        notifyListeners();
      }
    }
  }

  Future<void> _loadUser() async {
    me = Me.fromJson(await api.get('/api/v2/me'));
    AppLog.info('Signed in as ${me!.email} (${me!.usergroup ?? '-'}; roles: ${me!.roles.join(', ')})');
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
