"""Integration tests for Module 19 wizard/use-case flows against real Postgres."""

from __future__ import annotations

import uuid
from collections.abc import AsyncGenerator
from decimal import Decimal
from typing import Any

import pytest
from sqlalchemy import text

import app.solution_builder as solution_builder_module
from app.cache.redis_client import close_redis
from app.db.engine import dispose_database, get_db_session, initialize_database
from app.dependencies import get_settings
from app.llm.schemas import LLMResponse
from app.session.schemas import ConversationStateSchema, FactsSchema
from app.solution_builder.repository import UseCaseProfileRepository
from app.tools.schemas import ExecutionContext, SessionContext


async def _check_db_available() -> None:
    settings = get_settings()
    initialize_database(settings)
    try:
        async for session in get_db_session():
            await session.execute(text("SELECT 1"))
    except Exception as exc:
        pytest.skip(f"Configured database is not reachable: {exc}")


async def _ensure_tables() -> None:
    async for session in get_db_session():
        await session.execute(text("CREATE EXTENSION IF NOT EXISTS pgcrypto"))
        await session.execute(
            text(
                """
                CREATE TABLE IF NOT EXISTS products (
                  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                  tenant_id UUID NOT NULL,
                  name TEXT NOT NULL,
                  brand TEXT,
                  category TEXT,
                  description TEXT,
                  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
                )
                """
            )
        )
        await session.execute(
            text(
                """
                CREATE TABLE IF NOT EXISTS product_pricing (
                  product_id UUID NOT NULL REFERENCES products(id) ON DELETE CASCADE,
                  tenant_id UUID NOT NULL,
                  unit_price NUMERIC NOT NULL,
                  currency TEXT NOT NULL DEFAULT 'USD',
                  PRIMARY KEY (product_id, tenant_id)
                )
                """
            )
        )
        await session.execute(
            text(
                """
                CREATE TABLE IF NOT EXISTS wizard_sessions (
                  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                  tenant_id UUID NOT NULL,
                  session_id TEXT NOT NULL,
                  current_step INTEGER NOT NULL DEFAULT 0,
                  collected_requirements JSONB NOT NULL DEFAULT '{}',
                  completed BOOLEAN NOT NULL DEFAULT false,
                  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
                  updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
                )
                """
            )
        )
        await session.execute(
            text(
                """
                CREATE TABLE IF NOT EXISTS use_case_profiles (
                  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                  tenant_id UUID NOT NULL,
                  use_case TEXT NOT NULL,
                  requirements JSONB NOT NULL,
                  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
                  UNIQUE (tenant_id, use_case)
                )
                """
            )
        )
        await session.execute(
            text(
                """
                CREATE TABLE IF NOT EXISTS solutions (
                  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                  tenant_id UUID NOT NULL,
                  session_id TEXT NOT NULL,
                  use_case TEXT,
                  requirements JSONB NOT NULL,
                  line_items JSONB NOT NULL,
                  total_estimate NUMERIC(12,2),
                  currency TEXT NOT NULL DEFAULT 'USD',
                  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
                )
                """
            )
        )


@pytest.fixture(autouse=True)
async def _infra_cleanup() -> AsyncGenerator[None, None]:
    yield
    await close_redis()
    await dispose_database()
    get_settings.cache_clear()


async def _cleanup(tenant_id: uuid.UUID) -> None:
    async for session in get_db_session():
        await session.execute(text("DELETE FROM solutions WHERE tenant_id = :t"), {"t": tenant_id})
        await session.execute(text("DELETE FROM use_case_profiles WHERE tenant_id = :t"), {"t": tenant_id})
        await session.execute(text("DELETE FROM wizard_sessions WHERE tenant_id = :t"), {"t": tenant_id})
        await session.execute(text("DELETE FROM product_pricing WHERE tenant_id = :t"), {"t": tenant_id})
        await session.execute(text("DELETE FROM products WHERE tenant_id = :t"), {"t": tenant_id})


