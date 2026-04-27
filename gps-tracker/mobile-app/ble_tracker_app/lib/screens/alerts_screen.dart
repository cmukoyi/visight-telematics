import 'package:flutter/material.dart';
import 'package:intl/intl.dart';
import '../models/poi_model.dart';
import '../services/poi_service.dart';
import '../theme/app_theme.dart';

class AlertsScreen extends StatefulWidget {
  const AlertsScreen({Key? key}) : super(key: key);

  @override
  State<AlertsScreen> createState() => _AlertsScreenState();
}

class _AlertsScreenState extends State<AlertsScreen> {
  final POIService _poiService = POIService();
  final ScrollController _scrollController = ScrollController();
  
  List<GeofenceAlert> _alerts = [];
  bool _loading = true;
  bool _loadingMore = false;
  String? _error;
  int _unreadCount = 0;
  int _total = 0;
  int _offset = 0;
  final int _limit = 20;
  bool _hasMore = true;
  bool _showUnreadOnly = false;
  final int _daysToShow = 7; // Show only last 7 days
  
  // Filter alerts to only show last 7 days
  List<GeofenceAlert> get _filteredAlerts {
    final sevenDaysAgo = DateTime.now().subtract(Duration(days: _daysToShow));
    final filtered = _alerts.where((alert) {
      return alert.createdAt.isAfter(sevenDaysAgo);
    }).toList();
    if (_alerts.isNotEmpty && filtered.length != _alerts.length) {
      print('⏰ Filtering to last $_daysToShow days: $_alerts.length total → ${filtered.length} recent');
    }
    return filtered;
  }

  @override
  void initState() {
    super.initState();
    print('🔄 AlertsScreen initialized - 7 day filter v1.0');
    _loadAlerts();
    _scrollController.addListener(_onScroll);
  }

  @override
  void dispose() {
    _scrollController.dispose();
    super.dispose();
  }

  void _onScroll() {
    if (_scrollController.position.pixels >= 
        _scrollController.position.maxScrollExtent - 200) {
      if (!_loadingMore && _hasMore) {
        _loadMoreAlerts();
      }
    }
  }

  Future<void> _loadAlerts({bool refresh = false}) async {
    if (refresh) {
      setState(() {
        _offset = 0;
        _alerts = [];
        _hasMore = true;
      });
    }

    setState(() {
      _loading = true;
      _error = null;
    });

    try {
      final response = await _poiService.getAlerts(
        limit: _limit,
        offset: _offset,
        unreadOnly: _showUnreadOnly,
      );

      setState(() {
        if (refresh) {
          _alerts = response.alerts;
        } else {
          _alerts.addAll(response.alerts);
        }
        _unreadCount = response.unreadCount;
        _total = response.total;
        _hasMore = _alerts.length < _total;
        _loading = false;
        print('📋 Loaded ${_alerts.length} alerts (total: $_total, unread: $_unreadCount)');
        print('✅ 7-day filter active: showing ${_filteredAlerts.length} recent alerts');
      });
    } catch (e) {
      setState(() {
        _error = e.toString();
        _loading = false;
      });
    }
  }

  Future<void> _loadMoreAlerts() async {
    if (_loadingMore || !_hasMore) return;

    setState(() {
      _loadingMore = true;
      _offset += _limit;
    });

    try {
      final response = await _poiService.getAlerts(
        limit: _limit,
        offset: _offset,
        unreadOnly: _showUnreadOnly,
      );

      setState(() {
        _alerts.addAll(response.alerts);
        _unreadCount = response.unreadCount;
        _total = response.total;
        _hasMore = _alerts.length < _total;
        _loadingMore = false;
      });
    } catch (e) {
      setState(() {
        _loadingMore = false;
        _offset -= _limit; // Reset offset on error
      });
    }
  }

