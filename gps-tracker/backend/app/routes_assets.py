"""Asset management routes for QR/NFC tracking"""
from fastapi import APIRouter, HTTPException, Depends
from sqlalchemy.orm import Session
from sqlalchemy import text
from typing import Optional
from app.database import get_db
from app.schemas.asset import (
    AssetCreate, AssetResponse, AssetHistoryResponse, ScanEventResponse
)

router = APIRouter(prefix="/api/assets", tags=["assets"])


@router.post("", response_model=AssetResponse, status_code=201)
async def create_asset(body: AssetCreate, db: Session = Depends(get_db)):
    """
    Register a new asset (called when QR code is downloaded).
    Returns 409 if asset ID already exists (allow silent retry).
    """
    # Check if asset already exists
    existing = db.execute(
        text("SELECT id FROM assets WHERE id = :id"),
        {"id": body.id}
    ).fetchone()
    
    if existing:
        raise HTTPException(
            status_code=409,
            detail={"error": "Asset ID already exists", "asset_id": body.id}
        )
    
    # Insert new asset
    db.execute(
        text("""
            INSERT INTO assets (id, type_code, name, category, owner_id, notes)
            VALUES (:id, :type_code, :name, :category, :owner_id, :notes)
        """),
        {
            "id": body.id,
            "type_code": body.type_code,
            "name": body.name,
            "category": body.category,
            "owner_id": str(body.owner_id) if body.owner_id else None,
            "notes": body.notes
        }
    )
    db.commit()
    
    # Fetch and return created asset
    row = db.execute(
        text("""
            SELECT id, type_code, name, category, owner_id, created_at
            FROM assets WHERE id = :id
        """),
        {"id": body.id}
    ).fetchone()
    
    return AssetResponse(
        id=row.id,
        type_code=row.type_code,
        name=row.name,
        category=row.category,
        owner_id=row.owner_id,
        created_at=row.created_at
    )


@router.get("", response_model=list[AssetResponse])
async def list_assets(
    category: Optional[str] = None,
    owner_id: Optional[str] = None,
    db: Session = Depends(get_db)
):
    """
    List all assets with their latest known positions.
    Supports optional filtering by category and owner_id.
    """
    filters = []
    params = {}
    
    if category:
        filters.append("a.category = :category")
        params["category"] = category
    
    if owner_id:
        filters.append("a.owner_id = :owner_id")
        params["owner_id"] = owner_id
    
    where_clause = f"WHERE {' AND '.join(filters)}" if filters else ""
    
    rows = db.execute(
        text(f"""
            SELECT 
                a.id, a.type_code, a.name, a.category, a.owner_id, a.created_at,
                al.lat, al.lng, al.accuracy, al.last_seen, al.scan_count
            FROM assets a
            LEFT JOIN asset_locations al ON al.asset_id = a.id
            {where_clause}
            ORDER BY al.last_seen DESC NULLS LAST
        """),
        params
    ).fetchall()
    
    return [
        AssetResponse(
            id=r.id,
            type_code=r.type_code,
            name=r.name,
            category=r.category,
            owner_id=r.owner_id,
            created_at=r.created_at,
            lat=r.lat,
            lng=r.lng,
            accuracy=r.accuracy,
            last_seen=r.last_seen,
            scan_count=r.scan_count
        )
        for r in rows
    ]


@router.get("/{asset_id}", response_model=AssetResponse)
async def get_asset(asset_id: str, db: Session = Depends(get_db)):
    """Get a single asset with its latest position"""
    row = db.execute(
        text("""
            SELECT 
                a.id, a.type_code, a.name, a.category, a.owner_id, a.created_at,
                al.lat, al.lng, al.accuracy, al.last_seen, al.scan_count
            FROM assets a
            LEFT JOIN asset_locations al ON al.asset_id = a.id
            WHERE a.id = :asset_id
        """),
        {"asset_id": asset_id}
    ).fetchone()
    
    if not row:
        raise HTTPException(
            status_code=404,
            detail={"error": "Asset not found", "asset_id": asset_id}
        )
    
    return AssetResponse(
        id=row.id,
        type_code=row.type_code,
        name=row.name,
        category=row.category,
        owner_id=row.owner_id,
        created_at=row.created_at,
        lat=row.lat,
        lng=row.lng,
        accuracy=row.accuracy,
        last_seen=row.last_seen,
        scan_count=row.scan_count
    )


@router.get("/{asset_id}/history", response_model=AssetHistoryResponse)
async def get_asset_history(
    asset_id: str,
    limit: int = 100,
    offset: int = 0,
    db: Session = Depends(get_db)
):
    """
    Get full scan history for an asset in reverse chronological order.
    Used for movement trail visualization on the map.
    """
    # Verify asset exists
    asset_exists = db.execute(
        text("SELECT 1 FROM assets WHERE id = :asset_id"),
        {"asset_id": asset_id}
    ).fetchone()
    
    if not asset_exists:
        raise HTTPException(
            status_code=404,
            detail={"error": "Asset not found", "asset_id": asset_id}
        )
    
    # Get scan history
    rows = db.execute(
        text("""
            SELECT id, asset_id, lat, lng, accuracy, source, scanned_at, scanner_ip
            FROM scan_events
            WHERE asset_id = :asset_id
            ORDER BY scanned_at DESC
            LIMIT :limit OFFSET :offset
        """),
        {"asset_id": asset_id, "limit": limit, "offset": offset}
    ).fetchall()
    
    # Get total count
    total = db.execute(
        text("SELECT COUNT(*) FROM scan_events WHERE asset_id = :asset_id"),
        {"asset_id": asset_id}
    ).scalar()
    
    return AssetHistoryResponse(
        asset_id=asset_id,
        total=total,
        limit=limit,
        offset=offset,
        history=[
            ScanEventResponse(
                id=r.id,
                asset_id=r.asset_id,
                lat=r.lat,
                lng=r.lng,
                accuracy=r.accuracy,
                source=r.source,
                scanned_at=r.scanned_at,
                scanner_ip=r.scanner_ip
            )
            for r in rows
        ]
    )
