"""HIVE Tracking API routes.

All endpoints are scoped to the authenticated portal user's UserGroup.

Prefix: /api/portal/hive  (registered in main.py)
"""
from __future__ import annotations

import json
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.database import get_db
from sqlalchemy import or_

from app.models import (
    BLETag,
    Hive,
    HiveConfigVersion,
    HiveEvaluation,
    HiveEvent,
    HiveLiveState,
    HiveTagMembership,
    MOBILITY_PRESETS,
    User,
    UserGroup,
)
from app.routes_portal import get_portal_user_from_request   # reuse auth helper
from app.services import hive_service

router = APIRouter(prefix="/api/portal/hive", tags=["hive"])

UTC = timezone.utc

# ─── Helpers ─────────────────────────────────────────────────────────────────

def _str_id(val: Any) -> str:
    return str(val) if val is not None else None


def _current_config(hive_id: str, db: Session) -> Optional[HiveConfigVersion]:
    return (
        db.query(HiveConfigVersion)
        .filter(
            HiveConfigVersion.hive_id == hive_id,
            HiveConfigVersion.valid_to.is_(None),
        )
        .first()
    )


def _days_remaining(expires_at: Optional[datetime]) -> Optional[int]:
    if expires_at is None:
        return None
    exp = expires_at
    if exp.tzinfo is None:
        exp = exp.replace(tzinfo=UTC)
    delta = (exp - datetime.now(UTC)).days
    return max(delta, 0)


def _format_dt(dt: Optional[datetime]) -> Optional[str]:
    if dt is None:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    return dt.isoformat()


def _freshness_for_tag(tag: BLETag, cfg: HiveConfigVersion) -> str:
    return hive_service.freshness_tier(tag.last_seen, cfg)


def _hive_summary(hive: Hive, cfg: Optional[HiveConfigVersion],
                  live: Optional[HiveLiveState], db: Session) -> Dict:
    """Build the summary dict returned in the hive list."""
    days_left = _days_remaining(hive.expires_at)
    expires_label = _format_dt(hive.expires_at)

    # Build tag pips
    tags_info = []
    for m in hive.memberships:
        tag = db.query(BLETag).filter(BLETag.id == m.tag_id).first()
        if not tag:
            continue
        tier = _freshness_for_tag(tag, cfg) if cfg else "lost"
        tags_info.append({
            "tag_id": _str_id(m.tag_id),
            "label": m.label or (tag.device_name or _str_id(m.tag_id)),
            "freshness": tier,
            "is_outlier": _str_id(m.tag_id) == _str_id(live.outlier_tag_id) if live else False,
            "last_seen": _format_dt(tag.last_seen),
        })

    alert_state = live.alert_state if live else "OK"
    diameter_m = live.current_diameter_m if live else None
    threshold = cfg.distance_threshold_m if cfg else None
    profile = cfg.mobility_profile if cfg else None

    # Status label for card subtitle
    if alert_state == "BREACHING":
        status_label = "In Breach"
    elif alert_state == "BREACH_PENDING":
        status_label = "Suspected Breach"
    elif alert_state == "RESOLVING":
        status_label = "Resolving"
    else:
        stale_count = sum(1 for t in tags_info if t["freshness"] in ("stale", "lost"))
        if stale_count > 0:
            status_label = "Partial Data"
        else:
            status_label = "Together"

    return {
        "hive_id": _str_id(hive.id),
        "name": hive.name,
        "status": hive.status,
        "alert_state": alert_state,
        "status_label": status_label,
        "mobility_profile": profile,
        "diameter_m": diameter_m,
        "threshold_m": threshold,
        "outlier_tag_id": _str_id(live.outlier_tag_id) if live else None,
        "tags": tags_info,
        "tag_count": len(tags_info),
        "expires_at": expires_label,
        "days_remaining": days_left,
        "last_evaluated_at": _format_dt(live.last_evaluated_at) if live else None,
        "created_at": _format_dt(hive.created_at),
        "parent_hive_id": _str_id(hive.parent_hive_id),
    }


# ─── Pydantic schemas ─────────────────────────────────────────────────────────

