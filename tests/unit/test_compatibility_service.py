"""Unit tests for Module 18 CompatibilityService."""

from __future__ import annotations

import json
import uuid
from typing import Any

import pytest

from app.llm.schemas import LLMResponse
from app.product_intelligence.compatibility_service import CompatibilityService
from app.product_intelligence.models import CompatibilityRule


class FakeCompatibilityRepository:
    def __init__(self, rule: CompatibilityRule | None = None) -> None:
        self.rule = rule
        self.find_calls = 0

    async def find(self, primary_id, secondary_id, compatibility_type, tenant_id) -> CompatibilityRule | None:
        self.find_calls += 1
        return self.rule


class FakeSpecRepository:
    async def get_specs_for_products(self, product_ids, tenant_id) -> dict:
        return {}


class FakeLLMClient:
    def __init__(self, payload: dict[str, Any]) -> None:
        self.payload = payload

    async def chat(self, messages: list[Any], **kwargs: Any) -> LLMResponse:
        return LLMResponse(content=json.dumps(self.payload), tool_calls=[])


@pytest.mark.asyncio
async def test_compatibility_returns_rule_if_found() -> None:
    rule = CompatibilityRule(
        tenant_id=uuid.uuid4(),
        primary_product_id=uuid.uuid4(),
        secondary_product_id=uuid.uuid4(),
        compatibility_type="ups",
        is_compatible=True,
        notes="Verified by vendor datasheet",
    )
    service = CompatibilityService(
        db_session=None,  # type: ignore[arg-type]
        compatibility_repository=FakeCompatibilityRepository(rule),
        spec_repository=FakeSpecRepository(),
    )

    result = await service.check(uuid.uuid4(), uuid.uuid4(), "ups", uuid.uuid4(), FakeLLMClient({}))

    assert result.is_compatible is True
    assert result.source == "rule"
    assert result.notes == "Verified by vendor datasheet"


@pytest.mark.asyncio
async def test_compatibility_falls_back_to_llm_when_no_rule() -> None:
    repo = FakeCompatibilityRepository(rule=None)
    service = CompatibilityService(
        db_session=None,  # type: ignore[arg-type]
        compatibility_repository=repo,
        spec_repository=FakeSpecRepository(),
    )
    llm_client = FakeLLMClient({"is_compatible": True, "notes": "Both support the same voltage range"})

    result = await service.check(uuid.uuid4(), uuid.uuid4(), "battery", uuid.uuid4(), llm_client)

    assert repo.find_calls == 1
    assert result.source == "llm_inference"
    assert result.is_compatible is True
    assert result.notes == "Both support the same voltage range"


@pytest.mark.asyncio
async def test_compatibility_llm_failure_falls_back_to_unknown() -> None:
    service = CompatibilityService(
        db_session=None,  # type: ignore[arg-type]
        compatibility_repository=FakeCompatibilityRepository(rule=None),
        spec_repository=FakeSpecRepository(),
    )

    class FailingLLMClient:
        async def chat(self, *args: Any, **kwargs: Any) -> LLMResponse:
            raise RuntimeError("LLM unavailable")

    result = await service.check(uuid.uuid4(), uuid.uuid4(), "sfp", uuid.uuid4(), FailingLLMClient())

    assert result.is_compatible is None
    assert result.source == "llm_inference"
    assert result.notes == "Unable to determine compatibility from available data"
