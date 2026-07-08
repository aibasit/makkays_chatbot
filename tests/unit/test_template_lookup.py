"""Unit tests for Module 13 template lookup and clarification flow."""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import Any

import pytest

from app.clarification.exceptions import MaxClarificationRoundsExceededError
from app.clarification.flow import (
    ClarificationFlow,
    missing_preserved_options,
    option_lines,
)
from app.clarification.template_lookup import TemplateLookup
from app.config import ClarificationSettings
from app.flags.schemas import FeatureFlags
from app.llm.schemas import LLMResponse
from app.prompts.exceptions import PromptNotFoundError
from app.session.schemas import ConversationStateSchema, FactsSchema
from app.shared.intent_context import IntentResult


TEMPLATES = {
    "sales_vs_support_vs_quote": (
        "What would you like help with?\n\n"
        "- Product recommendations or buying guidance\n"
        "- Technical support for an existing product\n"
        "- Pricing or a formal quote"
    ),
    "sales_vs_support": (
        "Choose one:\n\n"
        "- Product recommendations or buying guidance\n"
        "- Technical support for an existing product"
    ),
    "generic_fallback": "What do you need?\n\n- Product recommendations\n- Technical support",
    "llm_rewrite_instructions": "Rewrite without changing options.",
}


@dataclass
class DummySettings:
    clarification: ClarificationSettings


class FakePromptProvider:
    def __init__(self, templates: dict[str, str] | None = None) -> None:
        self.templates = templates or TEMPLATES
        self.calls: list[str] = []

    def get(self, category: str, name: str, version: str) -> str:
        self.calls.append(name)
        if name not in self.templates:
            raise PromptNotFoundError(f"missing {name}")
        return self.templates[name]


class FakeLLMClient:
    def __init__(self, content: str | None = None, error: Exception | None = None) -> None:
        self.content = content
        self.error = error
        self.calls = 0

    async def chat(self, *args: Any, **kwargs: Any) -> LLMResponse:
        self.calls += 1
        if self.error is not None:
            raise self.error
        return LLMResponse(content=self.content)


class FakeSessionStateService:
    def __init__(self, starting_rounds: int = 0) -> None:
        self.rounds = starting_rounds
        self.calls: list[dict[str, Any]] = []

    async def update_clarification_state(
        self,
        tenant_id: uuid.UUID,
        session_id: str,
        *,
        candidates: list[str] | None = None,
        last_question: str | None = None,
    ) -> ConversationStateSchema:
        self.rounds += 1
        self.calls.append({"candidates": candidates, "last_question": last_question})
        return ConversationStateSchema(
            tenant_id=tenant_id,
            session_id=session_id,
            awaiting_clarification=True,
            clarification_candidates=candidates or [],
            clarification_rounds=self.rounds,
            last_question=last_question,
        )


def _facts(tenant_id: uuid.UUID) -> FactsSchema:
    return FactsSchema(tenant_id=tenant_id, session_id="s1")


def _state(tenant_id: uuid.UUID, rounds: int = 0) -> ConversationStateSchema:
    return ConversationStateSchema(
        tenant_id=tenant_id,
        session_id="s1",
        clarification_rounds=rounds,
    )


def _intent(candidates: list[str]) -> IntentResult:
    return IntentResult(
        intent=candidates[0] if candidates else "out_of_scope",
        confidence=0.2,
        source="tier2",
        candidates=candidates,
    )


def _flow(service: FakeSessionStateService, max_rounds: int = 2) -> ClarificationFlow:
    settings = DummySettings(clarification=ClarificationSettings(max_rounds=max_rounds))
    return ClarificationFlow(
        service,
        settings,  # type: ignore[arg-type]
    )


def test_template_lookup_matches_known_candidate_set() -> None:
    lookup = TemplateLookup()

    assert (
        lookup.resolve(["sales_inquiry", "technical_support", "quote_request"])
        == "sales_vs_support_vs_quote"
    )


def test_template_lookup_matches_regardless_of_candidate_order() -> None:
    lookup = TemplateLookup()

    assert (
        lookup.resolve(["quote_request", "sales_inquiry", "technical_support"])
        == "sales_vs_support_vs_quote"
    )


