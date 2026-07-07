"""Integration test: Module 06 Router must call PromptManager.get, not hardcode prompts."""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from typing import Any

import pytest

from app.config import INTENT_TAXONOMY
from app.llm.schemas import LLMResponse, ToolCall
from app.prompts.manager import prompt_manager
from app.router.classifier import Tier2Classifier
from app.session.schemas import ConversationStateSchema, FactsSchema


@dataclass
class CapturingLLMClient:
    captured_messages: list[Any] = field(default_factory=list)

    async def chat(
        self,
        messages: list[Any],
        tools: list[dict[str, Any]] | None = None,
        response_format: dict[str, Any] | None = None,
        temperature: float = 0.0,
    ) -> LLMResponse:
        self.captured_messages = messages
        return LLMResponse(
            content=None,
            tool_calls=[
                ToolCall(
                    id="1",
                    name="classify_intent",
                    arguments={"intent": "sales_inquiry", "confidence": 0.9},
                ),
            ],
        )


@pytest.mark.asyncio
async def test_prompt_manager_wired_into_router_produces_expected_system_message() -> None:
    tenant_id = uuid.uuid4()
    facts = FactsSchema(tenant_id=tenant_id, session_id="s1")
    state = ConversationStateSchema(tenant_id=tenant_id, session_id="s1")
    classifier = Tier2Classifier(INTENT_TAXONOMY)
    llm_client = CapturingLLMClient()

    await classifier.classify("hello", facts, state, [], prompt_manager, llm_client)

    expected_system_prompt = prompt_manager.get("classification", "classify_intent", "1")
    assert llm_client.captured_messages[0].role == "system"
    assert llm_client.captured_messages[0].content == expected_system_prompt
