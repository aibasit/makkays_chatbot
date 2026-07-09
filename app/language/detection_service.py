"""Synchronous language detection for supported chat languages."""

from __future__ import annotations

import re
from typing import cast

from app.language.schemas import LanguageCode, SUPPORTED_LANGUAGES
from app.logging_config import get_logger

logger = get_logger(__name__)

_MIN_DETECTION_LENGTH = 10
_ARABIC_BLOCK_PATTERN = re.compile(r"[\u0600-\u06FF]")
_URDU_HINT_CHARS = set("ٹڈڑںےگکچیپژ")


class LanguageDetectionService:
    """Detect English, Urdu, or Arabic with graceful fallback."""

    SUPPORTED = SUPPORTED_LANGUAGES

    def detect(self, text: str, current_language: LanguageCode = "en") -> LanguageCode:
        """Return a supported language code, falling back to current language."""
        stripped = text.strip()
        if len(stripped) < _MIN_DETECTION_LENGTH:
            return current_language

        heuristic = _script_heuristic(stripped)
        if heuristic is not None:
            logger.debug("language_detected_heuristic", extra={"language_code": heuristic})
            return heuristic

        try:
            from langdetect import detect

            detected = detect(stripped)
        except Exception as exc:
            logger.debug("language_detection_failed", extra={"error": str(exc)})
            return current_language

        mapped = detected if detected in self.SUPPORTED else "en"
        logger.debug("language_detected", extra={"raw": detected, "language_code": mapped})
        return cast(LanguageCode, mapped)


def _script_heuristic(text: str) -> LanguageCode | None:
    """Classify obvious Urdu/Arabic script even when langdetect is unavailable."""
    chars = _ARABIC_BLOCK_PATTERN.findall(text)
    if not chars:
        return None
    if any(char in _URDU_HINT_CHARS for char in chars):
        return "ur"
    return "ar"
