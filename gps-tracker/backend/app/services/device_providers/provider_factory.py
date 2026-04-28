"""
Device Provider Factory (Factory Pattern).

Maps the lowercase tag_type string (stored in the DB) to the correct
Strategy implementation. Adding a new device type means:
  1. Create a new provider class in its own module.
  2. Add one entry to _PROVIDERS below.
  Nothing else changes.
"""
from .base_provider import DeviceTagProvider
from .tracksolid_provider import TrackSolidTagProvider
from .scope_provider import ScopeTagProvider

# Registry: tag_type key → provider class.
# Both the canonical vendor names ('scope', 'tracksolid') and the
# user-facing series names ('series1', 'series2') are accepted so that
# the Flutter app (which sends 'series1'/'series2') and any older DB rows
# (which store 'scope'/'tracksolid') both resolve correctly.
_PROVIDERS: dict[str, type[DeviceTagProvider]] = {
    "scope":      ScopeTagProvider,       # Series 1
    "series1":    ScopeTagProvider,       # alias used by the Flutter app
    "tracksolid": TrackSolidTagProvider,  # Series 2
    "series2":    TrackSolidTagProvider,  # alias used by the Flutter app
}


class DeviceProviderFactory:
    """Returns the correct DeviceTagProvider for a given tag_type string."""

    @classmethod
    def get_provider(cls, tag_type: str) -> DeviceTagProvider:
        """
        Raise ValueError for unknown types so callers get a clear error
        rather than a silent wrong-provider fallback.
        """
        key = (tag_type or "scope").strip().lower()
        provider_class = _PROVIDERS.get(key)
        if provider_class is None:
            supported = ", ".join(sorted(_PROVIDERS))
            raise ValueError(
                f"Unknown tag type '{tag_type}'. Supported types: {supported}"
            )
        return provider_class()

    @classmethod
    def supported_types(cls) -> list[str]:
        """Return sorted list of supported tag type keys."""
        return sorted(_PROVIDERS.keys())
