import 'package:flutter/material.dart';
import 'package:google_fonts/google_fonts.dart';
import 'package:ble_tracker_app/theme/app_theme.dart';

class MapBubble extends StatelessWidget {
  final String title;
  final String? description;
  final String? subtitle;
  final Offset position;
  final VoidCallback onClose;
  
  const MapBubble({
    Key? key,
    required this.title,
    this.description,
    this.subtitle,
    required this.position,
    required this.onClose,
  }) : super(key: key);

  @override
  Widget build(BuildContext context) {
    // Responsive width - adapt based on screen size
    final screenWidth = MediaQuery.of(context).size.width;
    final maxBubbleWidth = screenWidth < 360 ? screenWidth * 0.75 : 280.0;
    
    return Positioned(
      left: position.dx,
      top: position.dy,
      child: GestureDetector(
        onTap: () {}, // Prevent closing when tapping inside bubble
        child: Container(
          constraints: BoxConstraints(maxWidth: maxBubbleWidth),
          decoration: BoxDecoration(
            color: Colors.white,
            borderRadius: BorderRadius.circular(12),
            boxShadow: [
              BoxShadow(
                color: Colors.black.withOpacity(0.15),
                blurRadius: 12,
                offset: Offset(0, 4),
              ),
            ],
            border: Border.all(
              color: AppTheme.brandPrimary.withOpacity(0.2),
              width: 1,
            ),
          ),
          child: Stack(
            children: [
              Padding(
                padding: EdgeInsets.all(12),
                child: Column(
                  mainAxisSize: MainAxisSize.min,
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    // Title
                    Text(
                      title,
                      style: GoogleFonts.inter(
                        fontSize: 13,
                        fontWeight: FontWeight.w700,
                        color: AppTheme.brandPrimary,
                      ),
                      maxLines: 2,
                      overflow: TextOverflow.ellipsis,
                    ),
                    
                    if (subtitle != null) ...[
                      SizedBox(height: 4),
                      Text(
                        subtitle!,
                        style: GoogleFonts.inter(
                          fontSize: 11,
                          color: Colors.grey.shade600,
                        ),
                        maxLines: 1,
                        overflow: TextOverflow.ellipsis,
                      ),
                    ],
                    
                    if (description != null && description!.isNotEmpty) ...[
                      SizedBox(height: 8),
                      Container(
                        padding: EdgeInsets.symmetric(horizontal: 8, vertical: 6),
                        decoration: BoxDecoration(
                          color: Colors.grey.shade50,
                          borderRadius: BorderRadius.circular(6),
                        ),
                        child: Text(
                          description!,
                          style: GoogleFonts.inter(
                            fontSize: 12,
                            color: Colors.grey.shade800,
                          ),
                          maxLines: 3,
                          overflow: TextOverflow.ellipsis,
                        ),
                      ),
                    ],
                  ],
                ),
              ),
              
              // Close button
              Positioned(
                top: 4,
                right: 4,
                child: GestureDetector(
                  onTap: onClose,
                  child: Container(
                    padding: EdgeInsets.all(4),
                    decoration: BoxDecoration(
                      color: Colors.grey.shade200,
                      shape: BoxShape.circle,
                    ),
                    child: Icon(
                      Icons.close,
                      size: 14,
                      color: Colors.grey.shade700,
                    ),
                  ),
                ),
              ),
            ],
          ),
        ),
      ),
    );
  }
}
