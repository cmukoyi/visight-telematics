#!/bin/bash
# Setup environment files for BeaconTelematics on production server
# Run this on your LOCAL machine, it will SSH to the server and create the files

set -e

SERVER="root@161.35.38.209"
DEPLOY_DIR="~/beacon-telematics/gps-tracker"

echo "🔐 Setting up BeaconTelematics environment files..."
echo ""

# Generate secure passwords
DB_PASSWORD=$(openssl rand -base64 32)
JWT_SECRET=$(python3 -c "import secrets; print(secrets.token_urlsafe(32))" 2>/dev/null || openssl rand -base64 32)

echo "📝 Generated credentials:"
echo "Database Password: $DB_PASSWORD"
echo "JWT Secret: $JWT_SECRET"
echo ""

# Prompt for SendGrid API key
read -p "Enter your SendGrid API Key (or press Enter to skip): " SENDGRID_KEY
if [ -z "$SENDGRID_KEY" ]; then
    SENDGRID_KEY="your_sendgrid_api_key_here"
    echo "⚠️  Using placeholder SendGrid key - email features won't work"
fi

echo ""
echo "🚀 Creating .env files on server..."

# Create root .env file
ssh $SERVER "cat > $DEPLOY_DIR/.env" <<EOF
# Database Configuration
POSTGRES_USER=beacon_user
POSTGRES_PASSWORD=$DB_PASSWORD
POSTGRES_DB=beacon_telematics

# MZone Client Secret
MZONE_CLIENT_SECRET=g_SkQ.B.z3TeBU\$g#hVeP#c2
EOF

echo "✅ Created $DEPLOY_DIR/.env"

# Create backend .env file
ssh $SERVER "cat > $DEPLOY_DIR/backend/.env" <<EOF
# Database Configuration
DATABASE_URL=postgresql://beacon_user:$DB_PASSWORD@db:5432/beacon_telematics

# JWT Secret Key
SECRET_KEY=$JWT_SECRET

# SendGrid Email Configuration
SENDGRID_API_KEY=$SENDGRID_KEY
FROM_EMAIL=noreply@beacontelematics.co.uk

# MZone API Configuration
MZONE_TOKEN_URL=https://login.mzoneweb.net/connect/token
MZONE_API_BASE=https://live.mzoneweb.net/mzone62.api
MZONE_CLIENT_ID=mz-scopeuk
MZONE_CLIENT_SECRET=g_SkQ.B.z3TeBU\$g#hVeP#c2
MZONE_USERNAME=ScopeUKAPI
MZONE_PASSWORD=ScopeUKAPI01!
MZONE_VEHICLE_GROUP_ID=e7042dff-f0d8-42ec-9324-c4b730cf177d

# Optional Settings
DEBUG=False
ENVIRONMENT=production
EOF

echo "✅ Created $DEPLOY_DIR/backend/.env"

echo ""
echo "🔄 Restarting containers to apply configuration..."
ssh $SERVER "cd $DEPLOY_DIR && docker-compose restart"

echo ""
echo "⏳ Waiting 15 seconds for containers to stabilize..."
sleep 15

echo ""
echo "🏥 Testing health endpoints..."
echo ""

echo "Backend API:"
ssh $SERVER "curl -f http://localhost:8001/api/health" && echo "✅ Backend healthy!" || echo "❌ Backend not responding"

echo ""
echo "Flutter Web:"
ssh $SERVER "curl -f -I http://localhost:3012/" > /dev/null 2>&1 && echo "✅ Flutter web healthy!" || echo "❌ Flutter web not responding"

echo ""
echo "Nginx:"
ssh $SERVER "curl -f http://localhost:8080/api/health" && echo "✅ Nginx routing healthy!" || echo "❌ Nginx not responding"

echo ""
echo "✅ Environment setup complete!"
echo ""
echo "📊 Container status:"
ssh $SERVER "cd $DEPLOY_DIR && docker-compose ps"

echo ""
echo "🌐 Access your deployment:"
echo "   http://beacontelematics.co.uk:8080/"
echo "   http://beacontelematics.co.uk:8080/api/health"
echo ""
echo "💾 IMPORTANT: Save these credentials securely:"
echo "   Database Password: $DB_PASSWORD"
echo "   JWT Secret: $JWT_SECRET"
