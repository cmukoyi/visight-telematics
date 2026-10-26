import 'dart:convert';

import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';
import 'package:visight_app/api/api_client.dart';
import 'package:visight_app/api/models.dart';
import 'package:visight_app/screens/breakdown_screen.dart';
import 'package:visight_app/session.dart';

void main() {
  test('the breakdown clock shows hours, minutes and seconds', () {
    expect(fmtClock(const Duration(seconds: 0)), '00:00:00');
    expect(fmtClock(const Duration(hours: 2, minutes: 41, seconds: 7)), '02:41:07');
    expect(fmtClock(const Duration(hours: 26, seconds: 5)), '26:00:05');
    expect(fmtClock(const Duration(seconds: -3)), '00:00:00');
  });

  test('a breakdown from the API, active then resolved', () {
    final active = Breakdown.fromJson({
      'id': 'b1', 'imei': '861', 'vehicle': 'Jeep Compass', 'cause': 'Engine', 'reported_by': 'Sipho',
      'started_at': '2026-10-26T08:00:00+00:00', 'ended_at': null, 'downtime_s': 120,
      'phases': [
        {'phase': 'Waiting for dispatch', 'at': '2026-10-26T08:01:00+00:00'},
        {'phase': 'Mechanic en route', 'at': '2026-10-26T08:20:00+00:00'},
      ],
    });
    expect(active.isActive, isTrue);
    expect(active.currentPhase, 'Mechanic en route');
    expect(active.phases.first.at.isBefore(active.phases.last.at), isTrue);

    final done = Breakdown.fromJson({
      'id': 'b1', 'imei': '861', 'started_at': '2026-10-26T08:00:00+00:00', 'ended_at': '2026-10-26T09:30:00+00:00',
      'downtime_s': 5400, 'phases': [],
    });
    expect(done.isActive, isFalse);
    expect(done.vehicle, '861');
    expect(done.currentPhase, isNull);
    expect(fmtClock(Duration(seconds: done.downtimeS)), '01:30:00');
  });

  testWidgets('start the timer, log a phase and resolve the breakdown', (tester) async {
    final calls = <String>[];
    final session = Session(api: ApiClient(client: breakdownBackend(calls)));
    final vehicle = Vehicle.fromJson({'id': '2', 'imei': '222', 'name': 'LR4', 'registration': 'DH68DMZN'});
    // The clock ticks every second, so the screen never "settles": let the requests finish, then draw
    Future<void> settle() async {
      for (var i = 0; i < 8; i++) {
        await tester.runAsync(() => Future<void>.delayed(const Duration(milliseconds: 20)));
        await tester.pump(const Duration(milliseconds: 100));
      }
    }

    await tester.pumpWidget(SessionScope(
        session: session, child: MaterialApp(home: BreakdownScreen(vehicle: vehicle))));

    await tester.tap(find.text('Engine'));
    await tester.tap(find.text('Start breakdown timer'));
    await settle();
    expect(calls, contains('POST /api/portal/breakdowns'));
    expect(find.text('Breakdown time'), findsOneWidget);
    expect(find.textContaining('00:03:'), findsOneWidget);   // the clock counts from the server's start time

    await tester.tap(find.text('Mechanic en route'));
    await settle();
    expect(calls, contains('POST /api/portal/breakdowns/b1/phases'));
    await tester.scrollUntilVisible(find.text('Timeline'), 200);
    expect(find.text('Timeline'), findsOneWidget);

    await tester.scrollUntilVisible(find.text('End breakdown / Resolve'), 200);
    await tester.tap(find.text('End breakdown / Resolve'));
    await settle();
    await tester.enterText(find.byType(TextField), 'Fan belt');
    await tester.tap(find.text('End breakdown / Resolved'));
    await settle();
    expect(calls, contains('POST /api/portal/breakdowns/b1/resolve'));
    expect(find.text('Total downtime'), findsOneWidget);
    expect(find.text('Fan belt'), findsOneWidget);
    session.dispose();
  });
}

/// A backend that keeps one breakdown, like /api/portal/breakdowns.
MockClient breakdownBackend(List<String> calls) {
  Map<String, dynamic>? b;
  return MockClient((req) async {
    calls.add('${req.method} ${req.url.path}');
    http.Response json(Object? body, [int status = 200]) => http.Response(jsonEncode(body), status);
    final body = req.body.isEmpty ? <String, dynamic>{} : jsonDecode(req.body) as Map<String, dynamic>;
    final now = DateTime.now().toUtc().toIso8601String();
    switch ((req.method, req.url.path)) {
      case ('POST', '/api/portal/breakdowns'):
        b = {'id': 'b1', 'imei': body['imei'], 'vehicle': 'LR4', 'cause': body['cause'],
             'started_at': DateTime.now().toUtc().subtract(const Duration(minutes: 3)).toIso8601String(),
             'ended_at': null, 'downtime_s': 180, 'phases': []};
        return json(b, 201);
      case ('POST', '/api/portal/breakdowns/b1/phases'):
        b!['phases'] = [...b!['phases'], {'phase': body['phase'], 'at': now}];
        return json(b);
      case ('POST', '/api/portal/breakdowns/b1/resolve'):
        b!['ended_at'] = now;
        b!['notes'] = body['notes'];
        return json(b);
    }
    return json({'detail': 'Not Found'}, 404);
  });
}
