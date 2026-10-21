"""Remove TrackSolid, MZone/Scope, Hubble, BLE/indoor, HIVE, QR asset and trip-engine data.

Revision ID: 065_remove_legacy_integrations
Revises: 064_add_device_events
Create Date: 2026-10-22

ViSight Track is Teltonika-only. This permanently deletes:
  - every device whose tag_type is not 'teltonika', with its geofence links,
    geofence alerts and positions (portal alerts are kept, detached)
  - positions not written by the DataProfiler ingest (source <> 'teltonika')
  - the tables of the removed integrations (see LEGACY_TABLES)
  - columns only those integrations used
  - critical-alert subscriptions for retired categories

IRREVERSIBLE: downgrade raises. Take a database backup before upgrading.
"""
from alembic import op

revision = "065_remove_legacy_integrations"
down_revision = "064_add_device_events"
branch_labels = None
depends_on = None

LEGACY_TABLES = [
    # TrackSolid / MZone polling and token cache
    "tracksolid_devices", "tracksolid_locations", "tracksolid_sync_state", "api_tokens",
    # Trip engine
    "journeys", "legs", "stationaries", "engine_state", "device_state", "trip_config", "async_jobs",
    # BLE beacons / indoor floorplans
    "beacon_sightings", "tag_indoor_positions", "indoor_gateways", "rooms", "floors", "buildings",
    # HIVE
    "hive_tag_membership", "hive_evaluations", "hive_events", "hive_live_state",
    "hive_config_versions", "hives",
    # QR / NFC assets
    "scan_events", "asset_locations", "assets",
    # Hubble webhooks
    "webhook_logs",
    # Mobile app
    "app_features", "verification_pins", "password_reset_tokens",
    # Mobile-user billing snapshots
    "billing_transactions", "billing_data",
]

RETIRED_ALERT_CATEGORIES = ("poller_core", "tracksolid", "mzone", "pareto_bridge")


def upgrade():
    # 1. Non-Teltonika devices and everything keyed to them
    legacy_tags = "SELECT id FROM ble_tags WHERE tag_type IS DISTINCT FROM 'teltonika'"
    op.execute(f"DELETE FROM poi_tracker_links WHERE tracker_id IN ({legacy_tags})")
    op.execute(f"DELETE FROM geofence_alerts WHERE tracker_id IN ({legacy_tags})")
    op.execute(f"UPDATE portal_alerts SET tag_id = NULL WHERE tag_id IN ({legacy_tags})")
    op.execute("DELETE FROM device_positions WHERE source IS DISTINCT FROM 'teltonika'")
    op.execute("DELETE FROM ble_tags WHERE tag_type IS DISTINCT FROM 'teltonika'")

    # 2. Legacy tables (CASCADE drops FKs from other legacy tables)
    for table in LEGACY_TABLES:
        op.execute(f'DROP TABLE IF EXISTS "{table}" CASCADE')

    # 3. Columns only the removed integrations used. Dropping mac_address also
    #    drops chk_ble_tags_identifier and ix_ble_tags_mac_address.
    op.execute("ALTER TABLE ble_tags DROP COLUMN IF EXISTS mzone_vehicle_id")
    op.execute("ALTER TABLE ble_tags DROP COLUMN IF EXISTS mac_address CASCADE")
    op.execute("ALTER TABLE ble_tags ALTER COLUMN imei SET NOT NULL")
    op.execute("ALTER TABLE ble_tags ALTER COLUMN tag_type SET DEFAULT 'teltonika'")
    op.execute("ALTER TABLE device_positions DROP COLUMN IF EXISTS leg_id")
    op.execute("ALTER TABLE device_positions DROP COLUMN IF EXISTS stationary_id")

    # 4. Critical-alert categories that monitored removed services
    op.execute(
        "DELETE FROM critical_service_alert_subscriptions WHERE category::text IN "
        f"{RETIRED_ALERT_CATEGORIES}"
    )


def downgrade():
    raise RuntimeError("065_remove_legacy_integrations deleted data and cannot be reversed; restore from backup.")
