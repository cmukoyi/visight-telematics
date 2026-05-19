"""Environment-variable strict access with placeholder detection.

All credential and tenant-bound env vars MUST come from the deployed
server's .env file. Unfilled placeholder strings copied from
.env.example (e.g. ``your-...``, ``<...>``, ``change-me``) are
rejected at startup so the container fails fast at import rather than
silently failing in production.

History
-------
On 2026-05-19 we discovered that beacon's production .env contained
``SCOPE_AUTH_HEADER=Basic <your-base64-credentials>`` — copied verbatim
from ``.env.example`` and never filled in. Every Series 1 tag
validation had been silently returning HTTP 401 from MProfiler since
the server was first provisioned. The empty-string check that already
existed in ``scope_provider.py`` only handled the empty case, not the
placeholder-still-in-value case. This module exists so that class of
failure becomes impossible: the container refuses to start when any
secret env var still contains a placeholder.
"""
from __future__ import annotations

import os

# Case-insensitive substrings that indicate an unfilled placeholder
# copied from .env.example. Keep this list short and unambiguous —
# real credentials should never contain any of these substrings.
_PLACEHOLDER_PATTERNS: tuple[str, ...] = (
    "your-",        # your-tracksolid-account, your-mzone-client-secret
    "<",            # <your-base64-credentials-here>
    "change-me",
    "change_me",
    "changeme",
    "change-this",  # your-secret-key-change-this
    "placeholder",
    "set-me",
    "set_me",
    "replace_with",  # REPLACE_WITH_… markers used in .env.example
    "replace-with",
)


def required_env(name: str) -> str:
    """Return a required env var, raising at startup if missing or placeholder.

    Use this for every secret or tenant-bound config value at the module
    or class-init level so the container crashes loudly when misconfigured
    instead of silently failing at runtime.
    """
    val = os.getenv(name)
    if not val or not val.strip():
        raise RuntimeError(
            f"{name} is required but not set. Add it to "
            f"gps-tracker/backend/.env on the server."
        )
    lower = val.lower()
    for pattern in _PLACEHOLDER_PATTERNS:
        if pattern in lower:
            raise RuntimeError(
                f"{name} appears to contain an unfilled placeholder "
                f"({pattern!r} found in value). Set the real credential "
                f"in gps-tracker/backend/.env on the server."
            )
    return val
