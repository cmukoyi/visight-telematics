import 'package:flutter/material.dart';
import 'package:google_fonts/google_fonts.dart';
import 'package:ble_tracker_app/theme/app_theme.dart';
import 'package:ble_tracker_app/services/logger_service.dart';
import 'package:ble_tracker_app/services/auth_service.dart';
import 'package:share_plus/share_plus.dart';

class SettingsScreen extends StatefulWidget {
  final bool showAppBar;
  
  const SettingsScreen({Key? key, this.showAppBar = true}) : super(key: key);

  @override
  State<SettingsScreen> createState() => _SettingsScreenState();
}

class _SettingsScreenState extends State<SettingsScreen> {
  final _logger = LoggerService();
  final _authService = AuthService();
  bool _isExporting = false;
  bool _emailAlertsEnabled = true;
  bool _loadingPreferences = true;
  String _userEmail = '';

  @override
  void initState() {
    super.initState();
    _loadUserPreferences();
  }

  Future<void> _loadUserPreferences() async {
    try {
      final userInfo = await _authService.getUserInfo();
      if (mounted && userInfo != null) {
        setState(() {
          _emailAlertsEnabled = userInfo['email_alerts_enabled'] ?? true;
          _userEmail = userInfo['email'] ?? '';
          _loadingPreferences = false;
        });
      }
    } catch (e) {
      _logger.error('Failed to load user preferences', e);
      if (mounted) {
        setState(() => _loadingPreferences = false);
      }
    }
  }

  Future<void> _toggleEmailAlerts(bool value) async {
    setState(() => _emailAlertsEnabled = value);
    
    try {
      final response = await _authService.updateUserPreferences(
        emailAlertsEnabled: value,
      );
      
      if (response['success'] == true) {
        _logger.info('Email alerts ${value ? "enabled" : "disabled"}');
        if (mounted) {
          ScaffoldMessenger.of(context).showSnackBar(
            SnackBar(
              content: Text(
                value 
                    ? '✅ Email alerts enabled' 
                    : '📧 Email alerts disabled',
              ),
              backgroundColor: value ? Colors.green : Colors.grey,
              duration: const Duration(seconds: 2),
            ),
          );
        }
      } else {
        // Revert on failure
        setState(() => _emailAlertsEnabled = !value);
        throw Exception('Failed to update preferences');
      }
    } catch (e) {
      _logger.error('Failed to update email preferences', e);
      // Revert on error
      setState(() => _emailAlertsEnabled = !value);
      if (mounted) {
        ScaffoldMessenger.of(context).showSnackBar(
          SnackBar(
            content: Text('❌ Failed to update email preferences: $e'),
            backgroundColor: Colors.red,
          ),
        );
      }
    }
  }

  Future<void> _showEditEmailDialog() async {
    final emailController = TextEditingController(text: _userEmail);
    
    final result = await showDialog<String>(
      context: context,
      builder: (context) => AlertDialog(
        title: Text('Update Email Address'),
        content: Column(
          mainAxisSize: MainAxisSize.min,
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Text(
              'Enter your new email address. You may need to verify it.',
              style: TextStyle(fontSize: 14, color: Colors.grey[600]),
            ),
            SizedBox(height: 16),
            TextField(
              controller: emailController,
              keyboardType: TextInputType.emailAddress,
              decoration: InputDecoration(
                labelText: 'Email Address',
                hintText: 'your@email.com',
                prefixIcon: Icon(Icons.email),
                border: OutlineInputBorder(
                  borderRadius: BorderRadius.circular(8),
                ),
              ),
            ),
          ],
        ),
        actions: [
          TextButton(
            onPressed: () => Navigator.pop(context),
            child: Text('Cancel'),
          ),
          ElevatedButton(
            onPressed: () {
              final newEmail = emailController.text.trim();
              if (newEmail.isEmpty || !newEmail.contains('@')) {
                ScaffoldMessenger.of(context).showSnackBar(
                  SnackBar(
                    content: Text('Please enter a valid email address'),
                    backgroundColor: Colors.red,
                  ),
                );
                return;
              }
              Navigator.pop(context, newEmail);
            },
            style: ElevatedButton.styleFrom(
              backgroundColor: AppTheme.brandPrimary,
              foregroundColor: Colors.white,
            ),
            child: Text('Update'),
          ),
        ],
      ),
    );
    
