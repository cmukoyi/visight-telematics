import 'package:flutter/material.dart';

import 'screens/login_screen.dart';
import 'screens/shell.dart';
import 'session.dart';
import 'theme.dart';

void main() {
  WidgetsFlutterBinding.ensureInitialized();
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
