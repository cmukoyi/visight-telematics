"""
Admin i18n API endpoints — translation management.

Routes are mounted at /api/admin/i18n (requires admin authentication).
Used by Admin Portal to manage languages, translation keys, and translations.
"""
from fastapi import APIRouter, Depends, HTTPException, status, UploadFile, File
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session
from sqlalchemy import and_, or_, func
from typing import List, Optional, Dict
from pydantic import BaseModel, Field
from datetime import datetime
import csv
import io
import logging
import httpx

from app.database import get_db
from app.models_i18n import Language, TranslationKey, Translation
from app.admin_auth import get_current_admin_user
from app.models_admin import AdminUser

router = APIRouter(prefix="/api/admin/i18n", tags=["admin-i18n"])
logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Pydantic schemas
# ---------------------------------------------------------------------------

class LanguageIn(BaseModel):
    """Create/update language"""
    code: str = Field(..., min_length=2, max_length=5, description="Language code (e.g., 'en', 'fr')")
    name: str = Field(..., min_length=1, max_length=50, description="Language name (e.g., 'English', 'Français')")
    is_active: bool = True


class LanguageOut(BaseModel):
    """Language with statistics"""
    id: int
    code: str
    name: str
    is_active: bool
    created_at: datetime
    translation_count: Optional[int] = 0
    completion_percentage: Optional[float] = 0.0
    
    class Config:
        from_attributes = True


class TranslationKeyIn(BaseModel):
    """Create/update translation key"""
    key: str = Field(..., min_length=1, max_length=255, description="Namespaced key (e.g., 'dashboard.welcome')")
    category: Optional[str] = Field(None, max_length=50, description="Category for grouping")
    context: Optional[str] = Field(None, description="Help text for translators")
    default_text: str = Field(..., min_length=1, description="Default English text")


class TranslationKeyOut(BaseModel):
    """Translation key with all translations"""
    id: int
    key: str
    category: Optional[str]
    context: Optional[str]
    default_text: str
    created_at: datetime
    translations: Dict[str, str] = {}  # {language_code: translated_text}
    
    class Config:
        from_attributes = True


class TranslationIn(BaseModel):
    """Create/update a translation"""
    language_code: str = Field(..., min_length=2, max_length=5)
    translation_key: str = Field(..., min_length=1, max_length=255)
    translated_text: str = Field(..., min_length=1)


class TranslationOut(BaseModel):
    """Translation details"""
    id: int
    language_code: str
    translation_key: str
    translated_text: str
    last_updated: datetime
    
    class Config:
        from_attributes = True


class BulkTranslationUpdate(BaseModel):
    """Batch update multiple translations"""
    translations: List[TranslationIn]


# ---------------------------------------------------------------------------
# Language management
# ---------------------------------------------------------------------------

@router.get("/languages", response_model=List[LanguageOut])
def list_languages_admin(
    include_inactive: bool = False,
    db: Session = Depends(get_db),
    admin: AdminUser = Depends(get_current_admin_user)
):
    """
    List all languages with translation statistics.
    Admin only.
    """
    query = db.query(Language)
    if not include_inactive:
        query = query.filter(Language.is_active == True)
    
    languages = query.all()
    
    # Add statistics
    total_keys = db.query(func.count(TranslationKey.id)).scalar()
    
    result = []
    for lang in languages:
        translation_count = db.query(func.count(Translation.id)).filter(
            Translation.language_code == lang.code
        ).scalar()
        
        completion = (translation_count / total_keys * 100) if total_keys > 0 else 0.0
        
        lang_dict = {
            "id": lang.id,
            "code": lang.code,
            "name": lang.name,
            "is_active": lang.is_active,
            "created_at": lang.created_at,
            "translation_count": translation_count,
            "completion_percentage": round(completion, 1)
        }
        result.append(lang_dict)
    
    return result