class HiveCreateRequest(BaseModel):
    name: str = Field(..., min_length=1, max_length=200)
    tag_ids: List[str] = Field(..., min_length=2)
    tag_labels: Optional[Dict[str, str]] = None      # tag_id → label
    mobility_profile: str = "mobile"                 # stationary|slow|mobile|fast
    distance_threshold_m: Optional[float] = None     # None → use preset default
    # Advanced overrides (ignored if not custom)
    fresh_window_s:     Optional[int]   = None
    recent_window_s:    Optional[int]   = None
    stale_window_s:     Optional[int]   = None
    lost_threshold_s:   Optional[int]   = None
    meaningful_change_m: Optional[float] = None
    hysteresis_pct:     Optional[float] = None
    confirmation_count: Optional[int]   = None


class HiveUpdateRequest(BaseModel):
    name: Optional[str] = Field(None, min_length=1, max_length=200)


class HiveConfigUpdateRequest(BaseModel):
    mobility_profile: str
    distance_threshold_m: Optional[float] = None
    fresh_window_s:     Optional[int]   = None
    recent_window_s:    Optional[int]   = None
    stale_window_s:     Optional[int]   = None
    lost_threshold_s:   Optional[int]   = None
    meaningful_change_m: Optional[float] = None
    hysteresis_pct:     Optional[float] = None
    confirmation_count: Optional[int]   = None


# ─── Stats ────────────────────────────────────────────────────────────────────

@router.get("/stats")
def get_hive_stats(request: Request, db: Session = Depends(get_db)):
    """Summary stats for the HIVE dashboard header."""
    me = get_portal_user_from_request(request, db)
    gid = str(me.usergroup_id)

    active_hives = db.query(Hive).filter(
        Hive.usergroup_id == gid, Hive.status == "active"
    ).all()

    in_breach = 0
    tags_tracked = 0
    stale_tags = 0

    for hive in active_hives:
        ls = db.query(HiveLiveState).filter(HiveLiveState.hive_id == str(hive.id)).first()
        if ls and ls.alert_state in ("BREACHING", "BREACH_PENDING"):
            in_breach += 1
        cfg = _current_config(str(hive.id), db)
        for m in hive.memberships:
            tags_tracked += 1
            tag = db.query(BLETag).filter(BLETag.id == m.tag_id).first()
            if tag and cfg and _freshness_for_tag(tag, cfg) in ("stale", "lost"):
                stale_tags += 1

    return {
        "active_hives": len(active_hives),
        "in_breach": in_breach,
        "tags_tracked": tags_tracked,
        "stale_tags": stale_tags,
    }


# ─── Available tags (for wizard) ─────────────────────────────────────────────

@router.get("/tags/available")
def get_available_tags(request: Request, db: Session = Depends(get_db)):
    """Return BLE tags that are NOT in any active hive and belong to the group."""
    me = get_portal_user_from_request(request, db)
    gid = str(me.usergroup_id)

    # IDs of tags already in an active hive for this group
    active_hive_ids = [
        str(row[0]) for row in
        db.query(Hive.id).filter(Hive.usergroup_id == gid, Hive.status == "active").all()
    ]
    in_use_tag_ids: set = set()
    if active_hive_ids:
        in_use_tag_ids = {
            str(row[0]) for row in
            db.query(HiveTagMembership.tag_id)
            .filter(HiveTagMembership.hive_id.in_(active_hive_ids))
            .all()
        }

    # Get all User IDs whose email matches the group's email domain
    group = db.query(UserGroup).filter(UserGroup.id == gid).first()
    if not group or not group.email_domain:
        return []

    domains = [d.strip().lower() for d in group.email_domain.split(",") if d.strip()]
    if not domains:
        return []

    domain_filter = or_(*(User.email.ilike(f"%@{d}") for d in domains))
    user_ids = [
        str(row[0]) for row in
        db.query(User.id).filter(domain_filter, User.is_active == True).all()
    ]
    if not user_ids:
        return []

    # Active tags owned by those users, excluding ones already in a hive
    tags = (
        db.query(BLETag)
        .filter(
            BLETag.user_id.in_(user_ids),
            BLETag.is_active == True,
            ~BLETag.id.in_(list(in_use_tag_ids)) if in_use_tag_ids else True,
        )
        .order_by(BLETag.device_name)
        .all()
    )

    return [
        {
            "tag_id": str(t.id),
            "label": t.device_name or t.imei or str(t.id),
            "device_name": t.device_name,
            "imei": t.imei,
            "last_seen": _format_dt(t.last_seen),
            "latitude": t.latitude,
            "longitude": t.longitude,
        }
        for t in tags
    ]


