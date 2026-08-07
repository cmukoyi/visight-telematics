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
        Validate a Series 5 device by checking if it exists in Hubble Platform.
        
        For Series 5 tags, users must register devices in Hubble Platform first,
        then provide the device_id here for validation. This method checks if
        the device_id exists in Hubble.
        
        Args:
            imei: Hubble device_id (UUID format from Hubble Platform)
        
        Returns:
            TagValidationResult with:
              - is_valid=True if device exists in Hubble
              - is_valid=False if device not found or API error
        """
        device_id = imei.strip()

        # Validate device_id format (should be a UUID)
        if not device_id or len(device_id) < 10:
            return TagValidationResult(
                is_valid=False,
                message="Device ID must be at least 10 characters. Please provide the Hubble device_id.",
            )

        # Check if API credentials are configured
        if not self.api_key or not self.org_id:
            logger.warning("Hubble API credentials not configured - Series 5 tags require HUBBLE_API_KEY and HUBBLE_ORG_ID")
            return TagValidationResult(
                is_valid=False,
                message="Hubble API not configured. Please contact administrator to set up Series 5 integration.",
            )

        # Check if device exists in Hubble Platform
        try:
            device = await self.get_device(device_id)
            
            if device:
                device_name = device.get("name", "Unknown")
                logger.info(f"Series 5 device validated: {device_id} (name: {device_name})")
                
                return TagValidationResult(
                    is_valid=True,
                    message=f"Series 5 device verified in Hubble: {device_name}",
                    device_id=device_id,
                )
            else:
                return TagValidationResult(
                    is_valid=False,
                    message=f"Device ID '{device_id}' not found in Hubble. Please register the device in Hubble Platform first.",
                )
                
        except Exception as e:
            logger.error(f"Hubble API error during device validation: {e}", exc_info=True)
            return TagValidationResult(
                is_valid=False,
                message=f"Could not verify device in Hubble: {str(e)}",
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

    async def list_devices(
        self, 
        filter_created_ts: Optional[str] = None,
        filter_most_recent_packet_ts: Optional[str] = None,
        continuation_token: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        List all devices registered in Hubble Platform.
        
        GET /v1/org/{org_id}/devices
        
        Use cases:
          - Sync device inventory between Hubble and PinPlot
          - Check if device exists before registration
          - Audit device lifecycle and activity
        
        Args:
            filter_created_ts: Filter by creation timestamp
                               Format: "between:{after}:{before}" (after inclusive, before exclusive)
                               Example: "between:1722960000:1723046400" (last 24h)
            filter_most_recent_packet_ts: Filter by last packet timestamp
                               Example: "between:0:1" (never sent packet)
            continuation_token: Pagination token from previous response
        
        Returns:
            Dict with keys:
              - success: bool
              - devices: List[Dict] (if success)
                - device_id: str
                - name: str
                - created_ts: int (Unix timestamp)
                - most_recent_packet: Dict (may be None)
              - continuation_token: str (if more pages available)
              - error: str (if failure)
        
        Example queries:
          - Unused devices: filter_most_recent_packet_ts="between:0:1"
          - Recently active (24h): filter_most_recent_packet_ts="between:{timestamp_1day_ago}:{now}"
          - Recently registered (24h): filter_created_ts="between:{timestamp_1day_ago}:{now}"
        """
        if not self.api_key or not self.org_id:
            return {
                "success": False,
                "error": "Hubble API credentials not configured",
            }
        
        url = f"{self.api_base}/v1/org/{self.org_id}/devices"
        
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Accept": "application/json",
            "X-Request-ID": f"pinplot-list-devices",
        }
        
        # Build query parameters
        params = {}
        if filter_created_ts:
            params["filter_created_ts"] = filter_created_ts
        if filter_most_recent_packet_ts:
            params["filter_most_recent_packet_ts"] = filter_most_recent_packet_ts
        if continuation_token:
            params["continuation_token"] = continuation_token
        
        try:
            async with httpx.AsyncClient(timeout=15.0) as client:
                response = await client.get(url, headers=headers, params=params)
                
                if response.status_code == 200:
                    data = response.json()
                    
                    # Expected response structure:
                    # {
                    #   "devices": [
                    #     {
                    #       "device_id": "abc123",
                    #       "name": "my-device",
                    #       "created_ts": 1722960000,
                    #       "most_recent_packet": {...} or null
                    #     }
                    #   ],
                    #   "continuation_token": "token" (optional)
                    # }
                    
                    result = {
                        "success": True,
                        "devices": data.get("devices", []),
                    }
                    
                    # Add continuation token if present (more pages available)
                    if "continuation_token" in data:
                        result["continuation_token"] = data["continuation_token"]
                    
                    return result
                
                elif response.status_code == 400:
                    error_data = response.json() if response.text else {}
                    return {
                        "success": False,
                        "error": f"Invalid request: {error_data.get('message', response.text)}",
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

    async def get_device_by_name(self, device_name: str) -> Optional[Dict[str, Any]]:
        """
        Find a device by name in Hubble Platform.
        
        Useful for checking if a device with a given name already exists
        before attempting registration.
        
        Args:
            device_name: Device name to search for
        
        Returns:
            Device dict if found, None otherwise
            Device dict contains: device_id, name, created_ts, most_recent_packet
        """
        result = await self.list_devices()
        
        if not result["success"]:
            logger.error(f"Failed to list Hubble devices: {result.get('error')}")
            return None
        
        # Search through devices for matching name
        for device in result.get("devices", []):
            if device.get("name") == device_name:
                return device
        
        # Handle pagination if continuation_token exists
        while "continuation_token" in result:
            result = await self.list_devices(continuation_token=result["continuation_token"])
            
            if not result["success"]:
                break
            
            for device in result.get("devices", []):
                if device.get("name") == device_name:
                    return device
        
        return None

    async def get_device(self, device_id: str) -> Dict[str, Any]:
        """
        Get a specific device by device_id from Hubble Platform.
        
        GET /v1/org/{org_id}/devices/{device_id}
        
        Use cases:
          - Verify device exists and is registered
          - Get device details and last activity
          - Check device configuration
        
        Args:
            device_id: Hubble device identifier
        
        Returns:
            Dict with keys:
              - success: bool
              - device: Dict (if success)
                - device_id: str
                - name: str
                - created_ts: int (Unix timestamp)
                - most_recent_packet: Dict (may be None)
              - error: str (if failure)
        """
        if not self.api_key or not self.org_id:
            return {
                "success": False,
                "error": "Hubble API credentials not configured",
            }
        
        url = f"{self.api_base}/v1/org/{self.org_id}/devices/{device_id}"
        
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Accept": "application/json",
            "X-Request-ID": f"pinplot-get-device-{device_id}",
        }
        
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                response = await client.get(url, headers=headers)
                
                if response.status_code == 200:
                    device = response.json()
                    
                    # Expected response structure:
                    # {
                    #   "device_id": "abc123",
                    #   "name": "my-device",
                    #   "created_ts": 1722960000,
                    #   "most_recent_packet": {...} or null
                    # }
                    
                    return {
                        "success": True,
                        "device": device,
                    }
                
                elif response.status_code == 404:
                    return {
                        "success": False,
                        "error": f"Device '{device_id}' not found in Hubble platform",
                    }
                
                elif response.status_code == 400:
                    error_data = response.json() if response.text else {}
                    return {
                        "success": False,
                        "error": f"Invalid request: {error_data.get('message', response.text)}",
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

    async def update_device(
        self,
        device_id: str,
        set_name: Optional[str] = None,
        set_tags: Optional[Dict[str, Any]] = None,
        set_install_location: Optional[Dict[str, Any]] = None,
        set_destination_org_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Update a registered device in Hubble Platform.
        
        PATCH /v1/org/{org_id}/devices/{device_id}
        
        Use cases:
          - Rename device
          - Add custom tags for filtering/organization
          - Set physical installation location
          - Transfer device to another organization
        
        Args:
            device_id: Hubble device identifier
            set_name: New device name (optional)
            set_tags: Custom tags dict (optional)
                     Example: {"_env": "production", "building": "warehouse-A"}
            set_install_location: Installation location (optional)
                                 Must include: lat, long, location_name
                                 Example: {
                                     "lat": 37.7749,
                                     "long": -122.4194,
                                     "location_name": "San Francisco Office"
                                 }
            set_destination_org_id: Target organization UUID for transfer (optional)
        
        Returns:
            Dict with keys:
              - success: bool
              - device: Dict (if success) - Updated device object
              - error: str (if failure)
        
        Notes:
          - All parameters are optional, but at least one must be provided
          - set_install_location requires all three fields (lat, long, location_name)
          - set_destination_org_id transfers ownership (requires appropriate permissions)
        """
        if not self.api_key or not self.org_id:
            return {
                "success": False,
                "error": "Hubble API credentials not configured",
            }
        
        # Build request body (only include provided fields)
        body = {}
        
        if set_name is not None:
            body["set_name"] = set_name
        
        if set_tags is not None:
            body["set_tags"] = set_tags
        
        if set_install_location is not None:
            # Validate required fields
            required = ["lat", "long", "location_name"]
            missing = [f for f in required if f not in set_install_location]
            if missing:
                return {
                    "success": False,
                    "error": f"set_install_location missing required fields: {missing}",
                }
            body["set_install_location"] = set_install_location
        
        if set_destination_org_id is not None:
            body["set_destination_org_id"] = set_destination_org_id
        
        # Must provide at least one update field
        if not body:
            return {
                "success": False,
                "error": "At least one update field must be provided",
            }
        
        url = f"{self.api_base}/v1/org/{self.org_id}/devices/{device_id}"
        
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
            "Accept": "application/json",
            "X-Request-ID": f"pinplot-update-device-{device_id}",
        }
        
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                response = await client.patch(url, headers=headers, json=body)
                
                if response.status_code == 200:
                    device = response.json()
                    
                    # Expected response: Updated device object
                    # {
                    #   "device_id": "abc123",
                    #   "name": "updated-name",
                    #   "created_ts": 1722960000,
                    #   "tags": {...},
                    #   "install_location": {...},
                    #   ...
                    # }
                    
                    return {
                        "success": True,
                        "device": device,
                    }
                
                elif response.status_code == 404:
                    return {
                        "success": False,
                        "error": f"Device '{device_id}' not found in Hubble platform",
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
                        "error": "Payload too large - reduce size of tags or location data",
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

    async def delete_device(self, device_id: str) -> Dict[str, Any]:
        """
        Delete a registered device from Hubble Platform.
        
        DELETE /v1/org/{org_id}/devices/{device_id}
        
        Permanently removes a device from your organization. This action cannot
        be undone. All historical data for the device may be lost.
        
        Use cases:
          - Remove decommissioned devices
          - Clean up test devices after development
          - Remove incorrectly registered devices
          - Revoke device access from organization
        
        Args:
            device_id: Hubble device identifier
        
        Returns:
            Dict with keys:
              - success: bool
              - message: str (if success) - Confirmation message
              - error: str (if failure)
        
        Warnings:
          - This operation is permanent and cannot be undone
          - Historical packet data may be lost
          - Device must be re-registered if needed again
          - Consider updating device status/tags instead of deleting
        """
        if not self.api_key or not self.org_id:
            return {
                "success": False,
                "error": "Hubble API credentials not configured",
            }
        
        url = f"{self.api_base}/v1/org/{self.org_id}/devices/{device_id}"
        
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Accept": "application/json",
            "X-Request-ID": f"pinplot-delete-device-{device_id}",
        }
        
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                response = await client.delete(url, headers=headers)
                
                if response.status_code == 200:
                    # Expected response: Success confirmation
                    # Response body may be empty or contain confirmation message
                    
                    return {
                        "success": True,
                        "message": f"Device '{device_id}' successfully deleted from Hubble platform",
                    }
                
                elif response.status_code == 404:
                    return {
                        "success": False,
                        "error": f"Device '{device_id}' not found in Hubble platform",
                    }
                
                elif response.status_code == 400:
                    error_data = response.json() if response.text else {}
                    return {
                        "success": False,
                        "error": f"Invalid request: {error_data.get('message', response.text)}",
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
