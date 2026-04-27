# Beacon Telematics - GPS Tracker Application

Real-time GPS tracking application with geofence alerts, email notifications, and multi-platform support.

🌐 **Production**: https://beacontelematics.co.uk  
🖥️ **Server**: ubuntu-s-1vcpu-512mb-10gb-lon1-01 (161.35.38.209)  
📧 **Email**: Powered by SendGrid  

## 🎯 Features

- ✅ **Real-time GPS Tracking** via MZone API integration
- ✅ **Geofence Alerts** with customizable zones (entry/exit notifications)
- ✅ **Email Notifications** for PIN verification and geofence events
- ✅ **Multi-platform Mobile App** (iOS, Android, Web)
- ✅ **Admin Dashboard** for system management
- ✅ **Customer Dashboard** for end users
- ✅ **Automatic Location Refresh** every 10 minutes
- ✅ **Custom Tracker Descriptions** synced from MZone API

## 📁 Project Structure

```
beaconTelematics/
├── .github/workflows/          # CI/CD pipelines
├── deploy/                     # Deployment scripts
├── gps-tracker/
│   ├── backend/               # FastAPI backend
│   │   ├── app/
│   │   │   ├── services/      # Email, MZone, Geofence services
│   │   │   ├── models.py      # Database models
│   │   │   └── main.py        # API endpoints
│   │   ├── alembic/           # Database migrations
│   │   └── requirements.txt
│   ├── admin-dashboard/       # Admin UI (Node.js + Express)
│   ├── customer-dashboard/    # Customer UI (Node.js + Express)
│   ├── mobile-app/            # Flutter mobile app
│   │   └── ble_tracker_app/
│   └── nginx/                 # Reverse proxy configuration
├── DEPLOYMENT.md              # General deployment guide
├── PRODUCTION_CONFIG.md       # PinPlot-specific production config
├── SENDGRID_SETUP.md         # Email service setup guide
└── README.md                  # This file
```

## 🚀 Quick Start

### Local Development

1. **Clone the repository**
```bash
git clone https://github.com/cmukoyi/beaconTelematics.git
cd beaconTelematics
```

2. **Configure environment variables**
```bash
cd gps-tracker/backend
cp .env.example .env
# Edit .env with your credentials
```

3. **Start services with Docker**
```bash
cd gps-tracker
docker-compose up -d
```

4. **Access services**
- Backend API: http://localhost:5001/docs
- Admin Dashboard: http://localhost:3000
- Customer Dashboard: http://localhost:3001
- MailHog (email testing): http://localhost:8025

### Production Deployment

Deployment to **beacontelematics.co.uk** is automated via GitHub Actions.

Push to main branch triggers automatic deployment:
```bash
git push origin main
```

Monitor deployment: https://github.com/cmukoyi/beaconTelematics/actions

## 🔧 Technology Stack

### Backend
- **Framework**: FastAPI (Python 3.11)
- **Database**: PostgreSQL 15
- **Email**: SendGrid API (Free tier: 100 emails/day)
- **Authentication**: JWT tokens with email verification
- **Integrations**: MZone API, MProfiler API

### Frontend
- **Admin Dashboard**: Node.js + Express + HTML/CSS
- **Customer Dashboard**: Node.js + Express + HTML/CSS
- **Mobile App**: Flutter 3.x (iOS, Android, Web)

### Infrastructure
- **Deployment**: Digital Ocean Ubuntu 22.04
- **Containerization**: Docker + Docker Compose
- **CI/CD**: GitHub Actions
- **Reverse Proxy**: Nginx
- **SSL**: Let's Encrypt

## 📱 Mobile App

### Development
```bash
cd gps-tracker/mobile-app/ble_tracker_app
flutter pub get
flutter run
```

### Build for Production
```bash
# Android
flutter build apk --release

# iOS
flutter build ios --release

# Web
flutter build web
```

### Configuration

Update backend URL in `lib/services/auth_service.dart`:
```dart
// Development
static const String baseUrl = 'http://localhost:8001';

// Production
static const String baseUrl = 'https://beacontelematics.co.uk/api';
```

## 📧 Email Notifications

The system sends emails for:
- **Verification PINs** - 6-digit codes for user registration
- **Welcome Emails** - After successful account verification
- **Geofence Alerts** - When tracker enters/exits geofenced areas

**Email Provider**: SendGrid  
**From Email**: noreply@beacontelematics.co.uk

## 🗄️ Database Schema

Key tables:
- `users` - User accounts with email verification
- `ble_tags` - GPS trackers (IMEI, description, device_name)
- `pois` - Points of Interest (geofence zones)
- `geofence_alerts` - Alert history for geofence events