# ─── Smart defaults (wizard suggest) ─────────────────────────────────────────

@router.get("/suggest")
def get_hive_suggestion(
    tag_ids: str,
    request: Request,
    db: Session = Depends(get_db),
):
    """
    Suggest mobility profile and threshold based on selected tags' recent history.
    tag_ids = comma-separated list of BLE tag UUIDs.
    """
    me = get_portal_user_from_request(request, db)
    ids = [t.strip() for t in tag_ids.split(",") if t.strip()]
    if len(ids) < 2:
        raise HTTPException(400, "At least 2 tag IDs required")

    # For MVP: suggest 'mobile' profile + 200m threshold when we have limited data.
    # A full implementation would query historical positions.
    # We check whether tags have recent GPS fixes to set confidence.
    has_recent = 0
    for tid in ids:
        tag = db.query(BLETag).filter(BLETag.id == tid).first()
        if tag and tag.last_seen:
            ls = tag.last_seen
            if ls.tzinfo is None:
                ls = ls.replace(tzinfo=UTC)
            if (datetime.now(UTC) - ls).days < 7:
                has_recent += 1

    confidence = "high" if has_recent >= len(ids) * 0.7 else "low"
    suggested_profile = "mobile"
    preset = MOBILITY_PRESETS[suggested_profile]

    return {
        "suggested_profile": suggested_profile,
        "suggested_threshold_m": preset["distance_threshold_m"],
        "confidence": confidence,
        "tag_count": len(ids),
        "preset": preset,
    }


# ─── List active hives ───────────────────────────────────────────────────────

@router.get("")
def list_hives(request: Request, db: Session = Depends(get_db)):
    me = get_portal_user_from_request(request, db)
    gid = str(me.usergroup_id)

    hives = (
        db.query(Hive)
        .filter(Hive.usergroup_id == gid, Hive.status == "active")
        .order_by(Hive.created_at.desc())
        .all()
    )

    result = []
    for hive in hives:
        cfg = _current_config(str(hive.id), db)
        ls = db.query(HiveLiveState).filter(HiveLiveState.hive_id == str(hive.id)).first()
        result.append(_hive_summary(hive, cfg, ls, db))
    return result


# ─── List archived hives ─────────────────────────────────────────────────────

@router.get("/archive")
def list_archived_hives(request: Request, db: Session = Depends(get_db)):
    me = get_portal_user_from_request(request, db)
    gid = str(me.usergroup_id)

    hives = (
        db.query(Hive)
        .filter(Hive.usergroup_id == gid, Hive.status == "archived")
        .order_by(Hive.archived_at.desc())
        .all()
    )

    result = []
    for hive in hives:
        cfg = (
            db.query(HiveConfigVersion)
            .filter(HiveConfigVersion.hive_id == str(hive.id))
            .order_by(HiveConfigVersion.version_number.desc())
            .first()
        )
        total_alerts = db.query(HiveEvent).filter(
            HiveEvent.hive_id == str(hive.id),
            HiveEvent.event_type == "CONFIRMED_BREACH",
        ).count()
        days_purge = _days_remaining(hive.archive_expires_at)
        result.append({
            "hive_id": str(hive.id),
            "name": hive.name,
            "status": hive.status,
            "archived_at": _format_dt(hive.archived_at),
            "archived_reason": hive.archived_reason,
            "archive_expires_at": _format_dt(hive.archive_expires_at),
            "days_until_purge": days_purge,
            "tag_count": 0,  # tags released on archive
            "mobility_profile": cfg.mobility_profile if cfg else None,
            "total_alerts": total_alerts,
            "created_at": _format_dt(hive.created_at),
            "lifetime_days": (
                (hive.archived_at - hive.created_at).days
                if hive.archived_at and hive.created_at else None
            ),
            "parent_hive_id": str(hive.parent_hive_id) if hive.parent_hive_id else None,
        })
    return result


# ─── Create hive ─────────────────────────────────────────────────────────────

@router.post("")
def create_hive(
    data: HiveCreateRequest,
    request: Request,
    db: Session = Depends(get_db),
):
    import traceback as _tb
    try:
        return _create_hive_inner(data, request, db)
    except HTTPException:
        raise
    except Exception as exc:
        db.rollback()
        raise HTTPException(500, detail=f"[DEBUG] {type(exc).__name__}: {exc}") from exc


