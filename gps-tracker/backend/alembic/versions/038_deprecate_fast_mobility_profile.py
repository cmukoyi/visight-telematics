"""deprecate fast mobility profile + refresh presets to v1.1 (HIVE spec v1.1)

Revision ID: 038
Revises: 037
Create Date: 2026-05-27

Spec v1.1 deprecates the Fast mobility profile (merged into Mobile, now
15 km/h motion threshold with 10 min settling) and recalibrates Stationary,
Slow, and Mobile presets per Appendix A.

This migration:
  1. Rewrites any existing hive_config_versions rows with mobility_profile='fast'
     to 'mobile'.
  2. Refreshes the snapshotted preset parameters on ALL existing rows so
     every active hive uses the v1.1 presets for its (possibly remapped)
     profile. This is safe because PinPlot and Beacon have only test hives at
     this point — no live customer hives whose behaviour we'd be changing
     mid-flight.
  3. Preserves any user-customised distance_threshold_m by NOT overwriting it
     when it differs from the legacy preset default (best-effort: legacy
     defaults were 50/100/200/500 m for stationary/slow/mobile/fast).

Hives created after this migration pick up v1.1 presets directly from
MOBILITY_PRESETS at creation time — see app/models.py.
"""
from alembic import op
from sqlalchemy import text


revision = "038"
down_revision = "037"
branch_labels = None
depends_on = None


# v1.1 Appendix A presets — keep in sync with app/models.py MOBILITY_PRESETS.
PRESETS_V1_1 = {
    "stationary": {
        "fresh_window_s":     1800,
        "recent_window_s":    14400,
        "stale_window_s":     86400,
        "lost_threshold_s":   86400,
        "meaningful_change_m": 2.5,
        "distance_threshold_m": 150.0,
        "hysteresis_pct":     90.0,
        "confirmation_count": 1,
        "motion_speed_threshold_kmh": None,
        "motion_settling_time_s":     None,
    },
    "slow": {
        "fresh_window_s":     1200,
        "recent_window_s":    7200,
        "stale_window_s":     28800,
        "lost_threshold_s":   28800,
        "meaningful_change_m": 15.0,
        "distance_threshold_m": 450.0,
        "hysteresis_pct":     85.0,
        "confirmation_count": 1,
        "motion_speed_threshold_kmh": 10.0,
        "motion_settling_time_s":     600,
    },
    "mobile": {
        "fresh_window_s":     900,
        "recent_window_s":    3600,
        "stale_window_s":     14400,
        "lost_threshold_s":   7200,
        "meaningful_change_m": 30.0,
        "distance_threshold_m": 1000.0,
        "hysteresis_pct":     75.0,
        "confirmation_count": 1,
        "motion_speed_threshold_kmh": 15.0,
        "motion_settling_time_s":     600,
    },
}

# Legacy default distance_threshold_m values per profile, used to detect
# user-customised thresholds we should preserve.
LEGACY_DEFAULT_THRESHOLDS = {
    "stationary": 50.0,
    "slow":       100.0,
    "mobile":     200.0,
    "fast":       500.0,
}


def upgrade():
    conn = op.get_bind()

    # ── 1. Remap 'fast' → 'mobile' ────────────────────────────────────────────
    conn.execute(
        text(
            "UPDATE hive_config_versions "
            "SET mobility_profile = 'mobile' "
            "WHERE mobility_profile = 'fast'"
        )
    )

    # ── 2. Refresh presets on all rows per their (now-current) profile ────────
    # Track the original profile for distance-threshold preservation logic.
    rows = conn.execute(
        text(
            "SELECT hive_id, version_number, mobility_profile, distance_threshold_m "
            "FROM hive_config_versions"
        )
    ).fetchall()

    for row in rows:
        hive_id, version_number, profile, current_threshold = row
        if profile not in PRESETS_V1_1:
            # 'custom' or unknown — leave untouched.
            continue

        preset = PRESETS_V1_1[profile]

        # Preserve a user-customised distance threshold: if the current value
        # doesn't match either the legacy default for this profile OR the
        # legacy 'fast' default (in case this row was just remapped), assume
        # the user set it deliberately and keep it.
        legacy_default = LEGACY_DEFAULT_THRESHOLDS.get(profile)
        legacy_fast    = LEGACY_DEFAULT_THRESHOLDS["fast"]
        if current_threshold in (legacy_default, legacy_fast):
            new_threshold = preset["distance_threshold_m"]
        else:
            new_threshold = current_threshold  # user-customised

        conn.execute(
            text(
                """
                UPDATE hive_config_versions SET
                    fresh_window_s             = :fresh_window_s,
                    recent_window_s            = :recent_window_s,
                    stale_window_s             = :stale_window_s,
                    lost_threshold_s           = :lost_threshold_s,
                    meaningful_change_m        = :meaningful_change_m,
                    distance_threshold_m       = :distance_threshold_m,
                    hysteresis_pct             = :hysteresis_pct,
                    confirmation_count         = :confirmation_count,
                    motion_speed_threshold_kmh = :motion_speed_threshold_kmh,
                    motion_settling_time_s     = :motion_settling_time_s
                WHERE hive_id = :hive_id AND version_number = :version_number
                """
            ),
            {
                **preset,
                "distance_threshold_m": new_threshold,
                "hive_id": hive_id,
                "version_number": version_number,
            },
        )


def downgrade():
    # No-op: we cannot reconstruct the original 'fast' rows nor the legacy
    # preset values from the v1.1 snapshot.
    pass