async def _seed_catalog(tenant_id: uuid.UUID) -> None:
    switch_id, ups_id = uuid.uuid4(), uuid.uuid4()
    async for session in get_db_session():
        await session.execute(
            text(
                "INSERT INTO products (id, tenant_id, name, brand, category) "
                "VALUES (:id, :t, 'TL-SG3428', 'TP-Link', 'switch')"
            ),
            {"id": switch_id, "t": tenant_id},
        )
        await session.execute(
            text(
                "INSERT INTO products (id, tenant_id, name, brand, category) "
                "VALUES (:id, :t, 'APC UPS', 'APC', 'ups')"
            ),
            {"id": ups_id, "t": tenant_id},
        )
        await session.execute(
            text("INSERT INTO product_pricing (product_id, tenant_id, unit_price) VALUES (:pid, :t, 120.00)"),
            {"pid": switch_id, "t": tenant_id},
        )
        await session.execute(
            text("INSERT INTO product_pricing (product_id, tenant_id, unit_price) VALUES (:pid, :t, 300.00)"),
            {"pid": ups_id, "t": tenant_id},
        )


def _session_context(tenant_id: uuid.UUID, message: str) -> SessionContext:
    facts = FactsSchema(tenant_id=tenant_id, session_id="s1")
    state = ConversationStateSchema(tenant_id=tenant_id, session_id="s1")
    return SessionContext(
        tenant_id=tenant_id, session_id="s1", facts=facts, conversation_state=state, message=message
    )


def _patch_llm(monkeypatch: pytest.MonkeyPatch, module: Any) -> None:
    def _fake_get_llm_client(settings: Any) -> Any:
        class _Fake:
            async def chat(self, *args: Any, **kwargs: Any) -> LLMResponse:
                return LLMResponse(content="Here is your solution.", tool_calls=[])

        return _Fake()

    monkeypatch.setattr(module, "get_llm_client", _fake_get_llm_client)


@pytest.mark.asyncio
async def test_wizard_multi_turn_completes_bom_in_5_turns(monkeypatch: pytest.MonkeyPatch) -> None:
    await _check_db_available()
    await _ensure_tables()
    _patch_llm(monkeypatch, solution_builder_module)
    tenant_id = uuid.uuid4()

    try:
        await _seed_catalog(tenant_id)

        step1 = await solution_builder_module.run_wizard_tool(
            _session_context(tenant_id, "help me build a solution"), ExecutionContext()
        )
        assert "use case" in step1.result_summary.lower()

        step2 = await solution_builder_module.run_wizard_tool(
            _session_context(tenant_id, "networking"), ExecutionContext()
        )
        assert "devices" in step2.result_summary.lower()

        step3 = await solution_builder_module.run_wizard_tool(
            _session_context(tenant_id, "200"), ExecutionContext()
        )
        assert "location" in step3.result_summary.lower()

        step4 = await solution_builder_module.run_wizard_tool(
            _session_context(tenant_id, "Karachi"), ExecutionContext()
        )
        assert "brand" in step4.result_summary.lower()

        step5 = await solution_builder_module.run_wizard_tool(
            _session_context(tenant_id, "TP-Link"), ExecutionContext()
        )

        assert step5.success is True
        assert step5.result_summary == "Here is your solution."

        async for session in get_db_session():
            row = (
                await session.execute(
                    text("SELECT total_estimate FROM solutions WHERE tenant_id = :t"), {"t": tenant_id}
                )
            ).one()
        assert row.total_estimate == Decimal("1380.00")
    finally:
        await _cleanup(tenant_id)


@pytest.mark.asyncio
async def test_use_case_recommendation_end_to_end(monkeypatch: pytest.MonkeyPatch) -> None:
    await _check_db_available()
    await _ensure_tables()
    _patch_llm(monkeypatch, solution_builder_module)
    tenant_id = uuid.uuid4()

    try:
        await _seed_catalog(tenant_id)
        async for session in get_db_session():
            await UseCaseProfileRepository(session).upsert(tenant_id, "school", {"device_count": 200})

        facts = FactsSchema(tenant_id=tenant_id, session_id="s1", product_interest="school")
        state = ConversationStateSchema(tenant_id=tenant_id, session_id="s1")
        session_context = SessionContext(tenant_id=tenant_id, session_id="s1", facts=facts, conversation_state=state)

        result = await solution_builder_module.build_use_case_solution_tool(session_context, ExecutionContext())

        assert result.success is True
        assert result.result_summary == "Here is your solution."
    finally:
        await _cleanup(tenant_id)
