import 'dart:async';
import 'dart:convert';
import 'dart:io';

import 'package:archive/archive.dart';
import 'package:device_info_plus/device_info_plus.dart';
import 'package:intl/intl.dart';
import 'package:path_provider/path_provider.dart';

import 'api/api_client.dart';
import 'build_info.dart';
import 'config.dart';

/// The app's own log: one text file per day (logs/2026-10-26.log in the app's private storage), kept
/// for [keepDays] days. Requests, their answers' status and error messages, screens' errors and crashes
/// are written here; never passwords, tokens or request bodies. "Report a problem" zips them to share.
class AppLog {
  AppLog._();

  static const keepDays = 7;
  static final _day = DateFormat('yyyy-MM-dd');
  static final _stamp = DateFormat('yyyy-MM-dd HH:mm:ss.SSS');

  static Directory? _dir;
  static final List<String> _pending = [];   // lines written before init() (or without storage, in tests)
  static Future<void> _writing = Future.value();

  /// Find the log folder and drop files older than [keepDays]. Safe to call more than once.
  static Future<void> init() async {
    if (_dir != null) return;
    try {
      final dir = Directory('${(await getApplicationSupportDirectory()).path}/logs');
      await dir.create(recursive: true);
      final oldest = _day.format(DateTime.now().subtract(const Duration(days: keepDays - 1)));
      await for (final f in dir.list()) {
        final name = f.uri.pathSegments.last;
        if (f is File && name.endsWith('.log') && name.compareTo('$oldest.log') < 0) await f.delete();
      }
      _dir = dir;
      final waiting = List.of(_pending);
      _pending.clear();
      _append(waiting);
    } catch (_) {
      // No storage (tests, or the platform refused): keep the most recent lines in memory only
    }
  }

  static void info(String message) => _log('INFO ', message);
  static void warn(String message) => _log('WARN ', message);
  static void error(String message, [Object? error, StackTrace? stack]) =>
      _log('ERROR', [message, ?error?.toString(), if (stack != null) stack.toString()].join('\n  '));

  static void _log(String level, String message) {
    final line = '${_stamp.format(DateTime.now())} $level $message';
    if (_dir == null) {
      _pending.add(line);
      if (_pending.length > 500) _pending.removeAt(0);
      return;
    }
    _append([line]);
  }

  static void _append(List<String> lines) {
    if (lines.isEmpty) return;
    final file = File('${_dir!.path}/${_day.format(DateTime.now())}.log');
    _writing = _writing.then((_) => file.writeAsString('${lines.join('\n')}\n', mode: FileMode.append, flush: true))
        .catchError((_) => file);
  }

  /// The day files of the last [keepDays] days, oldest first.
  static Future<List<File>> files() async {
    await _writing;
    final dir = _dir;
    if (dir == null || !await dir.exists()) return [];
    final out = [await for (final f in dir.list()) if (f is File && f.path.endsWith('.log')) f];
    out.sort((a, b) => a.path.compareTo(b.path));
    return out;
  }

  /// A zip of the day files plus report.txt (what the user wrote, who they are, the app and the phone).
  static Future<File> buildReport({required String description, required Map<String, String?> about}) async {
    info('Problem report created');
    final device = await _device();
    await AppBuild.load();
    final now = DateTime.now();
    final report = [
      'ViSight Track — problem report',
      'Created: ${_stamp.format(now)} (${now.timeZoneName}, UTC${now.timeZoneOffset.isNegative ? '' : '+'}${now.timeZoneOffset.inHours})',
      '',
      'What happened:',
      description.trim().isEmpty ? '(not described)' : description.trim(),
      '',
      'App: ${AppBuild.label}',
      'Server: ${Config.apiBaseUrl} (build ${ApiClient.serverBuild ?? 'unknown'})',
      ...device.entries.map((e) => '${e.key}: ${e.value}'),
      ...about.entries.where((e) => e.value != null && e.value!.isNotEmpty).map((e) => '${e.key}: ${e.value}'),
      '',
      'Logs: one file per day for the last $keepDays days (logs/yyyy-mm-dd.log).',
    ].join('\n');
    final archive = Archive()..addFile(ArchiveFile.string('report.txt', report));
    for (final f in await files()) {
      archive.addFile(ArchiveFile.bytes('logs/${f.uri.pathSegments.last}', await f.readAsBytes()));
    }
    if (_pending.isNotEmpty) archive.addFile(ArchiveFile.string('logs/unsaved.log', _pending.join('\n')));
    final out = File('${(await getTemporaryDirectory()).path}/visight-problem-report-${DateFormat('yyyyMMdd-HHmm').format(now)}.zip');
    await out.writeAsBytes(ZipEncoder().encodeBytes(archive), flush: true);
    return out;
  }

  static Future<Map<String, String>> _device() async {
    try {
      final info = DeviceInfoPlugin();
      if (Platform.isAndroid) {
        final a = await info.androidInfo;
        return {'Phone': '${a.manufacturer} ${a.model}', 'OS': 'Android ${a.version.release} (SDK ${a.version.sdkInt})'};
      }
      if (Platform.isIOS) {
        final i = await info.iosInfo;
        return {'Phone': i.utsname.machine, 'OS': '${i.systemName} ${i.systemVersion}'};
      }
    } catch (_) {}
    return {'OS': '${Platform.operatingSystem} ${Platform.operatingSystemVersion}'};
  }
}

/// Short text for a JSON body in the log (error answers only), without anything long.
String logSnippet(String body) {
  final s = body.replaceAll(RegExp(r'\s+'), ' ');
  try {
    final j = jsonDecode(body);
    if (j is Map && j['detail'] != null) return '${j['detail']}';
  } catch (_) {}
  return s.length > 300 ? '${s.substring(0, 300)}…' : s;
}
