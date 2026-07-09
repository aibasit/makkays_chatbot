"""Schemas and constants for multi-language support."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel

LanguageCode = Literal["en", "ur", "ar"]

SUPPORTED_LANGUAGES: frozenset[str] = frozenset({"en", "ur", "ar"})
LANGUAGE_NAMES: dict[LanguageCode, str] = {
    "en": "English",
    "ur": "Urdu",
    "ar": "Arabic (Modern Standard)",
}


class LanguagePreference(BaseModel):
    """Stored or detected language preference."""

    code: LanguageCode = "en"
    detected_this_turn: bool = False


class LanguageSetRequest(BaseModel):
    """Request payload for explicit language selection."""

    session_id: str
    language_code: LanguageCode


class LanguageSetResponse(BaseModel):
    """Response payload for explicit language selection."""

    language_code: LanguageCode
    status: str = "set"
