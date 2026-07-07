"""Unit tests for Module 06 Tier 2 LLM-based classification."""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from typing import Any

import pytest

from app.config import INTENT_TAXONOMY
from app.llm.schemas import LLMResponse, ToolCall
from app.router.classifier import Tier2Classifier
from app.session.schemas import ConversationStateSchema, FactsSchema


class FakePromptProvider:
    def get(self, category: str, name: str, version: str) -> str:
        return f"system prompt for {category}/{name}_v{version}"


@dataclass
class FakeLLMClient:
    response: LLMResponse | None = None
    error: Exception | None = None
    calls: int = field(default=0)

    async def chat(
        self,
        messages: list[Any],
        tools: list[dict[str, Any]] | None = None,
        response_format: dict[str, Any] | None = None,
        temperature: float = 0.0,
    ) -> LLMResponse:
        self.calls += 1
        if self.error is not None:
            raise self.error
        assert self.response is not None
        return self.response


def _facts_and_state() -> tuple[FactsSchema, ConversationStateSchema]:
    tenant_id = uuid.uuid4()
    facts = FactsSchema(tenant_id=tenant_id, session_id="s1")
    state = ConversationStateSchema(tenant_id=tenant_id, session_id="s1")
    return facts, state


@pytest.mark.asyncio
async def test_tier2_parses_valid_classify_intent_call() -> None:
    facts, state = _facts_and_state()
    classifier = Tier2Classifier(INTENT_TAXONOMY)
    llm_client = FakeLLMClient(
        response=LLMResponse(
            content=None,
            tool_calls=[
                ToolCall(
                    id="1",
                    name="classify_intent",
                    arguments={
                        "intent": "quote_request",
                        "confidence": 0.88,
                        "candidates": ["quote_request", "sales_inquiry"],
                    },
                ),
            ],
        ),
    )

    result = await classifier.classify(
        "how much for 10 units", facts, state, [], FakePromptProvider(), llm_client
    )

    assert result.intent == "quote_request"
    assert result.confidence == 0.88
    assert result.source == "tier2"
    assert result.candidates == ["quote_request", "sales_inquiry"]


@pytest.mark.asyncio
async def test_tier2_raises_on_llm_failure_treated_as_low_confidence() -> None:
    facts, state = _facts_and_state()
    classifier = Tier2Classifier(INTENT_TAXONOMY)
    llm_client = FakeLLMClient(error=ConnectionError("groq unavailable"))

    result = await classifier.classify("hello", facts, state, [], FakePromptProvider(), llm_client)

    assert result.confidence == 0.0
    assert result.source == "tier2"


@pytest.mark.asyncio
async def test_tier2_treats_missing_tool_call_as_low_confidence() -> None:
    facts, state = _facts_and_state()
    classifier = Tier2Classifier(INTENT_TAXONOMY)
    llm_client = FakeLLMClient(response=LLMResponse(content="just some text", tool_calls=[]))

    result = await classifier.classify("hello", facts, state, [], FakePromptProvider(), llm_client)

    assert result.confidence == 0.0


@pytest.mark.asyncio
async def test_tier2_clamps_out_of_range_confidence() -> None:
    facts, state = _facts_and_state()
    classifier = Tier2Classifier(INTENT_TAXONOMY)
    llm_client = FakeLLMClient(
        response=LLMResponse(
            content=None,
            tool_calls=[
                ToolCall(id="1", name="classify_intent", arguments={"intent": "sales_inquiry", "confidence": 1.4}),
            ],
        ),
    )

    result = await classifier.classify("hello", facts, state, [], FakePromptProvider(), llm_client)

    assert result.confidence == 1.0


@pytest.mark.asyncio
async def test_tier2_rejects_unrecognized_intent() -> None:
    facts, state = _facts_and_state()
    classifier = Tier2Classifier(INTENT_TAXONOMY)
    llm_client = FakeLLMClient(
        response=LLMResponse(
            content=None,
            tool_calls=[
                ToolCall(id="1", name="classify_intent", arguments={"intent": "not_a_real_intent", "confidence": 0.9}),
            ],
        ),
    )

    result = await classifier.classify("hello", facts, state, [], FakePromptProvider(), llm_client)

    assert result.confidence == 0.0
