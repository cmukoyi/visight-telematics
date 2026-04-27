#!/bin/bash

# Digital Ocean Server Setup Script
# Run this script on your Digital Ocean droplet to prepare for deployment

set -e

echo "🚀 Setting up GPS Tracker on Digital Ocean..."

# Update system
echo "📦 Updating system packages..."
sudo apt-get update
sudo apt-get upgrade -y

# Install Docker
echo "🐳 Installing Docker..."
if ! command -v docker &> /dev/null; then
    curl -fsSL https://get.docker.com -o get-docker.sh
    sudo sh get-docker.sh
    sudo usermod -aG docker $USER
    rm get-docker.sh
    echo "✅ Docker installed"
else
    echo "✅ Docker already installed"
fi

# Install Docker Compose
echo "🐳 Installing Docker Compose..."
if ! command -v docker-compose &> /dev/null; then
    sudo curl -L "https://github.com/docker/compose/releases/latest/download/docker-compose-$(uname -s)-$(uname -m)" -o /usr/local/bin/docker-compose
    sudo chmod +x /usr/local/bin/docker-compose
    echo "✅ Docker Compose installed"
else
    echo "✅ Docker Compose already installed"
fi

# Install Git
echo "📝 Installing Git..."
sudo apt-get install -y git

# Install other useful tools
echo "🔧 Installing additional tools..."
sudo apt-get install -y curl wget nano htop

# Setup firewall
echo "🔒 Configuring firewall..."
sudo ufw allow OpenSSH
sudo ufw allow 80/tcp    # HTTP
sudo ufw allow 443/tcp   # HTTPS
sudo ufw allow 5001/tcp  # Backend API
sudo ufw allow 3000/tcp  # Admin Dashboard
sudo ufw allow 3001/tcp  # Customer Dashboard
sudo ufw --force enable

# Create application directory
echo "📁 Creating application directory..."
mkdir -p ~/gps-tracker
cd ~/gps-tracker

# Setup log rotation
echo "📝 Setting up log rotation..."
sudo tee /etc/logrotate.d/gps-tracker > /dev/null << 'EOF'
/var/lib/docker/containers/*/*.log {
    rotate 7
    daily
    compress
    delaycompress
    missingok
    notifempty
    copytruncate
    maxsize 100M
}
EOF

# Create docker network
echo "🌐 Creating Docker network..."
docker network create gps-tracker-network 2>/dev/null || echo "Network already exists"

# Setup Docker log limits
echo "📊 Configuring Docker logging..."
sudo tee /etc/docker/daemon.json > /dev/null << 'EOF'
{
  "log-driver": "json-file",
  "log-opts": {
    "max-size": "10m",
    "max-file": "3"
  }
}
EOF

sudo systemctl restart docker

echo ""
echo "✅ Digital Ocean server setup complete!"
echo ""
echo "Next steps:"
echo "1. Add your SSH public key to GitHub: https://github.com/settings/keys"
echo "2. Configure GitHub Actions secrets:"
echo "   - DO_SERVER_IP: $(curl -s ifconfig.me)"
echo "   - DO_USER: $USER"
echo "   - DO_SSH_PRIVATE_KEY: (your SSH private key)"
echo "   - MZONE_CLIENT_ID, MZONE_CLIENT_SECRET"
echo "   - MPROFILER_USERNAME, MPROFILER_PASSWORD"
echo "   - SECRET_KEY: (generate with: openssl rand -hex 32)"
echo "   - DATABASE_URL: postgresql://user:pass@postgres:5432/dbname"
echo "   - SMTP_USERNAME, SMTP_PASSWORD"
echo ""
echo "3. Push your code to GitHub main branch"
echo "4. GitHub Actions will automatically deploy"
echo ""
echo "Server IP: $(curl -s ifconfig.me)"
echo "SSH User: $USER"
