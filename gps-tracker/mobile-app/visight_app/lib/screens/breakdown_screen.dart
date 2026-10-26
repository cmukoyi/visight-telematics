import 'dart:async';

import 'package:flutter/material.dart';

import '../api/api_client.dart';
import '../api/models.dart';
import '../format.dart';
import '../location.dart';
import '../session.dart';
import '../theme.dart';
import '../widgets/common.dart';

const _red = Color(0xFFD32F2F);
const _causes = ['Engine', 'Flat tyre', 'Electrical', 'Overheating', 'Battery', 'Accident', 'Fuel', 'Other'];
const _phases = ['Waiting for dispatch', 'Mechanic en route', 'Under repair', 'Being towed', 'Waiting for parts'];

/// "02:41:07": a running clock for the breakdown.
String fmtClock(Duration d) {
  final s = d.inSeconds < 0 ? 0 : d.inSeconds;
  String two(int n) => n.toString().padLeft(2, '0');
  return '${two(s ~/ 3600)}:${two((s % 3600) ~/ 60)}:${two(s % 60)}';
}

/// Assets → vehicle → Log breakdown: start the timer the moment the vehicle
/// breaks down, log phases while waiting, and resolve it when it's going again.
/// The time and the phone's position are recorded at each step; the manager
/// sees them with the vehicle's tracker data in Vehicle Maintenance → Breakdowns.
class BreakdownScreen extends StatefulWidget {
  const BreakdownScreen({super.key, required this.vehicle, this.breakdown});
  final Vehicle vehicle;
  final Breakdown? breakdown;

  @override
  State<BreakdownScreen> createState() => _BreakdownScreenState();
}

class _BreakdownScreenState extends State<BreakdownScreen> {
  Breakdown? _b;
  String? _cause;
  bool _busy = false;
  String? _busyLabel;
  bool _noLocation = false;
  Timer? _tick;

  @override
  void initState() {
    super.initState();
    _b = widget.breakdown;
    _tick = Timer.periodic(const Duration(seconds: 1), (_) {
      if (mounted && (_b?.isActive ?? false)) setState(() {});
    });
  }

  @override
  void dispose() {
    _tick?.cancel();
    super.dispose();
  }

  ApiClient get _api => SessionScope.read(context).api;

  Future<void> _run(String label, Future<Breakdown> Function(Map<String, Object> pos) call) async {
    setState(() {
      _busy = true;
      _busyLabel = label;
    });
    try {
      final pos = await currentPosition();
      _noLocation = pos == null;
      final b = await call(positionJson(pos));
      if (mounted) setState(() => _b = b);
    } on ApiException catch (e) {
      if (mounted) showError(context, e);
    } finally {
      if (mounted) {
        setState(() {
          _busy = false;
          _busyLabel = null;
        });
      }
    }
  }

  Future<void> _start() => _run('Recording time and location…', (pos) async => Breakdown.fromJson(
      await _api.post('/api/portal/breakdowns', {'imei': widget.vehicle.imei, 'cause': ?_cause, ...pos})));

  Future<void> _phase(String phase) => _run('Logging “$phase”…', (pos) async => Breakdown.fromJson(
      await _api.post('/api/portal/breakdowns/${_b!.id}/phases', {'phase': phase, ...pos})));

  Future<void> _resolve() async {
    final notes = TextEditingController();
    final ok = await showModalBottomSheet<bool>(
      context: context,
      isScrollControlled: true,
      showDragHandle: true,
      builder: (ctx) => Padding(
        padding: EdgeInsets.fromLTRB(20, 0, 20, MediaQuery.viewInsetsOf(ctx).bottom + 20),
        child: Column(mainAxisSize: MainAxisSize.min, crossAxisAlignment: CrossAxisAlignment.stretch, children: [
          const Text('End breakdown', style: TextStyle(fontSize: 20, fontWeight: FontWeight.w600)),
          const SizedBox(height: 4),
          Text('The clock stops now, at ${fmtClock(DateTime.now().difference(_b!.startedAt))}.',
              style: const TextStyle(color: AppColors.muted)),
          const SizedBox(height: 16),
          TextField(
            controller: notes,
            maxLines: 3,
            textCapitalization: TextCapitalization.sentences,
            decoration: const InputDecoration(hintText: 'What was wrong and what fixed it (optional)'),
          ),
          const SizedBox(height: 16),
          FilledButton(
            style: FilledButton.styleFrom(backgroundColor: _red),
            onPressed: () => Navigator.pop(ctx, true),
            child: const Text('End breakdown / Resolved', style: TextStyle(fontSize: 16)),
          ),
          TextButton(onPressed: () => Navigator.pop(ctx, false), child: const Text('Keep the timer running')),
        ]),
      ),
    );
    if (ok != true) return;
    await _run('Stopping the clock…', (pos) async => Breakdown.fromJson(
        await _api.post('/api/portal/breakdowns/${_b!.id}/resolve', {'notes': notes.text, ...pos})));
  }