@router.post("/languages", response_model=LanguageOut)
def create_language(
    language: LanguageIn,
    db: Session = Depends(get_db),
    admin: AdminUser = Depends(get_current_admin_user)
):
    """
    Add a new language to the system.
    Admin only.
    """
    # Check if language code already exists
    existing = db.query(Language).filter(Language.code == language.code).first()
    if existing:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Language with code '{language.code}' already exists"
        )
    
    new_lang = Language(
        code=language.code,
        name=language.name,
        is_active=language.is_active
    )
    
    db.add(new_lang)
    db.commit()
    db.refresh(new_lang)
    
    logger.info(f"Admin {admin.email} created language: {language.code} ({language.name})")
    
    return {
        "id": new_lang.id,
        "code": new_lang.code,
        "name": new_lang.name,
        "is_active": new_lang.is_active,
        "created_at": new_lang.created_at,
        "translation_count": 0,
        "completion_percentage": 0.0
    }


@router.put("/languages/{language_code}")
def update_language(
    language_code: str,
    language: LanguageIn,
    db: Session = Depends(get_db),
    admin: AdminUser = Depends(get_current_admin_user)
):
    """
    Update language details (name, active status).
    Admin only.
    """
    lang = db.query(Language).filter(Language.code == language_code).first()
    if not lang:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Language '{language_code}' not found"
        )
    
    lang.name = language.name
    lang.is_active = language.is_active
    
    db.commit()
    logger.info(f"Admin {admin.email} updated language: {language_code}")
    
    return {"message": "Language updated successfully"}


@router.delete("/languages/{language_code}")
def delete_language(
    language_code: str,
    db: Session = Depends(get_db),
    admin: AdminUser = Depends(get_current_admin_user)
):
    """
    Deactivate a language (soft delete).
    Admin only.
    """
    lang = db.query(Language).filter(Language.code == language_code).first()
    if not lang:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Language '{language_code}' not found"
        )
    
    if language_code == 'en':
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Cannot delete English (system default language)"
        )
    
    lang.is_active = False
    db.commit()
    
    logger.info(f"Admin {admin.email} deactivated language: {language_code}")
    return {"message": f"Language '{language_code}' deactivated"}


# ---------------------------------------------------------------------------
# Translation key management
# ---------------------------------------------------------------------------

@router.get("/translation-keys", response_model=List[TranslationKeyOut])
def list_translation_keys(
    category: Optional[str] = None,
    search: Optional[str] = None,
    language: Optional[str] = None,
    missing_only: bool = False,
    db: Session = Depends(get_db),
    admin: AdminUser = Depends(get_current_admin_user)
):
    """
    List all translation keys with their translations.
    
    Query params:
    - category: Filter by category
    - search: Search in key or default_text
    - language: Include translations for specific language
    - missing_only: Only show keys missing translations for specified language
    """
    query = db.query(TranslationKey)
    
    if category:
        query = query.filter(TranslationKey.category == category)
    
    if search:
        search_pattern = f"%{search}%"
        query = query.filter(
            or_(
                TranslationKey.key.ilike(search_pattern),
                TranslationKey.default_text.ilike(search_pattern)
            )
        )
    
    keys = query.order_by(TranslationKey.category, TranslationKey.key).all()
    
    # Build response with translations
    result = []
    for key in keys:
        translations_dict = {}
        
        # Get all translations for this key
        all_translations = db.query(Translation).filter(
            Translation.key == key.key
        ).all()
        
        for trans in all_translations:
            translations_dict[trans.language_code] = trans.translated_text
        
        # If filtering by language and missing_only, skip keys that have translations
        if missing_only and language and language in translations_dict:
            continue
        
        key_dict = {
            "id": key.id,
            "key": key.key,
            "category": key.category,
            "context": key.context,
            "default_text": key.default_text,
            "created_at": key.created_at,
            "translations": translations_dict
        }
        result.append(key_dict)
    
    return result


@router.post("/translation-keys", response_model=TranslationKeyOut)
def create_translation_key(
    key_data: TranslationKeyIn,
    db: Session = Depends(get_db),
    admin: AdminUser = Depends(get_current_admin_user)
):
    """
    Create a new translation key.
    Admin only.
    """
    # Check if key already exists
    existing = db.query(TranslationKey).filter(TranslationKey.key == key_data.key).first()
    if existing:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Translation key '{key_data.key}' already exists"
        )
    
    new_key = TranslationKey(
        key=key_data.key,
        category=key_data.category,
        context=key_data.context,
        default_text=key_data.default_text
    )
    
    db.add(new_key)
    db.commit()
    db.refresh(new_key)
    
    logger.info(f"Admin {admin.email} created translation key: {key_data.key}")
    
    return {
        "id": new_key.id,
        "key": new_key.key,
        "category": new_key.category,
        "context": new_key.context,
        "default_text": new_key.default_text,
        "created_at": new_key.created_at,
        "translations": {}
    }


