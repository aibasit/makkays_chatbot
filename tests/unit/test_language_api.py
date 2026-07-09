"""Unit tests for Module 21 chat language API helpers."""

from __future__ import annotations

from app.api.chat import parse_accept_language


def test_parse_accept_language_accepts_primary_supported_code() -> None:
    assert parse_accept_language("ur-PK, en;q=0.8") == "ur"
    assert parse_accept_language("ar-AE") == "ar"
    assert parse_accept_language("en-US") == "en"


def test_parse_accept_language_ignores_unsupported_or_missing_header() -> None:
    assert parse_accept_language("fr-FR") is None
    assert parse_accept_language(None) is None
