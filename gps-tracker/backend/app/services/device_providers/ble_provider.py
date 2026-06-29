"""
BLE Indoor Tag Provider (Series 4 / DX-Smart CP27/CP28/CP29).

Implements the Strategy interface for DX-Smart BLE indoor tracking tags
used with Pareto Anywhere and ESP32 gateways.

Validation accepts BLE MAC addresses (12 hex characters) with or without
colons/dashes. No external API call is made - we only validate the format
since these tags are self-provisioned by the customer.

The mac_address field is stored in BLETag.imei for consistency with the
portal API's PortalTagCreate schema.
"""
import re

from .base_provider import DeviceTagProvider, TagValidationResult


class BLEIndoorTagProvider(DeviceTagProvider):
    """
    BLE Indoor (Series 4) tag provider for DX-Smart CP27/CP28/CP29 tags.

    Validation flow:
      1. Check if input is a valid MAC address (12 hex chars, with/without separators)
      2. Normalize to lowercase without separators (e.g., 48872d9dbc66)
      3. Accept immediately - no external API validation needed
    """

    # Matches MAC addresses in formats:
    # - AA:BB:CC:DD:EE:FF
    # - AA-BB-CC-DD-EE-FF
    # - AABBCCDDEEFF
    _MAC_RE = re.compile(
        r"^([0-9a-f]{2}[:-]?){5}[0-9a-f]{2}$",
        re.IGNORECASE,
    )

    @property
    def provider_name(self) -> str:
        return "BLE Indoor (DX-Smart)"

    @property
    def tag_type(self) -> str:
        return "ble"

    async def validate_tag(self, imei: str) -> TagValidationResult:
        """
        Validate BLE MAC address format.
        
        Args:
            imei: BLE MAC address (stored in imei field for API compatibility)
        
        Returns:
            TagValidationResult with is_valid=True if MAC format is valid
        """
        mac_strip = imei.strip()

        # Check if it's a valid MAC address
        if not self._MAC_RE.match(mac_strip):
            return TagValidationResult(
                is_valid=False,
                message="Invalid MAC address. Please enter a 12-character hex MAC address (e.g., 48872D9DBC66 or 48:87:2D:9D:BC:66).",
            )

        # Normalize: remove colons/dashes, convert to lowercase
        normalized = mac_strip.replace(":", "").replace("-", "").lower()

        return TagValidationResult(
            is_valid=True,
            message=f"Series 4 BLE indoor tag verified (MAC: {normalized.upper()}).",
        )
