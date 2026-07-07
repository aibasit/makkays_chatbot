"""Integration tests for Module 10 ToolExecutor against real Postgres + Redis."""

from __future__ import annotations

import uuid
from collections.abc import AsyncGenerator
from decimal import Decimal
from typing import Any

import pytest
from sqlalchemy import text

import app.tools.executor as executor_module
from app.cache.redis_client import close_redis, get_redis, initialize_redis
from app.db.engine import dispose_database, get_db_session, initialize_database
from app.dependencies import get_settings
from app.flags.schemas import FeatureFlags
from app.planner.schemas import Plan
from app.session.schemas import ConversationStateSchema, FactsSchema
from app.tools.executor import ToolExecutor
from app.tools.policy import PolicyRegistry
from app.tools.registry import ToolRegistry
from app.tools.schemas import SessionContext, ToolExecutionResult


async def _check_db_available() -> None:
    settings = get_settings()
    initialize_database(settings)
    try:
        async for session in get_db_session():
            await session.execute(text("SELECT 1"))
    except Exception as exc:
        pytest.skip(f"Configured database is not reachable: {exc}")


async def _check_redis_available() -> None:
    settings = get_settings()
    redis = initialize_redis(settings)
    try:
        await redis.ping()
    except Exception as exc:
        pytest.skip(f"Configured Redis is not reachable: {exc}")


async def _ensure_tool_audit_log_table() -> None:
    async for session in get_db_session():
        await session.execute(text("CREATE EXTENSION IF NOT EXISTS pgcrypto"))
        await session.execute(
            text(
                """
                CREATE TABLE IF NOT EXISTS tool_audit_log (
                  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                  tenant_id UUID NOT NULL,
                  session_id TEXT NOT NULL,
                  tool_name TEXT NOT NULL,
                  intent TEXT,
                  allowed BOOLEAN NOT NULL,
                  denial_reason TEXT,
                  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
                )
                """,
            ),
        )


@pytest.fixture(autouse=True)
async def _infra_cleanup() -> AsyncGenerator[None, None]:
    yield
    await close_redis()
    await dispose_database()
    get_settings.cache_clear()


async def _cleanup_audit_rows(tenant_id: uuid.UUID) -> None:
    async for session in get_db_session():
        await session.execute(
            text("DELETE FROM tool_audit_log WHERE tenant_id = :tenant_id"),
            {"tenant_id": tenant_id},
        )


def _real_policy_registry() -> PolicyRegistry:
    registry = PolicyRegistry(get_settings().tools.policy_directory)
    registry.load()
    return registry


def _session_for(facts: FactsSchema, state: ConversationStateSchema) -> SessionContext:
    return SessionContext(
        tenant_id=facts.tenant_id, session_id=facts.session_id, facts=facts, conversation_state=state
    )


