import 'dart:convert';
import 'dart:io';

import 'package:archive/archive.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';
import 'package:path_provider_platform_interface/path_provider_platform_interface.dart';
import 'package:plugin_platform_interface/plugin_platform_interface.dart';
import 'package:visight_app/api/api_client.dart';
import 'package:visight_app/app_log.dart';

/// path_provider answering with a temporary folder.
class FakePaths extends Fake with MockPlatformInterfaceMixin implements PathProviderPlatform {
  FakePaths(this.root);
  final Directory root;
  @override
  Future<String?> getApplicationSupportPath() async => root.path;
  @override
  Future<String?> getTemporaryPath() async => root.path;
}

void main() {
  late Directory root;
  setUpAll(() async {
    root = await Directory.systemTemp.createTemp('visight_log_test');
    PathProviderPlatform.instance = FakePaths(root);
    // An 8-day-old file is removed when the log starts; a 3-day-old one is kept
    final logs = await Directory('${root.path}/logs').create();
    String day(int ago) => DateTime.now().subtract(Duration(days: ago)).toIso8601String().substring(0, 10);
    await File('${logs.path}/${day(8)}.log').writeAsString('old\n');
    await File('${logs.path}/${day(3)}.log').writeAsString('three days ago\n');
    AppLog.info('before init');   // kept in memory, then written
    await AppLog.init();
  });
  tearDownAll(() => root.delete(recursive: true));

  test('keeps a file per day for the last 7 days', () async {
    final names = [for (final f in await AppLog.files()) f.uri.pathSegments.last];
    expect(names.length, 2);
    final today = (await AppLog.files()).last;
    expect(await today.readAsString(), contains('INFO  before init'));
  });

  test('requests are logged with status and time; a server error with its message and code', () async {
    final api = ApiClient(client: MockClient((req) async => req.url.path == '/ok'
        ? http.Response('{}', 200)
        : http.Response(jsonEncode({'detail': 'Something went wrong on our side (error F1DFD2).'}), 500)));
    await api.get('/ok', {'imei': '861'});
    await expectLater(api.post('/api/portal/breakdowns', {'imei': '861', 'password': 'never logged'}), throwsA(isA<ApiException>()));
    final text = await (await AppLog.files()).last.readAsString();
    expect(text, matches(RegExp(r'INFO  GET /ok\?imei=861 → 200 \(\d+ ms\)')));
    expect(text, contains('ERROR POST /api/portal/breakdowns → 500'));
    expect(text, contains('error F1DFD2'));
    expect(text, isNot(contains('never logged')));   // request bodies stay out of the log
  });

  test('the problem report zips report.txt and the day files', () async {
    final zip = await AppLog.buildReport(description: 'Breakdown fails', about: {'User': 'Sipho <s@x.co>', 'Roles': null});
    final archive = ZipDecoder().decodeBytes(await zip.readAsBytes());
    final names = archive.files.map((f) => f.name).toList();
    expect(names.first, 'report.txt');
    expect(names.where((n) => n.startsWith('logs/')).length, 2);
    final report = utf8.decode(archive.findFile('report.txt')!.content as List<int>);
    expect(report, contains('Breakdown fails'));
    expect(report, contains('User: Sipho <s@x.co>'));
    expect(report, isNot(contains('Roles:')));
  });
}
