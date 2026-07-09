"""Unit tests for Module 21 response translation."""

from __future__ import annotations

from typing import Any

import pytest

from app.language.translation_service import TranslationService
from app.llm.schemas import LLMResponse


class FakePromptProvider:
    def get(self, category: str, name: str, version: str) -> str:
        assert category == "translation"
        return "Translate to {target_language_name}: {text}"


class FakeLLMClient:
    def __init__(self, *, fail: bool = False) -> None:
        self.fail = fail
        self.calls: list[Any] = []

    async def chat(self, messages: list[Any], **kwargs: Any) -> LLMResponse:
        self.calls.append((messages, kwargs))
        if self.fail:
            raise RuntimeError("translation unavailable")
        return LLMResponse(content="ترجمہ شدہ جواب")


@pytest.mark.asyncio
async def test_translate_skips_when_target_is_en() -> None:
    llm = FakeLLMClient()

    result = await TranslationService().translate("Hello", "en", llm, FakePromptProvider())

    assert result == "Hello"
    assert llm.calls == []


@pytest.mark.asyncio
async def test_translate_calls_llm_for_non_english_target() -> None:
    llm = FakeLLMClient()

    result = await TranslationService().translate("Hello", "ur", llm, FakePromptProvider())

    assert result == "ترجمہ شدہ جواب"
    assert len(llm.calls) == 1
    assert "Urdu" in llm.calls[0][0][0].content


@pytest.mark.asyncio
async def test_translate_falls_back_to_original_on_llm_failure() -> None:
    llm = FakeLLMClient(fail=True)

    result = await TranslationService().translate("Hello", "ar", llm, FakePromptProvider())

    assert result == "Hello"
