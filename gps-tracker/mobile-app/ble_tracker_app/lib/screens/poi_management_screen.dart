import 'package:flutter/material.dart';
import '../models/poi_model.dart';
import '../services/auth_service.dart';
import '../services/poi_service.dart';
import '../theme/app_theme.dart';

class POIManagementScreen extends StatefulWidget {
  const POIManagementScreen({Key? key}) : super(key: key);

  @override
  State<POIManagementScreen> createState() => _POIManagementScreenState();
}

class _POIManagementScreenState extends State<POIManagementScreen> {
  final AuthService _authService = AuthService();
  final POIService _poiService = POIService();
  
  List<POI> _pois = [];
  List<dynamic> _trackers = [];
  bool _isLoading = true;

  @override
  void initState() {
    super.initState();
    _loadData();
  }

  Future<void> _loadData() async {
    setState(() => _isLoading = true);
    try {
      final pois = await _poiService.getPOIs();
      final trackers = await _authService.getBLETags();
      
      if (mounted) {
        setState(() {
          _pois = pois;
          _trackers = trackers;
          _isLoading = false;
        });
      }
    } catch (e) {
      if (mounted) {
        setState(() => _isLoading = false);
        ScaffoldMessenger.of(context).showSnackBar(
          SnackBar(content: Text('Failed to load data: $e')),
        );
      }
    }
  }

  Future<void> _toggleArmStatus(POI poi, String trackerId, bool currentlyArmed) async {
    try {
      if (currentlyArmed) {
        await _poiService.disarmPOI(poi.id, trackerId);
        ScaffoldMessenger.of(context).showSnackBar(
          SnackBar(content: Text('✅ Disarmed ${poi.name}')),
        );
      } else {
        await _poiService.armPOI(poi.id, trackerId);
        ScaffoldMessenger.of(context).showSnackBar(
          SnackBar(content: Text('✅ Armed ${poi.name}')),
        );
      }
      
      // Reload data to get updated armed status
      _loadData();
    } catch (e) {
      ScaffoldMessenger.of(context).showSnackBar(
        SnackBar(content: Text('Failed to ${currentlyArmed ? "disarm" : "arm"}: $e')),
      );
    }
  }

