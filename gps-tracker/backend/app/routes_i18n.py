"""
Public i18n API endpoints — language and translation retrieval.

Routes are mounted at /api (public access).
Used by the customer dashboard and admin portal to fetch translations.
"""
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from sqlalchemy import and_
from typing import Dict, List
from pydantic import BaseModel

from app.database import get_db
from app.models_i18n import Language, TranslationKey, Translation
from app.models import User, UserGroup
import logging

router = APIRouter(prefix="/api", tags=["i18n"])
logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Pydantic schemas
# ---------------------------------------------------------------------------

class LanguageOut(BaseModel):
    """Public language information"""
    code: str
    name: str
    
    class Config:
        from_attributes = True


# ---------------------------------------------------------------------------
# Public endpoints
# ---------------------------------------------------------------------------

@router.get("/languages", response_model=List[LanguageOut])
def list_languages(db: Session = Depends(get_db)):
    """
    List all active languages available in the system.
    Public endpoint - no authentication required.
    """
    languages = db.query(Language).filter(Language.is_active == True).all()
    return languages


@router.get("/translations/{lang_code}", response_model=Dict[str, str])
def get_translations(lang_code: str, db: Session = Depends(get_db)):
    """
    Get all translations for a specific language.
    Returns a flat dictionary: {key: translated_text}
    Falls back to default_text if translation doesn't exist.
    
    Example response:
    {
        "common.save": "Enregistrer",
        "common.cancel": "Annuler",
        "dashboard.welcome": "Bienvenue sur votre tableau de bord"
    }
    """
    # Verify language exists and is active
    language = db.query(Language).filter(
        and_(Language.code == lang_code, Language.is_active == True)
    ).first()
    
    if not language:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Language '{lang_code}' not found or inactive"
        )
    
    # Fetch all keys once and all translations for the requested language once
    # to avoid N+1 database round-trips when key volume grows.
    all_keys = db.query(TranslationKey).all()
    lang_translations = db.query(Translation).filter(
        Translation.language_code == lang_code
    ).all()

    translated_by_key = {t.key: t.translated_text for t in lang_translations}

    # Build result dictionary with fallback to default English text.
    result = {
        key.key: translated_by_key.get(key.key, key.default_text)
        for key in all_keys
    }
    
    logger.info(f"Fetched {len(result)} translations for language '{lang_code}'")
    return result


@router.get("/user-language/{user_id}")
def get_user_language(user_id: str, db: Session = Depends(get_db)) -> Dict[str, str]:
    """
    Determine the appropriate language for a user based on:
    1. User's preferred_language (if set)
    2. User's usergroup default_language
    3. System default 'en'
    
    Returns: {"language_code": "fr"}
    """
    from uuid import UUID
    try:
        user_uuid = UUID(user_id)
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid user ID format"
        )
    
    user = db.query(User).filter(User.id == user_uuid).first()
    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User not found"
        )
    
    # Priority 1: User preference
    if user.preferred_language:
        return {"language_code": user.preferred_language}
    
    # Priority 2: Usergroup default
    if user.usergroup_id:
        usergroup = db.query(UserGroup).filter(UserGroup.id == user.usergroup_id).first()
        if usergroup and usergroup.default_language:
            return {"language_code": usergroup.default_language}
    
    # Priority 3: System default
    return {"language_code": "en"}