def _create_hive_inner(
    data: HiveCreateRequest,
    request: Request,
    db: Session,
):
    me = get_portal_user_from_request(request, db)
    gid = str(me.usergroup_id)

    # Validate mobility profile
    profile = data.mobility_profile
    if profile not in MOBILITY_PRESETS and profile != "custom":
        raise HTTPException(400, f"Unknown mobility profile: {profile}")
    preset = MOBILITY_PRESETS.get(profile, MOBILITY_PRESETS["mobile"])

    # Validate tags — not already in an active hive
    for tid in data.tag_ids:
        existing = db.query(HiveTagMembership).filter(HiveTagMembership.tag_id == tid).first()
        if existing:
            existing_hive = db.query(Hive).filter(
                Hive.id == existing.hive_id, Hive.status == "active"
            ).first()
            if existing_hive:
                raise HTTPException(
                    409,
                    f"Tag {tid} is already a member of active hive '{existing_hive.name}'",
                )

    now = datetime.now(UTC)
    hive_id = str(uuid.uuid4())

    hive = Hive(
        id=hive_id,
        usergroup_id=gid,
        created_by=str(me.id),
        name=data.name,
        status="active",
        expires_at=now + timedelta(days=60),
        settling_until=now + timedelta(minutes=10),  # 10-min settling window
    )
    db.add(hive)
    db.flush()

    # Config version 1
    cfg = HiveConfigVersion(
        id=str(uuid.uuid4()),
        hive_id=hive_id,
        version_number=1,
        valid_from=now,
        valid_to=None,
        mobility_profile=profile,
        distance_threshold_m=data.distance_threshold_m or preset["distance_threshold_m"],
        fresh_window_s=data.fresh_window_s or preset["fresh_window_s"],
        recent_window_s=data.recent_window_s or preset["recent_window_s"],
        stale_window_s=data.stale_window_s or preset["stale_window_s"],
        lost_threshold_s=data.lost_threshold_s or preset["lost_threshold_s"],
        meaningful_change_m=data.meaningful_change_m or preset["meaningful_change_m"],
        hysteresis_pct=data.hysteresis_pct or preset["hysteresis_pct"],
        confirmation_count=data.confirmation_count or preset["confirmation_count"],
        changed_by=str(me.id),
    )
    db.add(cfg)

    # Tag memberships
    labels = data.tag_labels or {}
    for tid in data.tag_ids:
        db.add(HiveTagMembership(
            tag_id=tid,
            hive_id=hive_id,
            label=labels.get(tid),
        ))

    # Live state
    db.add(HiveLiveState(
        hive_id=hive_id,
        alert_state="OK",
        consecutive_confirms=0,
    ))

    # Lifecycle creation event
    db.add(HiveEvent(
        id=str(uuid.uuid4()),
        hive_id=hive_id,
        occurred_at=now,
        event_type="HIVE_CREATED",
        config_version_number=1,
    ))

    db.commit()
    db.refresh(hive)

    return {"hive_id": hive_id, "message": "Hive created", "name": hive.name}

# ─── Get hive detail ─────────────────────────────────────────────────────────