Migrations managed with Alembic:
```bash
cd gps-tracker/backend
alembic upgrade head
```

## 🔐 Environment Variables

### Required for Production

```bash
# Application
DEBUG=False
SECRET_KEY=<generate-with-openssl-rand-hex-32>

# Database
DATABASE_URL=postgresql://gpsuser:password@postgres:5432/gpsdb

# Email (SendGrid)
SENDGRID_API_KEY=SG.your-api-key-here
FROM_EMAIL=noreply@beacontelematics.co.uk

# MZone API
MZONE_TOKEN_URL=https://login.mzoneweb.net/connect/token
MZONE_API_BASE=https://live.mzoneweb.net/mzone62.api
MZONE_CLIENT_ID=mz-scopeuk
MZONE_CLIENT_SECRET=g_SkQ.B.z3TeBU$g#hVeP#c2
MZONE_USERNAME=ScopeUKAPI
MZONE_PASSWORD=ScopeUKAPI01!
MZONE_VEHICLE_GROUP_ID=e7042dff-f0d8-42ec-9324-c4b730cf177d
```

See [.env.example](.env.example) for complete list.

## 🚦 API Endpoints

### Authentication
- `POST /api/v1/auth/register` - Register new user
- `POST /api/v1/auth/verify` - Verify email with PIN
- `POST /api/v1/auth/login` - Login user
- `POST /api/v1/auth/resend-pin` - Resend verification PIN

### Vehicles
- `GET /api/vehicles` - Get all tracked vehicles
- `POST /api/tags/add` - Add new tracker

### Geofencing
- `GET /api/pois` - List all POIs
- `POST /api/pois` - Create new POI
- `POST /api/pois/{poi_id}/arm` - Arm geofence
- `POST /api/pois/{poi_id}/disarm` - Disarm geofence

**Full API Documentation**: https://beacontelematics.co.uk/api/docs

## 🔄 Automatic Features

- **Location Refresh**: Every 10 minutes on map screen
- **Geofence Monitoring**: Continuous checking when geofences are armed
- **Description Sync**: Auto-sync tracker descriptions from MZone API
- **Email Alerts**: Instant notifications for geofence events

## 📊 Monitoring

### Health Checks
```bash
# Backend health
curl https://beacontelematics.co.uk/api/health

# Database connection
ssh root@161.35.38.209 'cd ~/beacon-telematics/gps-tracker && docker-compose exec beacon_telematics_db psql -U beacon_user -c "SELECT 1;"'
```

### Logs
```bash
# SSH to server
ssh root@161.35.38.209

# View logs
cd ~/beacon-telematics/gps-tracker
docker-compose logs -f backend
docker-compose logs -f admin
docker-compose logs -f customer
```

### Email Analytics
- SendGrid Dashboard: https://app.sendgrid.com
- Activity Feed for real-time email tracking

## 🐛 Troubleshooting

### Common Issues

**Emails not sending**
- Check SendGrid API key is configured
- Verify sender email in SendGrid dashboard
- Check backend logs: `docker-compose logs backend | grep "Email"`

**Location not loading**
- Verify MZone OAuth credentials
- Check backend logs for OAuth errors
- Ensure tracker IMEI is correct

**Geofence alerts not triggering**
- Ensure geofence is armed
- Check user has email alerts enabled
- Verify tracker is inside/outside geofence area

## 📚 Documentation

Documentation files are available locally but not tracked in git:
- Local development setup guides
- Email service configuration
- Geofence testing procedures
- Production deployment guides

## 🤝 Contributing

1. Create feature branch: `git checkout -b feature/my-feature`
2. Make changes and test locally
3. Commit: `git commit -m "Add my feature"`
4. Push: `git push origin feature/my-feature`
5. Create Pull Request

## 📝 License

Proprietary - All rights reserved

## 🔗 Links

- **Production Site**: https://beacontelematics.co.uk
- **Admin Dashboard**: https://beacontelematics.co.uk/admin
- **Customer Dashboard**: https://beacontelematics.co.uk/customer
- **API Docs**: https://beacontelematics.co.uk/api/docs
- **GitHub Actions**: https://github.com/cmukoyi/beaconTelematics/actions
- **Server**: ubuntu-s-1vcpu-512mb-10gb-lon1-01 (161.35.38.209)

## 📞 Support

- SSH to server and check logs: `ssh root@161.35.38.209`
- Monitor GitHub Actions for deployment status
- Check container health: `docker ps | grep beacon_telematics`

---

**Beacon Telematics** - Professional GPS Tracking Solution

**Version**: 1.0.0  
**Last Updated**: March 3, 2026  
**Production URL**: https://pinplot.me  
**Server**: 161.35.38.209