@pytest.mark.asyncio
async def test_execute_plan_runs_generate_quote_when_policy_and_plan_agree(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    await _check_db_available()
    await _check_redis_available()
    await _ensure_tool_audit_log_table()
    tenant_id = uuid.uuid4()

    fake_registry = ToolRegistry()

    async def _fake_generate_quote(session: Any, context: Any) -> ToolExecutionResult:
        return ToolExecutionResult(step="generate_quote", success=True, result_summary="Quote: $1000")

    fake_registry.register("generate_quote", _fake_generate_quote)
    monkeypatch.setattr(executor_module, "tool_registry", fake_registry)

    facts = FactsSchema(
        tenant_id=tenant_id,
        session_id="s1",
        company="Acme",
        product_interest="switch",
        quantity=5,
        budget=Decimal("1000"),
    )
    state = ConversationStateSchema(tenant_id=tenant_id, session_id="s1")
    plan = Plan(intent="quote_request", steps=["generate_quote"])

    try:
        async for db_session in get_db_session():
            executor = ToolExecutor(db_session, _real_policy_registry())
            results = await executor.execute_plan(plan, _session_for(facts, state), FeatureFlags())

        assert len(results) == 1
        assert results[0].success is True

        async for db_session in get_db_session():
            row = (
                await db_session.execute(
                    text("SELECT allowed FROM tool_audit_log WHERE tenant_id = :tenant_id"),
                    {"tenant_id": tenant_id},
                )
            ).one()
        assert row.allowed is True
    finally:
        await _cleanup_audit_rows(tenant_id)


@pytest.mark.asyncio
async def test_execute_plan_denies_generate_quote_when_slots_incomplete_even_if_in_plan(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    await _check_db_available()
    await _check_redis_available()
    await _ensure_tool_audit_log_table()
    tenant_id = uuid.uuid4()

    fake_registry = ToolRegistry()

    async def _fake_generate_quote(session: Any, context: Any) -> ToolExecutionResult:
        raise AssertionError("generate_quote must not execute when slots are incomplete")

    fake_registry.register("generate_quote", _fake_generate_quote)
    monkeypatch.setattr(executor_module, "tool_registry", fake_registry)

    facts = FactsSchema(tenant_id=tenant_id, session_id="s1")  # no company/quantity/budget
    state = ConversationStateSchema(tenant_id=tenant_id, session_id="s1")
    plan = Plan(intent="quote_request", steps=["generate_quote"])

    try:
        async for db_session in get_db_session():
            executor = ToolExecutor(db_session, _real_policy_registry())
            results = await executor.execute_plan(plan, _session_for(facts, state), FeatureFlags())

        assert len(results) == 1
        assert results[0].success is False
        assert results[0].error is not None

        async for db_session in get_db_session():
            row = (
                await db_session.execute(
                    text("SELECT allowed FROM tool_audit_log WHERE tenant_id = :tenant_id"),
                    {"tenant_id": tenant_id},
                )
            ).one()
        assert row.allowed is False
    finally:
        await _cleanup_audit_rows(tenant_id)


@pytest.mark.asyncio
async def test_rate_limit_enforced_across_repeated_calls_within_window(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    await _check_db_available()
    await _check_redis_available()
    await _ensure_tool_audit_log_table()
    tenant_id = uuid.uuid4()

    fake_registry = ToolRegistry()

    async def _fake_create_lead(session: Any, context: Any) -> ToolExecutionResult:
        return ToolExecutionResult(step="create_lead", success=True, result_summary="Lead created")

    fake_registry.register("create_lead", _fake_create_lead)
    monkeypatch.setattr(executor_module, "tool_registry", fake_registry)

    facts = FactsSchema(tenant_id=tenant_id, session_id="s1", contact_email="buyer@example.com")
    state = ConversationStateSchema(tenant_id=tenant_id, session_id="s1")
    plan = Plan(intent="sales_inquiry", steps=["create_lead"])

    try:
        results: list[ToolExecutionResult] = []
        for _ in range(6):  # create_lead.yaml sets rate_limit: "5/min"
            async for db_session in get_db_session():
                executor = ToolExecutor(db_session, _real_policy_registry())
                results.extend(await executor.execute_plan(plan, _session_for(facts, state), FeatureFlags()))

        assert sum(1 for result in results if result.success) == 5
        assert results[-1].success is False
        assert "rate limit" in (results[-1].error or "").lower()
    finally:
        await _cleanup_audit_rows(tenant_id)
        redis = get_redis()
        await redis.delete(f"rate_limit:tool:{tenant_id}:s1:create_lead")


def test_disabled_tool_not_present_in_llm_tool_schema() -> None:
    registry = ToolRegistry()

    async def _noop(session: Any, context: Any) -> ToolExecutionResult:
        return ToolExecutionResult(step="fake_tool", success=True, result_summary="")

    registry.register(
        "fake_tool",
        _noop,
        flag_name="enable_quotes",
        llm_schema={
            "type": "function",
            "function": {"name": "fake_tool", "description": "x", "parameters": {}},
        },
    )

    enabled_schema = registry.get_llm_tool_schema(FeatureFlags(enable_quotes=True))
    disabled_schema = registry.get_llm_tool_schema(FeatureFlags(enable_quotes=False))

    assert len(enabled_schema) == 1
    assert disabled_schema == []


@pytest.mark.asyncio
async def test_tool_failure_does_not_crash_turn(monkeypatch: pytest.MonkeyPatch) -> None:
    await _check_db_available()
    await _check_redis_available()
    await _ensure_tool_audit_log_table()
    tenant_id = uuid.uuid4()

    fake_registry = ToolRegistry()

    async def _broken_tool(session: Any, context: Any) -> ToolExecutionResult:
        raise ConnectionError("Qdrant unreachable")

    fake_registry.register("retrieve_products", _broken_tool)
    monkeypatch.setattr(executor_module, "tool_registry", fake_registry)

    facts = FactsSchema(tenant_id=tenant_id, session_id="s1")
    state = ConversationStateSchema(tenant_id=tenant_id, session_id="s1")
    plan = Plan(intent="sales_inquiry", steps=["retrieve_products"])

    async for db_session in get_db_session():
        executor = ToolExecutor(db_session, _real_policy_registry())
        results = await executor.execute_plan(plan, _session_for(facts, state), FeatureFlags())

    assert len(results) == 1
    assert results[0].success is False
    assert "Qdrant unreachable" in (results[0].error or "")
