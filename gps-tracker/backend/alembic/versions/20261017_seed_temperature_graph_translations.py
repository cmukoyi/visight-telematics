"""Seed French translations for the Live Map temperature graph.

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


TRANSLATIONS = (
    ("temp_graph.all_series5", "All Series 5", "Tous les tags Series 5"),
    ("temp_graph.altitude_dataset", "Altitude", "Altitude"),
    ("temp_graph.altitude_gap", "Altitude gap", "Interruption d'altitude"),
    ("temp_graph.apply_thresholds", "Apply thresholds", "Appliquer les seuils"),
    ("temp_graph.apply_to", "Apply to", "Appliquer à"),
    ("temp_graph.battery_dataset", "Battery", "Batterie"),
    ("temp_graph.battery_gap", "Battery gap", "Interruption de batterie"),
    ("temp_graph.battery_percent", "Battery %", "Batterie (%)"),
    ("temp_graph.drag_hint", "Drag the window to pan, drag its edges to zoom", "Faites glisser la fenêtre pour la déplacer et ses bords pour zoomer"),
    ("temp_graph.export_pdf", "Export PDF", "Exporter en PDF"),
    ("temp_graph.high", "High", "Haut"),
    ("temp_graph.high_threshold", "High threshold", "Seuil haut"),
    ("temp_graph.last_known_temperature", "Last Known Temperature", "Dernière température connue"),
    ("temp_graph.load_failed", "Failed to load temperature data", "Impossible de charger les données de température"),
    ("temp_graph.loading", "Loading temperature data...", "Chargement des données de température…"),
    ("temp_graph.low", "Low", "Bas"),
    ("temp_graph.low_threshold", "Low threshold", "Seuil bas"),
    ("temp_graph.no_reports_gap", "No reports", "Aucun rapport"),
    ("temp_graph.no_temperature_data", "No temperature data available for this period", "Aucune donnée de température pour cette période"),
    ("temp_graph.save_thresholds_failed", "Could not save thresholds.", "Impossible d’enregistrer les seuils."),
    ("temp_graph.temperature_dataset", "Temperature", "Température"),
    ("temp_graph.temperature_gap", "Temperature gap", "Interruption de température"),
    ("temp_graph.temperature_over_time", "Temperature over time", "Température au fil du temps"),
    ("temp_graph.this_tag_only", "This tag only", "Ce tag uniquement"),
    ("temp_graph.thresholds", "Temperature thresholds", "Seuils de température"),
    ("temp_graph.thresholds_updated", "{count} tag(s) updated.", "{count} tag(s) mis à jour."),
    ("temp_graph.unnamed_tag", "Tag", "Balise"),
)


def upgrade():
    connection = op.get_bind()
    for key, default_text, _french in TRANSLATIONS:
        connection.execute(
            text("""
                INSERT INTO translation_keys (key, category, default_text, context)
                VALUES (:key, 'temp_graph', :default_text, 'Live Map temperature graph')
                ON CONFLICT (key) DO NOTHING
            """),
            {"key": key, "default_text": default_text},
        )

    translation_params = {}
    for index, (key, _default_text, french_text) in enumerate(TRANSLATIONS):
        translation_params[f"key_{index}"] = key
        translation_params[f"text_{index}"] = french_text

    connection.execute(
        text("""
            INSERT INTO translations (language_code, key, translated_text)
            SELECT 'fr', seed.key, seed.translated_text
            FROM (VALUES
                """ + ",\n".join(
                    "(:key_%d, :text_%d)" % (index, index)
                    for index in range(len(TRANSLATIONS))
                ) + """
            ) AS seed(key, translated_text)
            WHERE EXISTS (SELECT 1 FROM languages WHERE code = 'fr')
            ON CONFLICT (language_code, key) DO UPDATE
            SET translated_text = EXCLUDED.translated_text
        """),
        translation_params,
    )


def downgrade():
    connection = op.get_bind()
    keys = [key for key, _default, _french in TRANSLATIONS]
    connection.execute(
        text("DELETE FROM translations WHERE language_code = 'fr' AND key = ANY(:keys)"),
        {"keys": keys},
    )
    connection.execute(
        text("DELETE FROM translation_keys WHERE key = ANY(:keys)"),
        {"keys": keys},
    )