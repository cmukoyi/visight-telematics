#!/bin/bash
# Pre-deployment validation - Ensures configuration correctness

set -e

echo "🔍 BeaconTelematics Deployment Validation"
echo "=========================================="

# 1. Check docker-compose.yml has correct ports
echo ""
echo "✓ Checking docker-compose.yml ports..."
if grep -q "- 80:80" docker-compose.yml && grep -q "- 443:443" docker-compose.yml; then
    echo "  ✅ docker-compose.yml: nginx exposed on 80:80 and 443:443"
else
    echo "  ❌ ERROR: docker-compose.yml has wrong port mappings!"
    echo "  Expected: 80:80 and 443:443"
    grep "ports:" -A 3 docker-compose.yml | grep -E "80|443" || true
    exit 1
fi

# 2. Check firewall rules
echo ""
echo "✓ Checking UFW firewall rules..."
if ufw status | grep -q "80/tcp.*ALLOW"; then
    echo "  ✅ Firewall: Port 80 is OPEN"
else
    echo "  ❌ ERROR: Port 80 not allowed in firewall!"
    exit 1
fi

if ufw status | grep -q "443/tcp.*ALLOW"; then
    echo "  ✅ Firewall: Port 443 is OPEN"
else
    echo "  ❌ ERROR: Port 443 not allowed in firewall!"
    exit 1
fi

# 3. Check BeaconTelemticsSetup.md documents correct ports
echo ""
echo "✓ Checking documentation..."
if grep -q "80 | 80 | HTTP" ../BeaconTelemticsSetup.md && grep -q "443 | 443 | HTTPS" ../BeaconTelemticsSetup.md; then
    echo "  ✅ Documentation: Ports correctly documented as 80/443"
else
    echo "  ⚠️  WARNING: Documentation may have outdated port info"
fi

# 4. Check SSL certificate
echo ""
echo "✓ Checking SSL certificate..."
if [ -f "/etc/letsencrypt/live/beacontelematics.co.uk/fullchain.pem" ]; then
    EXPIRY=$(openssl x509 -in /etc/letsencrypt/live/beacontelematics.co.uk/fullchain.pem -noout -enddate | cut -d= -f2)
    echo "  ✅ SSL Certificate: Valid until $EXPIRY"
else
    echo "  ❌ ERROR: SSL certificate not found!"
    exit 1
fi

# 5. Summary
echo ""
echo "=========================================="
echo "✅ All validation checks PASSED"
echo "Safe to proceed with deployment"
echo "=========================================="
