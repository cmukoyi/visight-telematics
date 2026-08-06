"""
Hubble Platform Tag Provider (Series 5).

Implements the Strategy interface for Hubble-based BLE tracking tags
that use the Hubble Cloud Platform API for device management and data access.

When a Series 5 tag is registered in PinPlot, this provider automatically
registers the device with Hubble's API and retrieves the device encryption key.

The device_id field is stored in BLETag.imei for consistency with the
portal API's PortalTagCreate schema. The device_key is stored in a new
field (TBD - needs migration for ble_tags.hubble_device_key column).

API Documentation: https://hubble.com/docs/
Authentication: Bearer token (JWT)
Rate Limits: 3 req/sec per endpoint, 15 req/sec per organization

Device Registration: POST /v2/org/{org_id}/devices
"""
import httpx
import logging
import os
import re
from typing import Optional, Dict, Any

from .base_provider import DeviceTagProvider, TagValidationResult

logger = logging.getLogger(__name__)


class HubbleTagProvider(DeviceTagProvider):
    """
    Hubble Platform (Series 5) tag provider.

    Registration flow:
      1. User provides device name in PinPlot customer dashboard
      2. validate_tag() registers device with Hubble API
      3. Hubble returns device_id and device_key
      4. device_id is stored in BLETag.imei field
      5. device_key is stored in BLETag.description field (encrypted storage TBD)
    
    Configuration (environment variables):
      HUBBLE_API_KEY: API token from Hubble dashboard (Developer Tools > API Tokens)
                      Required scopes: write-devices, read-devices
      HUBBLE_ORG_ID: Organization ID from Hubble dashboard
      HUBBLE_API_BASE: API base URL (default: https://api.hubble.com)
      HUBBLE_ENCRYPTION: Encryption mode (default: AES-256-CTR)
                        Options: AES-256-CTR, AES-128-CTR, AES-128-EAX
      HUBBLE_COUNTER_SOURCE: Counter source for EID rotation (default: UNIX_TIME)
                            Options: UNIX_TIME, DEVICE_UPTIME
    """

    def __init__(self):
        self.api_key = os.getenv("HUBBLE_API_KEY")
        self.org_id = os.getenv("HUBBLE_ORG_ID")
        self.api_base = os.getenv("HUBBLE_API_BASE", "https://api.hubble.com")
        self.encryption = os.getenv("HUBBLE_ENCRYPTION", "AES-256-CTR")
        self.counter_source = os.getenv("HUBBLE_COUNTER_SOURCE", "UNIX_TIME")

    @property
    def provider_name(self) -> str:
        return "Hubble Platform"

    @property
    def tag_type(self) -> str:
        return "hubble"

    async def validate_tag(self, imei: str) -> TagValidationResult:
        """
        Register a new device with Hubble Platform.
        
        For Series 5 tags, the "imei" parameter is actually the device name.
        This method registers the device with Hubble and returns the generated
        device_id and device_key.
        
        Args:
            imei: Device name (NOT device ID - Hubble generates the ID)
        
        Returns:
            TagValidationResult with:
              - is_valid=True if registration succeeds
              - message contains device_id and device_key for storage
              - device_id should be stored in BLETag.imei
              - device_key should be stored securely (currently in message)
        """
        device_name = imei.strip()

        # Validate device name format
        if not device_name or len(device_name) < 3:
            return TagValidationResult(
                is_valid=False,
                message="Device name must be at least 3 characters long.",
            )

        # Check if API credentials are configured
        if not self.api_key or not self.org_id:
            logger.warning("Hubble API credentials not configured - Series 5 tags require HUBBLE_API_KEY and HUBBLE_ORG_ID")
            return TagValidationResult(
                is_valid=False,
                message="Hubble API not configured. Please contact administrator to set up Series 5 integration.",
            )

        # Register device with Hubble API
        try:
            registration_result = await self._register_device_with_hubble(device_name)
            
            if registration_result["success"]:
                device_id = registration_result["device_id"]
                device_key = registration_result["device_key"]
                
                # Return device_id to be stored as IMEI
                # Device key will be stored in description field (temporary - need dedicated column)
                logger.info(f"Successfully registered Hubble device: {device_name} -> {device_id}")
                
                return TagValidationResult(
                    is_valid=True,
                    message=f"Hubble device registered successfully: {device_id}",
                    device_id=device_id,  # This will replace the imei field
                    device_key=device_key,  # This will be stored separately
                )
            else:
                return TagValidationResult(
                    is_valid=False,
                    message=f"Hubble registration failed: {registration_result.get('error', 'Unknown error')}",
                )
                
        except Exception as e:
            logger.error(f"Hubble API error during device registration: {e}", exc_info=True)
            return TagValidationResult(
                is_valid=False,
                message=f"Hubble API error: {str(e)}",
            )

    async def _register_device_with_hubble(self, device_name: str) -> Dict[str, Any]:
        """
        Register a new device with Hubble Platform API.
        
        POST /v2/org/{org_id}/devices
        
        Args:
            device_name: Human-readable device name
        
        Returns:
            Dict with keys:
              - success: bool
              - device_id: str (if success)
              - device_key: str (if success, base64-encoded)
              - error: str (if failure)
        """
        url = f"{self.api_base}/v2/org/{self.org_id}/devices"
        
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
            "Accept": "application/json",
            "X-Request-ID": f"pinplot-register-{device_name}",
        }
        
        # Register one device with specified encryption settings
        payload = {
            "n_devices": 1,
            "encryption": self.encryption,
            "counter_source": self.counter_source,
            "names": [device_name],
        }
        
        try:
            async with httpx.AsyncClient(timeout=15.0) as client:
                response = await client.post(url, headers=headers, json=payload)
                
                if response.status_code == 200:
                    data = response.json()
                    
                    # Expected response structure:
                    # {
                    #   "devices": [
                    #     {
                    #       "device_id": "abc123...",
                    #       "key": "base64encodedkey...",
                    #       "name": "my-device"
                    #     }
                    #   ]
                    # }
                    
                    if "devices" in data and len(data["devices"]) > 0:
                        device = data["devices"][0]
                        return {
                            "success": True,
                            "device_id": device.get("device_id") or device.get("id"),
                            "device_key": device.get("key") or device.get("device_key"),
                        }
                    else:
                        return {
                            "success": False,
                            "error": "No device data in response",
                        }
                
                elif response.status_code == 400:
                    error_data = response.json() if response.text else {}
                    return {
                        "success": False,
                        "error": f"Invalid request: {error_data.get('message', response.text)}",
                    }
                
                elif response.status_code == 413:
                    return {
                        "success": False,
                        "error": "Request too large (413)",
                    }
                
                elif response.status_code == 429:
                    return {
                        "success": False,
                        "error": "Rate limit exceeded - please wait and try again",
                    }
                
                elif response.status_code == 500:
                    return {
                        "success": False,
                        "error": "Hubble API server error (500)",
                    }
                
                else:
                    return {
                        "success": False,
                        "error": f"HTTP {response.status_code}: {response.text[:100]}",
                    }
                    
        except httpx.TimeoutException:
            return {
                "success": False,
                "error": "Request timed out - Hubble API not responding",
            }
        except httpx.RequestError as e:
            return {
                "success": False,
                "error": f"Network error: {str(e)}",
            }
        except Exception as e:
            return {
                "success": False,
                "error": f"Unexpected error: {str(e)}",
            }
