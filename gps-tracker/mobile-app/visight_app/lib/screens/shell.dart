import 'package:flutter/material.dart';

import '../session.dart';
import 'assets_screen.dart';
import 'home_screen.dart';
import 'map_screen.dart';
import 'trips_screen.dart';

/// The four tabs every user sees: Home | Map view | Trips | Assets.
class Shell extends StatelessWidget {
  const Shell({super.key});

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
