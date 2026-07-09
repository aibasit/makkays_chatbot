"""Unit tests for Module 06 FactsExtractor (Module 00 section 6 contract)."""

from __future__ import annotations

import uuid
from decimal import Decimal
from typing import Any

import pytest

from app.router.facts_extractor import FactsExtractor
from app.session.schemas import ConversationStateSchema, FactsSchema


class FakePromptProvider:
    def get(self, category: str, name: str, version: str) -> str:
        return "system prompt"


class UnusedLLMClient:
    """Raises if ever called, for tests where no LLM fallback should run."""

    async def chat(self, *args: Any, **kwargs: Any) -> Any:
        raise AssertionError("LLM should not have been called")


class FakeLLMClient:
    def __init__(self, content: str) -> None:
        self.content = content

    async def chat(self, *args: Any, **kwargs: Any) -> Any:
        from app.llm.schemas import LLMResponse

        return LLMResponse(content=self.content, tool_calls=[])


def _facts(**overrides: Any) -> FactsSchema:
    return FactsSchema(tenant_id=uuid.uuid4(), session_id="s1", **overrides)


def _state() -> ConversationStateSchema:
    return ConversationStateSchema(tenant_id=uuid.uuid4(), session_id="s1")


@pytest.mark.asyncio
async def test_extract_deterministic_email_quantity_and_budget() -> None:
    facts = _facts(
        company="Acme", industry="IT", product_interest="switches", project_size="10 users"
    )
    extractor = FactsExtractor()

    patch = await extractor.extract(
        "My email is jane@example.com, we need 10 units, budget of $5000",
        facts,
        _state(),
        [],
        FakePromptProvider(),
        UnusedLLMClient(),
    )

    assert patch.contact_email == "jane@example.com"
    assert patch.quantity == 10
    assert patch.budget == Decimal("5000")


@pytest.mark.asyncio
async def test_extract_ignores_same_normalized_value() -> None:
    facts = _facts(
        quantity=10, company="Acme", industry="IT", product_interest="switches", project_size="x"
    )
    extractor = FactsExtractor()

    patch = await extractor.extract(
        "we need 10 units", facts, _state(), [], FakePromptProvider(), UnusedLLMClient()
    )

    assert patch.quantity is None


@pytest.mark.asyncio
async def test_extract_deterministic_conflict_replaces_existing_value() -> None:
    facts = _facts(
        quantity=5, company="Acme", industry="IT", product_interest="switches", project_size="x"
    )
    extractor = FactsExtractor()

    patch = await extractor.extract(
        "we actually need 10 units now", facts, _state(), [], FakePromptProvider(), UnusedLLMClient()
    )

    assert patch.quantity == 10


@pytest.mark.asyncio
async def test_extract_llm_conflict_is_preserved_not_overwritten() -> None:
    facts = _facts(company="Acme Corp")
    extractor = FactsExtractor()
    llm_client = FakeLLMClient('{"company": "Other Corp", "industry": null, "product_interest": null, "project_size": null}')

    patch = await extractor.extract(
        "we are looking to expand our network setup soon",
        facts,
        _state(),
        [],
        FakePromptProvider(),
        llm_client,
    )

    assert patch.company is None


@pytest.mark.asyncio
async def test_extract_llm_conflict_replaced_when_explicit_in_current_message() -> None:
    """A user correcting themselves (e.g. "no, I need a UPS") must win, not be discarded.

    Regression test for a real bug: once product_interest was set to "camera" from
    an earlier message, the extractor kept preserving it forever even when the user
    explicitly and repeatedly restated a different product in later messages,
    because the old logic treated every LLM-sourced conflict as ambiguous rather
    than checking whether the new value was actually grounded in the current
    message (per readme.md §6: replace only when "explicit in the latest message").
    """
    facts = _facts(product_interest="camera system")
    extractor = FactsExtractor()
    llm_client = FakeLLMClient(
        '{"company": null, "industry": null, "product_interest": "UPS", "project_size": null}'
    )

    patch = await extractor.extract(
        "No. I need a UPS system",
        facts,
        _state(),
        [],
        FakePromptProvider(),
        llm_client,
    )

    assert patch.product_interest == "UPS"


@pytest.mark.asyncio
async def test_extract_llm_fills_missing_field() -> None:
    facts = _facts()
    extractor = FactsExtractor()
    llm_client = FakeLLMClient(
        '{"company": "Acme Corp", "industry": "Retail", "product_interest": "switches", "project_size": null}'
    )

    patch = await extractor.extract(
        "we are looking to expand our network setup soon",
        facts,
        _state(),
        [],
        FakePromptProvider(),
        llm_client,
    )

    assert patch.company == "Acme Corp"
    assert patch.industry == "Retail"
    assert patch.product_interest == "switches"
