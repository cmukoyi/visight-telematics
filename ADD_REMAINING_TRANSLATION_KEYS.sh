#!/bin/bash
# Add all remaining translation keys for 100% customer dashboard coverage
# Run on production: ssh root@159.89.50.65 "bash -s" < ADD_REMAINING_TRANSLATION_KEYS.sh

cat > /tmp/add_remaining_keys.py << 'SCRIPT_EOF'
"""Add ALL remaining translation keys for 100% customer dashboard coverage"""
import sys
sys.path.insert(0, '/app')
from app.database import SessionLocal
from app.models_i18n import TranslationKey, Translation

# Additional missing keys found in HTML
REMAINING_KEYS = [
    # Floor Plan dropzone & modals
    ("floor_plan.drop_image_hint", "Drop floor plan image to use as tracing overlay", "Déposez l'image du plan d'étage pour l'utiliser comme superposition", "Laat plattegrondafbeelding los om te gebruiken als overlay", "Rilascia l'immagine della planimetria da utilizzare come sovrapposizione", "拖放楼层平面图作为覆盖层"),
    ("floor_plan.supported_formats", "PNG, JPG, PDF, SVG supported", "PNG, JPG, PDF, SVG pris en charge", "PNG, JPG, PDF, SVG ondersteund", "PNG, JPG, PDF, SVG supportati", "支持PNG、JPG、PDF、SVG格式"),
    ("floor_plan.link_floor_plan", "Link Floor Plan", "Lier le plan d'étage", "Plattegrond koppelen", "Collega planimetria", "关联楼层平面图"),
    ("floor_plan.link_to_database", "Link this floor plan to a building and floor in your database.", "Liez ce plan d'étage à un bâtiment et un étage dans votre base de données.", "Koppel deze plattegrond aan een gebouw en verdieping in uw database.", "Collega questa planimetria a un edificio e un piano nel database.", "将此楼层平面图链接到数据库中的建筑物和楼层。"),
    ("floor_plan.building", "Building", "Bâtiment", "Gebouw", "Edificio", "建筑物"),
    ("floor_plan.floor", "Floor", "Étage", "Verdieping", "Piano", "楼层"),
    ("floor_plan.select_or_create", "Select or create new...", "Sélectionner ou créer nouveau...", "Selecteer of maak nieuw aan...", "Seleziona o crea nuovo...", "选择或创建新的..."),
    ("floor_plan.building_name", "Building name", "Nom du bâtiment", "Gebouwnaam", "Nome edificio", "建筑名称"),
    ("floor_plan.address_optional", "Address (optional)", "Adresse (facultatif)", "Adres (optioneel)", "Indirizzo (facoltativo)", "地址（可选）"),
    ("floor_plan.floor_name", "Floor name (e.g., Ground Floor)", "Nom de l'étage (par ex., Rez-de-chaussée)", "Verdiepingsnaam (bijv. Begane grond)", "Nome piano (es. Piano terra)", "楼层名称（例如：一层）"),
    ("floor_plan.floor_number", "Floor number (0 = ground, 1 = first, -1 = basement)", "Numéro d'étage (0 = rez-de-chaussée, 1 = premier, -1 = sous-sol)", "Verdiepingsnummer (0 = begane grond, 1 = eerste, -1 = kelder)", "Numero piano (0 = terra, 1 = primo, -1 = seminterrato)", "楼层编号（0=地面层，1=一楼，-1=地下室）"),
    ("floor_plan.upload_instructions", "Upload a PNG or JPEG image of the floor plan. It will be stored in the browser for this building.", "Téléchargez une image PNG ou JPEG du plan d'étage. Elle sera stockée dans le navigateur pour ce bâtiment.", "Upload een PNG- of JPEG-afbeelding van de plattegrond. Deze wordt opgeslagen in de browser voor dit gebouw.", "Carica un'immagine PNG o JPEG della planimetria. Verrà memorizzata nel browser per questo edificio.", "上传楼层平面图的PNG或JPEG图像。它将存储在此建筑物的浏览器中。"),
    
    # Floor Plan status labels
    ("floor_plan.total", "Total", "Total", "Totaal", "Totale", "总计"),
    ("floor_plan.active_dispatch", "Active / Dispatch", "Actif / Expédition", "Actief / Verzending", "Attivo / Spedizione", "活跃/调度"),
    ("floor_plan.loading_assets", "Loading assets…", "Chargement des actifs…", "Activa laden…", "Caricamento beni…", "加载资产..."),
    
    # Asset Management dropzone
    ("asset_mgmt.drop_file_hint", "Drop your file here, or click to browse", "Déposez votre fichier ici ou cliquez pour parcourir", "Laat uw bestand hier vallen of klik om te bladeren", "Rilascia il file qui o fai clic per sfogliare", "将文件拖到此处，或单击浏览"),
    ("asset_mgmt.csv_xlsx_only", "CSV or XLSX only", "CSV ou XLSX uniquement", "Alleen CSV of XLSX", "Solo CSV o XLSX", "仅CSV或XLSX"),
    ("asset_mgmt.download_template", "Download the Excel template with correct column headers and example rows.", "Téléchargez le modèle Excel avec les en-têtes de colonnes corrects et des exemples de lignes.", "Download de Excel-sjabloon met correcte kolomkoppen en voorbeeldrijen.", "Scarica il modello Excel con le intestazioni di colonna corrette e le righe di esempio.", "下载包含正确列标题和示例行的Excel模板。"),
    ("asset_mgmt.uploading", "Uploading…", "Téléchargement…", "Uploaden…", "Caricamento…", "上传中..."),
    ("asset_mgmt.processed", "Processed", "Traité", "Verwerkt", "Elaborato", "已处理"),
    ("asset_mgmt.errors", "Errors", "Erreurs", "Fouten", "Errori", "错误"),
    
    # Common loading states
    ("common.loading_users", "Loading users…", "Chargement des utilisateurs…", "Gebruikers laden…", "Caricamento utenti…", "加载用户..."),
    ("common.loading_packages", "Loading packages…", "Chargement des forfaits…", "Pakketten laden…", "Caricamento pacchetti…", "加载套餐..."),
    ("common.loading_tags", "Loading tags…", "Chargement des étiquettes…", "Tags laden…", "Caricamento tag…", "加载标签..."),
    ("common.select_tag_and_date", "Select a tag and date range, then click Load Journeys.", "Sélectionnez une étiquette et une plage de dates, puis cliquez sur Charger les trajets.", "Selecteer een tag en datumbereik, klik dan op Reizen laden.", "Seleziona un tag e un intervallo di date, quindi fai clic su Carica viaggi.", "选择标签和日期范围，然后单击加载旅程。"),
    
    # Status badges (for JS usage)
    ("status.active", "Active", "Actif", "Actief", "Attivo", "活跃"),
    ("status.inactive", "Inactive", "Inactif", "Inactief", "Inattivo", "未激活"),
    
    # Report column headers
    ("reports.battery", "Battery", "Batterie", "Batterij", "Batteria", "电池"),
    ("reports.battery_low_only", "Battery ≤", "Batterie ≤", "Batterij ≤", "Batteria ≤", "电池≤"),
    ("reports.journey_path", "Journey Path", "Chemin du trajet", "Reispad", "Percorso viaggio", "旅程路径"),
    ("reports.total_distance", "Total Distance", "Distance totale", "Totale afstand", "Distanza totale", "总距离"),
    
    # QR/NFC specific
    ("qr.total_scans", "Total scans", "Total des scans", "Totaal scans", "Scansioni totali", "总扫描次数"),
    
    # Hive specific
    ("hive.total_alerts", "Total Alerts", "Total des alertes", "Totaal waarschuwingen", "Avvisi totali", "总警报"),
    
    # Report tabs with longer descriptions
    ("reports.activity_report", "Activity Report", "Rapport d'activité", "Activiteitenrapport", "Report attività", "活动报告"),
    ("reports.trips_report", "Trips Report", "Rapport des trajets", "Reizenrapport", "Report viaggi", "旅程报告"),
    ("reports.geofence_report", "Geofence Report", "Rapport de géorepérage", "Geofence-rapport", "Report recinti geografici", "地理围栏报告"),
    ("reports.battery_report", "Battery Report", "Rapport de batterie", "Batterijenrapport", "Report batteria", "电池报告"),
    ("reports.alerts_report", "Alerts Report", "Rapport d'alertes", "Waarschuwingenrapport", "Report avvisi", "警报报告"),
    
    # User Accounts
    ("users.loading", "Loading...", "Chargement...", "Laden...", "Caricamento...", "加载中..."),
    
    # Settings - additional missing keys
    ("settings.interface_language", "Interface language", "Langue de l'interface", "Interfacetaal", "Lingua interfaccia", "界面语言"),
    ("settings.uploading", "Uploading...", "Téléchargement...", "Uploaden...", "Caricamento...", "上传中..."),
    ("settings.remove_logo", "Remove", "Supprimer", "Verwijderen", "Rimuovi", "删除"),
]

