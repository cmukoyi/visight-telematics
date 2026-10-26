import 'package:flutter/material.dart';
import 'package:flutter_map/flutter_map.dart';
import 'package:share_plus/share_plus.dart';
import 'package:url_launcher/url_launcher.dart';

import '../api/api_client.dart';
import '../app_log.dart';
import '../api/models.dart';
import '../config.dart';
import '../session.dart';
import '../theme.dart';

/// The square brand tile at the top left of every tab.
class BrandMark extends StatelessWidget {
  const BrandMark({super.key, this.size = 48});
  final double size;

  @override
  Widget build(BuildContext context) {
    return Container(
      width: size,
      height: size,
      decoration: BoxDecoration(color: Colors.white, borderRadius: BorderRadius.circular(size * 0.22), boxShadow: _shadow),
      child: Column(mainAxisAlignment: MainAxisAlignment.center, children: [
        Text('V', style: TextStyle(fontSize: size * 0.55, height: 1, fontWeight: FontWeight.w900, color: AppColors.navy)),
        Container(width: size * 0.5, height: size * 0.09, color: AppColors.blue),
      ]),
    );
  }
}

const _shadow = [BoxShadow(color: Color(0x22000000), blurRadius: 10, offset: Offset(0, 3))];

/// Logo, centred title and the menu button, as in the designs.
class AppHeader extends StatelessWidget {
  const AppHeader({super.key, required this.title, this.translucent = false});
  final String title;
  final bool translucent;

  @override
  Widget build(BuildContext context) {
    return Container(
      color: translucent ? Colors.white.withValues(alpha: 0.75) : Colors.white,
      padding: EdgeInsets.fromLTRB(16, MediaQuery.paddingOf(context).top + 8, 16, 8),
      child: Row(children: [
        const BrandMark(),
        Expanded(
          child: Text(title,
              textAlign: TextAlign.center,
              style: const TextStyle(fontSize: 20, fontWeight: FontWeight.w600, color: AppColors.navy)),
        ),
        Material(
          color: Colors.white,
          elevation: 3,
          shadowColor: Colors.black26,
          borderRadius: BorderRadius.circular(12),
          child: InkWell(
            borderRadius: BorderRadius.circular(12),
            onTap: () => showAccountSheet(context),
            child: const SizedBox(width: 48, height: 48, child: Icon(Icons.menu, color: AppColors.navy, size: 28)),
          ),
        ),
      ]),
    );
  }
}

/// The menu: who is signed in, whose vehicles they see, and sign out.
void showAccountSheet(BuildContext context) {
  final session = SessionScope.read(context);
  final me = session.me;
  if (me == null) return;
  showModalBottomSheet(
    context: context,
    showDragHandle: true,
    builder: (ctx) => SafeArea(
      child: Column(mainAxisSize: MainAxisSize.min, crossAxisAlignment: CrossAxisAlignment.stretch, children: [
        ListTile(
          leading: const CircleAvatar(backgroundColor: AppColors.navy, child: Icon(Icons.person, color: Colors.white)),
          title: Text(me.displayName, style: const TextStyle(fontWeight: FontWeight.w600)),
          subtitle: Text([me.email, if (me.usergroup != null) me.usergroup!].join('\n')),
          isThreeLine: me.usergroup != null,
        ),
        ListTile(
          leading: const Icon(Icons.shield_outlined),
          title: const Text('Vehicles you see'),
          subtitle: Text(me.seesAllVehicles
              ? 'All vehicles (administrator)'
              : 'Security group: ${me.securityGroup ?? 'none — ask your administrator'}'),
        ),
        if (me.roles.isNotEmpty)
          ListTile(leading: const Icon(Icons.badge_outlined), title: const Text('Roles'), subtitle: Text(me.roles.join(', '))),
        const Divider(),
        ListTile(
          leading: const Icon(Icons.refresh),
          title: const Text('Refresh vehicles'),
          onTap: () {
            Navigator.pop(ctx);
            session.refreshVehicles();
          },
        ),
        ListTile(
          leading: const Icon(Icons.bug_report_outlined),
          title: const Text('Report a problem'),
          subtitle: const Text("Share the app's logs from the last 7 days"),
          onTap: () {
            Navigator.pop(ctx);
            reportProblem(context);
          },
        ),
        ListTile(
          leading: const Icon(Icons.logout, color: Colors.red),
          title: const Text('Sign out', style: TextStyle(color: Colors.red)),
          onTap: () {
            Navigator.pop(ctx);
            session.signOut();
          },
        ),
      ]),
    ),
  );
}

Color statusColor(String status) => switch (status) {
      'active' => AppColors.moving,
      'idle' => AppColors.idle,
      _ => AppColors.offline,
    };

/// Rounded car tile, green when the vehicle is moving.
class VehicleAvatar extends StatelessWidget {
  const VehicleAvatar({super.key, required this.status, this.size = 64});
  final String status;
  final double size;

  @override
  Widget build(BuildContext context) {
    return Container(
      width: size,
      height: size,
      decoration: BoxDecoration(color: statusColor(status), borderRadius: BorderRadius.circular(size * 0.2)),
      child: Icon(Icons.directions_car_filled, color: AppColors.navy, size: size * 0.55),
    );
  }
}

