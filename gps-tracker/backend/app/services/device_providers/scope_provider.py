"""
Scope device provider.

Implements the Strategy interface for tags registered on the Scope / MZone
platform. The MZone API is already integrated into Pinplot; for Scope-type
tags validation simply confirms the IMEI looks structurally correct and
defers full matching to the existing MZone polling pipeline.

When Scope gains a dedicated management API, replace the body of
validate_tag() with real API calls — no other file needs to change.
"""
from .base_provider import DeviceTagProvider, TagValidationResult
import re


class ScopeTagProvider(DeviceTagProvider):
    """
    Scope BLE tag provider.

    Current behaviour: accepts any 15-digit IMEI or valid GUID as a
    Scope-compatible tag identifier. MZone will confirm the match at the
    next polling cycle once the tag is registered.
    """

    # Basic IMEI / GUID structural checks
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
        if self._IMEI_RE.match(imei_strip) or self._GUID_RE.match(imei_strip):
            return TagValidationResult(
                is_valid=True,
                message="Scope tag accepted. It will appear on the map once active.",
            )
        return TagValidationResult(
            is_valid=False,
            message="Invalid identifier. Please enter a 15-digit IMEI or a valid GUID.",
        )