@router.get("/{hive_id}")
def get_hive(hive_id: str, request: Request, db: Session = Depends(get_db)):
    me = get_portal_user_from_request(request, db)
    gid = str(me.usergroup_id)

    hive = db.query(Hive).filter(Hive.id == hive_id, Hive.usergroup_id == gid).first()
    if not hive:
        raise HTTPException(404, "Hive not found")

    cfg = _current_config(hive_id, db)
    ls = db.query(HiveLiveState).filter(HiveLiveState.hive_id == hive_id).first()

    # Full tag detail with positions and per-tag distances
    tag_details = []
    positions = []
    for m in hive.memberships:
        tag = db.query(BLETag).filter(BLETag.id == m.tag_id).first()
        if not tag:
            continue
        tier = _freshness_for_tag(tag, cfg) if cfg else "lost"
        is_outlier = str(m.tag_id) == (str(ls.outlier_tag_id) if ls else None)
        lat = float(tag.latitude) if tag.latitude else None
        lon = float(tag.longitude) if tag.longitude else None
        tag_details.append({
            "tag_id": str(m.tag_id),
            "label": m.label or tag.device_name or str(m.tag_id),
            "imei": tag.imei,
            "latitude": lat,
            "longitude": lon,
            "freshness": tier,
            "last_seen": _format_dt(tag.last_seen),
            "is_outlier": is_outlier,
            "distance_from_centre_m": None,  # computed below
        })
        if lat and lon and tier in ("fresh", "recent"):
            positions.append((str(m.tag_id), lat, lon))

    # Compute per-tag max distance from others (for the table)
    if len(positions) >= 2:
        from app.services.hive_service import haversine_m
        tag_max_dist: Dict[str, float] = {tid: 0.0 for tid, _, _ in positions}
        for i, (ta, la, loa) in enumerate(positions):
            for tb, lb, lob in positions[i + 1:]:
                d = haversine_m(la, loa, lb, lob)
                tag_max_dist[ta] = max(tag_max_dist[ta], d)
                tag_max_dist[tb] = max(tag_max_dist[tb], d)
        for td in tag_details:
            tid = td["tag_id"]
            if tid in tag_max_dist:
                td["distance_from_centre_m"] = round(tag_max_dist[tid], 1)

    # Recent events (last 24 h)
    cutoff = datetime.now(UTC) - timedelta(hours=24)
    recent_events = (
        db.query(HiveEvent)
        .filter(HiveEvent.hive_id == hive_id, HiveEvent.occurred_at >= cutoff)
        .order_by(HiveEvent.occurred_at.desc())
        .limit(20)
        .all()
    )
    events_out = [
        {
            "event_id": str(e.id),
            "event_type": e.event_type,
            "occurred_at": _format_dt(e.occurred_at),
            "from_state": e.from_state,
            "to_state": e.to_state,
            "triggering_tag_id": e.triggering_tag_id,
            "details": json.loads(e.details) if e.details else None,
        }
        for e in recent_events
    ]

    # Config
    cfg_out = None
    if cfg:
        cfg_out = {
            "version_number": cfg.version_number,
            "mobility_profile": cfg.mobility_profile,
            "distance_threshold_m": cfg.distance_threshold_m,
            "fresh_window_s": cfg.fresh_window_s,
            "recent_window_s": cfg.recent_window_s,
            "stale_window_s": cfg.stale_window_s,
            "lost_threshold_s": cfg.lost_threshold_s,
            "meaningful_change_m": cfg.meaningful_change_m,
            "hysteresis_pct": cfg.hysteresis_pct,
            "confirmation_count": cfg.confirmation_count,
            "valid_from": _format_dt(cfg.valid_from),
        }

    return {
        "hive_id": hive_id,
        "name": hive.name,
        "status": hive.status,
        "created_at": _format_dt(hive.created_at),
        "expires_at": _format_dt(hive.expires_at),
        "days_remaining": _days_remaining(hive.expires_at),
        "archived_at": _format_dt(hive.archived_at),
        "archived_reason": hive.archived_reason,
        "parent_hive_id": str(hive.parent_hive_id) if hive.parent_hive_id else None,
        "alert_state": ls.alert_state if ls else "OK",
        "breach_confidence": ls.breach_confidence if ls else None,
        "current_diameter_m": ls.current_diameter_m if ls else None,
        "outlier_tag_id": str(ls.outlier_tag_id) if ls and ls.outlier_tag_id else None,
        "last_evaluated_at": _format_dt(ls.last_evaluated_at) if ls else None,
        "config": cfg_out,
        "tags": tag_details,
        "recent_events": events_out,
    }


# ─── Update hive (name only) ──────────────────────────────────────────────────

@router.put("/{hive_id}")
def update_hive(
    hive_id: str,
    data: HiveUpdateRequest,
    request: Request,
    db: Session = Depends(get_db),
):
    me = get_portal_user_from_request(request, db)
    gid = str(me.usergroup_id)

    hive = db.query(Hive).filter(
        Hive.id == hive_id, Hive.usergroup_id == gid, Hive.status == "active"
    ).first()
    if not hive:
        raise HTTPException(404, "Hive not found")

    if data.name is not None:
        hive.name = data.name
    db.commit()
    return {"hive_id": hive_id, "name": hive.name}


# ─── Update config ────────────────────────────────────────────────────────────