/// Map pin: "P" when parked, an arrow when moving.
class VehicleMarker extends StatelessWidget {
  const VehicleMarker({super.key, required this.vehicle, this.selected = false});
  final Vehicle vehicle;
  final bool selected;

  static const size = 56.0;

  @override
  Widget build(BuildContext context) {
    return Stack(alignment: Alignment.topCenter, children: [
      Icon(Icons.location_on, size: size, color: selected ? AppColors.navy : AppColors.navy.withValues(alpha: 0.75)),
      Positioned(
        top: size * 0.12,
        child: Container(
          width: size * 0.42,
          height: size * 0.42,
          alignment: Alignment.center,
          decoration: BoxDecoration(color: statusColor(vehicle.status), shape: BoxShape.circle),
          child: vehicle.isMoving
              ? Icon(Icons.navigation, size: size * 0.26, color: AppColors.navy)
              : Text('P', style: TextStyle(fontWeight: FontWeight.w800, fontSize: size * 0.26, color: AppColors.navy)),
        ),
      ),
    ]);
  }
}

/// Marker for a vehicle, anchored at the tip of the pin.
Marker vehicleMarker(Vehicle v, {bool selected = false, VoidCallback? onTap}) => Marker(
      point: v.position!,
      width: VehicleMarker.size,
      height: VehicleMarker.size,
      alignment: Alignment.topCenter,
      child: GestureDetector(onTap: onTap, child: VehicleMarker(vehicle: v, selected: selected)),
    );

/// The OpenStreetMap tiles and their (required) attribution.
List<Widget> baseMapLayers() => [
      TileLayer(urlTemplate: Config.tileUrl, userAgentPackageName: Config.userAgentPackage),
      SimpleAttributionWidget(
        source: const Text('OpenStreetMap contributors'),
        onTap: () => launchUrl(Uri.parse('https://openstreetmap.org/copyright')),
      ),
    ];

/// White rounded square button used on maps.
class MapButton extends StatelessWidget {
  const MapButton({super.key, required this.icon, required this.onTap, this.dark = false, this.tooltip});
  final IconData icon;
  final VoidCallback onTap;
  final bool dark;
  final String? tooltip;

  @override
  Widget build(BuildContext context) {
    final button = Material(
      color: dark ? AppColors.navy : Colors.white,
      elevation: 3,
      shadowColor: Colors.black26,
      borderRadius: BorderRadius.circular(12),
      child: InkWell(
        borderRadius: BorderRadius.circular(12),
        onTap: onTap,
        child: SizedBox(width: 46, height: 46, child: Icon(icon, color: dark ? Colors.white : AppColors.navy)),
      ),
    );
    return Padding(
      padding: const EdgeInsets.only(bottom: 10),
      child: tooltip == null ? button : Tooltip(message: tooltip!, child: button),
    );
  }
}

/// Grey pill with a white selected segment (Shortcuts | Insights | Latest trips).
class SegmentTabs extends StatelessWidget {
  const SegmentTabs({super.key, required this.labels, required this.index, required this.onChanged});
  final List<String> labels;
  final int index;
  final ValueChanged<int> onChanged;

  @override
  Widget build(BuildContext context) {
    return Container(
      padding: const EdgeInsets.all(6),
      decoration: BoxDecoration(color: AppColors.segment, borderRadius: BorderRadius.circular(24)),
      child: Row(children: [
        for (var i = 0; i < labels.length; i++)
          Expanded(
            child: GestureDetector(
              onTap: () => onChanged(i),
              child: AnimatedContainer(
                duration: const Duration(milliseconds: 180),
                padding: const EdgeInsets.symmetric(vertical: 10),
                decoration: BoxDecoration(
                  color: i == index ? Colors.white : Colors.transparent,
                  borderRadius: BorderRadius.circular(18),
                ),
                child: Text(labels[i],
                    textAlign: TextAlign.center,
                    style: TextStyle(
                        fontSize: 16,
                        fontWeight: i == index ? FontWeight.w600 : FontWeight.w400,
                        color: AppColors.navy)),
              ),
            ),
          ),
      ]),
    );
  }
}

/// Loads [load] and shows a spinner, the result, or the reason it failed —
/// including "your role doesn't allow this" when the backend answers 403.
class AsyncView<T> extends StatefulWidget {
  const AsyncView({super.key, required this.load, required this.builder, this.padding = const EdgeInsets.all(24)});
  final Future<T> Function() load;
  final Widget Function(BuildContext context, T data, Future<void> Function() reload) builder;
  final EdgeInsets padding;

  @override
  State<AsyncView<T>> createState() => AsyncViewState<T>();
}

class AsyncViewState<T> extends State<AsyncView<T>> {
  late Future<T> _future = widget.load();

  Future<void> reload() async {
    final f = widget.load();
    setState(() => _future = f);
    try {
      await f;
    } catch (_) {
      // shown by the FutureBuilder
    }
  }

