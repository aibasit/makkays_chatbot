"""Language detection and translation package."""

from __future__ import annotations

from app.language.detection_service import LanguageDetectionService
from app.language.translation_service import TranslationService

__all__ = ["LanguageDetectionService", "TranslationService"]
