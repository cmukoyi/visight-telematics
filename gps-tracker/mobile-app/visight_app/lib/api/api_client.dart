import 'dart:async';
import 'dart:convert';
import 'dart:io';

import 'package:http/http.dart' as http;

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

  /// Called when the token is rejected (expired or the user was deactivated).
  void Function()? onUnauthorized;

  Uri _uri(String path, Map<String, String?>? query) {
    final q = {for (final e in (query ?? {}).entries) if (e.value != null && e.value!.isNotEmpty) e.key: e.value!};
    return Uri.parse('${Config.apiBaseUrl}$path').replace(queryParameters: q.isEmpty ? null : q);
  }

  Map<String, String> get _headers => {
        'Accept': 'application/json',
        'Content-Type': 'application/json',
        if (token != null) 'Authorization': 'Bearer $token',
      };

  Future<dynamic> get(String path, [Map<String, String?>? query]) async {
    return _handle(await _send(() => _http.get(_uri(path, query), headers: _headers)));
  }

  Future<dynamic> post(String path, Object body) async {
    return _handle(await _send(() => _http.post(_uri(path, null), headers: _headers, body: jsonEncode(body))));
  }

  Future<http.Response> _send(Future<http.Response> Function() call) async {
    try {
      return await call().timeout(const Duration(seconds: 30));
    } on Exception catch (e) {
      if (e is! http.ClientException && e is! SocketException && e is! TimeoutException) rethrow;
      throw ApiException(0, "Can't reach the server. Check your connection and try again.");
    }
  }

  dynamic _handle(http.Response res) {
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
