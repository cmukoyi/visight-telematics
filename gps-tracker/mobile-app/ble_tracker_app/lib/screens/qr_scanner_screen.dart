import 'package:flutter/material.dart';
import 'package:mobile_scanner/mobile_scanner.dart';
import 'package:google_fonts/google_fonts.dart';

class QRScannerScreen extends StatefulWidget {
  const QRScannerScreen({Key? key}) : super(key: key);

  @override
  State<QRScannerScreen> createState() => _QRScannerScreenState();
}

class _QRScannerScreenState extends State<QRScannerScreen> {
  MobileScannerController controller = MobileScannerController();
  String? scannedCode;
  bool isProcessing = false;

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      backgroundColor: Colors.black,
      body: Stack(
        children: [
          // QR Scanner View
          MobileScanner(
            controller: controller,
            onDetect: _onDetect,
          ),

          // Top Info Bar
          SafeArea(
            child: Column(
              children: [
                Container(
                  margin: EdgeInsets.all(16),
                  padding: EdgeInsets.symmetric(horizontal: 20, vertical: 16),
                  decoration: BoxDecoration(
                    color: Colors.black.withOpacity(0.7),
                    borderRadius: BorderRadius.circular(16),
                  ),
                  child: Row(
                    children: [
                      Icon(
                        Icons.qr_code_scanner,
                        color: Colors.lightBlueAccent,
                        size: 28,
                      ),
                      SizedBox(width: 12),
                      Expanded(
                        child: Column(
                          crossAxisAlignment: CrossAxisAlignment.start,
                          children: [
                            Text(
                              'Scan QR Code',
                              style: GoogleFonts.poppins(
                                fontSize: 18,
                                fontWeight: FontWeight.bold,
                                color: Colors.white,
                              ),
                            ),
                            Text(
                              'Position QR code within frame',
                              style: GoogleFonts.inter(
                                fontSize: 12,
                                color: Colors.white70,
                              ),
                            ),
                          ],
                        ),
                      ),
                    ],
                  ),
                ),
                Spacer(),
                // Close Button
                Container(
                  margin: EdgeInsets.all(24),
                  child: ElevatedButton.icon(
                    icon: Icon(Icons.close),
                    label: Text(
                      'Cancel',
                      style: GoogleFonts.inter(
                        fontSize: 16,
                        fontWeight: FontWeight.w600,
                      ),
                    ),
                    onPressed: () {
                      Navigator.pop(context);
                    },
                    style: ElevatedButton.styleFrom(
                      backgroundColor: Colors.red,
                      foregroundColor: Colors.white,
                      padding: EdgeInsets.symmetric(horizontal: 32, vertical: 16),
                      shape: RoundedRectangleBorder(
                        borderRadius: BorderRadius.circular(16),
                      ),
                    ),
                  ),
                ),
              ],
            ),
          ),

          // Processing Overlay
          if (isProcessing)
            Container(
              color: Colors.black.withOpacity(0.8),
              child: Center(
                child: Column(
                  mainAxisSize: MainAxisSize.min,
                  children: [
                    CircularProgressIndicator(
                      valueColor: AlwaysStoppedAnimation<Color>(Colors.lightBlueAccent),
                    ),
                    SizedBox(height: 16),
                    Text(
                      'Processing QR Code...',
                      style: GoogleFonts.inter(
                        fontSize: 16,
                        fontWeight: FontWeight.w600,
                        color: Colors.white,
                      ),
                    ),
                  ],
                ),
              ),
            ),
        ],
      ),
    );
  }

  void _onDetect(BarcodeCapture capture) {
    if (isProcessing) return;
    
    final List<Barcode> barcodes = capture.barcodes;
    
    for (final barcode in barcodes) {
      final String? code = barcode.rawValue;
      
      if (code != null && code.isNotEmpty) {
        setState(() {
          isProcessing = true;
        });
        
        final imei = _extractIMEIFromQR(code);
        
        if (imei != null) {
          // Valid IMEI found
          controller.stop();
          Navigator.pop(context, imei);
          return;
        } else {
          // No valid IMEI found
          setState(() {
            isProcessing = false;
          });
          
          ScaffoldMessenger.of(context).showSnackBar(
            SnackBar(
              content: Text('❌ No valid IMEI found in QR code'),
              backgroundColor: Colors.red,
              duration: Duration(seconds: 2),
            ),
          );
          
          // Resume scanning after 2 seconds
          Future.delayed(Duration(seconds: 2), () {
            if (mounted) {
              setState(() {
                isProcessing = false;
              });
            }
          });
        }
        break;
      }
    }
  }

  String? _extractIMEIFromQR(String qrData) {
    print('🔍 Attempting to extract IMEI from: $qrData');

    // Pattern 1: MHub369F:IMEI868695060772926:MAC format
    final pattern1 = RegExp(r'IMEI(\d{15})', caseSensitive: false);
    final match1 = pattern1.firstMatch(qrData);
    if (match1 != null) {
      print('✅ Match Pattern 1: ${match1.group(1)}');
      return match1.group(1);
    }

    // Pattern 2: Plain IMEI (15 digits)
    final pattern2 = RegExp(r'\b(\d{15})\b');
    final match2 = pattern2.firstMatch(qrData);
    if (match2 != null) {
      print('✅ Match Pattern 2: ${match2.group(1)}');
      return match2.group(1);
    }

    // Pattern 3: Key-value format (imei=868695060734355)
    final pattern4 = RegExp(r'imei[=:]\s*(\d{15})', caseSensitive: false);
    final match4 = pattern4.firstMatch(qrData);
    if (match4 != null) {
      print('✅ Match Pattern 4: ${match4.group(1)}');
      return match4.group(1);
    }

    // Pattern 4: URL format
    final pattern5 = RegExp(r'/imei/(\d{15})', caseSensitive: false);
    final match5 = pattern5.firstMatch(qrData);
    if (match5 != null) {
      print('✅ Match Pattern 5: ${match5.group(1)}');
      return match5.group(1);
    }

    print('❌ No IMEI pattern matched in QR data');
    return null;
  }

  @override
  void dispose() {
    controller?.dispose();
    super.dispose();
  }
}