@router.put("/{hive_id}/config")
def update_hive_config(
    hive_id: str,
    data: HiveConfigUpdateRequest,
    request: Request,
    db: Session = Depends(get_db),
):
    me = get_portal_user_from_request(request, db)
    gid = str(me.usergroup_id)

    hive = db.query(Hive).filter(
        Hive.id == hive_id, Hive.usergroup_id == gid, Hive.status == "active"
    ).first()
    if not hive:
        raise HTTPException(404, "Hive not found")

    profile = data.mobility_profile
    if profile not in MOBILITY_PRESETS and profile != "custom":
        raise HTTPException(400, f"Unknown mobility profile: {profile}")
    preset = MOBILITY_PRESETS.get(profile, MOBILITY_PRESETS["mobile"])

    # Close current config version
    now = datetime.now(UTC)
    current = _current_config(hive_id, db)
    next_version = (current.version_number + 1) if current else 1
    if current:
        current.valid_to = now

    new_cfg = HiveConfigVersion(
        id=str(uuid.uuid4()),
        hive_id=hive_id,
        version_number=next_version,
        valid_from=now,
        valid_to=None,
        mobility_profile=profile,
        distance_threshold_m=data.distance_threshold_m or preset["distance_threshold_m"],
        fresh_window_s=data.fresh_window_s or preset["fresh_window_s"],
        recent_window_s=data.recent_window_s or preset["recent_window_s"],
        stale_window_s=data.stale_window_s or preset["stale_window_s"],
        lost_threshold_s=data.lost_threshold_s or preset["lost_threshold_s"],
        meaningful_change_m=data.meaningful_change_m or preset["meaningful_change_m"],
        hysteresis_pct=data.hysteresis_pct or preset["hysteresis_pct"],
        confirmation_count=data.confirmation_count or preset["confirmation_count"],
        changed_by=str(me.id),
    )
    db.add(new_cfg)
    db.add(HiveEvent(
        id=str(uuid.uuid4()),
        hive_id=hive_id,
        occurred_at=now,
        event_type="CONFIG_CHANGED",
        config_version_number=next_version,
    ))
    db.commit()

    # Immediately re-evaluate under new config
    hive_service.evaluate_hive(hive_id, db)

    return {"hive_id": hive_id, "config_version": next_version, "message": "Config updated"}


# ─── Archive (soft delete) ────────────────────────────────────────────────────

@router.delete("/{hive_id}")
def delete_hive(hive_id: str, request: Request, db: Session = Depends(get_db)):
    me = get_portal_user_from_request(request, db)
    gid = str(me.usergroup_id)

    hive = db.query(Hive).filter(
        Hive.id == hive_id, Hive.usergroup_id == gid,
        Hive.status.in_(["active"]),
    ).first()
    if not hive:
        raise HTTPException(404, "Hive not found or not active")

    hive_service.archive_hive(hive, "user_deleted", db)
    return {"hive_id": hive_id, "status": "archived"}


# ─── Permanent purge ──────────────────────────────────────────────────────────

@router.delete("/{hive_id}/purge")
def purge_hive(hive_id: str, request: Request, db: Session = Depends(get_db)):
    me = get_portal_user_from_request(request, db)
    gid = str(me.usergroup_id)

    hive = db.query(Hive).filter(
        Hive.id == hive_id, Hive.usergroup_id == gid,
        Hive.status.in_(["active", "archived"]),
    ).first()
    if not hive:
        raise HTTPException(404, "Hive not found")

    hive_service.purge_hive(hive, "user_purged", db)
    return {"hive_id": hive_id, "status": "purged"}


# ─── Recreate ─────────────────────────────────────────────────────────────────

