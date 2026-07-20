"""Unit tests for Module 10 ToolExecutor plan-conformance and policy enforcement."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

import pytest

import app.tools.executor as executor_module
from app.flags.schemas import FeatureFlags
from app.llm.schemas import LLMResponse
from app.planner.schemas import Plan
from app.session.schemas import ConversationStateSchema, FactsSchema
from app.tools.exceptions import PlanViolationError
from app.tools.executor import ToolExecutor
from app.tools.policy import SecurityPolicy
from app.tools.registry import ToolRegistry
from app.tools.schemas import ExecutionContext, SecurityPolicySchema, SessionContext, ToolExecutionResult
from app.turns.schemas import ConversationTurnRead


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


@pytest.mark.asyncio
async def test_respond_tool_passes_full_context_to_llm(monkeypatch: pytest.MonkeyPatch) -> None:
    """Regression test: `respond` must see the real message, history, and retrieved
    sources — not just a facts/state snapshot. A prior bug dropped all three,
    which meant the LLM couldn't tell it had already asked something, couldn't see
    what the user actually said, and had nothing to ground its answer in.
    """
    captured: dict[str, Any] = {}

    def _fake_build_llm_messages(**kwargs: Any) -> tuple[list[Any], Any]:
        captured.update(kwargs)
        return [], None

    class _FakeLLMClient:
        async def chat(self, *args: Any, **kwargs: Any) -> LLMResponse:
            return LLMResponse(content="ok")

    monkeypatch.setattr(executor_module, "build_llm_messages", _fake_build_llm_messages)
    monkeypatch.setattr(executor_module, "get_llm_client", lambda settings: _FakeLLMClient())

    tenant_id = uuid.uuid4()
    turn = ConversationTurnRead(
        id=uuid.uuid4(),
        tenant_id=tenant_id,
        session_id="s1",
        turn_number=1,
        user_message="hi",
        assistant_message="hello",
        created_at=datetime.now(UTC),
    )
    product_result = ToolExecutionResult(
        step="retrieve_products",
        success=True,
        result_summary='[{"product_id":"' + str(uuid.uuid4()) + '","name":"T-4001 UPS","score":0.9}]',
    )
    session = SessionContext(
        tenant_id=tenant_id,
        session_id="s1",
        facts=FactsSchema(tenant_id=tenant_id, session_id="s1"),
        conversation_state=ConversationStateSchema(tenant_id=tenant_id, session_id="s1"),
        message="Tell me about the T-4001",
        recent_turns=(turn,),
    )
    context = ExecutionContext(retrieve_products=product_result)

    result = await executor_module._respond_tool(session, context)

    assert result.success is True
    assert captured["latest_user_message"] == "Tell me about the T-4001"
    assert captured["recent_turns"] == [turn]
    assert captured["retrieved_sources"][0]["name"] == "T-4001 UPS"


@pytest.mark.asyncio
async def test_respond_tool_signals_no_match_when_a_grounding_step_failed(monkeypatch: pytest.MonkeyPatch) -> None:
    """Regression test for a real bug found live: the wizard's plan is just
    `["run_wizard", "respond"]` with no `retrieve_products` step, so when
    `run_wizard` failed (a power-only catalog has no "switch" products, but
    the BOM builder always required one), `respond` had zero real product
    data and invented fictional competitor UPS models (Eaton, APC, Vertiv)
    with fabricated specs. `respond` must now inject an explicit "no match
    found" notice into the context whenever a grounding step failed, so the
    LLM has a clear signal to say so honestly instead of filling the gap.
    """
    captured: dict[str, Any] = {}

    def _fake_build_llm_messages(**kwargs: Any) -> tuple[list[Any], Any]:
        captured.update(kwargs)
        return [], None

    class _FakeLLMClient:
        async def chat(self, *args: Any, **kwargs: Any) -> LLMResponse:
            return LLMResponse(content="ok")

    monkeypatch.setattr(executor_module, "build_llm_messages", _fake_build_llm_messages)
    monkeypatch.setattr(executor_module, "get_llm_client", lambda settings: _FakeLLMClient())

    tenant_id = uuid.uuid4()
    session = SessionContext(
        tenant_id=tenant_id,
        session_id="s1",
        facts=FactsSchema(tenant_id=tenant_id, session_id="s1"),
        conversation_state=ConversationStateSchema(tenant_id=tenant_id, session_id="s1"),
        message="My power requirement is 20KVA, suggest me a UPS",
    )
    failed_wizard = ToolExecutionResult(
        step="run_wizard", success=False, result_summary="", error="No products found for category 'switch'"
    )
    context = ExecutionContext(run_wizard=failed_wizard)

    result = await executor_module._respond_tool(session, context)

    assert result.success is True
    notices = [s for s in captured["retrieved_sources"] if "notice" in s]
    assert len(notices) == 1
    assert "no specific product model" in notices[0]["notice"].lower() or "no match" in notices[0]["notice"].lower()