  @override
  Widget build(BuildContext context) {
    final b = _b;
    return Scaffold(
      appBar: AppBar(
          title: Text(b == null ? 'Log breakdown' : (b.isActive ? 'Breakdown in progress' : 'Breakdown resolved')),
          backgroundColor: Colors.white,
          surfaceTintColor: Colors.transparent),
      body: SafeArea(
        child: Stack(children: [
          ListView(padding: const EdgeInsets.all(20), children: [
            Text(widget.vehicle.name, style: const TextStyle(fontSize: 22, fontWeight: FontWeight.w600)),
            if (widget.vehicle.registration != null)
              Text(widget.vehicle.registration!, style: const TextStyle(color: AppColors.muted)),
            const SizedBox(height: 20),
            if (b == null) ..._startView() else if (b.isActive) ..._activeView(b) else ..._summaryView(b),
            if (_noLocation)
              const Padding(
                padding: EdgeInsets.only(top: 12),
                child: Text('Your location was off, so this step was saved without it.',
                    style: TextStyle(color: AppColors.alert)),
              ),
          ]),
          if (_busy)
            Positioned.fill(
              child: ColoredBox(
                color: Colors.white70,
                child: Center(
                  child: Column(mainAxisSize: MainAxisSize.min, children: [
                    const CircularProgressIndicator(),
                    const SizedBox(height: 12),
                    Text(_busyLabel ?? ''),
                  ]),
                ),
              ),
            ),
        ]),
      ),
    );
  }

  List<Widget> _startView() => [
        const Text('What happened?', style: TextStyle(fontSize: 16, fontWeight: FontWeight.w600)),
        const SizedBox(height: 8),
        Wrap(spacing: 8, runSpacing: 8, children: [
          for (final c in _causes)
            ChoiceChip(
              label: Text(c),
              selected: _cause == c,
              onSelected: (on) => setState(() => _cause = on ? c : null),
            ),
        ]),
        const SizedBox(height: 28),
        SizedBox(
          height: 64,
          child: FilledButton.icon(
            style: FilledButton.styleFrom(backgroundColor: _red),
            onPressed: _busy ? null : _start,
            icon: const Icon(Icons.timer_outlined, size: 28),
            label: const Text('Start breakdown timer', style: TextStyle(fontSize: 18, fontWeight: FontWeight.w600)),
          ),
        ),
        const SizedBox(height: 12),
        const Text(
          'Start it the moment the vehicle breaks down. The time and your location are recorded, '
          'and your manager can compare them with the vehicle\'s tracker.',
          style: TextStyle(color: AppColors.muted),
        ),
      ];

  List<Widget> _activeView(Breakdown b) => [
        Container(
          padding: const EdgeInsets.symmetric(vertical: 24, horizontal: 16),
          decoration: BoxDecoration(color: const Color(0xFFFDECEA), borderRadius: BorderRadius.circular(16)),
          child: Column(children: [
            const Text('Breakdown time', style: TextStyle(color: _red, fontWeight: FontWeight.w600)),
            const SizedBox(height: 4),
            Text(fmtClock(DateTime.now().difference(b.startedAt)),
                style: const TextStyle(
                    fontSize: 52, fontWeight: FontWeight.w700, color: _red, fontFeatures: [FontFeature.tabularFigures()])),
            Text('Since ${fmtTime(b.startedAt)}${b.cause != null ? ' · ${b.cause}' : ''}',
                style: const TextStyle(color: AppColors.muted)),
            if (b.currentPhase != null) ...[
              const SizedBox(height: 8),
              Chip(label: Text(b.currentPhase!), avatar: const Icon(Icons.flag, size: 18)),
            ],
          ]),
        ),
        const SizedBox(height: 20),
        const Text('Update the status', style: TextStyle(fontSize: 16, fontWeight: FontWeight.w600)),
        const SizedBox(height: 4),
        for (final p in _phases)
          Card(
            elevation: 0,
            color: b.currentPhase == p ? AppColors.segment : AppColors.surface,
            child: ListTile(
              leading: Icon(b.currentPhase == p ? Icons.radio_button_checked : Icons.radio_button_unchecked,
                  color: b.currentPhase == p ? _red : AppColors.muted),
              title: Text(p),
              enabled: !_busy && b.currentPhase != p,
              onTap: () => _phase(p),
            ),
          ),
        if (b.phases.isNotEmpty) ...[
          const SizedBox(height: 12),
          _Timeline(b),
        ],
        const SizedBox(height: 24),
        SizedBox(
          height: 60,
          child: FilledButton.icon(
            onPressed: _busy ? null : _resolve,
            icon: const Icon(Icons.check_circle_outline),
            label: const Text('End breakdown / Resolve', style: TextStyle(fontSize: 17, fontWeight: FontWeight.w600)),
          ),
        ),
      ];