@router.post("/{hive_id}/recreate")
def recreate_hive(
    hive_id: str,
    request: Request,
    db: Session = Depends(get_db),
):
    """Create a new hive with the same name, config, and tag labels as a source hive."""
    me = get_portal_user_from_request(request, db)
    gid = str(me.usergroup_id)

    source = db.query(Hive).filter(
        Hive.id == hive_id, Hive.usergroup_id == gid
    ).first()
    if not source:
        raise HTTPException(404, "Source hive not found")

    # Get last config version
    src_cfg = (
        db.query(HiveConfigVersion)
        .filter(HiveConfigVersion.hive_id == hive_id)
        .order_by(HiveConfigVersion.version_number.desc())
        .first()
    )
    if not src_cfg:
        raise HTTPException(400, "Source hive has no config")

    # Get old memberships (for archived hives these will be gone — use hive_events for tag list)
    old_labels = {str(m.tag_id): m.label for m in source.memberships}

    # Validate tags are free (for active hive recreation, they should already be released)
    for tid in old_labels:
        existing = db.query(HiveTagMembership).filter(HiveTagMembership.tag_id == tid).first()
        if existing:
            existing_hive = db.query(Hive).filter(
                Hive.id == existing.hive_id, Hive.status == "active"
            ).first()
            if existing_hive and existing_hive.id != source.id:
                raise HTTPException(
                    409,
                    f"Tag {tid} is in active hive '{existing_hive.name}' — cannot recreate",
                )

    now = datetime.now(UTC)
    new_id = str(uuid.uuid4())

    new_hive = Hive(
        id=new_id,
        usergroup_id=gid,
        created_by=str(me.id),
        name=source.name,
        status="active",
        expires_at=now + timedelta(days=60),
        settling_until=now + timedelta(minutes=10),
        parent_hive_id=str(source.id),
    )
    db.add(new_hive)
    db.flush()

    new_cfg = HiveConfigVersion(
        id=str(uuid.uuid4()),
        hive_id=new_id,
        version_number=1,
        valid_from=now,
        valid_to=None,
        mobility_profile=src_cfg.mobility_profile,
        distance_threshold_m=src_cfg.distance_threshold_m,
        fresh_window_s=src_cfg.fresh_window_s,
        recent_window_s=src_cfg.recent_window_s,
        stale_window_s=src_cfg.stale_window_s,
        lost_threshold_s=src_cfg.lost_threshold_s,
        meaningful_change_m=src_cfg.meaningful_change_m,
        hysteresis_pct=src_cfg.hysteresis_pct,
        confirmation_count=src_cfg.confirmation_count,
        changed_by=str(me.id),
    )
    db.add(new_cfg)

    for tid, label in old_labels.items():
        db.add(HiveTagMembership(tag_id=tid, hive_id=new_id, label=label))

    db.add(HiveLiveState(hive_id=new_id, alert_state="OK", consecutive_confirms=0))
    db.add(HiveEvent(
        id=str(uuid.uuid4()),
        hive_id=new_id,
        occurred_at=now,
        event_type="HIVE_CREATED",
        config_version_number=1,
        details=json.dumps({"recreated_from": hive_id}),
    ))

    db.commit()
    return {"hive_id": new_id, "name": new_hive.name, "message": "Hive recreated"}


# ─── Manual evaluate trigger ─────────────────────────────────────────────────

@router.post("/{hive_id}/evaluate")
def trigger_evaluate(hive_id: str, request: Request, db: Session = Depends(get_db)):
    me = get_portal_user_from_request(request, db)
    gid = str(me.usergroup_id)

    hive = db.query(Hive).filter(
        Hive.id == hive_id, Hive.usergroup_id == gid, Hive.status == "active"
    ).first()
    if not hive:
        raise HTTPException(404, "Hive not found")

    new_state = hive_service.evaluate_hive(hive_id, db)
    return {"hive_id": hive_id, "alert_state": new_state}


# ─── Event history ───────────────────────────────────────────────────────────

@router.get("/{hive_id}/events")
def get_hive_events(
    hive_id: str,
    hours: int = 24,
    request: Request = None,
    db: Session = Depends(get_db),
):
    me = get_portal_user_from_request(request, db)
    gid = str(me.usergroup_id)

    hive = db.query(Hive).filter(Hive.id == hive_id, Hive.usergroup_id == gid).first()
    if not hive:
        raise HTTPException(404, "Hive not found")

    cutoff = datetime.now(UTC) - timedelta(hours=hours)
    events = (
        db.query(HiveEvent)
        .filter(HiveEvent.hive_id == hive_id, HiveEvent.occurred_at >= cutoff)
        .order_by(HiveEvent.occurred_at.desc())
        .limit(100)
        .all()
    )
    return [
        {
            "event_id": str(e.id),
            "event_type": e.event_type,
            "occurred_at": _format_dt(e.occurred_at),
            "from_state": e.from_state,
            "to_state": e.to_state,
            "triggering_tag_id": e.triggering_tag_id,
            "details": json.loads(e.details) if e.details else None,
        }
        for e in events
    ]