def test_template_lookup_falls_back_to_generic() -> None:
    assert TemplateLookup().resolve(["out_of_scope"]) == "generic_fallback"


@pytest.mark.asyncio
async def test_clarification_flow_verbatim_when_rewrite_disabled() -> None:
    tenant_id = uuid.uuid4()
    service = FakeSessionStateService()

    result = await _flow(service).run(
        tenant_id,
        "s1",
        _intent(["sales_inquiry", "technical_support"]),
        _facts(tenant_id),
        _state(tenant_id),
        FeatureFlags(enable_llm_clarification_rewrite=False),
        FakePromptProvider(),
        FakeLLMClient("should not be used"),
    )

    assert result.source == "template"
    assert result.question_text == TEMPLATES["sales_vs_support"]
    assert result.clarification_rounds == 1
    assert service.calls[0]["candidates"] == ["sales_inquiry", "technical_support"]


@pytest.mark.asyncio
async def test_clarification_flow_uses_llm_rewrite_when_enabled() -> None:
    tenant_id = uuid.uuid4()
    rewritten = (
        "Could you choose between Product recommendations or buying guidance and "
        "Technical support for an existing product?"
    )
    llm = FakeLLMClient(rewritten)

    result = await _flow(FakeSessionStateService()).run(
        tenant_id,
        "s1",
        _intent(["sales_inquiry", "technical_support"]),
        _facts(tenant_id),
        _state(tenant_id),
        FeatureFlags(enable_llm_clarification_rewrite=True),
        FakePromptProvider(),
        llm,
    )

    assert result.source == "template+llm_rewrite"
    assert result.question_text == rewritten
    assert llm.calls == 1


@pytest.mark.asyncio
async def test_clarification_flow_falls_back_when_rewrite_fails_validation() -> None:
    tenant_id = uuid.uuid4()
    service = FakeSessionStateService()

    result = await _flow(service).run(
        tenant_id,
        "s1",
        _intent(["sales_inquiry", "technical_support"]),
        _facts(tenant_id),
        _state(tenant_id),
        FeatureFlags(enable_llm_clarification_rewrite=True),
        FakePromptProvider(),
        FakeLLMClient("Could you clarify?"),
    )

    assert result.source == "template"
    assert result.question_text == TEMPLATES["sales_vs_support"]


@pytest.mark.asyncio
async def test_clarification_flow_raises_max_rounds_exceeded_at_threshold() -> None:
    tenant_id = uuid.uuid4()

    with pytest.raises(MaxClarificationRoundsExceededError):
        await _flow(FakeSessionStateService(), max_rounds=2).run(
            tenant_id,
            "s1",
            _intent(["sales_inquiry"]),
            _facts(tenant_id),
            _state(tenant_id, rounds=2),
            FeatureFlags(),
            FakePromptProvider(),
        )


@pytest.mark.asyncio
async def test_template_prompt_not_found_falls_back_to_generic() -> None:
    tenant_id = uuid.uuid4()
    provider = FakePromptProvider({"generic_fallback": TEMPLATES["generic_fallback"]})

    result = await _flow(FakeSessionStateService()).run(
        tenant_id,
        "s1",
        _intent(["sales_inquiry", "technical_support"]),
        _facts(tenant_id),
        _state(tenant_id),
        FeatureFlags(),
        provider,
    )

    assert result.template_name == "sales_vs_support"
    assert result.question_text == TEMPLATES["generic_fallback"]
    assert provider.calls == ["sales_vs_support", "generic_fallback"]


def test_rewrite_validation_rejects_altered_option_set() -> None:
    missing = missing_preserved_options(TEMPLATES["sales_vs_support"], "Just tell me more.")

    assert missing == [
        "Product recommendations or buying guidance",
        "Technical support for an existing product",
    ]


def test_rewrite_validation_accepts_option_preserving_text() -> None:
    rewritten = (
        "Do you want Product recommendations or buying guidance, or "
        "Technical support for an existing product?"
    )

    assert missing_preserved_options(TEMPLATES["sales_vs_support"], rewritten) == []
    assert option_lines(TEMPLATES["sales_vs_support"]) == [
        "Product recommendations or buying guidance",
        "Technical support for an existing product",
    ]