@router.put("/translation-keys/{key_id}")
def update_translation_key(
    key_id: int,
    key_data: TranslationKeyIn,
    db: Session = Depends(get_db),
    admin: AdminUser = Depends(get_current_admin_user)
):
    """
    Update translation key metadata (category, context, default_text).
    Admin only.
    """
    key = db.query(TranslationKey).filter(TranslationKey.id == key_id).first()
    if not key:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Translation key not found"
        )
    
    key.category = key_data.category
    key.context = key_data.context
    key.default_text = key_data.default_text
    
    db.commit()
    logger.info(f"Admin {admin.email} updated translation key: {key.key}")
    
    return {"message": "Translation key updated successfully"}


@router.delete("/translation-keys/{key_id}")
def delete_translation_key(
    key_id: int,
    db: Session = Depends(get_db),
    admin: AdminUser = Depends(get_current_admin_user)
):
    """
    Delete a translation key and all its translations.
    Admin only. Use with caution!
    """
    key = db.query(TranslationKey).filter(TranslationKey.id == key_id).first()
    if not key:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Translation key not found"
        )
    
    key_name = key.key
    db.delete(key)
    db.commit()
    
    logger.warning(f"Admin {admin.email} deleted translation key: {key_name}")
    return {"message": f"Translation key '{key_name}' deleted"}


# ---------------------------------------------------------------------------
# Translation management
# ---------------------------------------------------------------------------

@router.post("/translations", response_model=TranslationOut)
def create_or_update_translation(
    translation: TranslationIn,
    db: Session = Depends(get_db),
    admin: AdminUser = Depends(get_current_admin_user)
):
    """
    Create or update a translation for a specific key and language.
    Admin only.
    """
    # Verify language exists
    language = db.query(Language).filter(Language.code == translation.language_code).first()
    if not language:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Language '{translation.language_code}' not found"
        )
    
    # Verify translation key exists
    key = db.query(TranslationKey).filter(TranslationKey.key == translation.translation_key).first()
    if not key:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Translation key '{translation.translation_key}' not found"
        )
    
    # Check if translation already exists
    existing = db.query(Translation).filter(
        and_(
            Translation.language_code == translation.language_code,
            Translation.key == translation.translation_key
        )
    ).first()
    
    if existing:
        # Update existing translation
        existing.translated_text = translation.translated_text
        existing.last_updated = datetime.utcnow()
        db.commit()
        db.refresh(existing)
        logger.info(f"Admin {admin.email} updated translation: {translation.translation_key} ({translation.language_code})")
        return existing
    else:
        # Create new translation
        new_translation = Translation(
            language_code=translation.language_code,
            key=translation.translation_key,
            translated_text=translation.translated_text
        )
        db.add(new_translation)
        db.commit()
        db.refresh(new_translation)
        logger.info(f"Admin {admin.email} created translation: {translation.translation_key} ({translation.language_code})")
        return new_translation


