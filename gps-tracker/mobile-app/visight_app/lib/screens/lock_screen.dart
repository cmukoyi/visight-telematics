import 'package:flutter/material.dart';

import '../session.dart';
import '../theme.dart';
import '../widgets/common.dart';

/// Covers the app until the phone's owner unlocks it; asks as soon as it appears.
class LockScreen extends StatefulWidget {
  const LockScreen({super.key});

  @override
  State<LockScreen> createState() => _LockScreenState();
}

class _LockScreenState extends State<LockScreen> {
  String? _problem;

  @override
  void initState() {
    super.initState();
    WidgetsBinding.instance.addPostFrameCallback((_) => _unlock());
  }

  Future<void> _unlock() async {
    final problem = await SessionScope.read(context).unlock();
    if (mounted) setState(() => _problem = problem);
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      body: SafeArea(
        child: Center(
          child: Padding(
            padding: const EdgeInsets.all(24),
            child: Column(mainAxisSize: MainAxisSize.min, children: [
              const BrandMark(size: 72),
              const SizedBox(height: 24),
              const Text('ViSight Track', style: TextStyle(fontSize: 26, fontWeight: FontWeight.w700)),
              const SizedBox(height: 6),
              Text(_problem ?? 'Locked', textAlign: TextAlign.center, style: const TextStyle(color: AppColors.muted)),
              const SizedBox(height: 32),
              FilledButton.icon(
                onPressed: _unlock,
                icon: const Icon(Icons.fingerprint),
                label: const Text('Unlock', style: TextStyle(fontSize: 16)),
              ),
              const SizedBox(height: 8),
              TextButton(
                onPressed: SessionScope.read(context).signOut,
                child: const Text('Sign in with your password instead'),
              ),
            ]),
          ),
        ),
      ),
    );
  }
}
