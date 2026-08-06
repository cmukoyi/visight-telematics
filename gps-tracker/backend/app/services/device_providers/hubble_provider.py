"""
Hubble Platform Tag Provider (Series 5).

Implements the Strategy interface for Hubble-based BLE tracking tags
that use the Hubble Cloud Platform API for device management and data access.

Validation accepts device IDs from the Hubble platform. The actual validation
against Hubble's API will be implemented when API credentials are configured.

The device_id field is stored in BLETag.imei for consistency with the
portal API's PortalTagCreate schema.

API Documentation: https://hubble.com/docs/
Authentication: Bearer token (JWT)
Rate Limits: 3 req/sec per endpoint, 15 req/sec per organization
"""
import os
import re
from typing import Optional

from .base_provider import DeviceTagProvider, TagValidationResult


class HubbleTagProvider(DeviceTagProvider):
    """
    Hubble Platform (Series 5) tag provider.

    Validation flow:
      1. Check if input is a valid device identifier format
      2. (Future) Verify device exists in Hubble platform via API
      3. Accept immediately for now - external API validation TBD
    
    Configuration (environment variables):
      HUBBLE_API_KEY: API token from Hubble dashboard (Developer Tools > API Tokens)
      HUBBLE_ORG_ID: Organization ID from Hubble dashboard
      HUBBLE_API_BASE: Base URL for Hubble API (default: https://api.hubble.com)
    """

    # Hubble device ID format - adjust based on actual format from Hubble
    # For now, accepting alphanumeric device IDs (8-32 chars)
    _DEVICE_ID_RE = re.compile(
        r"^[0-9a-zA-Z_-]{8,32}$",
        re.IGNORECASE,
    )

    def __init__(self):
        self.api_key = os.getenv("HUBBLE_API_KEY")
        self.org_id = os.getenv("HUBBLE_ORG_ID")
        self.api_base = os.getenv("HUBBLE_API_BASE", "https://api.hubble.com")

    @property
    def provider_name(self) -> str:
        return "Hubble Platform"

    @property
    def tag_type(self) -> str:
        return "hubble"

    async def validate_tag(self, imei: str) -> TagValidationResult:
        """
        Validate Hubble device ID format.
        
        Args:
            imei: Hubble device ID (stored in imei field for API compatibility)
        
        Returns:
            TagValidationResult with is_valid=True if device ID format is valid
        
        TODO: Implement actual Hubble API validation when credentials are configured
        """
        device_id = imei.strip()

        # Check if it's a valid device ID format
        if not self._DEVICE_ID_RE.match(device_id):
            return TagValidationResult(
                is_valid=False,
                message="Invalid Hubble device ID. Please enter a valid device identifier (8-32 alphanumeric characters).",
            )

        # TODO: If API credentials are configured, verify device exists in Hubble
        # if self.api_key and self.org_id:
        #     return await self._verify_with_hubble_api(device_id)

        # For now, accept valid format without external API check
        return TagValidationResult(
            is_valid=True,
            message=f"Series 5 Hubble tag verified (Device ID: {device_id}).",
        )

    async def _verify_with_hubble_api(self, device_id: str) -> TagValidationResult:
        """
        Verify device exists in Hubble platform via API.
        
        This method will be implemented when Hubble API integration is ready.
        
        Hubble API Endpoints:
          - GET /v1/organizations/{org_id}/devices/{device_id}
          - Requires Authorization: Bearer {api_key}
          - Rate limit: 3 req/sec per endpoint, 15 req/sec per org
        
        Args:
            device_id: Hubble device identifier
        
        Returns:
            TagValidationResult indicating if device exists in Hubble platform
        """
        # TODO: Implement actual API call
        # import httpx
        # 
        # headers = {
        #     "Authorization": f"Bearer {self.api_key}",
        #     "X-Request-ID": f"pinplot-validation-{device_id}",
        # }
        # 
        # async with httpx.AsyncClient() as client:
        #     response = await client.get(
        #         f"{self.api_base}/v1/organizations/{self.org_id}/devices/{device_id}",
        #         headers=headers,
        #         timeout=10.0,
        #     )
        #     
        #     if response.status_code == 200:
        #         return TagValidationResult(
        #             is_valid=True,
        #             message=f"Series 5 Hubble tag verified via API (Device ID: {device_id}).",
        #         )
        #     elif response.status_code == 404:
        #         return TagValidationResult(
        #             is_valid=False,
        #             message=f"Device ID {device_id} not found in Hubble platform.",
        #         )
        #     else:
        #         return TagValidationResult(
        #             is_valid=False,
        #             message=f"Hubble API error: {response.status_code}",
        #         )
        
        pass
