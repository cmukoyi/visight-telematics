"""Seed English source keys for the Live Map temperature graph.

Revision ID: seed_temp_graph_translations
Revises: temperature_alert_preferences
Create Date: 2026-10-17
"""
from alembic import op
from sqlalchemy.sql import text


revision = "seed_temp_graph_translations"
down_revision = "temperature_alert_preferences"
branch_labels = None
depends_on = None


GRAPH_KEYS = (
    ("temp_graph.all_series5", "All Series 5"),
    ("temp_graph.altitude_dataset", "Altitude"),
    ("temp_graph.altitude_gap", "Altitude gap"),
    ("temp_graph.apply_thresholds", "Apply thresholds"),
    ("temp_graph.apply_to", "Apply to"),
    ("temp_graph.battery_dataset", "Battery"),
    ("temp_graph.battery_gap", "Battery gap"),
    ("temp_graph.battery_percent", "Battery %"),
    ("temp_graph.drag_hint", "Drag the window to pan, drag its edges to zoom"),
    ("temp_graph.export_pdf", "Export PDF"),
    ("temp_graph.high", "High"),
    ("temp_graph.high_threshold", "High threshold"),
    ("temp_graph.last_known_temperature", "Last Known Temperature"),
    ("temp_graph.load_failed", "Failed to load temperature data"),
    ("temp_graph.loading", "Loading temperature data..."),
    ("temp_graph.low", "Low"),
    ("temp_graph.low_threshold", "Low threshold"),
    ("temp_graph.no_reports_gap", "No reports"),
    ("temp_graph.no_temperature_data", "No temperature data available for this period"),
    ("temp_graph.save_thresholds_failed", "Could not save thresholds."),
    ("temp_graph.temperature_dataset", "Temperature"),
    ("temp_graph.temperature_gap", "Temperature gap"),
    ("temp_graph.temperature_over_time", "Temperature over time"),
    ("temp_graph.this_tag_only", "This tag only"),
    ("temp_graph.thresholds", "Temperature thresholds"),
    ("temp_graph.thresholds_updated", "{count} tag(s) updated."),
    ("temp_graph.unnamed_tag", "Tag"),
)


def upgrade():
    connection = op.get_bind()
    for key, default_text in GRAPH_KEYS:
        connection.execute(
            text("""
                INSERT INTO translation_keys (key, category, default_text, context)
                VALUES (:key, 'temp_graph', :default_text, 'Live Map temperature graph')
                ON CONFLICT (key) DO NOTHING
            """),
            {"key": key, "default_text": default_text},
        )

def downgrade():
    connection = op.get_bind()
    keys = [key for key, _default in GRAPH_KEYS]
    connection.execute(
        text("DELETE FROM translations WHERE key = ANY(:keys)"),
        {"keys": keys},
    )
    connection.execute(
        text("DELETE FROM translation_keys WHERE key = ANY(:keys)"),
        {"keys": keys},
    )