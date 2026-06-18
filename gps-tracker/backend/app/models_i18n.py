"""SQLAlchemy models for internationalization (i18n) system"""

from sqlalchemy import Column, String, Boolean, DateTime, ForeignKey, Integer, Text, UniqueConstraint
from sqlalchemy.sql import func
from sqlalchemy.orm import relationship
from app.database import Base


class Language(Base):
    """Available languages in the system"""
    __tablename__ = "languages"
    
    id = Column(Integer, primary_key=True, index=True)
    code = Column(String(5), unique=True, nullable=False, index=True)  # 'en', 'fr', 'es'
    name = Column(String(50), nullable=False)  # 'English', 'Français'
    is_active = Column(Boolean, default=True, nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    
    # Relationships
    translations = relationship("Translation", back_populates="language", cascade="all, delete-orphan")


class TranslationKey(Base):
    """Translation keys with namespaced identifiers"""
    __tablename__ = "translation_keys"
    
    id = Column(Integer, primary_key=True, index=True)
    key = Column(String(255), unique=True, nullable=False, index=True)  # 'dashboard.welcome'
    category = Column(String(50), nullable=True, index=True)  # 'dashboard', 'fleet', 'common'
    context = Column(Text, nullable=True)  # Help text for translators
    default_text = Column(Text, nullable=False)  # Fallback English text
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    
    # Relationships
    translations = relationship("Translation", back_populates="translation_key", cascade="all, delete-orphan")


class Translation(Base):
    """Actual translations for each key in each language"""
    __tablename__ = "translations"
    
    id = Column(Integer, primary_key=True, index=True)
    language_code = Column(String(5), ForeignKey('languages.code', ondelete='CASCADE'), nullable=False, index=True)
    translation_key = Column(String(255), ForeignKey('translation_keys.key', ondelete='CASCADE'), nullable=False, index=True)
    translated_text = Column(Text, nullable=False)
    last_updated = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
    
    # Composite unique constraint
    __table_args__ = (
        UniqueConstraint('language_code', 'translation_key', name='uq_language_key'),
    )
    
    # Relationships
    language = relationship("Language", back_populates="translations")
    translation_key = relationship("TranslationKey", back_populates="translations")