  Future<void> _markAlertRead(GeofenceAlert alert) async {
    if (alert.isRead) return;

    try {
      await _poiService.markAlertRead(alert.id);
      
      setState(() {
        final index = _alerts.indexWhere((a) => a.id == alert.id);
        if (index != -1) {
          _alerts[index] = GeofenceAlert(
            id: alert.id,
            poiId: alert.poiId,
            trackerId: alert.trackerId,
            userId: alert.userId,
            eventType: alert.eventType,
            latitude: alert.latitude,
            longitude: alert.longitude,
            isRead: true,
            createdAt: alert.createdAt,
            poiName: alert.poiName,
            trackerName: alert.trackerName,
          );
        }
        _unreadCount = (_unreadCount - 1).clamp(0, _unreadCount);
      });
    } catch (e) {
      ScaffoldMessenger.of(context).showSnackBar(
        SnackBar(content: Text('Failed to mark alert as read: $e')),
      );
    }
  }

  Future<void> _markAllRead() async {
    try {
      await _poiService.markAllAlertsRead();
      _loadAlerts(refresh: true);
      
      ScaffoldMessenger.of(context).showSnackBar(
        const SnackBar(content: Text('All alerts marked as read')),
      );
    } catch (e) {
      ScaffoldMessenger.of(context).showSnackBar(
        SnackBar(content: Text('Failed to mark all as read: $e')),
      );
    }
  }

