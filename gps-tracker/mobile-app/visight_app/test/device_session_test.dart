import 'dart:async';
import 'dart:convert';
import 'dart:io';

import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:flutter_secure_storage/flutter_secure_storage.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';
import 'package:visight_app/api/api_client.dart';
import 'package:visight_app/device_lock.dart';
import 'package:visight_app/main.dart';
import 'package:visight_app/screens/lock_screen.dart';
import 'package:visight_app/screens/login_screen.dart';
import 'package:visight_app/session.dart';

/// The phone's lock: says yes, or [problem] when set.
class FakeLock implements DeviceLock {
  String? problem;
  bool supported = true;
  int asked = 0;

  @override
  Future<bool> available() async => supported;

  @override
  Future<String?> confirm(String reason) async {
    asked++;
    return problem;
  }
}

/// A backend whose access tokens can expire: only [valid] is accepted, and /refresh hands out the next one.
class Backend {
  String valid = 'tok1';
  int renewals = 0;
  http.Response? refreshAnswer; // set to make POST /api/auth/refresh fail this way
  bool offline = false;
  final calls = <String>[];
  final bodies = <String, Object?>{};

  static http.Response json(Object body, [int status = 200]) => http.Response(jsonEncode(body), status);

  late final client = MockClient((req) async {
    if (offline) throw http.ClientException('Failed host lookup');
    final path = req.url.path;
    calls.add('${req.method} $path');
    if (req.body.isNotEmpty) bodies[path] = jsonDecode(req.body);
    if (path == '/api/auth/login') {
      return json({'access_token': valid, 'refresh_token': 'device', 'usergroup_id': 'g', 'portal_user_id': 'u'});
    }
    if (path == '/api/auth/logout') return http.Response('', 204);
    if (path == '/api/auth/refresh') {
      if (refreshAnswer != null) return refreshAnswer!;
      renewals++;
      valid = 'tok${renewals + 1}';
      return json({'access_token': valid, 'usergroup_id': 'g', 'portal_user_id': 'u'});
    }
    final auth = req.headers['Authorization'];
    if (auth == null) return json({'detail': 'Missing or invalid authorization header'}, 401);
    if (auth != 'Bearer $valid') return json({'detail': 'Invalid or expired token'}, 401);
    return switch (path) {
      '/api/v2/me' => json({
          'id': 'u', 'email': 'driver@example.com', 'first_name': 'Sam', 'last_name': 'N', 'usergroup': 'Acme',
          'roles': ['Driver'], 'permissions': <String>[], 'is_admin': false,
        }),
      '/api/v2/vehicles' || '/api/v2/fleet-status' => json([]),
      _ => json({'ok': true}),
    };
  });

  void expireToken() => valid = 'server-only';
}

Session sessionFor(Backend b, {FakeLock? lock}) => Session(api: ApiClient(client: b.client), deviceLock: lock ?? FakeLock());

/// Stands in for the breakdown screen: a page pushed over the tabs, calling the API from a button.
Widget endBreakdownPage(Session session, List<String> errors) => Scaffold(
      body: TextButton(
        onPressed: () async {
          try {
            await session.api.post('/api/portal/breakdowns/1/resolve', {});
            errors.add('resolved');
          } on ApiException catch (e) {
            errors.add(e.message);
          }
        },
        child: const Text('End breakdown'),
      ),
    );

Future<NavigatorState> openPage(WidgetTester tester, Session session, List<String> out) async {
  await tester.pumpWidget(VisightApp(session: session));
  await tester.pump();
  final nav = tester.state<NavigatorState>(find.byType(Navigator).first);
  unawaited(nav.push(MaterialPageRoute(builder: (_) => endBreakdownPage(session, out))));
  await tester.pump();
  await tester.pump(const Duration(seconds: 1));
  return nav;
}

