"""Which build of the backend is running: the commit and time the deploy wrote to BUILD
(e.g. "96c92b6 2026-10-27T08:15Z"), or "dev" when running from a checkout. Sent on every
response as X-Server-Build, so app logs and problem reports show which server answered."""
from pathlib import Path


def _read() -> str:
    for path in (Path(__file__).resolve().parent.parent / "BUILD", Path("/app/BUILD")):
        try:
            text = path.read_text().strip()
            if text:
                return text[:80]
        except OSError:
            pass
    return "dev"


SERVER_BUILD = _read()