def main():
    db = SessionLocal()
    try:
        added_keys = 0
        added_translations = 0
        skipped = 0
        
        for key, en, fr, nl, it, zh in REMAINING_KEYS:
            existing = db.query(TranslationKey).filter(TranslationKey.key == key).first()
            if existing:
                skipped += 1
                continue
            
            category = key.split('.')[0]
            tk = TranslationKey(key=key, category=category, default_text=en)
            db.add(tk)
            db.flush()
            added_keys += 1
            
            for lang_code, text in [('en', en), ('fr', fr), ('nl', nl), ('it', it), ('zh', zh)]:
                if text:
                    db.add(Translation(language_code=lang_code, key=key, translated_text=text))
                    added_translations += 1
        
        db.commit()
        print(f"✅ Added {added_keys} remaining keys, {added_translations} translations")
        print(f"⏭️  Skipped {skipped} existing keys")
        print(f"\n🎉 ALL translation keys for 100% coverage now in database!")
    except Exception as e:
        db.rollback()
        print(f"❌ Error: {e}")
        import traceback
        traceback.print_exc()
        raise
    finally:
        db.close()

if __name__ == "__main__":
    main()
SCRIPT_EOF

docker cp /tmp/add_remaining_keys.py pinplot_backend:/tmp/
docker exec pinplot_backend python /tmp/add_remaining_keys.py
