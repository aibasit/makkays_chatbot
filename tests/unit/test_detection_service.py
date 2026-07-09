"""Unit tests for Module 21 language detection."""

from __future__ import annotations

from app.language.detection_service import LanguageDetectionService


def test_detect_returns_en_for_english_text() -> None:
    service = LanguageDetectionService()

    assert service.detect("I need a network switch for my office") == "en"


def test_detect_returns_ur_for_urdu_text() -> None:
    service = LanguageDetectionService()

    assert service.detect("مجھے نیٹ ورکنگ سوئچ چاہیے") == "ur"


def test_detect_returns_ar_for_arabic_text() -> None:
    service = LanguageDetectionService()

    assert service.detect("أحتاج إلى مفتاح شبكة للمكتب") == "ar"


def test_detect_falls_back_to_current_language_on_short_text() -> None:
    service = LanguageDetectionService()

    assert service.detect("hi", current_language="ur") == "ur"
