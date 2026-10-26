"""ViSight Track API — FastAPI application wiring.

Routers: public auth + API v2, admin (incl. DataProfiler), customer portal,
container ops and i18n. Background work started here is limited to device
housekeeping and the critical-service log monitor; device data arrives through
the DataProfiler pipeline services (app/dataprofiler).
"""
import logging
import os
import secrets
from datetime import datetime
from time import perf_counter

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.database import init_db
from app.models_dataprofiler import Reseller, DataExchange, ResellerDevice, UnitType, DeviceEvent, Trip, TripBuilderState, ReportSchedule  # noqa: F401 — registers tables
from app import models_maintenance, models_reports  # noqa: F401 — registers tables
from app.routes_admin import router as admin_router, public_router as admin_public_router
from app.services import housekeeping_service
from app.services.critical_service_alert_service import critical_service_alerts
from app.services.email_service import EmailService

import asyncio

app = FastAPI(
    title="ViSight Track API",
    version="3.0.0",
    description="""
## ViSight Track API

Your fleet's data: vehicles, live positions, trips with routes, decoded events, places, alerts, reports and analytics.

### Authentication

1. **Get a token:** `POST /api/auth/login` with a portal user's email and password.
2. **Use it:** send `Authorization: Bearer <access_token>` with every request (in this page: **Authorize**, top right).

Tokens last 12 hours. The API answers exactly what that user may see in the web app — their user group, the vehicles
in their security group, and only what their roles allow. A dedicated user with only the features an integration needs
is the safest way to connect a system.

```bash
TOKEN=$(curl -s -X POST https://track.visighttelematics.co.za/api/auth/login \\
  -H "Content-Type: application/json" -d '{"email": "api@yourcompany.co.za", "password": "..."}' | jq -r .access_token)
curl "https://track.visighttelematics.co.za/api/v2/trips?date_from=2026-10-01T00:00:00Z" -H "Authorization: Bearer $TOKEN"
```

Times are ISO 8601 (UTC unless an offset is given). Distances are metres (`_m`) or kilometres (`_km`), speeds km/h.
""",
    docs_url="/docs",
    redoc_url="/redoc",
    openapi_url="/openapi.json",
    swagger_ui_parameters={
        "defaultModelsExpandDepth": -1,
        "persistAuthorization": True,
        "docExpansion": "list",
        "tryItOutEnabled": True,
    },
    openapi_tags=[
        {"name": "Authentication", "description": "Get a bearer token"},
        {"name": "Account", "description": "The token's user"},
        {"name": "Vehicles", "description": "Vehicles, their status and live position"},
        {"name": "Trips", "description": "Trips with distance, duration, addresses, routes and events"},
        {"name": "Events", "description": "Decoded device events (ignition, speeding, harsh driving, …)"},
        {"name": "Places", "description": "Places (geofences)"},
        {"name": "Reports", "description": "The web app's reports as JSON"},
        {"name": "Analytics", "description": "Measures by vehicle, group, driver or time"},
        {"name": "Devices (v2)", "description": "Earlier v2 endpoints: devices, movement history, geofences, alerts"},
    ]
)

# ==============================================================================
# PUBLIC API - Visible in /docs
# ==============================================================================

# Authentication API (login)
from app.routes_auth import router as auth_router  # noqa: E402
app.include_router(auth_router)

# API v2 (production endpoints)
from app.routes_api_v2 import router as api_v2_router  # noqa: E402
app.include_router(api_v2_router)

# Public API v2 — vehicles, trips, events, places, reports, analytics (same data and permissions as the web app)
from app.routes_api_public import router as api_public_router  # noqa: E402
app.include_router(api_public_router)

# ==============================================================================
# INTERNAL APIS - Hidden from /docs (dashboard/admin use only)
# ==============================================================================

# Include admin PUBLIC router (login, logs - no auth required)
app.include_router(admin_public_router, include_in_schema=False)

# Include admin router (hidden from public API docs, AUTH REQUIRED)
app.include_router(admin_router, include_in_schema=False)

# Include portal router (dashboard internal endpoints - hidden)
from app.routes_portal import router as portal_router  # noqa: E402
app.include_router(portal_router, include_in_schema=False)

# Include admin ops router (Docker container management - hidden)
from app.routes_ops import router as ops_router  # noqa: E402
app.include_router(ops_router, include_in_schema=False)

