"""Integration-style coverage for the Module 22 availability tool wiring."""

from __future__ import annotations

import uuid
from typing import Any

import pytest

import app.availability.tool as availability_tool_module
import app.tools.executor as executor_module
from app.availability.schemas import AvailabilityResult
from app.dependencies import get_settings
from app.flags.schemas import FeatureFlags
from app.planner.schemas import Plan
from app.session.schemas import ConversationStateSchema, FactsSchema
from app.tools.executor import ToolExecutor
from app.tools.policy import PolicyRegistry
from app.tools.registry import ToolRegistry
from app.tools.schemas import ExecutionContext, SessionContext, ToolExecutionResult


class FakeRedis:
    """Small async Redis stand-in for SecurityPolicy rate-limit checks."""

    def __init__(self) -> None:
        self._counts: dict[str, int] = {}

    async def incr(self, key: str) -> int:
        self._counts[key] = self._counts.get(key, 0) + 1
        return self._counts[key]

    async def expire(self, key: str, seconds: int) -> bool:
        return True


class FakeAvailabilityService:
    async def check_batch(self, product_ids: list[uuid.UUID], tenant_id: uuid.UUID) -> list[AvailabilityResult]:
        return [
            AvailabilityResult(
                product_id=product_id,
                in_stock=True,
                quantity=12,
                estimated_delivery_days=3,
                source="local_db",
            )
            for product_id in product_ids
        ]


class FakeSessionContextManager:
    async def __aenter__(self) -> object:
        return object()

    async def __aexit__(self, exc_type: Any, exc: Any, traceback: Any) -> None:
        return None


def _real_policy_registry() -> PolicyRegistry:
    registry = PolicyRegistry(get_settings().tools.policy_directory)
    registry.load()
    return registry


def _session_for(facts: FactsSchema, state: ConversationStateSchema) -> SessionContext:
    return SessionContext(
        tenant_id=facts.tenant_id,
        session_id=facts.session_id,
        facts=facts,
        conversation_state=state,
    )


@pytest.mark.asyncio
async def test_check_availability_tool_end_to_end(monkeypatch: pytest.MonkeyPatch) -> None:
    tenant_id = uuid.uuid4()
    product_id = uuid.uuid4()
    fake_registry = ToolRegistry()

    async def _fake_retrieve_products(session: SessionContext, context: ExecutionContext) -> ToolExecutionResult:
        return ToolExecutionResult(
            step="retrieve_products",
            success=True,
            result_summary="Found one product.",
            product_ids=[product_id],
        )

    fake_registry.register("retrieve_products", _fake_retrieve_products)
    fake_registry.register(
        "check_availability",
        availability_tool_module.check_availability_tool,
        flag_name="enable_availability_check",
    )

    monkeypatch.setattr(executor_module, "tool_registry", fake_registry)
    monkeypatch.setattr(executor_module, "get_redis", lambda: FakeRedis())
    monkeypatch.setattr(
        availability_tool_module,
        "get_sessionmaker",
        lambda: lambda: FakeSessionContextManager(),
    )
    monkeypatch.setattr(
        availability_tool_module,
        "get_availability_service",
        lambda db_session, settings: FakeAvailabilityService(),
    )

    facts = FactsSchema(tenant_id=tenant_id, session_id="availability-session")
    state = ConversationStateSchema(tenant_id=tenant_id, session_id="availability-session")
    plan = Plan(intent="availability_inquiry", steps=["retrieve_products", "check_availability"])

    executor = ToolExecutor(object(), _real_policy_registry())  # type: ignore[arg-type]
    results = await executor.execute_plan(
        plan,
        _session_for(facts, state),
        FeatureFlags(enable_availability_check=True),
    )

    assert [result.step for result in results] == ["retrieve_products", "check_availability"]
    assert results[1].success is True
    assert f"Product {product_id}" in results[1].result_summary
    assert "quantity 12" in results[1].result_summary
