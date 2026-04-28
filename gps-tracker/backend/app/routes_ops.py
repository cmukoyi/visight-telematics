"""
Admin Ops API — Docker container management via mounted Docker socket.

Endpoints:
  GET  /api/admin/ops/containers                - list pinplot_* containers
  GET  /api/admin/ops/containers/{name}/logs    - tail container logs
  POST /api/admin/ops/containers/{name}/restart - restart a container

Requires /var/run/docker.sock mounted into the backend container (read for
list/logs; the restart call needs write access, so mount without :ro for POST).
Only containers whose name starts with 'pinplot_' can be managed.
"""
import logging
from fastapi import APIRouter, HTTPException, Query

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/admin/ops", tags=["admin-ops"])

# Safety guard — only containers with this prefix may be touched
ALLOWED_PREFIX = "pinplot_"


def _client():
    """Return a Docker client connected via the host socket."""
    try:
        import docker
        return docker.from_env()
    except Exception as exc:
        logger.error("Docker socket unavailable: %s", exc)
        raise HTTPException(
            status_code=503,
            detail="Docker socket unavailable — is /var/run/docker.sock mounted?",
        )


def _guard(name: str) -> None:
    """Reject any container name that doesn't have the allowed prefix."""
    if not name.startswith(ALLOWED_PREFIX):
        raise HTTPException(
            status_code=403,
            detail=f"Only '{ALLOWED_PREFIX}*' containers may be managed via this API",
        )


# ── Endpoints ─────────────────────────────────────────────────────────────────

@router.get("/containers")
def list_containers():
    """Return status of every pinplot_* container (running or stopped)."""
    client = _client()
    result = []
    for c in client.containers.list(all=True):
        if not c.name.startswith(ALLOWED_PREFIX):
            continue
        state = c.attrs.get("State", {})
        health_obj = state.get("Health", {})
        health_status = health_obj.get("Status", "none") if health_obj else "none"
        tags = c.image.tags
        image = tags[0] if tags else c.image.short_id
        result.append({
            "name": c.name,
            "id": c.short_id,
            "status": c.status,           # running | exited | restarting | created …
            "health": health_status,      # healthy | unhealthy | starting | none
            "image": image,
            "started_at": state.get("StartedAt", ""),
        })
    result.sort(key=lambda x: x["name"])
    return result


@router.get("/containers/{name}/logs")
def get_logs(name: str, lines: int = Query(default=150, ge=10, le=500)):
    """Return the last *lines* log lines from the named container."""
    _guard(name)
    client = _client()
    try:
        from docker.errors import NotFound  # noqa: PLC0415
        container = client.containers.get(name)
        raw = container.logs(tail=lines, timestamps=True)
        return {"name": name, "logs": raw.decode("utf-8", errors="replace")}
    except NotFound:
        raise HTTPException(status_code=404, detail=f"Container '{name}' not found")
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


@router.post("/containers/{name}/restart")
def restart_container(name: str):
    """Gracefully restart the named container (15 s timeout before SIGKILL)."""
    _guard(name)
    client = _client()
    try:
        from docker.errors import NotFound  # noqa: PLC0415
        container = client.containers.get(name)
        container.restart(timeout=15)
        logger.info("Admin ops: restarted container %s", name)
        return {"ok": True, "message": f"'{name}' restarted successfully"}
    except NotFound:
        raise HTTPException(status_code=404, detail=f"Container '{name}' not found")
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))