  void _toggleFilter() {
    setState(() {
      _showUnreadOnly = !_showUnreadOnly;
    });
    _loadAlerts(refresh: true);
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(
        title: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            const Text('Location Alerts'),
            if (_unreadCount > 0)
              Text(
                '$_unreadCount unread',
                style: const TextStyle(fontSize: 12, fontWeight: FontWeight.normal),
              ),
          ],
        ),
        actions: [
          IconButton(
            icon: Icon(_showUnreadOnly ? Icons.filter_list : Icons.filter_list_off),
            onPressed: _toggleFilter,
            tooltip: _showUnreadOnly ? 'Show all' : 'Show unread only',
          ),
          if (_unreadCount > 0)
            IconButton(
              icon: const Icon(Icons.done_all),
              onPressed: _markAllRead,
              tooltip: 'Mark all as read',
            ),
        ],
      ),
      body: _buildBody(),
    );
  }

  Widget _buildBody() {
    if (_loading && _alerts.isEmpty) {
      return const Center(child: CircularProgressIndicator());
    }

    if (_error != null && _alerts.isEmpty) {
      return Center(
        child: Column(
          mainAxisAlignment: MainAxisAlignment.center,
          children: [
            const Icon(Icons.error_outline, size: 64, color: Colors.grey),
            const SizedBox(height: 16),
            Text(_error!, textAlign: TextAlign.center),
            const SizedBox(height: 16),
            ElevatedButton(
              onPressed: () => _loadAlerts(refresh: true),
              child: const Text('Retry'),
            ),
          ],
        ),
      );
    }

    if (_alerts.isEmpty) {
      return Center(
        child: Column(
          mainAxisAlignment: MainAxisAlignment.center,
          children: [
            const Icon(Icons.notifications_none, size: 64, color: Colors.grey),
            const SizedBox(height: 16),
            Text(
              _showUnreadOnly ? 'No unread alerts' : 'No alerts yet',
              style: const TextStyle(fontSize: 18, color: Colors.grey),
            ),
            const SizedBox(height: 8),
            const Text(
              'Alerts will appear when your trackers\nenter or exit geofenced areas',
              textAlign: TextAlign.center,
              style: TextStyle(color: Colors.grey),
            ),
          ],
        ),
      );
    }

    print('🎨 Building alerts UI with ${_filteredAlerts.length} filtered alerts');
    return RefreshIndicator(
      onRefresh: () => _loadAlerts(refresh: true),
      child: Column(
        children: [
          // Last 7 days label
          Padding(
            padding: const EdgeInsets.all(16.0),
            child: Align(
              alignment: Alignment.centerLeft,
              child: Text(
                'Last $_daysToShow days',
                style: const TextStyle(
                  fontSize: 14,
                  fontWeight: FontWeight.w500,
                  color: Colors.grey,
                ),
              ),
            ),
          ),
          // Alerts list
          Expanded(
            child: ListView.builder(
              controller: _scrollController,
              itemCount: _filteredAlerts.length + (_loadingMore ? 1 : 0),
              itemBuilder: (context, index) {
                if (index == _filteredAlerts.length) {
                  return const Center(
                    child: Padding(
                      padding: EdgeInsets.all(16.0),
                      child: CircularProgressIndicator(),
                    ),
                  );
                }

                final alert = _filteredAlerts[index];
                return _buildAlertCard(alert);
              },
            ),
          ),
        ],
      ),
    );
  }

  Widget _buildAlertCard(GeofenceAlert alert) {
    final dateFormat = DateFormat('MMM d, yyyy • h:mm a');
    final isEntry = alert.eventType == GeofenceEventType.entry;

    return Card(
      margin: const EdgeInsets.symmetric(horizontal: 12, vertical: 6),
      elevation: alert.isRead ? 1 : 3,
      color: alert.isRead ? null : Colors.blue.shade50,
      child: InkWell(
        onTap: () => _markAlertRead(alert),
        child: Padding(
          padding: const EdgeInsets.all(16.0),
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Row(
                children: [
                  Container(
                    padding: const EdgeInsets.all(8),
                    decoration: BoxDecoration(
                      color: isEntry ? Colors.green.shade100 : Colors.red.shade100,
                      borderRadius: BorderRadius.circular(8),
                    ),
                    child: Icon(
                      isEntry ? Icons.login : Icons.logout,
                      color: isEntry ? Colors.green.shade700 : Colors.red.shade700,
                      size: 24,
                    ),
                  ),
                  const SizedBox(width: 12),
                  Expanded(
                    child: Column(
                      crossAxisAlignment: CrossAxisAlignment.start,
                      children: [
                        Row(
                          children: [
                            Text(
                              alert.eventEmoji,
                              style: const TextStyle(fontSize: 16),
                            ),
                            const SizedBox(width: 4),
                            Expanded(
                              child: Text(
                                '${alert.eventDescription} ${alert.poiName ?? 'POI'}',
                                style: const TextStyle(
                                  fontSize: 16,
                                  fontWeight: FontWeight.bold,
                                ),
                                overflow: TextOverflow.ellipsis,
                              ),
                            ),
                            if (!alert.isRead)
                              Container(
                                width: 8,
                                height: 8,
                                decoration: const BoxDecoration(
                                  color: Colors.blue,
                                  shape: BoxShape.circle,
                                ),
                              ),
                          ],
                        ),
                        const SizedBox(height: 4),
                        Text(
                          alert.trackerName ?? 'Tracker ${alert.trackerId}',
                          style: TextStyle(
                            fontSize: 14,
                            color: Colors.grey.shade600,
                          ),
                        ),
                      ],
                    ),
                  ),
                ],
              ),
              const SizedBox(height: 12),
              Row(
                children: [
                  Icon(Icons.access_time, size: 14, color: Colors.grey.shade600),
                  const SizedBox(width: 4),
                  Text(
                    dateFormat.format(alert.createdAt.toLocal()),
                    style: TextStyle(
                      fontSize: 12,
                      color: Colors.grey.shade600,
                    ),
                  ),
                  const Spacer(),
                  Icon(Icons.location_on, size: 14, color: Colors.grey.shade600),
                  const SizedBox(width: 4),
                  Text(
                    '${alert.latitude.toStringAsFixed(4)}, ${alert.longitude.toStringAsFixed(4)}',
                    style: TextStyle(
                      fontSize: 12,
                      color: Colors.grey.shade600,
                    ),
                  ),
                ],
              ),
            ],
          ),
        ),
      ),
    );
  }
}
