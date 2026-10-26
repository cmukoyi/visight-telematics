import 'dart:async';
import 'dart:ui';

import 'package:flutter/material.dart';

import 'app_log.dart';

import 'screens/login_screen.dart';
import 'screens/shell.dart';
import 'session.dart';
import 'theme.dart';

void main() {
  WidgetsFlutterBinding.ensureInitialized();
  // Crashes and errors go to the app log too ("Report a problem" shares it)
  final showError = FlutterError.onError;
  FlutterError.onError = (details) {
    AppLog.error('Flutter error: ${details.exceptionAsString()}', null, details.stack);
    showError?.call(details);
  };
  PlatformDispatcher.instance.onError = (error, stack) {
    AppLog.error('Uncaught error', error, stack);
    return false;
  };
  unawaited(AppLog.init().then((_) => AppLog.info('App started')));
  final session = Session()..restore();
  runApp(VisightApp(session: session));
}

class VisightApp extends StatelessWidget {
  const VisightApp({super.key, required this.session});
  final Session session;

  @override
  Widget build(BuildContext context) {
    return SessionScope(
      session: session,
      child: MaterialApp(
        title: 'ViSight Track',
        debugShowCheckedModeBanner: false,
        theme: buildTheme(),
        home: const _AuthGate(),
      ),
    );
  }
}

/// Splash while the stored token is checked, then the login or the tabs.
class _AuthGate extends StatelessWidget {
  const _AuthGate();

  @override
  Widget build(BuildContext context) {
    final session = SessionScope.of(context);
    if (session.restoring) return const Scaffold(body: Center(child: CircularProgressIndicator()));
    return session.signedIn ? const Shell() : const LoginScreen();
  }
}