from app.routes_i18n import router as i18n_router  # noqa: E402
app.include_router(i18n_router, include_in_schema=False)

from app.routes_admin_i18n import router as admin_i18n_router  # noqa: E402
app.include_router(admin_i18n_router, include_in_schema=False)

# Customer app — dashboard KPIs, workspace events, inbox, reports (portal auth)
from app.routes_fleet import router as fleet_router  # noqa: E402
from app.routes_access import router as access_router  # noqa: E402
from app.routes_rules import router as rules_router  # noqa: E402
from app.routes_catalog import router as catalog_router  # noqa: E402
from app.routes_analytics import router as analytics_router  # noqa: E402
from app.routes_maintenance import router as maintenance_router  # noqa: E402
from app.routes_breakdowns import router as breakdowns_router  # noqa: E402
from app.routes_people import router as people_router  # noqa: E402
from app.routes_custom_reports import router as custom_reports_router  # noqa: E402
app.include_router(fleet_router, include_in_schema=False)
app.include_router(access_router, include_in_schema=False)
app.include_router(rules_router, include_in_schema=False)
app.include_router(catalog_router, include_in_schema=False)
app.include_router(analytics_router, include_in_schema=False)
app.include_router(maintenance_router, include_in_schema=False)
app.include_router(breakdowns_router, include_in_schema=False)
app.include_router(people_router, include_in_schema=False)
app.include_router(custom_reports_router, include_in_schema=False)

# DataProfiler — resellers, data exchanges, IMEI routing (admin auth required)
from app.routes_dataprofiler import router as dataprofiler_router  # noqa: E402
app.include_router(dataprofiler_router, include_in_schema=False)

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Verbose request logging for production incident diagnosis (disabled by default).
# Enable with PORTAL_VERBOSE_LOGGING=1 and tune threshold with PORTAL_VERBOSE_SLOW_MS.
_PORTAL_VERBOSE_LOGGING = os.getenv("PORTAL_VERBOSE_LOGGING", "0").strip().lower() in ("1", "true", "yes", "on")
_PORTAL_VERBOSE_SLOW_MS = int(os.getenv("PORTAL_VERBOSE_SLOW_MS", "800"))

def _is_verbose_path(path: str) -> bool:
    return path.startswith("/api/portal/") or path.startswith("/api/assets")


@app.middleware("http")
async def portal_request_timing_middleware(request, call_next):
    path = request.url.path
    if not _PORTAL_VERBOSE_LOGGING or not _is_verbose_path(path):
        return await call_next(request)

    req_id = request.headers.get("x-request-id") or secrets.token_hex(4)
    method = request.method
    query = request.url.query or "-"
    xff = request.headers.get("x-forwarded-for", "")
    client_ip = xff.split(",")[0].strip() if xff else (request.client.host if request.client else "unknown")
    ua = request.headers.get("user-agent", "-")
    started_at = perf_counter()
    status_code = 500

    try:
        response = await call_next(request)
        status_code = response.status_code
    except Exception:
        elapsed_ms = (perf_counter() - started_at) * 1000.0
        logger.exception(
            "portal-req exception req_id=%s method=%s path=%s query=%s ip=%s elapsed_ms=%.1f ua=%s",
            req_id,
            method,
            path,
            query,
            client_ip,
            elapsed_ms,
            ua,
        )
        raise

    elapsed_ms = (perf_counter() - started_at) * 1000.0
    response.headers["X-Portal-Req-Id"] = req_id
    response.headers["X-Portal-Elapsed-Ms"] = f"{elapsed_ms:.1f}"

    if elapsed_ms >= _PORTAL_VERBOSE_SLOW_MS or status_code >= 500:
        logger.warning(
            "portal-req slow req_id=%s method=%s path=%s query=%s status=%s elapsed_ms=%.1f ip=%s ua=%s",
            req_id,
            method,
            path,
            query,
            status_code,
            elapsed_ms,
            client_ip,
            ua,
        )
    else:
        logger.info(
            "portal-req req_id=%s method=%s path=%s status=%s elapsed_ms=%.1f ip=%s",
            req_id,
            method,
            path,
            status_code,
            elapsed_ms,
            client_ip,
        )
    return response

# Audit trail of changes made through the customer portal (services/audit_service.py)
from app.services.audit_service import AuditMiddleware
app.add_middleware(AuditMiddleware)

