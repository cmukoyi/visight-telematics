import 'package:flutter/material.dart';

import '../session.dart';
import 'assets_screen.dart';
import 'home_screen.dart';
import 'map_screen.dart';
import 'trips_screen.dart';

/// The four tabs every user sees: Home | Map view | Trips | Assets.
class Shell extends StatefulWidget {
  const Shell({super.key});

  @override
  State<Shell> createState() => _ShellState();
}

class _ShellState extends State<Shell> {
  @override
  void initState() {
    super.initState();
    WidgetsBinding.instance.addPostFrameCallback((_) => _offerLock());
  }

  Future<void> _offerLock() async {
    final session = SessionScope.read(context);
    if (!session.offerLock) return;
    session.offerLock = false;
    final turnOn = await showDialog<bool>(
      context: context,
      builder: (ctx) => AlertDialog(
        title: const Text('Unlock with your fingerprint?'),
        content: const Text('Use your fingerprint, face or phone PIN, whichever this phone has, to open ViSight Track. '
            'You can change this in the menu.'),
        actions: [
          TextButton(onPressed: () => Navigator.pop(ctx, false), child: const Text('Not now')),
          FilledButton(onPressed: () => Navigator.pop(ctx, true), child: const Text('Turn on')),
        ],
      ),
    );
    if (turnOn != true) return;
    final problem = await session.setLockEnabled(true);
    if (problem != null && mounted) {
      ScaffoldMessenger.of(context).showSnackBar(SnackBar(content: Text(problem)));
    }
  }

  @override
  Widget build(BuildContext context) {
    final tab = SessionScope.of(context).tab;
    return ValueListenableBuilder<int>(
      valueListenable: tab,
      builder: (context, index, _) => Scaffold(
        body: IndexedStack(index: index, children: const [HomeScreen(), MapScreen(), TripsScreen(), AssetsScreen()]),
        bottomNavigationBar: NavigationBar(
          selectedIndex: index,
          onDestinationSelected: (i) => tab.value = i,
          destinations: const [
            NavigationDestination(icon: Icon(Icons.home_outlined), selectedIcon: Icon(Icons.home), label: 'Home'),
            NavigationDestination(icon: Icon(Icons.map_outlined), selectedIcon: Icon(Icons.map), label: 'Map view'),
            NavigationDestination(icon: Icon(Icons.route_outlined), selectedIcon: Icon(Icons.route), label: 'Trips'),
            NavigationDestination(
                icon: Icon(Icons.directions_car_outlined), selectedIcon: Icon(Icons.directions_car), label: 'Assets'),
          ],
        ),
      ),
    );
  }
}