  @override
  Widget build(BuildContext context) {
    return FutureBuilder<T>(
      future: _future,
      builder: (context, snap) {
        if (snap.connectionState != ConnectionState.done) {
          return const Center(child: Padding(padding: EdgeInsets.all(32), child: CircularProgressIndicator()));
        }
        if (snap.hasError) {
          final e = snap.error;
          return Padding(
            padding: widget.padding,
            child: e is ApiException && e.isForbidden
                ? RoleLimited(message: e.message)
                : MessageView(icon: Icons.cloud_off, title: "Couldn't load this", message: '$e', onRetry: reload),
          );
        }
        return widget.builder(context, snap.data as T, reload);
      },
    );
  }
}

/// Shown in place of a tab's content when the user's roles don't include it.
class RoleLimited extends StatelessWidget {
  const RoleLimited({super.key, required this.message});
  final String message;

  @override
  Widget build(BuildContext context) => MessageView(
        icon: Icons.lock_outline,
        title: 'Not included in your role',
        message: '$message.\nAsk your administrator to add it to your role in the customer dashboard.',
      );
}

class MessageView extends StatelessWidget {
  const MessageView({super.key, required this.icon, required this.title, required this.message, this.onRetry});
  final IconData icon;
  final String title, message;
  final VoidCallback? onRetry;

  @override
  Widget build(BuildContext context) {
    return Center(
      child: Column(mainAxisSize: MainAxisSize.min, children: [
        Icon(icon, size: 48, color: AppColors.muted),
        const SizedBox(height: 12),
        Text(title, style: const TextStyle(fontSize: 18, fontWeight: FontWeight.w600), textAlign: TextAlign.center),
        const SizedBox(height: 6),
        Text(message, style: const TextStyle(color: AppColors.muted), textAlign: TextAlign.center),
        if (onRetry != null) ...[
          const SizedBox(height: 16),
          OutlinedButton.icon(onPressed: onRetry, icon: const Icon(Icons.refresh), label: const Text('Try again')),
        ],
      ]),
    );
  }
}

/// Shows an API error in a snackbar.
void showError(BuildContext context, Object error) {
  final text = error is ApiException && error.isForbidden ? '$error. Ask your administrator.' : '$error';
  ScaffoldMessenger.of(context).showSnackBar(SnackBar(content: Text(text)));
}

/// Card surface used by asset and trip rows.
BoxDecoration cardDecoration() => BoxDecoration(
      color: AppColors.surface,
      borderRadius: BorderRadius.circular(10),
      boxShadow: const [BoxShadow(color: Color(0x1F000000), blurRadius: 8, offset: Offset(0, 3))],
    );


/// Menu → Report a problem: ask what went wrong, zip the last 7 days' logs with it, and open the phone's
/// share sheet (email, WhatsApp, Drive…) so the user sends it to support themselves.
Future<void> reportProblem(BuildContext context) async {
  final session = SessionScope.read(context);
  final text = TextEditingController();
  final send = await showDialog<bool>(
    context: context,
    builder: (ctx) => AlertDialog(
      title: const Text('Report a problem'),
      content: Column(mainAxisSize: MainAxisSize.min, crossAxisAlignment: CrossAxisAlignment.start, children: [
        const Text("What happened? The app's logs from the last 7 days are attached as a zip file.",
            style: TextStyle(color: AppColors.muted)),
        const SizedBox(height: 12),
        TextField(
          controller: text,
          autofocus: true,
          maxLines: 4,
          textCapitalization: TextCapitalization.sentences,
          decoration: const InputDecoration(hintText: 'e.g. "Something went wrong" when I log a breakdown'),
        ),
      ]),
      actions: [
        TextButton(onPressed: () => Navigator.pop(ctx, false), child: const Text('Cancel')),
        FilledButton(
          style: FilledButton.styleFrom(minimumSize: const Size(0, 44)),
          onPressed: () => Navigator.pop(ctx, true),
          child: const Text('Share report'),
        ),
      ],
    ),
  );
  if (send != true || !context.mounted) return;
  final box = context.findRenderObject() as RenderBox?;
  try {
    final me = session.me;
    final zip = await AppLog.buildReport(description: text.text, about: {
      'User': me == null ? null : '${me.displayName} <${me.email}>',
      'User group': me?.usergroup,
      'Roles': me?.roles.join(', '),
      'Security group': me?.securityGroup,
      'Vehicles loaded': '${session.vehicles.length}',
    });
    await SharePlus.instance.share(ShareParams(
      files: [XFile(zip.path, mimeType: 'application/zip')],
      subject: 'ViSight Track problem report',
      text: text.text.trim().isEmpty ? 'ViSight Track problem report' : 'ViSight Track problem: ${text.text.trim()}',
      sharePositionOrigin: box == null ? null : box.localToGlobal(Offset.zero) & box.size,   // iPad
    ));
  } catch (e, st) {
    AppLog.error('Problem report failed', e, st);
    if (context.mounted) {
      ScaffoldMessenger.of(context).showSnackBar(SnackBar(content: Text("Couldn't create the report: $e")));
    }
  }
}