@router.post("/translations/bulk")
def bulk_update_translations(
    data: BulkTranslationUpdate,
    db: Session = Depends(get_db),
    admin: AdminUser = Depends(get_current_admin_user)
):
    """
    Bulk create/update translations.
    Admin only.
    """
    created = 0
    updated = 0
    errors = []
    
    for trans in data.translations:
        try:
            # Verify language and key exist
            language = db.query(Language).filter(Language.code == trans.language_code).first()
            key = db.query(TranslationKey).filter(TranslationKey.key == trans.translation_key).first()
            
            if not language or not key:
                errors.append(f"Invalid language or key: {trans.translation_key} ({trans.language_code})")
                continue
            
            # Check if exists
            existing = db.query(Translation).filter(
                and_(
                    Translation.language_code == trans.language_code,
                    Translation.key == trans.translation_key
                )
            ).first()
            
            if existing:
                existing.translated_text = trans.translated_text
                existing.last_updated = datetime.utcnow()
                updated += 1
            else:
                new_translation = Translation(
                    language_code=trans.language_code,
                    key=trans.translation_key,
                    translated_text=trans.translated_text
                )
                db.add(new_translation)
                created += 1
        
        except Exception as e:
            errors.append(f"Error processing {trans.translation_key}: {str(e)}")
    
    db.commit()
    
    logger.info(f"Admin {admin.email} bulk updated translations: {created} created, {updated} updated")
    
    return {
        "created": created,
        "updated": updated,
        "errors": errors
    }


@router.delete("/translations/{translation_id}")
def delete_translation(
    translation_id: int,
    db: Session = Depends(get_db),
    admin: AdminUser = Depends(get_current_admin_user)
):
    """
    Delete a translation (will fall back to default_text).
    Admin only.
    """
    translation = db.query(Translation).filter(Translation.id == translation_id).first()
    if not translation:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Translation not found"
        )
    
    key_name = translation.key
    lang = translation.language_code
    
    db.delete(translation)
    db.commit()
    
    logger.info(f"Admin {admin.email} deleted translation: {key_name} ({lang})")
    return {"message": "Translation deleted"}


@router.delete("/translations/{language_code}/{translation_key:path}")
def delete_translation_by_key(
    language_code: str,
    translation_key: str,
    db: Session = Depends(get_db),
    admin: AdminUser = Depends(get_current_admin_user)
):
    """
    Delete a translation by language code and key.
    Used for cleanup (e.g., removing failed auto-translations).
    Admin only.
    """
    translation = db.query(Translation).filter(
        and_(
            Translation.language_code == language_code,
            Translation.key == translation_key
        )
    ).first()
    
    if not translation:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Translation not found for {language_code}/{translation_key}"
        )
    
    db.delete(translation)
    db.commit()
    
    logger.info(f"Admin {admin.email} deleted translation by key: {translation_key} ({language_code})")
    return {"message": "Translation deleted"}


# ---------------------------------------------------------------------------
# Import/Export
# ---------------------------------------------------------------------------

@router.get("/export/{language_code}")
def export_translations(
    language_code: str,
    format: str = "csv",  # 'csv' or 'json'
    missing_only: bool = False,
    db: Session = Depends(get_db),
    admin: AdminUser = Depends(get_current_admin_user)
):
    """
    Export translations for a language as CSV or JSON.
    If missing_only=true, only exports keys without translations.
    Admin only.
    """
    # Verify language exists
    language = db.query(Language).filter(Language.code == language_code).first()
    if not language:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Language '{language_code}' not found"
        )
    
    # Get all keys
    all_keys = db.query(TranslationKey).order_by(TranslationKey.category, TranslationKey.key).all()
    
    # Build export data
    export_data = []
    for key in all_keys:
        translation = db.query(Translation).filter(
            and_(
                Translation.language_code == language_code,
                Translation.key == key.key
            )
        ).first()
        
        translated_text = translation.translated_text if translation else ""
        
        # If missing_only, skip keys that have translations
        if missing_only and translated_text:
            continue
        
        export_data.append({
            "key": key.key,
            "category": key.category or "",
            "context": key.context or "",
            "default_english": key.default_text,
            "translated_text": translated_text
        })
    
    if format == "csv":
        # Create CSV
        output = io.StringIO()
        writer = csv.DictWriter(output, fieldnames=["key", "category", "context", "default_english", "translated_text"])
        writer.writeheader()
        writer.writerows(export_data)
        
        csv_content = output.getvalue()
        output.close()
        
        filename = f"translations_{language_code}{'_missing' if missing_only else ''}.csv"
        
        return StreamingResponse(
            io.BytesIO(csv_content.encode('utf-8')),
            media_type="text/csv",
            headers={"Content-Disposition": f"attachment; filename={filename}"}
        )
    
    else:  # JSON
        import json
        json_data = json.dumps(export_data, indent=2, ensure_ascii=False)
        filename = f"translations_{language_code}{'_missing' if missing_only else ''}.json"
        
        return StreamingResponse(
            io.BytesIO(json_data.encode('utf-8')),
            media_type="application/json",
            headers={"Content-Disposition": f"attachment; filename={filename}"}
        )