  List<Widget> _summaryView(Breakdown b) => [
        Container(
          padding: const EdgeInsets.all(20),
          decoration: BoxDecoration(color: const Color(0xFFE8F5E9), borderRadius: BorderRadius.circular(16)),
          child: Column(children: [
            const Icon(Icons.check_circle, color: Color(0xFF2E7D32), size: 40),
            const SizedBox(height: 8),
            const Text('Total downtime', style: TextStyle(color: AppColors.muted)),
            Text(fmtClock(Duration(seconds: b.downtimeS)),
                style: const TextStyle(fontSize: 40, fontWeight: FontWeight.w700, fontFeatures: [FontFeature.tabularFigures()])),
          ]),
        ),
        const SizedBox(height: 16),
        Container(
          decoration: cardDecoration(),
          padding: const EdgeInsets.all(14),
          child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
            _row('Started', fmtDateTime(b.startedAt)),
            _row('Ended', b.endedAt == null ? '—' : fmtDateTime(b.endedAt!)),
            if (b.cause != null) _row('Cause', b.cause!),
            if (b.location != null) _row('Where', b.location!),
            if (b.notes != null) _row('Notes', b.notes!),
          ]),
        ),
        if (b.phases.isNotEmpty) ...[const SizedBox(height: 16), _Timeline(b)],
        const SizedBox(height: 24),
        FilledButton(onPressed: () => Navigator.pop(context), child: const Text('Done')),
      ];

  Widget _row(String label, String value) => Padding(
        padding: const EdgeInsets.symmetric(vertical: 4),
        child: Row(crossAxisAlignment: CrossAxisAlignment.start, children: [
          SizedBox(width: 90, child: Text(label, style: const TextStyle(color: AppColors.muted))),
          Expanded(child: Text(value)),
        ]),
      );
}

class _Timeline extends StatelessWidget {
  const _Timeline(this.b);
  final Breakdown b;

  @override
  Widget build(BuildContext context) {
    final rows = [('Breakdown started', b.startedAt), for (final p in b.phases) (p.phase, p.at), if (b.endedAt != null) ('Resolved', b.endedAt!)];
    return Container(
      decoration: cardDecoration(),
      padding: const EdgeInsets.all(14),
      child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
        const Text('Timeline', style: TextStyle(fontSize: 16, fontWeight: FontWeight.w600)),
        const SizedBox(height: 8),
        for (final (label, at) in rows)
          Padding(
            padding: const EdgeInsets.symmetric(vertical: 4),
            child: Row(children: [
              SizedBox(width: 56, child: Text(fmtTime(at), style: const TextStyle(color: AppColors.muted))),
              Expanded(child: Text(label)),
              Text('+${fmtClock(at.difference(b.startedAt))}', style: const TextStyle(color: AppColors.muted, fontSize: 12)),
            ]),
          ),
      ]),
    );
  }
}

/// The vehicle screen's button: "Log breakdown", or the running clock when one is in progress.
class BreakdownButton extends StatefulWidget {
  const BreakdownButton({super.key, required this.vehicle});
  final Vehicle vehicle;

  @override
  State<BreakdownButton> createState() => _BreakdownButtonState();
}

class _BreakdownButtonState extends State<BreakdownButton> {
  Breakdown? _active;
  Timer? _tick;

  @override
  void initState() {
    super.initState();
    _load();
    _tick = Timer.periodic(const Duration(seconds: 1), (_) {
      if (mounted && _active != null) setState(() {});
    });
  }

  @override
  void dispose() {
    _tick?.cancel();
    super.dispose();
  }

  Future<void> _load() async {
    try {
      final j = await SessionScope.read(context).api.get('/api/portal/breakdowns/active', {'imei': widget.vehicle.imei});
      if (mounted) setState(() => _active = j == null ? null : Breakdown.fromJson(j));
    } on ApiException catch (_) {
      // Shown without the clock; the screen reports problems when it's opened
    }
  }

  Future<void> _open() async {
    await Navigator.of(context)
        .push(MaterialPageRoute(builder: (_) => BreakdownScreen(vehicle: widget.vehicle, breakdown: _active)));
    _load();
  }

  @override
  Widget build(BuildContext context) {
    final a = _active;
    return Padding(
      padding: const EdgeInsets.only(bottom: 16),
      child: a == null
          ? OutlinedButton.icon(
              style: OutlinedButton.styleFrom(
                  foregroundColor: _red,
                  side: const BorderSide(color: _red),
                  minimumSize: const Size.fromHeight(52),
                  shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(12))),
              onPressed: _open,
              icon: const Icon(Icons.car_crash_outlined),
              label: const Text('Log breakdown', style: TextStyle(fontSize: 16, fontWeight: FontWeight.w600)),
            )
          : FilledButton.icon(
              style: FilledButton.styleFrom(backgroundColor: _red, minimumSize: const Size.fromHeight(52)),
              onPressed: _open,
              icon: const Icon(Icons.timer_outlined),
              label: Text('Breakdown in progress · ${fmtClock(DateTime.now().difference(a.startedAt))}',
                  style: const TextStyle(fontSize: 16, fontWeight: FontWeight.w600)),
            ),
    );
  }
}