  Future<void> _showDeleteConfirmation(POI poi) async {
    final confirmed = await showDialog<bool>(
      context: context,
      builder: (BuildContext context) {
        return AlertDialog(
          title: Text('Delete Location'),
          content: Text(
            'This action will disable all active tracker monitoring for this location.',
            style: TextStyle(fontSize: 14),
          ),
          actions: [
            TextButton(
              onPressed: () => Navigator.of(context).pop(false),
              child: Text('Cancel'),
            ),
            ElevatedButton(
              onPressed: () => Navigator.of(context).pop(true),
              style: ElevatedButton.styleFrom(
                backgroundColor: Colors.red,
                foregroundColor: Colors.white,
              ),
              child: Text('Delete'),
            ),
          ],
        );
      },
    );

    if (confirmed == true) {
      try {
        await _poiService.deletePOI(poi.id);
        ScaffoldMessenger.of(context).showSnackBar(
          SnackBar(content: Text('✅ Location deleted successfully')),
        );
        _loadData();
      } catch (e) {
        ScaffoldMessenger.of(context).showSnackBar(
          SnackBar(content: Text('Failed to delete location: $e')),
        );
      }
    }
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(
        title: Text('Manage Locations'),
        backgroundColor: AppTheme.brandPrimary,
        foregroundColor: Colors.white,
      ),
      body: _isLoading
          ? Center(child: CircularProgressIndicator())
          : _pois.isEmpty
              ? Center(
                  child: Column(
                    mainAxisAlignment: MainAxisAlignment.center,
                    children: [
                      Icon(Icons.location_off, size: 64, color: Colors.grey),
                      SizedBox(height: 16),
                      Text(
                        'No locations created yet',
                        style: TextStyle(fontSize: 18, color: Colors.grey[600]),
                      ),
                      SizedBox(height: 24),
                      ElevatedButton.icon(
                        onPressed: () => Navigator.pop(context, 'create'),
                        icon: Icon(Icons.add_location_alt),
                        label: Text('Create Location'),
                        style: ElevatedButton.styleFrom(
                          backgroundColor: AppTheme.brandPrimary,
                          foregroundColor: Colors.white,
                          padding: EdgeInsets.symmetric(horizontal: 28, vertical: 14),
                          shape: RoundedRectangleBorder(
                            borderRadius: BorderRadius.circular(12),
                          ),
                        ),
                      ),
                    ],
                  ),
                )
              : _trackers.isEmpty
                  ? Center(
                      child: Column(
                        mainAxisAlignment: MainAxisAlignment.center,
                        children: [
                          Icon(Icons.devices, size: 64, color: Colors.grey),
                          SizedBox(height: 16),
                          Text(
                            'No trackers found',
                            style: TextStyle(fontSize: 18, color: Colors.grey[600]),
                          ),
                          SizedBox(height: 8),
                          Text(
                            'Add a tracker to arm locations',
                            style: TextStyle(fontSize: 14, color: Colors.grey[500]),
                          ),
                        ],
                      ),
                    )
                  : RefreshIndicator(
                      onRefresh: _loadData,
                      child: ListView.builder(
                        padding: EdgeInsets.all(16),
                        itemCount: _pois.length,
                        itemBuilder: (context, index) {
                          final poi = _pois[index];
                          return _buildPOICard(poi);
                        },
                      ),
                    ),
    );
  }

  Widget _buildPOICard(POI poi) {
    return Card(
      margin: EdgeInsets.only(bottom: 16),
      elevation: 2,
      child: Padding(
        padding: EdgeInsets.all(16),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Row(
              children: [
                Icon(
                  poi.isRoute ? Icons.route : Icons.location_on,
                  color: AppTheme.brandPrimary,
                  size: 28,
                ),
                SizedBox(width: 12),
                Expanded(
                  child: Column(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      Text(
                        poi.name,
                        style: TextStyle(
                          fontSize: 18,
                          fontWeight: FontWeight.bold,
                        ),
                      ),
                      if (poi.description != null && poi.description!.isNotEmpty)
                        Text(
                          poi.description!,
                          style: TextStyle(
                            fontSize: 14,
                            color: Colors.grey[600],
                          ),
                        ),
                      SizedBox(height: 4),
                      Text(
                        poi.isRoute ? '🚩 From | To' : '📍 Single Location',
                        style: TextStyle(
                          fontSize: 12,
                          color: Colors.grey[600],
                          fontWeight: FontWeight.w500,
                        ),
                      ),
                    ],
                  ),
                ),
                IconButton(
                  icon: Icon(Icons.delete, color: Colors.red),
                  onPressed: () => _showDeleteConfirmation(poi),
                  tooltip: 'Delete Location',
                ),
              ],
            ),
            if (poi.isRoute && poi.hasDestination) ...[
              SizedBox(height: 12),
              Container(
                padding: EdgeInsets.all(8),
                decoration: BoxDecoration(
                  color: Colors.blue.withOpacity(0.1),
                  borderRadius: BorderRadius.circular(8),
                ),
                child: Column(
                  children: [
                    Row(
                      children: [
                        Text('START: ', style: TextStyle(fontWeight: FontWeight.bold, fontSize: 12)),
                        Expanded(child: Text(poi.address ?? 'Unknown', style: TextStyle(fontSize: 12))),
                      ],
                    ),
                    SizedBox(height: 4),
                    Row(
                      children: [
                        Text('END: ', style: TextStyle(fontWeight: FontWeight.bold, fontSize: 12)),
                        Expanded(child: Text(poi.destinationAddress ?? 'Unknown', style: TextStyle(fontSize: 12))),
                      ],
                    ),
                  ],
                ),
              ),
            ],
            Divider(height: 24),
            Text(
              'TRACKER STATUS',
              style: TextStyle(
                fontSize: 12,
                fontWeight: FontWeight.bold,
                color: Colors.grey[700],
                letterSpacing: 0.5,
              ),
            ),
            SizedBox(height: 12),
            ..._trackers.map((tracker) => _buildTrackerToggle(poi, tracker)).toList(),
            if (_trackers.isEmpty)
              Padding(
                padding: EdgeInsets.symmetric(vertical: 8),
                child: Text(
                  'No trackers available',
                  style: TextStyle(color: Colors.grey[600], fontSize: 14),
                ),
              ),
          ],
        ),
      ),
    );
  }

  Widget _buildTrackerToggle(POI poi, dynamic tracker) {
    final trackerId = tracker['id']?.toString() ?? tracker['imei']?.toString();
    if (trackerId == null) {
      return SizedBox.shrink(); // Skip trackers without valid IDs
    }
    
    final trackerName = tracker['device_name'] ?? tracker['imei'] ?? 'Unknown Tracker';
    final isArmed = poi.isArmedTo(trackerId);

    return Container(
      margin: EdgeInsets.only(bottom: 8),
      decoration: BoxDecoration(
        color: isArmed ? Colors.green.withOpacity(0.1) : Colors.red.withOpacity(0.05),
        borderRadius: BorderRadius.circular(8),
        border: Border.all(
          color: isArmed ? Colors.green.withOpacity(0.4) : Colors.red.withOpacity(0.3),
        ),
      ),
      child: SwitchListTile(
        title: Text(
          trackerName,
          style: TextStyle(
            fontSize: 14,
            fontWeight: isArmed ? FontWeight.w600 : FontWeight.normal,
            color: isArmed ? Colors.green.shade700 : Colors.red.shade700,
          ),
        ),
        subtitle: Text(
          isArmed ? '✓ Armed - Monitoring active' : '✗ Disarmed - No monitoring',
          style: TextStyle(
            fontSize: 12,
            color: isArmed ? Colors.green.shade600 : Colors.red.shade600,
            fontWeight: FontWeight.w500,
          ),
        ),
        value: isArmed,
        activeColor: Colors.green,
        onChanged: (value) => _toggleArmStatus(poi, trackerId, isArmed),
        dense: true,
        contentPadding: EdgeInsets.symmetric(horizontal: 12, vertical: 4),
      ),
    );
  }
}
