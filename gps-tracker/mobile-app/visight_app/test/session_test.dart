import 'dart:convert';

import 'package:flutter/material.dart';
import 'package:flutter_secure_storage/flutter_secure_storage.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';
import 'package:visight_app/api/api_client.dart';
import 'package:visight_app/api/models.dart';
import 'package:visight_app/screens/login_screen.dart';
import 'package:visight_app/session.dart';
import 'package:visight_app/widgets/common.dart';

/// A backend that answers like /api/auth/login and /api/v2 for a non-admin in the "Depot A" security group.
MockClient fakeBackend({List<String>? calls, bool rejectPassword = false}) => MockClient((req) async {
      calls?.add('${req.method} ${req.url.path}');
      http.Response json(Object body, [int status = 200]) => http.Response(jsonEncode(body), status);
      if (req.url.path != '/api/auth/login' && req.headers['Authorization'] != 'Bearer tok') {
        return json({'detail': 'Missing or invalid authorization header'}, 401);
      }
      switch (req.url.path) {
        case '/api/auth/login':
          return rejectPassword
              ? json({'detail': 'Invalid email or password'}, 401)
              : json({'access_token': 'tok', 'token_type': 'bearer', 'usergroup_id': 'g', 'portal_user_id': 'u'});
        case '/api/v2/me':
          return json({
            'id': 'u', 'email': 'driver@example.com', 'first_name': 'Sam', 'last_name': 'Ndlovu', 'usergroup': 'Acme',
            'roles': ['MZone Driver'], 'permissions': ['map.view', 'live.track', 'history.view'], 'is_admin': false,
            'security_group': 'Depot A',
          });
        case '/api/v2/vehicles':
          return json([
            {'id': '2', 'imei': '222', 'name': 'LR4', 'status': 'idle', 'latitude': -26.1, 'longitude': 28.0,
                'registration': 'DH68DMZN', 'last_seen': '2026-10-22T13:06:00Z'},
            {'id': '1', 'imei': '111', 'name': 'Hyundai Elantra', 'status': 'active', 'latitude': '-26.2',
                'longitude': '28.1'},
          ]);
        case '/api/v2/fleet-status':
          return json([
            {'imei': '222', 'event': 'Ignition off', 'recorded_at': '2026-10-22T13:06:00Z', 'speed': 0,
                'ignition': false, 'odometer_km': 1234.5, 'address': 'Frere Avenue, Discovery'},
          ]);
        case '/api/v2/events':
          return json({'detail': "Your roles don't allow this (vehicle events)"}, 403);
      }
      return json({'detail': 'Not Found'}, 404);
    });

void main() {
  setUp(() => FlutterSecureStorage.setMockInitialValues({}));

  test('signs in with dashboard credentials and loads only the vehicles the API returns', () async {
    final calls = <String>[];
    final session = Session(api: ApiClient(client: fakeBackend(calls: calls)));
    await session.signIn(' driver@example.com ', 'secret');

    expect(calls.take(4), ['POST /api/auth/login', 'GET /api/v2/me', 'GET /api/v2/vehicles', 'GET /api/v2/fleet-status']);
    expect(session.me!.displayName, 'Sam Ndlovu');
    expect(session.me!.seesAllVehicles, isFalse);
    expect(session.me!.securityGroup, 'Depot A');
    expect(session.vehicles.map((v) => v.name), ['Hyundai Elantra', 'LR4']);
    expect(session.selected!.imei, '111');
    expect(session.vehicle('111')!.position!.latitude, -26.2);
    expect(session.fleet['222']!.address, 'Frere Avenue, Discovery');
    session.dispose();
  });

  test('restores the stored token and signs out when it is rejected', () async {
    FlutterSecureStorage.setMockInitialValues({'access_token': 'expired'});
    final session = Session(api: ApiClient(client: fakeBackend()));
    await session.restore();
    expect(session.signedIn, isFalse);
    expect(session.restoring, isFalse);
    session.dispose();
  });

  test('administrators see every vehicle', () {
    final me = Me.fromJson({'email': 'a@b.c', 'is_admin': true, 'permissions': [], 'roles': ['Administrator']});
    expect(me.seesAllVehicles, isTrue);
    expect(Me.fromJson({'email': 'a@b.c', 'permissions': ['security.all_vehicles']}).seesAllVehicles, isTrue);
  });

  test('parses a trip with its route, events and exception count', () {
    final t = TripDetail.fromJson({
      'id': 't', 'imei': '111', 'status': 'closed', 'started_at': '2026-10-22T13:06:00Z',
      'ended_at': '2026-10-22T13:40:00Z', 'start': [-26.1, 28.0], 'end': null, 'distance_m': 12345,
      'duration_s': 2040, 'max_speed': 110, 'avg_speed': 45.5, 'speeding_count': 2, 'harsh_braking_count': 1,
      'points': [[-26.1, 28.0, 0, '2026-10-22T13:06:00Z'], [null, null, 0, null], [-26.2, 28.1, 60, '2026-10-22T13:10:00Z']],
      'events': [{'id': 1, 'label': 'Overspeed', 'kind': 'alert', 'recorded_at': '2026-10-22T13:08:00Z'}],
    });
    expect(t.points.length, 2);
    expect(t.exceptions, 3);
    expect(t.end, isNull);
    expect(t.events.single.label, 'Overspeed');
  });

  testWidgets('a feature the role lacks shows the role message instead of an error', (tester) async {
    final api = ApiClient(client: fakeBackend())..token = 'tok';
    await tester.pumpWidget(MaterialApp(
      home: Scaffold(body: AsyncView<dynamic>(load: () => api.get('/api/v2/events'), builder: (_, _, _) => const Text('ok'))),
    ));
    await tester.pumpAndSettle();
    expect(find.text('Not included in your role'), findsOneWidget);
    expect(find.textContaining("Your roles don't allow this (vehicle events)"), findsOneWidget);
  });

  testWidgets('login shows the backend message for a wrong password', (tester) async {
    final session = Session(api: ApiClient(client: fakeBackend(rejectPassword: true)));
    await tester.pumpWidget(SessionScope(session: session, child: const MaterialApp(home: LoginScreen())));
    await tester.enterText(find.byType(TextField).at(0), 'driver@example.com');
    await tester.enterText(find.byType(TextField).at(1), 'wrong');
    await tester.tap(find.text('Sign in'));
    await tester.pumpAndSettle();
    expect(find.text('Invalid email or password'), findsOneWidget);
    expect(session.signedIn, isFalse);
  });
}
