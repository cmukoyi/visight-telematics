"""
Scope device provider.

Implements the Strategy interface for tags registered on the Scope / MZone
platform.

Validation calls the Scope unitconnections API to confirm the IMEI exists
before the tag is registered.  Credentials are read from environment
variables so they are never hard-coded in source.

    SCOPE_API_BASE_URL  — base URL of the Scope REST API
                          default: https://live.scopemp.net/Scope.MProfilerIa.WPI/api/v1
    SCOPE_AUTH_HEADER   — value of the Authorization header (Basic …)
                          Required. Set this in the server .env file — never commit a real
                          token to source control.
"""
import os
import re

import httpx

from .base_provider import DeviceTagProvider, TagValidationResult

_SCOPE_API_BASE = os.getenv(
    "SCOPE_API_BASE_URL",
    "https://live.scopemp.net/Scope.MProfilerIa.WPI/api/v1",
)
# No default — must be set in .env on the server.
# See gps-tracker/backend/.env.example for the variable name.
_SCOPE_AUTH = os.getenv("SCOPE_AUTH_HEADER", "")


class ScopeTagProvider(DeviceTagProvider):
    """
    Scope (Series 1) BLE tag provider.

    Validation flow:
      1. Quick structural check — must be a 15-digit IMEI or valid GUID.
      2. GET /units/unitconnections/{imei} on the Scope platform.
         • 200 → tag exists and can be added.
         • 404 → "Unknown Tag or incorrect type".
         • Other / network error → fail closed with a clear message.
    """

    _IMEI_RE = re.compile(r"^\d{15}$")
    _GUID_RE = re.compile(
        r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$",
        re.IGNORECASE,
    )

    @property
    def provider_name(self) -> str:
        return "Scope"

    @property
    def tag_type(self) -> str:
        return "scope"

    async def validate_tag(self, imei: str) -> TagValidationResult:
        imei_strip = imei.strip()

        # ── 1. Structural check (fast, no network) ─────────────────────────
        if not (self._IMEI_RE.match(imei_strip) or self._GUID_RE.match(imei_strip)):
            return TagValidationResult(
                is_valid=False,
                message="Invalid identifier. Please enter a 15-digit IMEI or a valid GUID.",
            )

        # ── 2. Guard: require auth header configured ────────────────────────
        if not _SCOPE_AUTH:
            return TagValidationResult(
                is_valid=False,
                message="Scope validation is not configured on this server. Contact your administrator.",
            )

        # ── 3. Scope API — confirm the tag exists ───────────────────────────
        url = f"{_SCOPE_API_BASE}/units/unitconnections/{imei_strip}"
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                resp = await client.get(url, headers={"Authorization": _SCOPE_AUTH})
        except httpx.RequestError:
            return TagValidationResult(
                is_valid=False,
                message="Could not verify this tag. Please check your connection and try again.",
            )

        if resp.status_code == 200:
            return TagValidationResult(
                is_valid=True,
                message="Series 1 tag verified.",
            )
        elif resp.status_code == 404:
            return TagValidationResult(
                is_valid=False,
                message="Unknown Tag or incorrect type",
            )
        else:
            return TagValidationResult(
                is_valid=False,
                message=f"Tag verification returned an unexpected response (HTTP {resp.status_code}). Please try again.",
            )
