#!/usr/bin/env python3
"""
Comprehensive translation keys for entire customer dashboard.
Adds ALL remaining translation keys needed to make the customer dashboard fully translatable.
Run: docker exec pinplot_backend python app/add_all_customer_dashboard_translation_keys.py
"""

import sys
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from app.config import settings
from app.models_i18n import TranslationKey, Translation, Language

# Translation keys: (key, en, fr, nl, it, zh)
KEYS_TO_ADD = [
    # === FLOOR PLAN TAB ===
    ("floor_plan.floor_plan_builder", "Floor Plan Builder", "Constructeur de plans d'étage", "Plattegrond bouwer", "Costruttore di planimetrie", "楼层平面图生成器"),
    ("floor_plan.undo", "Undo", "Annuler", "Ongedaan maken", "Annulla", "撤消"),
    ("floor_plan.redo", "Redo", "Rétablir", "Opnieuw", "Ripeti", "重做"),
    ("floor_plan.import_image", "Import floor plan image", "Importer l'image du plan d'étage", "Importeer plattegrondafbeelding", "Importa immagine planimetria", "导入楼层平面图"),
    ("floor_plan.save_browser", "Save to browser", "Enregistrer dans le navigateur", "Opslaan in browser", "Salva nel browser", "保存到浏览器"),
    ("floor_plan.export_json", "Export JSON", "Exporter JSON", "Exporteer JSON", "Esporta JSON", "导出JSON"),
    ("floor_plan.export_svg", "Export SVG", "Exporter SVG", "Exporteer SVG", "Esporta SVG", "导出SVG"),
    ("floor_plan.preview", "Preview", "Aperçu", "Voorbeeld", "Anteprima", "预览"),
    ("floor_plan.setup", "Setup", "Configuration", "Instelling", "Configurazione", "设置"),
    ("floor_plan.setup_building_floor", "Setup Building & Floor", "Configuration bâtiment et étage", "Gebouw en verdieping instellen", "Configura edificio e piano", "设置建筑物和楼层"),
    ("floor_plan.publish", "Publish", "Publier", "Publiceren", "Pubblica", "发布"),
    ("floor_plan.publish_to_database", "Publish Floor Plan to Database", "Publier le plan d'étage dans la base de données", "Plattegrond publiceren naar database", "Pubblica planimetria nel database", "发布楼层平面图到数据库"),
    ("floor_plan.select", "Select", "Sélectionner", "Selecteren", "Seleziona", "选择"),
    ("floor_plan.select_move", "Select / Move", "Sélectionner / Déplacer", "Selecteren / Verplaatsen", "Seleziona / Sposta", "选择/移动"),
    ("floor_plan.walls", "Walls", "Murs", "Muren", "Pareti", "墙壁"),
    ("floor_plan.concrete_wall", "Concrete Wall", "Mur en béton", "Betonnen muur", "Muro in cemento", "混凝土墙"),
    ("floor_plan.concrete", "Concrete", "Béton", "Beton", "Cemento", "混凝土"),
    ("floor_plan.drywall", "Drywall / Partition", "Cloison sèche", "Gipsplaat / Scheidingswand", "Cartongesso / Divisorio", "石膏板/隔断"),
    ("floor_plan.glass_wall", "Glass Wall / Curtain", "Mur de verre / Rideau", "Glazen wand / Gordijn", "Parete di vetro / Tenda", "玻璃墙/幕墙"),
    ("floor_plan.glass", "Glass", "Verre", "Glas", "Vetro", "玻璃"),
    ("floor_plan.exterior_wall", "Exterior Wall", "Mur extérieur", "Buitenmuur", "Muro esterno", "外墙"),
    ("floor_plan.exterior", "Exterior", "Extérieur", "Buiten", "Esterno", "外部"),
    ("floor_plan.openings", "Openings", "Ouvertures", "Openingen", "Aperture", "开口"),
    ("floor_plan.single_door", "Single Door", "Porte simple", "Enkele deur", "Porta singola", "单门"),
    ("floor_plan.door", "Door", "Porte", "Deur", "Porta", "门"),
    ("floor_plan.double_door", "Double Door", "Porte double", "Dubbele deur", "Porta doppia", "双门"),
    ("floor_plan.dbl_door", "Dbl Door", "Porte dbl", "Dubbele dr", "Porta dop", "双门"),
    ("floor_plan.window", "Window", "Fenêtre", "Raam", "Finestra", "窗户"),
    ("floor_plan.areas", "Areas", "Zones", "Gebieden", "Aree", "区域"),
    ("floor_plan.room_rectangle", "Room / Space (Rectangle)", "Pièce / Espace (Rectangle)", "Kamer / Ruimte (Rechthoek)", "Stanza / Spazio (Rettangolo)", "房间/空间（矩形）"),
    ("floor_plan.room", "Room", "Pièce", "Kamer", "Stanza", "房间"),
    ("floor_plan.polygon_room", "Polygon Room", "Pièce polygonale", "Polygoon kamer", "Stanza poligonale", "多边形房间"),
    ("floor_plan.polygon", "Polygon", "Polygone", "Polygoon", "Poligono", "多边形"),
    ("floor_plan.features", "Features", "Éléments", "Kenmerken", "Caratteristiche", "功能"),
    ("floor_plan.staircase", "Staircase", "Escalier", "Trap", "Scale", "楼梯"),
    ("floor_plan.stairs", "Stairs", "Escaliers", "Trappen", "Scale", "楼梯"),
    ("floor_plan.lift_elevator", "Lift / Elevator", "Ascenseur", "Lift", "Ascensore", "电梯"),
    ("floor_plan.lift", "Lift", "Ascenseur", "Lift", "Ascensore", "电梯"),
    ("floor_plan.structural_column", "Structural Column", "Colonne structurelle", "Structurele kolom", "Colonna strutturale", "结构柱"),
    ("floor_plan.column", "Column", "Colonne", "Kolom", "Colonna", "柱"),
    ("floor_plan.text_label", "Text Label", "Étiquette texte", "Tekstlabel", "Etichetta testo", "文本标签"),
    ("floor_plan.label", "Label", "Étiquette", "Label", "Etichetta", "标签"),
    ("floor_plan.ble_gateway", "BLE Gateway", "Passerelle BLE", "BLE-gateway", "Gateway BLE", "BLE网关"),
    ("floor_plan.gateway", "Gateway", "Passerelle", "Gateway", "Gateway", "网关"),
    ("floor_plan.trace", "Trace", "Tracer", "Traceren", "Traccia", "跟踪"),
    ("floor_plan.show_overlay", "Show overlay", "Afficher le calque", "Overlay tonen", "Mostra sovrapposizione", "显示叠加层"),
    ("floor_plan.opacity", "Opacity", "Opacité", "Dekking", "Opacità", "不透明度"),
    ("floor_plan.upload_image", "Upload Image", "Télécharger l'image", "Afbeelding uploaden", "Carica immagine", "上传图片"),
    ("floor_plan.fit_to_view", "Fit to view", "Ajuster à la vue", "Aanpassen aan weergave", "Adatta alla vista", "适应视图"),
    ("floor_plan.grid", "Grid", "Grille", "Raster", "Griglia", "网格"),
    ("floor_plan.snap", "Snap", "Accrochage", "Uitlijnen", "Aggancia", "吸附"),
    ("floor_plan.floor", "Floor", "Étage", "Verdieping", "Piano", "楼层"),
    ("floor_plan.add_floor", "Add floor", "Ajouter un étage", "Verdieping toevoegen", "Aggiungi piano", "添加楼层"),
    ("floor_plan.properties", "Properties", "Propriétés", "Eigenschappen", "Proprietà", "属性"),
    ("floor_plan.select_element_hint", "Select an element to edit properties", "Sélectionnez un élément pour modifier les propriétés", "Selecteer een element om eigenschappen te bewerken", "Seleziona un elemento per modificare le proprietà", "选择一个元素以编辑属性"),
    ("floor_plan.room_name", "Room name…", "Nom de la pièce…", "Kamernaam…", "Nome stanza…", "房间名称…"),
    ("floor_plan.mac_address_label", "MAC Address", "Adresse MAC", "MAC-adres", "Indirizzo MAC", "MAC地址"),
    ("floor_plan.mac_address", "MAC Address", "Adresse MAC", "MAC-adres", "Indirizzo MAC", "MAC地址"),
    ("floor_plan.esp32_gateway_hint", "ESP32S3 gateway MAC address", "Adresse MAC de la passerelle ESP32S3", "ESP32S3-gateway MAC-adres", "Indirizzo MAC gateway ESP32S3", "ESP32S3网关MAC地址"),
    ("floor_plan.gateway_status", "Gateway Status", "État de la passerelle", "Gateway-status", "Stato gateway", "网关状态"),
    ("floor_plan.not_registered", "Not registered", "Non enregistré", "Niet geregistreerd", "Non registrato", "未注册"),
    ("floor_plan.register_gateway", "Register Gateway", "Enregistrer la passerelle", "Gateway registreren", "Registra gateway", "注册网关"),
    ("floor_plan.font_size", "Font Size", "Taille de police", "Lettergrootte", "Dimensione carattere", "字体大小"),
    ("floor_plan.decrease_font", "Decrease font size", "Diminuer la taille de la police", "Lettergrootte verkleinen", "Riduci dimensione carattere", "减小字体大小"),
    ("floor_plan.increase_font", "Increase font size", "Augmenter la taille de la police", "Lettergrootte vergroten", "Aumenta dimensione carattere", "增大字体大小"),
    
    # === USER ACCOUNTS TAB ===
    ("users.user_accounts", "User Accounts", "Comptes utilisateurs", "Gebruikersaccounts", "Account utente", "用户账户"),
    ("users.search_users", "Search users…", "Rechercher des utilisateurs…", "Gebruikers zoeken…", "Cerca utenti…", "搜索用户…"),
    ("users.add_user", "Add User", "Ajouter un utilisateur", "Gebruiker toevoegen", "Aggiungi utente", "添加用户"),
    ("users.user_name", "User Name", "Nom d'utilisateur", "Gebruikersnaam", "Nome utente", "用户名"),
    ("users.email", "Email", "E-mail", "E-mail", "Email", "电子邮件"),
    ("users.role", "Role", "Rôle", "Rol", "Ruolo", "角色"),
    ("users.admin", "Admin", "Administrateur", "Beheerder", "Amministratore", "管理员"),
    ("users.viewer", "Viewer", "Visualisateur", "Kijker", "Visualizzatore", "查看者"),
    ("users.editor", "Editor", "Éditeur", "Bewerker", "Editor", "编辑者"),
    ("users.last_login", "Last Login", "Dernière connexion", "Laatste aanmelding", "Ultimo accesso", "最后登录"),
    ("users.created_date", "Created", "Créé", "Gemaakt", "Creato", "已创建"),
    ("users.edit_user", "Edit User", "Modifier l'utilisateur", "Gebruiker bewerken", "Modifica utente", "编辑用户"),
    ("users.delete_user", "Delete User", "Supprimer l'utilisateur", "Gebruiker verwijderen", "Elimina utente", "删除用户"),
    ("users.reset_password", "Reset Password", "Réinitialiser le mot de passe", "Wachtwoord resetten", "Reimposta password", "重置密码"),
    ("users.permissions", "Permissions", "Autorisations", "Machtigingen", "Permessi", "权限"),
    ("users.can_view_assets", "Can view assets", "Peut voir les actifs", "Kan activa bekijken", "Può visualizzare risorse", "可以查看资产"),
    ("users.can_edit_assets", "Can edit assets", "Peut modifier les actifs", "Kan activa bewerken", "Può modificare risorse", "可以编辑资产"),
    ("users.can_manage_users", "Can manage users", "Peut gérer les utilisateurs", "Kan gebruikers beheren", "Può gestire utenti", "可以管理用户"),
    ("users.can_view_reports", "Can view reports", "Peut voir les rapports", "Kan rapporten bekijken", "Può visualizzare report", "可以查看报告"),
    
    # === REPORTS TAB ===
    ("reports.tag_subscriptions", "Tag Subscriptions", "Abonnements aux tags", "Tag-abonnementen", "Abbonamenti tag", "标签订阅"),
    ("reports.asset_activity", "Asset Activity", "Activité des actifs", "Activiteit activa", "Attività risorse", "资产活动"),
    ("reports.journey_log", "Journey Log", "Journal de parcours", "Reislog", "Registro viaggi", "行程日志"),
    ("reports.geofence_events", "Geofence Events", "Événements de géorepérage", "Geofence-gebeurtenissen", "Eventi geofence", "地理围栏事件"),
    ("reports.battery_offline", "Battery & Offline", "Batterie et hors ligne", "Batterij & offline", "Batteria e offline", "电池和离线"),
    ("reports.export_report", "Export Report", "Exporter le rapport", "Rapport exporteren", "Esporta report", "导出报告"),
    ("reports.date_range", "Date Range", "Plage de dates", "Datumbereik", "Intervallo date", "日期范围"),
    ("reports.apply_filters", "Apply Filters", "Appliquer les filtres", "Filters toepassen", "Applica filtri", "应用过滤器"),
    ("reports.clear_filters", "Clear Filters", "Effacer les filtres", "Filters wissen", "Cancella filtri", "清除过滤器"),
    ("reports.showing_results", "Showing results", "Affichage des résultats", "Resultaten weergeven", "Mostra risultati", "显示结果"),
    ("reports.no_data", "No data for selected period", "Pas de données pour la période sélectionnée", "Geen gegevens voor geselecteerde periode", "Nessun dato per il periodo selezionato", "所选期间无数据"),
    ("reports.entry_event", "Entry", "Entrée", "Binnenkomst", "Ingresso", "进入"),
    ("reports.exit_event", "Exit", "Sortie", "Vertrek", "Uscita", "退出"),
    ("reports.duration", "Duration", "Durée", "Duur", "Durata", "持续时间"),
    ("reports.event_time", "Event Time", "Heure de l'événement", "Gebeurtenistijd", "Ora evento", "事件时间"),
    ("reports.location", "Location", "Emplacement", "Locatie", "Posizione", "位置"),
    
    # === SETTINGS MODAL ===
    ("settings.title", "Settings", "Paramètres", "Instellingen", "Impostazioni", "设置"),
    ("settings.general", "General", "Général", "Algemeen", "Generale", "常规"),
    ("settings.interface_language", "Interface Language", "Langue de l'interface", "Interface-taal", "Lingua interfaccia", "界面语言"),
    ("settings.theme", "Theme", "Thème", "Thema", "Tema", "主题"),
    ("settings.light", "Light", "Clair", "Licht", "Chiaro", "浅色"),
    ("settings.dark", "Dark", "Sombre", "Donker", "Scuro", "深色"),
    ("settings.auto", "Auto", "Automatique", "Automatisch", "Automatico", "自动"),
    ("settings.notifications", "Notifications", "Notifications", "Meldingen", "Notifiche", "通知"),
    ("settings.email_alerts", "Email alerts", "Alertes par e-mail", "E-mailwaarschuwingen", "Avvisi email", "电子邮件警报"),
    ("settings.browser_notifications", "Browser notifications", "Notifications du navigateur", "Browsermeldingen", "Notifiche browser", "浏览器通知"),
    ("settings.save_changes", "Save Changes", "Enregistrer les modifications", "Wijzigingen opslaan", "Salva modifiche", "保存更改"),
    ("settings.changes_saved", "Changes saved successfully", "Modifications enregistrées avec succès", "Wijzigingen succesvol opgeslagen", "Modifiche salvate con successo", "更改已成功保存"),
    
    # === COMMON/GENERAL (additional) ===
    ("common.refresh", "Refresh", "Actualiser", "Vernieuwen", "Aggiorna", "刷新"),
    ("common.loading", "Loading…", "Chargement…", "Laden…", "Caricamento…", "加载中…"),
    ("common.no_results", "No results found", "Aucun résultat trouvé", "Geen resultaten gevonden", "Nessun risultato trovato", "未找到结果"),
    ("common.search", "Search", "Rechercher", "Zoeken", "Cerca", "搜索"),
    ("common.filter", "Filter", "Filtrer", "Filteren", "Filtra", "筛选"),
    ("common.sort_by", "Sort by", "Trier par", "Sorteren op", "Ordina per", "排序方式"),
    ("common.actions", "Actions", "Actions", "Acties", "Azioni", "操作"),
    ("common.details", "Details", "Détails", "Details", "Dettagli", "详情"),
    ("common.confirm", "Confirm", "Confirmer", "Bevestigen", "Conferma", "确认"),
    ("common.confirm_delete", "Are you sure you want to delete this?", "Êtes-vous sûr de vouloir supprimer ceci ?", "Weet u zeker dat u dit wilt verwijderen?", "Sei sicuro di voler eliminare questo?", "您确定要删除这个吗？"),
    ("common.success", "Success", "Succès", "Succes", "Successo", "成功"),
    ("common.error", "Error", "Erreur", "Fout", "Errore", "错误"),
    ("common.warning", "Warning", "Avertissement", "Waarschuwing", "Avviso", "警告"),
    ("common.info", "Information", "Information", "Informatie", "Informazione", "信息"),
    ("common.meters", "meters", "mètres", "meters", "metri", "米"),
    ("common.kilometers", "kilometers", "kilomètres", "kilometers", "chilometri", "公里"),
    ("common.miles", "miles", "miles", "mijlen", "miglia", "英里"),
    ("common.minutes", "minutes", "minutes", "minuten", "minuti", "分钟"),
    ("common.hours", "hours", "heures", "uren", "ore", "小时"),
    ("common.days", "days", "jours", "dagen", "giorni", "天"),
    ("common.weeks", "weeks", "semaines", "weken", "settimane", "周"),
    ("common.months", "months", "mois", "maanden", "mesi", "月"),
    ("common.years", "years", "années", "jaren", "anni", "年"),
    ("common.today", "Today", "Aujourd'hui", "Vandaag", "Oggi", "今天"),
    ("common.yesterday", "Yesterday", "Hier", "Gisteren", "Ieri", "昨天"),
    ("common.this_week", "This week", "Cette semaine", "Deze week", "Questa settimana", "本周"),
    ("common.last_week", "Last week", "La semaine dernière", "Vorige week", "Settimana scorsa", "上周"),
    ("common.this_month", "This month", "Ce mois-ci", "Deze maand", "Questo mese", "本月"),
    ("common.last_month", "Last month", "Le mois dernier", "Vorige maand", "Mese scorso", "上个月"),
    ("common.custom", "Custom", "Personnalisé", "Aangepast", "Personalizzato", "自定义"),
    ("common.select_all", "Select all", "Tout sélectionner", "Alles selecteren", "Seleziona tutto", "全选"),
    ("common.deselect_all", "Deselect all", "Tout désélectionner", "Alles deselecteren", "Deseleziona tutto", "取消全选"),
    ("common.apply", "Apply", "Appliquer", "Toepassen", "Applica", "应用"),
    ("common.reset", "Reset", "Réinitialiser", "Resetten", "Reimposta", "重置"),
    ("common.previous", "Previous", "Précédent", "Vorige", "Precedente", "上一个"),
    ("common.next", "Next", "Suivant", "Volgende", "Successivo", "下一个"),
    ("common.page", "Page", "Page", "Pagina", "Pagina", "页"),
    ("common.of", "of", "de", "van", "di", "共"),
    ("common.showing", "Showing", "Affichage", "Weergave", "Mostra", "显示"),
    ("common.to", "to", "à", "tot", "a", "至"),
    ("common.results", "results", "résultats", "resultaten", "risultati", "结果"),
    ("common.per_page", "per page", "par page", "per pagina", "per pagina", "每页"),
]

