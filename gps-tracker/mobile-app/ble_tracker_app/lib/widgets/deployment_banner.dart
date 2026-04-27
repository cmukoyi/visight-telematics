import 'package:flutter/material.dart';
import 'package:google_fonts/google_fonts.dart';
import 'package:ble_tracker_app/theme/app_theme.dart';
import 'package:ble_tracker_app/services/deployment_monitor_service.dart';

class DeploymentBanner extends StatefulWidget {
  const DeploymentBanner({Key? key}) : super(key: key);

  @override
  State<DeploymentBanner> createState() => _DeploymentBannerState();
}

class _DeploymentBannerState extends State<DeploymentBanner>
    with SingleTickerProviderStateMixin {
  late AnimationController _animationController;
  late Animation<Offset> _slideAnimation;
  late DeploymentMonitorService _deploymentMonitor;

  @override
  void initState() {
    super.initState();
    _deploymentMonitor = DeploymentMonitorService();

    _animationController = AnimationController(
      duration: Duration(milliseconds: 500),
      vsync: this,
    );

    _slideAnimation = Tween<Offset>(
      begin: Offset(0, -1),
      end: Offset.zero,
    ).animate(CurvedAnimation(parent: _animationController, curve: Curves.easeOut));

    // Listen to deployment state changes
    _deploymentMonitor.deploymentStateChanged.listen((isDeploying) {
      if (isDeploying) {
        _animationController.forward();
      } else {
        _animationController.reverse();
      }
    });
  }

  @override
  void dispose() {
    _animationController.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    return SlideTransition(
      position: _slideAnimation,
      child: StreamBuilder<bool>(
        stream: _deploymentMonitor.deploymentStateChanged,
        initialData: _deploymentMonitor.isDeploying,
        builder: (context, snapshot) {
          final isDeploying = snapshot.data ?? false;

          if (!isDeploying) {
            return SizedBox.shrink();
          }

          return Container(
            color: Colors.orange.shade600,
            child: SafeArea(
              bottom: false,
              child: Padding(
                padding: EdgeInsets.symmetric(horizontal: 16, vertical: 12),
                child: Row(
                  children: [
                    SizedBox(
                      width: 20,
                      height: 20,
                      child: CircularProgressIndicator(
                        strokeWidth: 2,
                        valueColor: AlwaysStoppedAnimation<Color>(Colors.white),
                      ),
                    ),
                    SizedBox(width: 16),
                    Expanded(
                      child: Column(
                        mainAxisSize: MainAxisSize.min,
                        crossAxisAlignment: CrossAxisAlignment.start,
                        children: [
                          Text(
                            'App Update in Progress',
                            style: GoogleFonts.inter(
                              fontSize: 13,
                              fontWeight: FontWeight.w700,
                              color: Colors.white,
                            ),
                          ),
                          SizedBox(height: 2),
                          Text(
                            'Please wait a few minutes...',
                            style: GoogleFonts.inter(
                              fontSize: 12,
                              color: Colors.white.withOpacity(0.9),
                            ),
                          ),
                        ],
                      ),
                    ),
                  ],
                ),
              ),
            ),
          );
        },
      ),
    );
  }
}
