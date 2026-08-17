"""
Add missing translation keys for Movement Analytics i18n support.

This script adds translation keys that are referenced in the customer dashboard
but don't yet exist in the database.
"""
import sys
from sqlalchemy.orm import Session
from database import SessionLocal
from models_i18n import TranslationKey, Translation, Language
from datetime import datetime

# Translation keys to add (key, default_english_text, french, dutch, italian, chinese)
KEYS_TO_ADD = [
    ("assets.title", "Assets", "Actifs", "Activa", "Beni", "资产"),
    ("general.last_reported", "last reported", "dernière mise à jour", "laatst gemeld", "ultimo rapporto", "最后报告"),
    ("general.show_assets", "SHOW ASSETS", "AFFICHER LES ACTIFS", "TOON ACTIVA", "MOSTRA BENI", "显示资产"),
    ("general.show_journeys", "SHOW JOURNEYS", "AFFICHER LES TRAJETS", "TOON REIZEN", "MOSTRA VIAGGI", "显示旅程"),
    ("general.journey_map", "Journey Map", "Carte des trajets", "Reiskaart", "Mappa dei viaggi", "旅程地图"),
    ("general.how_to", "How To", "Comment faire", "Hoe te", "Come fare", "如何"),
    ("general.open_user_manual", "Open the Movement Analytics user manual in a new tab", "Ouvrir le manuel d'utilisation de l'analyse des mouvements dans un nouvel onglet", "Open de gebruikershandleiding voor bewegingsanalyse in een nieuw tabblad", "Aprire il manuale utente di Movement Analytics in una nuova scheda", "在新标签页中打开移动分析用户手册"),
    ("map.reset_view", "Reset view", "Réinitialiser la vue", "Weergave resetten", "Reimposta vista", "重置视图"),
    ("geofence.show_geofences", "Show geofences", "Afficher les géorepérages", "Toon geofences", "Mostra recinti geografici", "显示地理围栏"),
    ("map.clear_markers", "Clear markers", "Effacer les marqueurs", "Markers wissen", "Cancella marcatori", "清除标记"),
    ("general.leg", "Leg", "Étape", "Etappe", "Tappa", "段"),
    ("general.position", "Position", "Position", "Positie", "Posizione", "位置"),
    ("general.stationary", "Stationary", "Stationnaire", "Stilstand", "Stazionario", "静止"),
    ("general.positions", "Positions", "Positions", "Posities", "Posizioni", "位置"),
    ("general.select_asset_positions", "Select an asset to view positions", "Sélectionnez un actif pour afficher les positions", "Selecteer een actief om posities te bekijken", "Seleziona un bene per visualizzare le posizioni", "选择资产以查看位置"),
    ("general.show_assets_panel", "Show Assets Panel", "Afficher le panneau des actifs", "Toon activapaneel", "Mostra pannello beni", "显示资产面板"),
    ("general.show_journeys_panel", "Show Journeys Panel", "Afficher le panneau des trajets", "Toon reizenpaneel", "Mostra pannello viaggi", "显示旅程面板"),
    ("general.collapse_panel", "Collapse panel", "Réduire le panneau", "Paneel inklappen", "Riduci pannello", "折叠面板"),
]

def add_translation_keys():
    """Add missing translation keys to the database."""
    db: Session = SessionLocal()
    
    try:
        # Get all active languages
        languages = db.query(Language).filter(Language.is_active == True).all()
        lang_codes = {lang.code for lang.code in ['en', 'fr', 'nl', 'it', 'zh']}
        
        added_keys = 0
        added_translations = 0
        
        for key_data in KEYS_TO_ADD:
            key = key_data[0]
            default_text = key_data[1]
            
            # Check if key already exists
            existing_key = db.query(TranslationKey).filter(TranslationKey.key == key).first()
            
            if not existing_key:
                # Create translation key
                translation_key = TranslationKey(
                    key=key,
                    default_text=default_text,
                    last_updated=datetime.utcnow()
                )
                db.add(translation_key)
                db.flush()  # Get the ID
                added_keys += 1
                print(f"✅ Added key: {key}")
                
                # Add translations for each language
                translations_map = {
                    'en': key_data[1],
                    'fr': key_data[2] if len(key_data) > 2 else default_text,
                    'nl': key_data[3] if len(key_data) > 3 else default_text,
                    'it': key_data[4] if len(key_data) > 4 else default_text,
                    'zh': key_data[5] if len(key_data) > 5 else default_text,
                }
                
                for lang_code, translated_text in translations_map.items():
                    if lang_code in lang_codes:
                        translation = Translation(
                            language_code=lang_code,
                            key=key,
                            translated_text=translated_text,
                            last_updated=datetime.utcnow()
                        )
                        db.add(translation)
                        added_translations += 1
            else:
                print(f"ℹ️  Key already exists: {key}")
        
        # Commit all changes
        db.commit()
        
        print(f"\n✅ Done!")
        print(f"   Added {added_keys} new translation keys")
        print(f"   Added {added_translations} new translations")
        
    except Exception as e:
        print(f"❌ Error: {e}")
        db.rollback()
        sys.exit(1)
    finally:
        db.close()

if __name__ == "__main__":
    add_translation_keys()