void main() {
  setUp(() {
    FlutterSecureStorage.setMockInitialValues({});
    // The Map tab's tile cache asks for a folder
    TestDefaultBinaryMessengerBinding.instance.defaultBinaryMessenger.setMockMethodCallHandler(
        const MethodChannel('plugins.flutter.io/path_provider'), (_) async => Directory.systemTemp.path);
  });

  test('asks for a device token and keeps it', () async {
    final b = Backend(), session = sessionFor(b);
    await session.signIn('driver@example.com', 'secret');
    expect((b.bodies['/api/auth/login'] as Map)['remember_device'], true);
    expect(await const FlutterSecureStorage().read(key: 'refresh_token'), 'device');
    session.dispose();
  });

  test('an expired token is renewed and the request goes through, without signing out', () async {
    final b = Backend(), session = sessionFor(b);
    await session.signIn('driver@example.com', 'secret');
    b.expireToken();
    await session.api.post('/api/portal/breakdowns/1/resolve', {});

    expect(b.renewals, 1);
    expect(b.calls.where((c) => c.endsWith('/resolve')), hasLength(2));
    expect(session.signedIn, isTrue);
    expect(await const FlutterSecureStorage().read(key: 'access_token'), session.api.token);
    session.dispose();
  });

  test('requests refused together share one renewal', () async {
    final b = Backend(), session = sessionFor(b);
    await session.signIn('driver@example.com', 'secret');
    b.expireToken();
    await Future.wait([for (var i = 0; i < 4; i++) session.api.get('/api/v2/vehicles')]);
    expect(b.renewals, 1);
    session.dispose();
  });

  test('no signal or a server error while renewing does not sign out', () async {
    final b = Backend(), session = sessionFor(b);
    await session.signIn('driver@example.com', 'secret');
    b.expireToken();
    b.refreshAnswer = http.Response('<html>Bad gateway</html>', 502);
    await expectLater(session.api.post('/api/portal/breakdowns/1/resolve', {}),
        throwsA(isA<ApiException>().having((e) => e.status, 'status', 502)));
    expect(session.signedIn, isTrue);

    b.refreshAnswer = null; // and the next try works
    await session.api.post('/api/portal/breakdowns/1/resolve', {});
    expect(session.signedIn, isTrue);
    session.dispose();
  });

  test('a refused renewal ends the session and clears the phone', () async {
    final b = Backend(), session = sessionFor(b);
    await session.signIn('driver@example.com', 'secret');
    await session.setLockEnabled(true);
    b.expireToken();
    b.refreshAnswer = Backend.json({'detail': 'Please sign in again'}, 401);
    await expectLater(session.api.post('/api/portal/breakdowns/1/resolve', {}), throwsA(isA<ApiException>()));
    await pumpEventQueue();

    expect(session.signedIn, isFalse);
    expect(session.signedOutMessage, isNotNull);
    expect(session.lockEnabled, isFalse);
    for (final key in ['access_token', 'refresh_token', 'device_lock']) {
      expect(await const FlutterSecureStorage().read(key: key), isNull);
    }
    session.dispose();
  });

  test('cold start with an expired token renews it', () async {
    final b = Backend()..valid = 'current';
    FlutterSecureStorage.setMockInitialValues({'access_token': 'old', 'refresh_token': 'device'});
    final session = sessionFor(b);
    await session.restore();
    expect(session.signedIn, isTrue);
    expect(b.renewals, 1);
    session.dispose();
  });

  test('cold start with no signal keeps the sign-in and offers a retry', () async {
    FlutterSecureStorage.setMockInitialValues({'access_token': 'tok1', 'refresh_token': 'device'});
    final b = Backend()..offline = true;
    final session = sessionFor(b);
    await session.restore();
    expect(session.signedIn, isFalse);
    expect(session.restoreError, isNotNull);
    expect(await const FlutterSecureStorage().read(key: 'refresh_token'), 'device');

    b.offline = false;
    await session.restore();
    expect(session.signedIn, isTrue);
    expect(session.restoreError, isNull);
    session.dispose();
  });

  test('signing out forgets the device on the server', () async {
    final b = Backend(), session = sessionFor(b);
    await session.signIn('driver@example.com', 'secret');
    await session.signOut();
    await pumpEventQueue();
    expect((b.bodies['/api/auth/logout'] as Map)['refresh_token'], 'device');
    session.dispose();
  });

  group('lock', () {
    test('is offered after signing in only on a phone that has one', () async {
      final b = Backend();
      final yes = sessionFor(b), no = sessionFor(b, lock: FakeLock()..supported = false);
      await yes.signIn('a@b.co', 'x');
      await no.signIn('a@b.co', 'x');
      expect(yes.offerLock, isTrue);
      expect(no.offerLock, isFalse);
      yes.dispose();
      no.dispose();
    });

    test('only turns on when the phone confirms it', () async {
      final lock = FakeLock()..problem = 'Cancelled. Try again.';
      final session = sessionFor(Backend(), lock: lock);
      await session.signIn('a@b.co', 'x');
      expect(await session.setLockEnabled(true), lock.problem);
      expect(session.lockEnabled, isFalse);
      lock.problem = null;
      expect(await session.setLockEnabled(true), isNull);
      expect(session.lockEnabled, isTrue);
      expect(await const FlutterSecureStorage().read(key: 'device_lock'), '1');
      session.dispose();
    });

    test('locks on cold start and after 5 minutes away, not after a quick look at another app', () async {
      FlutterSecureStorage.setMockInitialValues({'access_token': 'tok1', 'refresh_token': 'device', 'device_lock': '1'});
      final session = sessionFor(Backend());
      await session.restore();
      expect(session.locked, isTrue);
      await session.unlock();
      expect(session.locked, isFalse);

      final t = DateTime(2026, 11, 6, 8);
      session.appStateChanged(AppLifecycleState.paused, now: t);
      session.appStateChanged(AppLifecycleState.resumed, now: t.add(const Duration(minutes: 4)));
      expect(session.locked, isFalse);

      session.appStateChanged(AppLifecycleState.paused, now: t);
      session.appStateChanged(AppLifecycleState.resumed, now: t.add(const Duration(minutes: 5)));
      expect(session.locked, isTrue);
      session.dispose();
    });

    test('the fingerprint prompt pausing the app does not lock it again', () async {
      final t = DateTime(2026, 11, 6, 8);
      late Session session;
      session = sessionFor(Backend(), lock: _PausingLock(() {
        session.appStateChanged(AppLifecycleState.paused, now: t);
        session.appStateChanged(AppLifecycleState.resumed, now: t.add(const Duration(hours: 1)));
      }));
      await session.signIn('a@b.co', 'x');
      await session.setLockEnabled(true);
      await session.unlock();
      expect(session.locked, isFalse);
      session.dispose();
    });
  });

  group('whole app', () {
    testWidgets('overnight: the breakdown screen stays up and ending it just works', (tester) async {
      final b = Backend(), out = <String>[];
      final session = sessionFor(b);
      await tester.runAsync(() => session.signIn('driver@example.com', 'secret'));
      session
        ..offerLock = false
        ..restoring = false;
      await openPage(tester, session, out);

      b.expireToken();
      await tester.runAsync(session.refreshVehicles); // the poll is the first to find it has expired
      await tester.pump();
      expect(session.signedIn, isTrue);

      await tester.tap(find.text('End breakdown'));
      await tester.runAsync(() => Future<void>.delayed(const Duration(milliseconds: 50)));
      await tester.pump();
      expect(out, ['resolved']);
      session.dispose();
    });

    testWidgets('when the session really ends, the login is shown, not a screen with no token', (tester) async {
      final b = Backend(), out = <String>[];
      final session = sessionFor(b);
      await tester.runAsync(() => session.signIn('driver@example.com', 'secret'));
      session
        ..offerLock = false
        ..restoring = false;
      await openPage(tester, session, out);
      expect(find.text('End breakdown'), findsOneWidget);

      b.expireToken();
      b.refreshAnswer = Backend.json({'detail': 'Please sign in again'}, 401);
      await tester.runAsync(() async {
        await session.refreshVehicles();
        await Future<void>.delayed(const Duration(milliseconds: 50));
      });
      await tester.pump();
      await tester.pump(const Duration(seconds: 1));

      expect(find.byType(LoginScreen), findsOneWidget);
      expect(find.text('End breakdown'), findsNothing);
      session.dispose();
    });

    testWidgets('the lock covers the open screen, asks at once, and leaves it there when unlocked', (tester) async {
      final b = Backend(), out = <String>[], lock = FakeLock();
      final session = sessionFor(b, lock: lock);
      await tester.runAsync(() => session.signIn('driver@example.com', 'secret'));
      session
        ..offerLock = false
        ..restoring = false;
      await tester.runAsync(() => session.setLockEnabled(true));
      lock
        ..asked = 0
        ..problem = 'Cancelled. Try again.';
      await openPage(tester, session, out);

      final t = DateTime(2026, 11, 6, 8);
      session.appStateChanged(AppLifecycleState.paused, now: t);
      session.appStateChanged(AppLifecycleState.resumed, now: t.add(const Duration(hours: 10)));
      await tester.pump();
      await tester.pump();
      expect(find.byType(LockScreen), findsOneWidget);
      expect(lock.asked, 1);
      expect(find.text('Cancelled. Try again.'), findsOneWidget);

      await tester.tap(find.text('End breakdown'), warnIfMissed: false);
      await tester.pump();
      expect(out, isEmpty, reason: 'nothing behind the lock can be touched');
      expect(await tester.binding.handlePopRoute(), isTrue);
      await tester.pump();
      expect(find.text('End breakdown', skipOffstage: false), findsOneWidget, reason: 'back must not pop the screen behind');

      lock.problem = null;
      await tester.tap(find.text('Unlock'));
      await tester.pump();
      await tester.pump();
      expect(find.byType(LockScreen), findsNothing);
      expect(find.text('End breakdown'), findsOneWidget);
      session.dispose();
    });
  });
}

/// A prompt that pauses and resumes the app while it is up, as some phones do.
class _PausingLock extends FakeLock {
  _PausingLock(this.whileAsking);
  final void Function() whileAsking;

  @override
  Future<String?> confirm(String reason) async {
    whileAsking();
    return null;
  }
}
