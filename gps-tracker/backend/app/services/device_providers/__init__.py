"""
Device Provider package — Strategy + Factory patterns for BLE tag validation.

Design:
- DeviceTagProvider  (Strategy interface)   — each tag type implements its own validation
- DeviceProviderFactory (Factory)           — creates the right provider given a tag type
- TrackSolidTokenManager (Singleton)        — caches the TrackSolid JWT, reusing it for 1 hour
"""
from .provider_factory import DeviceProviderFactory
from .base_provider import DeviceTagProvider, TagValidationResult

__all__ = ["DeviceProviderFactory", "DeviceTagProvider", "TagValidationResult"]
