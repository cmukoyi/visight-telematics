# Beacon QR/NFC Guide Manual Deployment

**Date:** June 22, 2026  
**Issue:** Tenant brand drift in CI/CD pipeline  

## Problem

The `QR_NFC_Guide_Beacon.html` file contains tenant-specific branding ("Beacon Telematics") which triggers the tenant brand drift check in the CI/CD pipeline. This file cannot be included in the shared PinPlot-HPS repository.

## Solution

The Beacon QR/NFC guide must be deployed **manually** to Beacon production servers only.

### Deployment Steps for Beacon Servers

1. **Create the directory and copy the file:**
   ```bash
   # SSH into Beacon server and create directory
   ssh root@beacontelematics.co.uk "mkdir -p /root/beacon-telematics/gps-tracker/customer-dashboard/public/customer/help"
   
   # Copy from local machine
   scp features_dev/QR_NFC_Guide_Beacon.html root@beacontelematics.co.uk:/root/beacon-telematics/gps-tracker/customer-dashboard/public/customer/help/
   ```

2. **Restart the customer dashboard container:**
   ```bash
   ssh root@beacontelematics.co.uk "docker restart beacon_telematics_customer"
   ```

3. **Verify the file is accessible:**
   ```bash
   curl https://beacontelematics.co.uk/customer/help/QR_NFC_Guide_Beacon.html
   ```

## How the Code Works

The `qrOpenHelp()` function in `index.html` detects the tenant:

```javascript
const brandName = (window.APP_BRANDING && window.APP_BRANDING.name) || 'PinPlot';
const isBeacon = brandName.toLowerCase().includes('beacon');
const guidePath = isBeacon ? 'QR_NFC_Guide_Beacon.html' : 'QR_NFC_Guide_Pinplot.html';
```

- **PinPlot tenants:** Opens `/customer/help/QR_NFC_Guide_Pinplot.html` (included in shared repo)
- **Beacon tenants:** Opens `/customer/help/QR_NFC_Guide_Beacon.html` (deployed manually)

## Files Location

- **Source file:** `/Users/carl/Documents/MobileCode/Pinplot/features_dev/QR_NFC_Guide_Beacon.html`
- **Beacon deployment path:** `/customer/help/QR_NFC_Guide_Beacon.html`
- **PinPlot guide (in repo):** `gps-tracker/customer-dashboard/public/customer/help/QR_NFC_Guide_Pinplot.html`

## Alternative: Docker Volume Mount

For containerized deployments, mount the guide file as a volume:

```yaml
# docker-compose.yml
services:
  customer-dashboard:
    volumes:
      - ./tenants/beacon/QR_NFC_Guide_Beacon.html:/app/public/customer/help/QR_NFC_Guide_Beacon.html:ro
```

## Notes

- The PinPlot guide remains in the shared repository and deploys automatically
- The Beacon guide must be deployed after each server rebuild/reset
- If the Beacon guide is missing, users will see a 404 error when clicking "How To"
- Consider adding a health check to verify the guide file exists on Beacon servers

---

**Commit:** Removed from eff7165, fixing tenant brand drift  
**Related:** IMEI_MAC_QR_UPDATES.md, QR_NFC_COLOR_THEMING_FIX.md