@router.post("/import/{language_code}")
async def import_translations(
    language_code: str,
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    admin: AdminUser = Depends(get_current_admin_user)
):
    """
    Import translations from CSV file.
    Expected columns: key, translated_text
    Admin only.
    """
    # Verify language exists
    language = db.query(Language).filter(Language.code == language_code).first()
    if not language:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Language '{language_code}' not found"
        )
    
    # Read CSV
    content = await file.read()
    csv_text = content.decode('utf-8')
    reader = csv.DictReader(io.StringIO(csv_text))
    
    created = 0
    updated = 0
    skipped = 0
    errors = []
    
    for row in reader:
        try:
            key = row.get('key', '').strip()
            translated_text = row.get('translated_text', '').strip()
            
            if not key or not translated_text:
                skipped += 1
                continue
            
            # Verify key exists
            translation_key = db.query(TranslationKey).filter(TranslationKey.key == key).first()
            if not translation_key:
                errors.append(f"Key not found: {key}")
                continue
            
            # Check if translation exists
            existing = db.query(Translation).filter(
                and_(
                    Translation.language_code == language_code,
                    Translation.key == key
                )
            ).first()
            
            if existing:
                existing.translated_text = translated_text
                existing.last_updated = datetime.utcnow()
                updated += 1
            else:
                new_translation = Translation(
                    language_code=language_code,
                    key=key,
                    translated_text=translated_text
                )
                db.add(new_translation)
                created += 1
        
        except Exception as e:
            errors.append(f"Error processing row: {str(e)}")
    
    db.commit()
    
    logger.info(f"Admin {admin.email} imported translations for {language_code}: {created} created, {updated} updated")
    
    return {
        "created": created,
        "updated": updated,
        "skipped": skipped,
        "errors": errors
    }


# ---------------------------------------------------------------------------
# Auto-translate endpoint (LibreTranslate proxy)
# ---------------------------------------------------------------------------

class TranslateRequest(BaseModel):
    """Request to translate text"""
    text: str = Field(..., description="Text to translate")
    source_lang: str = Field(..., description="Source language code (e.g., 'en')")
    target_lang: str = Field(..., description="Target language code (e.g., 'fr')")


class TranslateResponse(BaseModel):
    """Translation result"""
    translated_text: str
    source: str = "libretranslate"


@router.post("/translate", response_model=TranslateResponse)
async def translate_text(
    request: TranslateRequest,
    admin: AdminUser = Depends(get_current_admin_user)
):
    """
    Proxy endpoint for LibreTranslate API.
    
    Translates text from source language to target language using LibreTranslate.
    This avoids CORS issues when calling from the browser.
    
    Admin authentication required.
    """
    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.post(
                'https://libretranslate.com/translate',
                json={
                    'q': request.text,
                    'source': request.source_lang,
                    'target': request.target_lang,
                    'format': 'text'
                },
                headers={'Content-Type': 'application/json'}
            )
            
            if response.status_code != 200:
                logger.error(f"LibreTranslate API error: {response.status_code} - {response.text}")
                raise HTTPException(
                    status_code=status.HTTP_502_BAD_GATEWAY,
                    detail=f"Translation service error: {response.status_code}"
                )
            
            data = response.json()
            translated = data.get('translatedText', '')
            
            if not translated:
                raise HTTPException(
                    status_code=status.HTTP_502_BAD_GATEWAY,
                    detail="Translation service returned empty result"
                )
            
            logger.info(f"Admin {admin.email} translated text: {request.source_lang} -> {request.target_lang}")
            
            return TranslateResponse(translated_text=translated)
    
    except httpx.HTTPError as e:
        logger.error(f"Translation API network error: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Translation service unavailable: {str(e)}"
        )
    except Exception as e:
        logger.error(f"Translation error: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Translation failed: {str(e)}"
        )
