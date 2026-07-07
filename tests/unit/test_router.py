"""Unit tests for Module 06 Router (Tier 1 -> Tier 2 fallback)."""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from typing import Any

import pytest

from app.config import INTENT_TAXONOMY
from app.llm.schemas import LLMResponse, ToolCall
from app.router.router import Router
from app.session.schemas import ConversationStateSchema, FactsSchema


class FakePromptProvider:
    def get(self, category: str, name: str, version: str) -> str:
        return "system prompt"


@dataclass
class FakeLLMClient:
    response: LLMResponse | None = None
    calls: int = field(default=0)

    async def chat(
        self,
        messages: list[Any],
        tools: list[dict[str, Any]] | None = None,
        response_format: dict[str, Any] | None = None,
        temperature: float = 0.0,
    ) -> LLMResponse:
        self.calls += 1
        if self.response is None:
            raise AssertionError("Tier 2 should not have been called")
        return self.response


def _facts_and_state() -> tuple[FactsSchema, ConversationStateSchema]:
    tenant_id = uuid.uuid4()
    return (
        FactsSchema(tenant_id=tenant_id, session_id="s1"),
        ConversationStateSchema(tenant_id=tenant_id, session_id="s1"),
    )


@pytest.mark.asyncio
async def test_router_prefers_tier1_when_confident() -> None:
    facts, state = _facts_and_state()
    router = Router(INTENT_TAXONOMY)
    llm_client = FakeLLMClient()  # raises if Tier 2 is ever called

    result = await router.classify(
        "I'd like a quote for this switch", facts, state, [], FakePromptProvider(), llm_client
    )

    assert result.intent == "quote_request"
    assert result.source == "tier1"
    assert llm_client.calls == 0


@pytest.mark.asyncio
async def test_router_falls_back_to_tier2_when_tier1_uncertain() -> None:
    facts, state = _facts_and_state()
    router = Router(INTENT_TAXONOMY)
    llm_client = FakeLLMClient(
        response=LLMResponse(
            content=None,
            tool_calls=[
                ToolCall(
                    id="1",
                    name="classify_intent",
                    arguments={"intent": "quote_request", "confidence": 0.88, "candidates": []},
                ),
            ],
        ),
    )

    result = await router.classify(
        "How much is this broken switch going to cost to fix?",
        facts,
        state,
        [],
        FakePromptProvider(),
        llm_client,
    )

    assert result.intent == "quote_request"
    assert result.source == "tier2"
    assert llm_client.calls == 1


@pytest.mark.asyncio
async def test_router_carries_spec_question_detected_through_tier1() -> None:
    facts, state = _facts_and_state()
    router = Router(INTENT_TAXONOMY)
    llm_client = FakeLLMClient()

    result = await router.classify(
        "What is the price of this switch? I'd like a quote.",
        facts,
        state,
        [],
        FakePromptProvider(),
        llm_client,
    )

    assert result.source == "tier1"
    assert result.spec_question_detected is True
