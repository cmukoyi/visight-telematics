"""Trip Engine schema for Movement History Advanced

Revision ID: 055
Revises: 054
Create Date: 2026-07-05

Implements complete Trip Engine architecture from PinPlot_Trip_Engine_Spec_v2.md:

Section 1 (Ingestion):
- device_positions: Single source of truth for GPS points from TrackSolid
- device_state: Per-device trigger tracking for smart API calling
- tracksolid_sync_state: Global sync metadata and rate limiting

Section 2 (Trip State Engine):
- engine_state: Per-device state machine (STATIONARY ↔ MOVE)
- stationaries: Grouped idle periods with anchor centroids
- legs: Movement segments between stationaries
- journeys: Grouped legs/stationaries within 30-min dwell threshold

Configuration:
- trip_config: Global and per-tenant overrides for all engine parameters
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy import text

revision = "055"
down_revision = "054"
branch_labels = None
depends_on = None


def _table_exists(conn, table_name: str) -> bool:
    result = conn.execute(
        text(
            "SELECT EXISTS (SELECT FROM information_schema.tables "
            "WHERE table_name = :table_name)"
        ),
        {"table_name": table_name},
    )
    return result.scalar()


def upgrade():
    conn = op.get_bind()
    
    # ═══════════════════════════════════════════════════════════════════════════
    # SECTION 1: DATA INGESTION
    # ═══════════════════════════════════════════════════════════════════════════
    
    # ── 1. device_positions (single source of truth) ──────────────────────────
    if not _table_exists(conn, "device_positions"):
        op.create_table(
            "device_positions",
            sa.Column("id", sa.BigInteger, primary_key=True, autoincrement=True),
            sa.Column("device_imei", sa.String(20), nullable=False, index=True),
            
            # Core position data (from TrackSolid API)
            sa.Column("lat", sa.Double, nullable=False),
            sa.Column("lng", sa.Double, nullable=False),
            sa.Column("observed_at", sa.DateTime(timezone=True), nullable=False, index=True),
            
            # Movement metadata
            sa.Column("direction", sa.Integer, nullable=True),           # 0-360 degrees
            sa.Column("gps_speed", sa.Double, nullable=True),            # km/h
            sa.Column("pos_type", sa.Integer, nullable=True),            # 1=GPS, 2=LBS, 3=WIFI, 5=unknown
            sa.Column("satellite", sa.Integer, nullable=True),           # GPS satellite count
            sa.Column("ignition", sa.String(10), nullable=True),         # ON/OFF
            sa.Column("acc_status", sa.String(10), nullable=True),       # ON/OFF
            sa.Column("gps_mode", sa.Integer, nullable=True),
            sa.Column("confidence", sa.Integer, nullable=True),          # 1-3 (NEVER use for classification per spec)
            
            # Metadata
            sa.Column("source", sa.String(20), nullable=False, server_default="batch"),  # 'batch' or 'tracklist'
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), index=True),
            
            # Unique constraint: one position per device per timestamp
            sa.UniqueConstraint("device_imei", "observed_at", name="uq_device_positions_imei_observed_at"),
        )
        
        # Composite index for time-range queries
        op.create_index(
            "idx_device_positions_imei_observed_at",
            "device_positions",
            ["device_imei", "observed_at"],
        )
    
    # ── 2. device_state (trigger tracking) ────────────────────────────────────
    if not _table_exists(conn, "device_state"):
        op.create_table(
            "device_state",
            sa.Column("device_imei", sa.String(20), primary_key=True),
            
            # Trigger detection timestamps
            sa.Column("last_batch_ts", sa.DateTime(timezone=True), nullable=True),        # Latest batch sweep timestamp
            sa.Column("last_position_ts", sa.DateTime(timezone=True), nullable=True),     # Latest GPS point timestamp (for forward-only window)
            sa.Column("last_tracklist_pull_at", sa.DateTime(timezone=True), nullable=True),  # Last time track.list was called
            
            # Subscription model (premium opt-in for expensive track.list calls)
            sa.Column("trip_subscribed", sa.Boolean, nullable=False, server_default="false", index=True),
            
            # Per-device config override (NULL = use global/tenant default)
            sa.Column("coalesce_floor_minutes", sa.Integer, nullable=True),
            
            # Metadata
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
            sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), onupdate=sa.func.now()),
        )
        
        # Index for subscription queries
        op.create_index("idx_device_state_trip_subscribed", "device_state", ["trip_subscribed"])
    
    # ── 3. tracksolid_sync_state (global sync metadata) ───────────────────────
    if not _table_exists(conn, "tracksolid_sync_state"):
        op.create_table(
            "tracksolid_sync_state",
            sa.Column("id", sa.Integer, primary_key=True, server_default="1"),  # Singleton row
            
            # Last sync timestamps
            sa.Column("last_batch_sweep_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("last_selective_sweep_at", sa.DateTime(timezone=True), nullable=True),
            
            # Rate limiting (TrackSolid limit: 86,400 calls/day)
            sa.Column("api_calls_today", sa.Integer, nullable=False, server_default="0"),
            sa.Column("api_calls_reset_at", sa.DateTime(timezone=True), nullable=True),
            
            # Metadata
            sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), onupdate=sa.func.now()),
        )
    
    # ═══════════════════════════════════════════════════════════════════════════
    # SECTION 2: TRIP STATE ENGINE
    # ═══════════════════════════════════════════════════════════════════════════
    
    # ── 4. engine_state (per-device state machine) ────────────────────────────
    if not _table_exists(conn, "engine_state"):
        op.create_table(
            "engine_state",
            sa.Column("device_imei", sa.String(20), primary_key=True),
            
            # State machine
            sa.Column("current_state", sa.String(20), nullable=False, server_default="STATIONARY"),  # STATIONARY or MOVE
            
            # Rolling anchor (for STATIONARY state)
            sa.Column("anchor_lat", sa.Double, nullable=True),
            sa.Column("anchor_lng", sa.Double, nullable=True),
            sa.Column("anchor_count", sa.Integer, nullable=False, server_default="0"),  # Points in current anchor
            
            # Current trip context (for MOVE state)
            sa.Column("current_leg_id", UUID(as_uuid=True), nullable=True),           # FK to legs.id
            sa.Column("current_journey_id", UUID(as_uuid=True), nullable=True),       # FK to journeys.id
            
            # Processing watermark
            sa.Column("last_processed_at", sa.DateTime(timezone=True), nullable=True),  # Latest device_positions.observed_at processed
            
            # Metadata
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
            sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), onupdate=sa.func.now()),
        )
        
        # Index for state queries
        op.create_index("idx_engine_state_current_state", "engine_state", ["current_state"])
    
    # ── 5. stationaries (idle periods) ────────────────────────────────────────
    if not _table_exists(conn, "stationaries"):
        op.create_table(
            "stationaries",
            sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
            sa.Column("device_imei", sa.String(20), nullable=False, index=True),
            sa.Column("journey_id", UUID(as_uuid=True), nullable=True, index=True),  # FK to journeys.id (NULL if ungrouped)
            
            # Position references
            sa.Column("start_position_id", sa.BigInteger, nullable=False),  # FK to device_positions.id
            sa.Column("end_position_id", sa.BigInteger, nullable=False),    # FK to device_positions.id
            
            # Time window
            sa.Column("started_at", sa.DateTime(timezone=True), nullable=False, index=True),
            sa.Column("ended_at", sa.DateTime(timezone=True), nullable=False),
            
            # Geometry
            sa.Column("anchor_lat", sa.Double, nullable=False),
            sa.Column("anchor_lng", sa.Double, nullable=False),
            sa.Column("point_count", sa.Integer, nullable=False),
            
            # Metrics
            sa.Column("duration_seconds", sa.Integer, nullable=False),
            
            # Metadata
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        )
        
        # Composite index for device + time queries
        op.create_index(
            "idx_stationaries_imei_started_at",
            "stationaries",
            ["device_imei", "started_at"],
        )
    
    # ── 6. legs (movement segments) ───────────────────────────────────────────
    if not _table_exists(conn, "legs"):
        op.create_table(
            "legs",
            sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
            sa.Column("device_imei", sa.String(20), nullable=False, index=True),
            sa.Column("journey_id", UUID(as_uuid=True), nullable=True, index=True),  # FK to journeys.id (NULL if ungrouped)
            
            # Position references
            sa.Column("start_position_id", sa.BigInteger, nullable=False),  # FK to device_positions.id
            sa.Column("end_position_id", sa.BigInteger, nullable=False),    # FK to device_positions.id
            
            # Time window
            sa.Column("started_at", sa.DateTime(timezone=True), nullable=False, index=True),
            sa.Column("ended_at", sa.DateTime(timezone=True), nullable=False),
            
            # Metrics
            sa.Column("distance_m", sa.Double, nullable=False),
            sa.Column("duration_seconds", sa.Integer, nullable=False),
            sa.Column("point_count", sa.Integer, nullable=False),
            
            # Classification
            sa.Column("is_air_leg", sa.Boolean, nullable=False, server_default="false", index=True),
            
            # Metadata
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        )
        
        # Composite index for device + time queries
        op.create_index(
            "idx_legs_imei_started_at",
            "legs",
            ["device_imei", "started_at"],
        )
        
        # Index for air leg queries
        op.create_index("idx_legs_is_air_leg", "legs", ["is_air_leg"])
    
    # ── 7. journeys (grouped trips) ───────────────────────────────────────────
    if not _table_exists(conn, "journeys"):
        op.create_table(
            "journeys",
            sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
            sa.Column("device_imei", sa.String(20), nullable=False, index=True),
            
            # Time window
            sa.Column("started_at", sa.DateTime(timezone=True), nullable=False, index=True),
            sa.Column("ended_at", sa.DateTime(timezone=True), nullable=False),
            
            # Journey structure references
            sa.Column("first_leg_id", UUID(as_uuid=True), nullable=True),   # FK to legs.id (NULL if journey is single stationary)
            sa.Column("last_leg_id", UUID(as_uuid=True), nullable=True),    # FK to legs.id
            
            # Metrics
            sa.Column("leg_count", sa.Integer, nullable=False, server_default="0"),
            sa.Column("stationary_count", sa.Integer, nullable=False, server_default="0"),
            sa.Column("total_distance_m", sa.Double, nullable=False, server_default="0"),
            sa.Column("total_duration_seconds", sa.Integer, nullable=False),
            
            # Classification
            sa.Column("is_air_journey", sa.Boolean, nullable=False, server_default="false", index=True),  # Has air legs
            
            # Metadata
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        )
        
        # Composite index for device + time queries
        op.create_index(
            "idx_journeys_imei_started_at",
            "journeys",
            ["device_imei", "started_at"],
        )
        
        # Index for air journey queries
        op.create_index("idx_journeys_is_air_journey", "journeys", ["is_air_journey"])
    
    # ═══════════════════════════════════════════════════════════════════════════
    # CONFIGURATION
    # ═══════════════════════════════════════════════════════════════════════════
    
    # ── 8. trip_config (admin configuration) ──────────────────────────────────
    if not _table_exists(conn, "trip_config"):
        op.create_table(
            "trip_config",
            sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
            sa.Column("tenant_id", UUID(as_uuid=True), nullable=True, unique=True, index=True),  # NULL = global default
            
            # ── Ingestion parameters ──
            sa.Column("batch_sweep_interval_minutes", sa.Integer, nullable=False, server_default="10"),
            sa.Column("tracklist_delay_minutes", sa.Integer, nullable=False, server_default="5"),
            sa.Column("coalesce_floor_minutes", sa.Integer, nullable=False, server_default="120"),
            
            # ── Engine geometry parameters ──
            sa.Column("engine_anchor_radius_m", sa.Integer, nullable=False, server_default="100"),
            sa.Column("engine_min_leg_distance_m", sa.Integer, nullable=False, server_default="300"),
            sa.Column("engine_move_confirm_m", sa.Integer, nullable=False, server_default="150"),
            
            # ── Engine thresholds ──
            sa.Column("engine_max_speed_kmh", sa.Integer, nullable=False, server_default="200"),
            sa.Column("engine_gap_timeout_min", sa.Integer, nullable=False, server_default="30"),
            sa.Column("engine_smoothing_window", sa.Integer, nullable=False, server_default="3"),
            
            # ── Air leg detection ──
            sa.Column("engine_air_speed_kmh", sa.Integer, nullable=False, server_default="300"),
            sa.Column("engine_air_min_distance_km", sa.Integer, nullable=False, server_default="150"),
            
            # ── Journey grouping ──
            sa.Column("engine_journey_break_dwell_min", sa.Integer, nullable=False, server_default="30"),
            
            # Metadata
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
            sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), onupdate=sa.func.now()),
        )
        
        # Insert global default configuration (validated from spec)
        op.execute(
            text(
                """
                INSERT INTO trip_config (
                    tenant_id,
                    batch_sweep_interval_minutes,
                    tracklist_delay_minutes,
                    coalesce_floor_minutes,
                    engine_anchor_radius_m,
                    engine_min_leg_distance_m,
                    engine_move_confirm_m,
                    engine_max_speed_kmh,
                    engine_gap_timeout_min,
                    engine_smoothing_window,
                    engine_air_speed_kmh,
                    engine_air_min_distance_km,
                    engine_journey_break_dwell_min
                ) VALUES (
                    NULL,              -- Global default
                    10,                -- batch_sweep_interval_minutes
                    5,                 -- tracklist_delay_minutes
                    120,               -- coalesce_floor_minutes
                    100,               -- engine_anchor_radius_m
                    300,               -- engine_min_leg_distance_m
                    150,               -- engine_move_confirm_m
                    200,               -- engine_max_speed_kmh
                    30,                -- engine_gap_timeout_min
                    3,                 -- engine_smoothing_window
                    300,               -- engine_air_speed_kmh
                    150,               -- engine_air_min_distance_km
                    30                 -- engine_journey_break_dwell_min
                )
                """
            )
        )
    
    # ═══════════════════════════════════════════════════════════════════════════
    # FOREIGN KEY CONSTRAINTS
    # ═══════════════════════════════════════════════════════════════════════════
    
    # Foreign keys are added after all tables exist to avoid circular dependencies
    
    # engine_state → legs
    op.create_foreign_key(
        "fk_engine_state_current_leg",
        "engine_state",
        "legs",
        ["current_leg_id"],
        ["id"],
        ondelete="SET NULL",
    )
    
    # engine_state → journeys
    op.create_foreign_key(
        "fk_engine_state_current_journey",
        "engine_state",
        "journeys",
        ["current_journey_id"],
        ["id"],
        ondelete="SET NULL",
    )
    
    # stationaries → device_positions (start)
    op.create_foreign_key(
        "fk_stationaries_start_position",
        "stationaries",
        "device_positions",
        ["start_position_id"],
        ["id"],
        ondelete="CASCADE",
    )
    
    # stationaries → device_positions (end)
    op.create_foreign_key(
        "fk_stationaries_end_position",
        "stationaries",
        "device_positions",
        ["end_position_id"],
        ["id"],
        ondelete="CASCADE",
    )
    
    # stationaries → journeys
    op.create_foreign_key(
        "fk_stationaries_journey",
        "stationaries",
        "journeys",
        ["journey_id"],
        ["id"],
        ondelete="SET NULL",
    )
    
    # legs → device_positions (start)
    op.create_foreign_key(
        "fk_legs_start_position",
        "legs",
        "device_positions",
        ["start_position_id"],
        ["id"],
        ondelete="CASCADE",
    )
    
    # legs → device_positions (end)
    op.create_foreign_key(
        "fk_legs_end_position",
        "legs",
        "device_positions",
        ["end_position_id"],
        ["id"],
        ondelete="CASCADE",
    )
    
    # legs → journeys
    op.create_foreign_key(
        "fk_legs_journey",
        "legs",
        "journeys",
        ["journey_id"],
        ["id"],
        ondelete="SET NULL",
    )
    
    # journeys → legs (first)
    op.create_foreign_key(
        "fk_journeys_first_leg",
        "journeys",
        "legs",
        ["first_leg_id"],
        ["id"],
        ondelete="SET NULL",
    )
    
    # journeys → legs (last)
    op.create_foreign_key(
        "fk_journeys_last_leg",
        "journeys",
        "legs",
        ["last_leg_id"],
        ["id"],
        ondelete="SET NULL",
    )


def downgrade():
    """Drop all Trip Engine tables in reverse dependency order"""
    
    # Drop foreign keys first
    op.drop_constraint("fk_journeys_last_leg", "journeys", type_="foreignkey")
    op.drop_constraint("fk_journeys_first_leg", "journeys", type_="foreignkey")
    op.drop_constraint("fk_legs_journey", "legs", type_="foreignkey")
    op.drop_constraint("fk_legs_end_position", "legs", type_="foreignkey")
    op.drop_constraint("fk_legs_start_position", "legs", type_="foreignkey")
    op.drop_constraint("fk_stationaries_journey", "stationaries", type_="foreignkey")
    op.drop_constraint("fk_stationaries_end_position", "stationaries", type_="foreignkey")
    op.drop_constraint("fk_stationaries_start_position", "stationaries", type_="foreignkey")
    op.drop_constraint("fk_engine_state_current_journey", "engine_state", type_="foreignkey")
    op.drop_constraint("fk_engine_state_current_leg", "engine_state", type_="foreignkey")
    
    # Drop tables in reverse order
    op.drop_table("trip_config")
    op.drop_table("journeys")
    op.drop_table("legs")
    op.drop_table("stationaries")
    op.drop_table("engine_state")
    op.drop_table("tracksolid_sync_state")
    op.drop_table("device_state")
    op.drop_table("device_positions")