# CORS middleware - restrict to known origins only
_cors_origins_env = os.getenv("CORS_ORIGINS", "https://track.visighttelematics.co.za")
_allowed_origins = [o.strip() for o in _cors_origins_env.split(",") if o.strip()]
app.add_middleware(
    CORSMiddleware,
    allow_origins=_allowed_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Initialize email service
email_service = EmailService()
_background_tasks: list = []


@app.on_event("startup")
async def startup_event():
    # Tables are created by Alembic (entrypoint) and init_admin.py; init_db
    # only adds genuinely new tables.
    init_db()
    print(f"SMTP configured: {email_service.smtp_host}:{email_service.smtp_port}")

    # Wire up DB log handler so backend logs appear in admin portal
    from app.db_log_handler import setup_db_logging
    setup_db_logging(level=logging.WARNING)

    _background_tasks.extend(housekeeping_service.start())  # keep references so tasks aren't garbage-collected
    print("🧹 Device housekeeping started (offline alerts, alert purge, package expiry)")

    # Critical-service error monitor (subscriptions drive whether emails send)
    asyncio.create_task(critical_service_alerts.start())
    print("🚨 Critical service alert monitor started (60-second cycle)")


@app.on_event("shutdown")
async def shutdown_event():
    critical_service_alerts.stop()


@app.get("/", include_in_schema=False)
def root():
    return {
        "message": "ViSight Track API",
        "status": "running",
        "timestamp": datetime.utcnow().isoformat()
    }

@app.get("/health", include_in_schema=False)
def health_check():
    """Health check endpoint"""
    return {
        "status": "healthy",
        "timestamp": datetime.utcnow().isoformat()
    }

@app.get("/api/health", include_in_schema=False)
def api_health_check():
    """API health check endpoint"""
    return {
        "status": "healthy",
        "timestamp": datetime.utcnow().isoformat()
    }


@app.get("/api/branding", include_in_schema=False)
def branding():
    """Public branding endpoint — drives white-label theming.

    All values come from BRAND_* environment variables; the frontend reads
    this at boot and overrides <title>, theme-color, header text, primary
    colour, etc."""
    
    # Parse disabled features from env (comma-separated)
    disabled_features = [
        f.strip() for f in os.getenv("TENANT_DISABLED_FEATURES", "").split(",") if f.strip()
    ]
    
    return {
        "name":         os.getenv("BRAND_NAME", "ViSight Track"),
        "product":      os.getenv("BRAND_PRODUCT", "ViSight Track Portal"),
        "domain":       os.getenv("BRAND_DOMAIN", "track.visighttelematics.co.za"),
        "supportEmail": os.getenv("BRAND_SUPPORT_EMAIL", "support@visighttelematics.co.za"),
        "fromEmail":    os.getenv("BRAND_FROM_EMAIL", "noreply@visighttelematics.co.za"),
        "primaryColor": os.getenv("BRAND_PRIMARY_COLOR", "#3B82F6"),
        "themeColor":   os.getenv("BRAND_THEME_COLOR", "#0F1117"),
        "tagline":      os.getenv("BRAND_TAGLINE", "Live vehicle tracking, geofencing, and reporting."),
        # MapTiler key. No default — MAPTILER_KEY must be set in backend/.env
        # (free-tier keys are origin-restricted).
        "maptilerKey":  os.getenv("MAPTILER_KEY") or None,
        # Feature gates: list of feature keys (tab names) that should be hidden
        # from navigation and disabled at API level. Set via TENANT_DISABLED_FEATURES env.
        "disabledFeatures": disabled_features,
    }


@app.get("/api/manifest", include_in_schema=False)
def manifest():
    """Deployment manifest endpoint - lists API capabilities and version info"""
    return {
        "deployment": {
            "timestamp": datetime.utcnow().isoformat(),
            "version": "visight-track-api",
            "environment": os.getenv("NODE_ENV", "production")
        },
        "api": {
            "version": "v2",
            "endpoints": {
                "health": "/api/health",
                "manifest": "/api/manifest",
                "auth": "/api/auth/login",
                "devices": "/api/v2/devices",
                "movement_history": "/api/v2/movement-history/{imei}",
                "geofences": "/api/v2/geofences",
                "alerts": "/api/v2/alerts",
            }
        },
        "status": "operational"
    }


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