    if (result != null && result.isNotEmpty && result != _userEmail) {
      await _updateEmail(result);
    }
  }

  Future<void> _updateEmail(String newEmail) async {
    try {
      final response = await _authService.updateUserEmail(newEmail);
      
      if (response['success'] == true) {
        setState(() {
          _userEmail = newEmail;
        });
        
        _logger.info('Email updated to $newEmail');
        if (mounted) {
          ScaffoldMessenger.of(context).showSnackBar(
            SnackBar(
              content: Text('✅ Email updated successfully'),
              backgroundColor: Colors.green,
              duration: const Duration(seconds: 2),
            ),
          );
        }
      } else {
        throw Exception(response['error'] ?? 'Failed to update email');
      }
    } catch (e) {
      _logger.error('Failed to update email', e);
      if (mounted) {
        ScaffoldMessenger.of(context).showSnackBar(
          SnackBar(
            content: Text('❌ Failed to update email: $e'),
            backgroundColor: Colors.red,
          ),
        );
      }
    }
  }

  Future<void> _reportProblem() async {
    _logger.info('User initiated problem report');
    
    setState(() => _isExporting = true);

    try {
      // Export logs to file
      final file = await _logger.exportLogsToFile();
      
      // Share the file
      final result = await Share.shareXFiles(
        [XFile(file.path)],
        subject: 'BLE Tracker - Problem Report',
        text: 'BLE Tracker debug logs attached. Please describe your issue when sharing this file.',
      );

      if (result.status == ShareResultStatus.success) {
        _logger.success('Logs shared successfully');
        if (mounted) {
          ScaffoldMessenger.of(context).showSnackBar(
            const SnackBar(
              content: Text('✅ Logs exported successfully'),
              backgroundColor: Colors.green,
            ),
          );
        }
      }
    } catch (e) {
      _logger.error('Failed to export logs', e);
      if (mounted) {
        ScaffoldMessenger.of(context).showSnackBar(
          SnackBar(
            content: Text('❌ Failed to export logs: $e'),
            backgroundColor: Colors.red,
          ),
        );
      }
    } finally {
      if (mounted) {
        setState(() => _isExporting = false);
      }
    }
  }

  Future<void> _viewLogs() async {
    _logger.info('User viewing logs');
    
    Navigator.push(
      context,
      MaterialPageRoute(
        builder: (context) => LogViewerScreen(),
      ),
    );
  }

  Future<void> _clearLogs() async {
    final confirm = await showDialog<bool>(
      context: context,
      builder: (context) => AlertDialog(
        title: const Text('Clear Logs?'),
        content: const Text('This will delete all stored debug logs. This cannot be undone.'),
        actions: [
          TextButton(
            onPressed: () => Navigator.pop(context, false),
            child: const Text('Cancel'),
          ),
          TextButton(
            onPressed: () => Navigator.pop(context, true),
            child: const Text('Clear', style: TextStyle(color: Colors.red)),
          ),
        ],
      ),
    );

    if (confirm == true) {
      _logger.clearLogs();
      setState(() {});
      if (mounted) {
        ScaffoldMessenger.of(context).showSnackBar(
          const SnackBar(
            content: Text('✅ Logs cleared'),
            backgroundColor: Colors.green,
          ),
        );
      }
    }
  }

  Future<void> _logout() async {
    _logger.info('User logging out');
    
    await _authService.logout();
    
    if (mounted) {
      Navigator.pushNamedAndRemoveUntil(context, '/', (route) => false);
    }
  }

  @override
  Widget build(BuildContext context) {
    final logsCount = _logger.getLogsCount();

    return Scaffold(
      appBar: widget.showAppBar ? AppBar(
        title: Text(
          'Settings',
          style: GoogleFonts.poppins(
            fontWeight: FontWeight.w600,
          ),
        ),
        backgroundColor: AppTheme.brandPrimary,
        foregroundColor: Colors.white,
      ) : null,
      body: ListView(
        children: [
          // Notifications Section
          _buildSectionHeader('Notifications'),
          
          // Email Address
          _buildListTile(
            icon: Icons.email_outlined,
            title: 'Email Address',
            subtitle: _loadingPreferences ? 'Loading...' : (_userEmail.isEmpty ? 'No email set' : _userEmail),
            trailing: Icon(Icons.edit, color: AppTheme.brandPrimary),
            onTap: _loadingPreferences ? null : _showEditEmailDialog,
          ),
          
          // Email Alerts Toggle
          _buildSwitchTile(
            icon: Icons.notifications_active,
            title: 'Email Alerts',
            subtitle: _emailAlertsEnabled
                ? 'Receive geofence alerts via email'
                : 'Email alerts are disabled',
            value: _emailAlertsEnabled,
            onChanged: _loadingPreferences ? null : _toggleEmailAlerts,
          ),
          
          const Divider(height: 32),
          
          // Debug Section
          _buildSectionHeader('Debug & Support'),
          _buildListTile(
            icon: Icons.bug_report,
            title: 'Report a Problem',
            subtitle: 'Export and share debug logs',
            trailing: _isExporting
                ? const SizedBox(
                    width: 24,
                    height: 24,
                    child: CircularProgressIndicator(strokeWidth: 2),
                  )
                : const Icon(Icons.share),
            onTap: _isExporting ? null : _reportProblem,
          ),
          _buildListTile(
            icon: Icons.article,
            title: 'View Logs',
            subtitle: '$logsCount log entries',
            trailing: const Icon(Icons.chevron_right),
            onTap: _viewLogs,
          ),
          _buildListTile(
            icon: Icons.delete_outline,
            title: 'Clear Logs',
            subtitle: 'Delete all debug logs',
            trailing: const Icon(Icons.chevron_right),
            onTap: _clearLogs,
          ),
          
          const Divider(height: 32),
          
          // Account Section
          _buildSectionHeader('Account'),
          _buildListTile(
            icon: Icons.logout,
            title: 'Logout',
            subtitle: 'Sign out of your account',
            trailing: const Icon(Icons.chevron_right),
            onTap: _logout,
          ),
        ],
      ),
    );
  }

  Widget _buildSectionHeader(String title) {
    return Padding(
      padding: const EdgeInsets.fromLTRB(16, 16, 16, 8),
      child: Text(
        title,
        style: GoogleFonts.inter(
          fontSize: 14,
          fontWeight: FontWeight.w600,
          color: AppTheme.brandPrimary,
          letterSpacing: 0.5,
        ),
      ),
    );
  }

  Widget _buildListTile({
    required IconData icon,
    required String title,
    required String subtitle,
    required Widget trailing,
    VoidCallback? onTap,
  }) {
    return ListTile(
      leading: Container(
        width: 40,
        height: 40,
        decoration: BoxDecoration(
          color: AppTheme.brandPrimary.withOpacity(0.1),
          borderRadius: BorderRadius.circular(8),
        ),
        child: Icon(icon, color: AppTheme.brandPrimary, size: 20),
      ),
      title: Text(
        title,
        style: GoogleFonts.inter(
          fontSize: 16,
          fontWeight: FontWeight.w500,
        ),
      ),
      subtitle: Text(
        subtitle,
        style: GoogleFonts.inter(
          fontSize: 14,
          color: Colors.grey.shade600,
        ),
      ),
      trailing: trailing,
      onTap: onTap,
    );
  }

  Widget _buildSwitchTile({
    required IconData icon,
    required String title,
    required String subtitle,
    required bool value,
    required ValueChanged<bool>? onChanged,
  }) {
    return ListTile(
      leading: Container(
        width: 40,
        height: 40,
        decoration: BoxDecoration(
          color: AppTheme.brandPrimary.withOpacity(0.1),
          borderRadius: BorderRadius.circular(8),
        ),
        child: Icon(icon, color: AppTheme.brandPrimary, size: 20),
      ),
      title: Text(
        title,
        style: GoogleFonts.inter(
          fontSize: 16,
          fontWeight: FontWeight.w500,
        ),
      ),
      subtitle: Text(
        subtitle,
        style: GoogleFonts.inter(
          fontSize: 14,
          color: Colors.grey.shade600,
        ),
      ),
      trailing: Switch(
        value: value,
        onChanged: onChanged,
        activeColor: AppTheme.brandPrimary,
      ),
    );
  }
}

class LogViewerScreen extends StatelessWidget {
  final _logger = LoggerService();

  LogViewerScreen({Key? key}) : super(key: key);

  @override
  Widget build(BuildContext context) {
    final logs = _logger.getAllLogs();

    return Scaffold(
      appBar: AppBar(
        title: Text(
          'Debug Logs',
          style: GoogleFonts.poppins(fontWeight: FontWeight.w600),
        ),
        backgroundColor: AppTheme.brandPrimary,
        foregroundColor: Colors.white,
      ),
      body: logs.isEmpty
          ? Center(
              child: Column(
                mainAxisAlignment: MainAxisAlignment.center,
                children: [
                  Icon(Icons.article_outlined, size: 64, color: Colors.grey),
                  const SizedBox(height: 16),
                  Text(
                    'No logs available',
                    style: GoogleFonts.inter(
                      fontSize: 16,
                      color: Colors.grey.shade600,
                    ),
                  ),
                ],
              ),
            )
          : SingleChildScrollView(
              padding: const EdgeInsets.all(16),
              child: SelectableText(
                logs,
                style: GoogleFonts.robotoMono(
                  fontSize: 12,
                  height: 1.5,
                ),
              ),
            ),
    );
  }
}
