import 'dart:async';
import 'dart:ui';

import 'package:flutter/material.dart';

import 'app_log.dart';
import 'build_info.dart';

import 'screens/lock_screen.dart';
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
  unawaited(AppLog.init().then((_) => AppBuild.load()).then((_) => AppLog.info('App started: ${AppBuild.label}')));
  final session = Session()..restore();
  runApp(VisightApp(session: session));
}

class VisightApp extends StatefulWidget {
  const VisightApp({super.key, required this.session});
  final Session session;

  @override
  State<VisightApp> createState() => _VisightAppState();
}

class _VisightAppState extends State<VisightApp> with WidgetsBindingObserver {
  final _navigator = GlobalKey<NavigatorState>();

  @override
  void initState() {
    super.initState();
    WidgetsBinding.instance.addObserver(this);
    // Screens pushed on top of the tabs must not outlive the session, or they stay up with no token
    widget.session.onSignedOut = () => _navigator.currentState?.popUntil((r) => r.isFirst);
  }

  @override
  void dispose() {
    WidgetsBinding.instance.removeObserver(this);
    super.dispose();
  }

  @override
  void didChangeAppLifecycleState(AppLifecycleState state) => widget.session.appStateChanged(state);

  // The back button mustn't reach the screens behind the lock
  @override
  Future<bool> didPopRoute() async => widget.session.locked;

  @override
  Widget build(BuildContext context) {
    return SessionScope(
      session: widget.session,
      child: MaterialApp(
        title: 'ViSight Track',
        debugShowCheckedModeBanner: false,
        navigatorKey: _navigator,
        theme: buildTheme(),
        home: const _AuthGate(),
        // Over the navigator, so the screen the user was on (a running breakdown) is still there when unlocked
        builder: (context, child) {
          final locked = SessionScope.of(context).locked;
          return Stack(fit: StackFit.expand, children: [
            AbsorbPointer(absorbing: locked, child: ExcludeSemantics(excluding: locked, child: child!)),
            if (locked) const LockScreen(),
          ]);
        },
      ),
    );
  }
}

/// Splash while the stored token is checked, then the login or the tabs (or a retry if the server can't be reached).
class _AuthGate extends StatelessWidget {
  const _AuthGate();

  @override
  Widget build(BuildContext context) {
    final session = SessionScope.of(context);
    if (session.restoring) return const Scaffold(body: Center(child: CircularProgressIndicator()));
    if (session.restoreError != null) {
      return Scaffold(
        body: Center(
          child: Padding(
            padding: const EdgeInsets.all(24),
            child: Column(mainAxisSize: MainAxisSize.min, children: [
              Text(session.restoreError!, textAlign: TextAlign.center),
              const SizedBox(height: 16),
              FilledButton(onPressed: session.restore, child: const Text('Try again')),
              TextButton(onPressed: session.signOut, child: const Text('Sign in with your password instead')),
            ]),
          ),
        ),
      );
    }
    return session.signedIn ? const Shell() : const LoginScreen();
  }
}
