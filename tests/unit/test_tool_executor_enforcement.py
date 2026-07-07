"""Unit tests for Module 10 ToolExecutor plan-conformance and policy enforcement."""

from __future__ import annotations

import uuid
from typing import Any

import pytest

import app.tools.executor as executor_module
from app.flags.schemas import FeatureFlags
from app.planner.schemas import Plan
from app.session.schemas import ConversationStateSchema, FactsSchema
from app.tools.exceptions import PlanViolationError
from app.tools.executor import ToolExecutor
from app.tools.policy import SecurityPolicy
from app.tools.registry import ToolRegistry
from app.tools.schemas import SecurityPolicySchema, SessionContext, ToolExecutionResult


class FakeRedis:
    async def incr(self, key: str) -> int:
        return 1

    async def expire(self, key: str, seconds: int) -> None:
        return None


class FakePolicyRegistry:
    def __init__(self, policies: dict[str, SecurityPolicy]) -> None:
        self.policies = policies

    def get(self, tool_name: str) -> SecurityPolicy | None:
        return self.policies.get(tool_name)


def _allow_policy(tool_name: str, *, audit_log: bool = False) -> SecurityPolicy:
    return SecurityPolicy(
        SecurityPolicySchema(
            tool_name=tool_name,
            allowed_intents=["sales_inquiry", "quote_request"],
            required_state=[],
            required_slots=[],
            rate_limit=None,
            audit_log=audit_log,
        )
    )


def _session() -> SessionContext:
    tenant_id = uuid.uuid4()
    return SessionContext(
        tenant_id=tenant_id,
        session_id="s1",
        facts=FactsSchema(tenant_id=tenant_id, session_id="s1"),
        conversation_state=ConversationStateSchema(tenant_id=tenant_id, session_id="s1"),
    )


@pytest.mark.asyncio
async def test_execute_plan_rejects_step_not_in_plan() -> None:
    executor = ToolExecutor(db_session=None, policy_registry=FakePolicyRegistry({}))  # type: ignore[arg-type]
    plan = Plan(intent="quote_request", steps=["retrieve_products", "respond"])

    with pytest.raises(PlanViolationError):
        await executor.execute_step("generate_quote", plan, _session(), FeatureFlags())


@pytest.mark.asyncio
async def test_execute_step_skips_unregistered_tool(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(executor_module, "tool_registry", ToolRegistry())
    executor = ToolExecutor(db_session=None, policy_registry=FakePolicyRegistry({}))  # type: ignore[arg-type]
    plan = Plan(intent="quote_request", steps=["retrieve_products"])

    result = await executor.execute_step("retrieve_products", plan, _session(), FeatureFlags())

    assert result is None


@pytest.mark.asyncio
async def test_execute_step_skips_tool_without_policy(monkeypatch: pytest.MonkeyPatch) -> None:
    fake_registry = ToolRegistry()

    async def _fake_tool(session: Any, context: Any) -> ToolExecutionResult:
        return ToolExecutionResult(step="retrieve_products", success=True, result_summary="ok")

    fake_registry.register("retrieve_products", _fake_tool)
    monkeypatch.setattr(executor_module, "tool_registry", fake_registry)
    executor = ToolExecutor(db_session=None, policy_registry=FakePolicyRegistry({}))  # type: ignore[arg-type]
    plan = Plan(intent="quote_request", steps=["retrieve_products"])

    result = await executor.execute_step("retrieve_products", plan, _session(), FeatureFlags())

    assert result is None


@pytest.mark.asyncio
async def test_critical_step_failure_aborts_remaining_steps(monkeypatch: pytest.MonkeyPatch) -> None:
    fake_registry = ToolRegistry()

    async def _failing_tool(session: Any, context: Any) -> ToolExecutionResult:
        raise RuntimeError("boom")

    async def _should_not_run(session: Any, context: Any) -> ToolExecutionResult:
        raise AssertionError("this step must not run after a critical failure")

    fake_registry.register("generate_quote", _failing_tool)
    fake_registry.register("respond", _should_not_run)
    monkeypatch.setattr(executor_module, "tool_registry", fake_registry)
    monkeypatch.setattr(executor_module, "get_redis", lambda: FakeRedis())
    policies = {"generate_quote": _allow_policy("generate_quote"), "respond": _allow_policy("respond")}
    executor = ToolExecutor(db_session=None, policy_registry=FakePolicyRegistry(policies))  # type: ignore[arg-type]
    plan = Plan(intent="quote_request", steps=["generate_quote", "respond"])

    results = await executor.execute_plan(plan, _session(), FeatureFlags())

    assert len(results) == 1
    assert results[0].success is False


@pytest.mark.asyncio
async def test_non_critical_step_failure_continues_plan(monkeypatch: pytest.MonkeyPatch) -> None:
    fake_registry = ToolRegistry()

    async def _failing_tool(session: Any, context: Any) -> ToolExecutionResult:
        raise RuntimeError("boom")

    async def _ok_tool(session: Any, context: Any) -> ToolExecutionResult:
        return ToolExecutionResult(step="respond", success=True, result_summary="done")

    fake_registry.register("retrieve_products", _failing_tool)
    fake_registry.register("respond", _ok_tool)
    monkeypatch.setattr(executor_module, "tool_registry", fake_registry)
    monkeypatch.setattr(executor_module, "get_redis", lambda: FakeRedis())
    policies = {"retrieve_products": _allow_policy("retrieve_products"), "respond": _allow_policy("respond")}
    executor = ToolExecutor(db_session=None, policy_registry=FakePolicyRegistry(policies))  # type: ignore[arg-type]
    plan = Plan(intent="quote_request", steps=["retrieve_products", "respond"])

    results = await executor.execute_plan(plan, _session(), FeatureFlags())

    assert len(results) == 2
    assert results[0].success is False
    assert results[1].success is True


@pytest.mark.asyncio
async def test_policy_denial_is_recorded_as_failed_result(monkeypatch: pytest.MonkeyPatch) -> None:
    fake_registry = ToolRegistry()

    async def _should_not_run(session: Any, context: Any) -> ToolExecutionResult:
        raise AssertionError("denied tool must not execute")

    fake_registry.register("retrieve_products", _should_not_run)
    monkeypatch.setattr(executor_module, "tool_registry", fake_registry)
    monkeypatch.setattr(executor_module, "get_redis", lambda: FakeRedis())
    deny_policy = SecurityPolicy(
        SecurityPolicySchema(
            tool_name="retrieve_products",
            allowed_intents=["technical_support"],  # plan intent below won't match
            required_state=[],
            required_slots=[],
            rate_limit=None,
            audit_log=False,
        )
    )
    executor = ToolExecutor(
        db_session=None, policy_registry=FakePolicyRegistry({"retrieve_products": deny_policy})
    )  # type: ignore[arg-type]
    plan = Plan(intent="quote_request", steps=["retrieve_products"])

    result = await executor.execute_step("retrieve_products", plan, _session(), FeatureFlags())

    assert result is not None
    assert result.success is False
    assert "intent" in (result.error or "")
