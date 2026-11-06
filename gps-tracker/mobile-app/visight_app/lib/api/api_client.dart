import 'dart:async';
import 'dart:convert';
import 'dart:io';

import 'package:http/http.dart' as http;

import '../app_log.dart';
import '../build_info.dart';
import '../config.dart';

/// An error answer from the backend, with FastAPI's `detail` as the message.
class ApiException implements Exception {
  ApiException(this.status, this.message);

  final int status;
  final String message;

  bool get isUnauthorized => status == 401;

  /// The user's roles don't include this feature (e.g. trips without "Trips and routes").
  bool get isForbidden => status == 403;

  @override
  String toString() => message;
}

/// JSON over HTTP to the platform's public API, with the bearer token from POST /api/auth/login.
class ApiClient {
  ApiClient({http.Client? client}) : _http = client ?? http.Client();

  final http.Client _http;
  String? token;

  /// Gets a new [token] when it expires, so a long job (a breakdown overnight) doesn't lose the session.
  String? refreshToken;

  /// Called when the session is over: the token was rejected and can't be renewed.
  void Function()? onUnauthorized;

  /// Called with a new [token] to keep.
  void Function()? onTokenRenewed;

  Future<bool>? _renewing;

  Uri _uri(String path, Map<String, String?>? query) {
    final q = {for (final e in (query ?? {}).entries) if (e.value != null && e.value!.isNotEmpty) e.key: e.value!};
    return Uri.parse('${Config.apiBaseUrl}$path').replace(queryParameters: q.isEmpty ? null : q);
  }

  Map<String, String> get _headers => {
        'Accept': 'application/json',
        'Content-Type': 'application/json',
        if (token != null) 'Authorization': 'Bearer $token',
        'X-App-Version': AppBuild.header,
      };

  /// The server build that last answered (X-Server-Build), logged when it changes.
  static String? serverBuild;

  Future<dynamic> get(String path, [Map<String, String?>? query]) {
    final uri = _uri(path, query);
    return _request('GET', uri, () => _http.get(uri, headers: _headers));
  }

  Future<dynamic> post(String path, Object body) {
    final uri = _uri(path, null);
    return _request('POST', uri, () => _http.post(uri, headers: _headers, body: jsonEncode(body)));
  }

  // A 401 did nothing on the server, so the request can safely go again with a new token
  Future<dynamic> _request(String method, Uri uri, Future<http.Response> Function() call) async {
    final took = Stopwatch()..start(), sentWith = token;
    var res = await _send(method, uri, took, call);
    if (res.statusCode == 401 && sentWith != null && await _renew(sentWith)) {
      res = await _send(method, uri, took, call);
    }
    return _handle(method, uri, took, res);
  }

  /// A new token after [rejected] was refused: true if there is one to use. Every request refused
  /// meanwhile shares the one renewal. Throws when the server can't answer: that doesn't end the session.
  Future<bool> _renew(String rejected) async {
    if (token == null) return false; // signed out while the request was on its way
    if (token != rejected) return true; // another request has already renewed it
    if (refreshToken == null) return false;
    return _renewing ??= _requestNewToken().whenComplete(() => _renewing = null);
  }

  Future<bool> _requestNewToken() async {
    final device = refreshToken, uri = _uri('/api/auth/refresh', null), took = Stopwatch()..start();
    final res = await _send('POST', uri, took,
        () => _http.post(uri, headers: _headers, body: jsonEncode({'refresh_token': device})));
    final body = _tryDecode(res.body), renewed = body is Map ? body['access_token'] : null;
    if (res.statusCode == 401) {
      AppLog.warn('Token renewal refused (${took.elapsedMilliseconds} ms)');
      return false;
    }
    if (res.statusCode != 200 || renewed is! String) {
      AppLog.warn('Token renewal failed: ${res.statusCode} (${took.elapsedMilliseconds} ms)');
      throw ApiException(res.statusCode, 'Something went wrong (${res.statusCode})');
    }
    if (refreshToken != device) return false; // signed out while renewing
    AppLog.info('Access token renewed (${took.elapsedMilliseconds} ms)');
    token = renewed;
    onTokenRenewed?.call();
    return true;
  }

  // Every request goes in the app log (AppLog): method, path, status and time; error answers with their message
  Future<http.Response> _send(String method, Uri uri, Stopwatch took, Future<http.Response> Function() call) async {
    try {
      return await call().timeout(const Duration(seconds: 30));
    } on Exception catch (e) {
      AppLog.warn('$method ${uri.path}${uri.hasQuery ? '?${uri.query}' : ''} failed after ${took.elapsedMilliseconds} ms: $e');
      if (e is! http.ClientException && e is! SocketException && e is! TimeoutException) rethrow;
      throw ApiException(0, "Can't reach the server. Check your connection and try again.");
    }
  }

  dynamic _handle(String method, Uri uri, Stopwatch took, http.Response res) {
    final build = res.headers['x-server-build'];
    if (build != serverBuild) {
      serverBuild = build;
      AppLog.info('Server build: ${build ?? 'unknown (older than version reporting)'}');
    }
    final what = '$method ${uri.path}${uri.hasQuery ? '?${uri.query}' : ''} → ${res.statusCode} (${took.elapsedMilliseconds} ms)';
    if (res.statusCode >= 400) {
      (res.statusCode >= 500 ? AppLog.error : AppLog.warn)('$what: ${logSnippet(res.body)}');
    } else {
      AppLog.info(what);
    }
    final body = res.body.isEmpty ? null : _tryDecode(res.body);
    if (res.statusCode >= 200 && res.statusCode < 300) return body;
    if (res.statusCode == 401 && token != null) onUnauthorized?.call();
    throw ApiException(res.statusCode, _detail(body) ?? 'Something went wrong (${res.statusCode})');
  }

  static dynamic _tryDecode(String s) {
    try {
      return jsonDecode(s);
    } catch (_) {
      return null;
    }
  }

  static String? _detail(dynamic body) {
    final d = body is Map ? body['detail'] : null;
    if (d is String) return d;
    if (d is List && d.isNotEmpty && d.first is Map) return '${d.first['msg']}';
    return null;
  }
}
