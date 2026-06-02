"""Portal API for the Floor Plan feature.

All routes are tenant-scoped via the portal JWT (usergroup_id) and gated
behind the `floorplan` feature flag (TENANT_DISABLED_FEATURES env). The
admin-side CRUD for buildings/floors/rooms/gateways lives in routes_admin.py.

URL prefix: /api/portal/floorplan
"""
from __future__ import annotations

from datetime import datetime, timezone
import time
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import (
    BLETag, Building, Floor, IndoorGateway, Room, TagIndoorPosition,
)
from app.routes_portal import (
    get_portal_user_from_request, require_feature_enabled,
)
from app.services import pareto_bridge


router = APIRouter(
    prefix="/api/portal/floorplan",
    tags=["floorplan"],
    dependencies=[Depends(require_feature_enabled("floorplan"))],
)

_ASSET_CACHE_TTL_S = 2.5
_ASSET_CACHE: dict[tuple[str, str, str], tuple[float, dict]] = {}


# ── Helpers ────────────────────────────────────────────────────────────────

def _format_age(dt: Optional[datetime]) -> str:
    if dt is None:
        return "unknown"
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    secs = int((datetime.now(timezone.utc) - dt).total_seconds())
    if secs < 0:        return "just now"
    if secs < 60:       return f"{secs}s ago"
    if secs < 3600:     return f"{secs // 60}m ago"
    if secs < 86400:    return f"{secs // 3600}h ago"
    return f"{secs // 86400}d ago"


def _tenant_floor_ids(db: Session, usergroup_id) -> list:
    """All floor ids owned by this tenant — single query for filtering."""
    return [fid for (fid,) in db.query(Floor.id)
            .join(Building, Building.id == Floor.building_id)
            .filter(Building.usergroup_id == usergroup_id).all()]


def _asset_to_ui(row: TagIndoorPosition, floor_key: str,
                 name: str, asset_type: str, emoji: str) -> dict:
    """Map the DB row into the shape the floor-plan UI expects."""
    return {
        "id":         row.tag_id,
        "tagId":      row.tag_id,
        "name":       name,
        "type":       asset_type,
        "emoji":      emoji,
        "floor":      floor_key,
        "status":     row.status,
        "zone":       row.zone or "",
        "x":          row.x,
        "y":          row.y,
        "lastSeen":   _format_age(row.last_seen),
        "battery":    row.battery,
        "gatewayId":  str(row.gateway_id) if row.gateway_id else None,
        "rssi":       row.rssi,
    }


_TYPE_EMOJI = {
    "vehicle": "🚛", "equipment": "📦", "container": "📦", "personnel": "🧑",
}


def _emoji_for_tag(tag: Optional[BLETag]) -> str:
    if tag is None:
        return "📦"
    # No dedicated type column on BLETag — derive a friendly icon from the
    # tag_type ('tracksolid' | 'scope') for now.
    return "📡" if (tag.tag_type == "scope") else "🚛"


def _name_for_tag(tag_id: str, tag: Optional[BLETag]) -> str:
    if tag and tag.description:
        return tag.description
    if tag and tag.device_name:
        return tag.device_name
    return f"Tag {tag_id[-6:].upper()}"


# ── Schemas ────────────────────────────────────────────────────────────────

class AssetRename(BaseModel):
    name: str


# ── Routes ─────────────────────────────────────────────────────────────────

@router.get("/floors")
def list_floors(request: Request, db: Session = Depends(get_db)):
    """Return the tenant's floors (one entry per Floor row across all of
    their Buildings). `floor_key` is what the UI uses to switch tabs and
    must match the hardcoded FLOORS keys in floorplan/app.js
    ('G' / '1F' / '2F' / '3F'); admins set this via the Floor.label.
    """
    me = get_portal_user_from_request(request, db)
    floors = (db.query(Floor, Building)
                .join(Building, Building.id == Floor.building_id)
                .filter(Building.usergroup_id == me.usergroup_id)
                .order_by(Building.name, Floor.floor_order)
                .all())
    return {
        "floors": [{
            "floor_id":    str(f.id),
            "building_id": str(b.id),
            "building":    b.name,
            "floor_key":   f.label,   # convention: 'G' | '1F' | '2F' | '3F'
            "label":       f.label,
            "order":       f.floor_order,
            "map_w":       f.map_w,
            "map_h":       f.map_h,
        } for f, b in floors]
    }


@router.get("/floors/{floor_id}")
def get_floor(floor_id: str, request: Request, db: Session = Depends(get_db)):
    """Single floor incl. floor_plan base64, rooms, gateways."""
    me = get_portal_user_from_request(request, db)
    row = (db.query(Floor, Building)
             .join(Building, Building.id == Floor.building_id)
             .filter(Floor.id == floor_id,
                     Building.usergroup_id == me.usergroup_id)
             .first())
    if not row:
        raise HTTPException(status_code=404, detail="Floor not found")
    floor, building = row
    rooms = db.query(Room).filter(Room.floor_id == floor.id).all()
    gateways = db.query(IndoorGateway).filter(IndoorGateway.floor_id == floor.id).all()
    return {
        "floor_id":    str(floor.id),
        "building_id": str(building.id),
        "building":    building.name,
        "floor_key":   floor.label,
        "label":       floor.label,
        "map_w":       floor.map_w,
        "map_h":       floor.map_h,
        "floor_plan":  floor.floor_plan,
        "rooms":       [{"id": str(r.id), "name": r.name,
                         "x": r.x, "y": r.y, "w": r.w, "h": r.h} for r in rooms],
        "gateways":    [{"id": str(g.id), "receiver_id": g.receiver_id,
                         "label": g.label, "x": g.x, "y": g.y} for g in gateways],
    }