def main():
    try:
        # Use direct connection with settings
        engine = create_engine(
            f"postgresql://{settings.DB_USER}:{settings.DB_PASSWORD}@{settings.DB_HOST}/{settings.DB_NAME}",
            echo=False
        )
        Session = sessionmaker(bind=engine)
        session = Session()
        
        # Get all languages
        languages = {lang.code: lang for lang in session.query(Language).all()}
        if not languages:
            print("ERROR: No languages found in database")
            return 1
        
        keys_added = 0
        translations_added = 0
        
        for key, en, fr, nl, it, zh in KEYS_TO_ADD:
            # Check if key already exists
            existing = session.query(TranslationKey).filter(TranslationKey.key == key).first()
            if existing:
                print(f"SKIP: {key} (already exists)")
                continue
            
            # Create translation key
            trans_key = TranslationKey(key=key, description=f"Customer Dashboard: {key}")
            session.add(trans_key)
            session.flush()  # Get the ID
            
            # Create translations for all languages
            lang_map = {"en": en, "fr": fr, "nl": nl, "it": it, "zh": zh}
            for lang_code, text in lang_map.items():
                if lang_code in languages:
                    trans = Translation(
                        translation_key_id=trans_key.id,
                        language_id=languages[lang_code].id,
                        text=text
                    )
                    session.add(trans)
                    translations_added += 1
            
            keys_added += 1
            print(f"ADD: {key}")
        
        session.commit()
        print(f"\n✓ Added {keys_added} new translation keys")
        print(f"✓ Added {translations_added} new translations")
        return 0
        
    except Exception as e:
        print(f"ERROR: {str(e)}")
        import traceback
        traceback.print_exc()
        return 1
    finally:
        if 'session' in locals():
            session.close()

if __name__ == "__main__":
    sys.exit(main())
