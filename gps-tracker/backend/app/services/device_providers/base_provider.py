"""
Abstract base class for device tag providers (Strategy Pattern).

Every supported BLE tag type (TrackSolid, Scope, …) implements this
interface so callers never need to know the underlying vendor API.
"""
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Optional


@dataclass
class TagValidationResult:
    is_valid: bool
    message: str
    battery_level: Optional[int] = field(default=None)  # Battery % as integer, e.g. 98


class DeviceTagProvider(ABC):
    """Strategy interface — implement one per supported tag/device type."""

    @property
    @abstractmethod
    def provider_name(self) -> str:
        """Human-readable provider name, e.g. 'TrackSolid'."""

    @property
    @abstractmethod
    def tag_type(self) -> str:
        """Lowercase string key used in the DB, e.g. 'tracksolid'."""

    @abstractmethod
    async def validate_tag(self, imei: str) -> TagValidationResult:
        """
        Verify that *imei* exists in the vendor's platform and can be
        registered by this Pinplot account.

        Returns a TagValidationResult with is_valid=True when the IMEI
        was found, or is_valid=False with a user-friendly message otherwise.
        """