@router.get("/assets")
def list_assets(
    request: Request,
    floor_key: Optional[str] = None,
    floor_id: Optional[str] = None,
    status_filter: Optional[str] = None,
    db: Session = Depends(get_db),
):
    """Current indoor positions of all tenant tags.

    Optional filters:
      floor_key — Floor.label (e.g. 'G'); preferred from UI.
      floor_id  — explicit Floor UUID.
      status_filter — 'online' | 'idle' | 'offline'.
    """
    me = get_portal_user_from_request(request, db)
    cache_key = (str(me.usergroup_id), floor_key or "", status_filter or "")
    now_m = time.monotonic()
    cached = _ASSET_CACHE.get(cache_key)
    if cached and cached[0] > now_m:
        return cached[1]

    q = db.query(TagIndoorPosition).filter(
        TagIndoorPosition.usergroup_id == me.usergroup_id
    )
    if floor_id:
        q = q.filter(TagIndoorPosition.floor_id == floor_id)
    if status_filter:
        q = q.filter(TagIndoorPosition.status == status_filter)
    rows = q.all()

    # Bulk-fetch the floors so we can resolve floor_key without N+1.
    floor_ids = {r.floor_id for r in rows}
    floor_map = {f.id: f.label for f in
                 db.query(Floor.id, Floor.label).filter(Floor.id.in_(floor_ids)).all()
                 } if floor_ids else {}

    if floor_key:
        rows = [r for r in rows if floor_map.get(r.floor_id) == floor_key]

    # Resolve names/types from BLETag (best-effort — many BLE tags from the
    # XIAO sniffer are not registered as customer-owned BLETag rows).
    tag_ids = [r.tag_id for r in rows]
    tag_map: dict = {}
    if tag_ids:
        # BLETag.imei is the customer-facing tag identifier; floor-plan tags
        # use BLE MAC. Match on either column.
        for t in db.query(BLETag).filter(
            (BLETag.imei.in_(tag_ids)) | (BLETag.mac_address.in_(tag_ids))
        ).all():
            tag_map[t.imei] = t
            if t.mac_address:
                tag_map[t.mac_address.lower().replace(":", "")] = t

    out = []
    for r in rows:
        tag = tag_map.get(r.tag_id)
        out.append(_asset_to_ui(
            r,
            floor_key=floor_map.get(r.floor_id, ""),
            name=_name_for_tag(r.tag_id, tag),
            asset_type="equipment",
            emoji=_emoji_for_tag(tag),
        ))
    payload = {"count": len(out), "assets": out}
    _ASSET_CACHE[cache_key] = (now_m + _ASSET_CACHE_TTL_S, payload)
    if len(_ASSET_CACHE) > 64:
        expired = [k for k, (exp, _) in _ASSET_CACHE.items() if exp <= now_m]
        for k in expired:
            _ASSET_CACHE.pop(k, None)
    return payload


@router.put("/assets/{tag_id}")
def rename_asset(tag_id: str, body: AssetRename,
                 request: Request, db: Session = Depends(get_db)):
    """Rename a tag's display name. Persists to BLETag.description if the
    tag is registered to this tenant; otherwise 404 (we don't want the
    portal to create stray BLETag rows for unknown sniffer hits)."""
    me = get_portal_user_from_request(request, db)
    tag = db.query(BLETag).filter(
        (BLETag.imei == tag_id) | (BLETag.mac_address.ilike(tag_id))
    ).first()
    if tag is None or tag.user_id is None:
        raise HTTPException(status_code=404, detail="Tag not registered to this tenant")
    # Tenant check via the tag's owning user's usergroup.
    if getattr(tag.user, "usergroup_id", None) != me.usergroup_id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN)
    tag.description = (body.name or "").strip()[:255]
    db.commit()
    return {"ok": True, "name": tag.description}


@router.get("/health")
def floorplan_health(request: Request, db: Session = Depends(get_db)):
    """Bridge connection + gateway online counts for this tenant.
    Useful for a topbar status indicator and for ops debugging."""
    me = get_portal_user_from_request(request, db)
    floor_ids = _tenant_floor_ids(db, me.usergroup_id)
    gw_total = (db.query(IndoorGateway)
                .filter(IndoorGateway.floor_id.in_(floor_ids)).count()
                if floor_ids else 0)
    asset_online = (db.query(TagIndoorPosition)
                    .filter(TagIndoorPosition.usergroup_id == me.usergroup_id,
                            TagIndoorPosition.status == "online").count())
    asset_total = (db.query(TagIndoorPosition)
                   .filter(TagIndoorPosition.usergroup_id == me.usergroup_id).count())
    bridge = pareto_bridge.get_status()
    return {
        "bridge": {
            "connected":           bridge["connected"],
            "pareto_url":          bridge["pareto_url"],
            "raddec_count":        bridge["raddec_count"],
            "last_raddec_at":      bridge["last_raddec_at"],
        },
        "gateways":   {"total": gw_total},
        "assets":     {"total": asset_total, "online": asset_online},
    }


@router.get("/gateways/unregistered")
def list_unregistered_gateways(request: Request, db: Session = Depends(get_db)):
    """Receiver IDs the bridge has seen on the wire but that aren't yet
    registered in IndoorGateway. Useful when installing a new XIAO unit —
    flash with its target ID, power it on, then refresh this list to
    confirm Pareto is hearing it before registering via the admin API."""
    # Not tenant-scoped (deployment-wide deduplication of unknowns), but
    # gated behind portal auth + floorplan feature.
    get_portal_user_from_request(request, db)
    return {"unregistered": pareto_bridge.get_status()["unregistered_gateways"]}
