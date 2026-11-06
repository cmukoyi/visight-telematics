"""Lock out an IP after repeated failed logins. The address is blocked, never the account, so nobody
can shut a real user out by guessing wrongly on their username.

Counters are in memory: fine for the single backend container, and restarting it clears every lockout.
"""
import logging
import os
import time
from typing import Dict, List

from fastapi import HTTPException, Request, status

logger = logging.getLogger(__name__)

MAX_ATTEMPTS = int(os.getenv("PORTAL_LOGIN_MAX_ATTEMPTS", "5"))
WINDOW_SECONDS = int(os.getenv("PORTAL_LOGIN_WINDOW_SECONDS", "60"))
LOCKOUT_SECONDS = int(os.getenv("PORTAL_LOGIN_LOCKOUT_SECONDS", "900"))


def client_ip(request: Request) -> str:
    """The caller's address. nginx sets X-Forwarded-For to the address it saw, replacing any the client sent."""
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


class LoginLimiter:
    def __init__(self, name: str):
        self.name = name
        self._failures: Dict[str, List[float]] = {}
        self._locked_until: Dict[str, float] = {}

    def check(self, ip: str) -> None:
        """Raise HTTP 429 if this address is locked out. Call before looking at the password."""
        now = time.monotonic()
        until = self._locked_until.get(ip)
        if until is None:
            return
        if until <= now:
            del self._locked_until[ip]
            return
        retry = max(1, int(until - now))
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail=f"Too many failed login attempts. Try again in {retry} seconds.",
            headers={"Retry-After": str(retry)},
        )

    def record_failure(self, ip: str) -> None:
        now = time.monotonic()
        recent = [t for t in self._failures.get(ip, []) if t >= now - WINDOW_SECONDS]
        recent.append(now)
        if len(recent) >= MAX_ATTEMPTS:
            self._locked_until[ip] = now + LOCKOUT_SECONDS
            self._failures.pop(ip, None)
            logger.warning("%s: locking out %s for %ds after %d failures", self.name, ip, LOCKOUT_SECONDS, len(recent))
        else:
            self._failures[ip] = recent

    def record_success(self, ip: str) -> None:
        self._failures.pop(ip, None)
        self._locked_until.pop(ip, None)
