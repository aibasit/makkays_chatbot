"""Integration tests for Module 18 tool wrappers against real Postgres."""

from __future__ import annotations

import uuid
from collections.abc import AsyncGenerator
from typing import Any

import pytest
from sqlalchemy import text

import app.product_intelligence as product_intelligence_module
from app.cache.redis_client import close_redis
from app.db.engine import dispose_database, get_db_session, initialize_database
from app.dependencies import get_settings
from app.llm.schemas import LLMResponse
from app.session.schemas import ConversationStateSchema, FactsSchema
from app.tools.schemas import ExecutionContext, SessionContext, ToolExecutionResult


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
                CREATE TABLE IF NOT EXISTS product_specs (
                  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                  product_id UUID NOT NULL REFERENCES products(id) ON DELETE CASCADE,
                  tenant_id UUID NOT NULL,
                  spec_key TEXT NOT NULL,
                  spec_value TEXT NOT NULL
                )
                """
            )
        )
        await session.execute(
            text(
                """
                CREATE TABLE IF NOT EXISTS compatibility_rules (
                  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                  tenant_id UUID NOT NULL,
                  primary_product_id UUID NOT NULL REFERENCES products(id),
                  secondary_product_id UUID NOT NULL REFERENCES products(id),
                  compatibility_type TEXT NOT NULL,
                  is_compatible BOOLEAN NOT NULL,
                  notes TEXT,
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
        await session.execute(text("DELETE FROM compatibility_rules WHERE tenant_id = :t"), {"t": tenant_id})
        await session.execute(text("DELETE FROM product_specs WHERE tenant_id = :t"), {"t": tenant_id})
        await session.execute(text("DELETE FROM products WHERE tenant_id = :t"), {"t": tenant_id})


def _session_context(tenant_id: uuid.UUID, message: str = "") -> SessionContext:
    facts = FactsSchema(tenant_id=tenant_id, session_id="s1")
    state = ConversationStateSchema(tenant_id=tenant_id, session_id="s1")
    return SessionContext(
        tenant_id=tenant_id, session_id="s1", facts=facts, conversation_state=state, message=message
    )


@pytest.mark.asyncio
async def test_compare_products_tool_end_to_end_with_orchestrator(monkeypatch: pytest.MonkeyPatch) -> None:
    await _check_db_available()
    await _ensure_tables()
    tenant_id = uuid.uuid4()

    def _fake_get_llm_client(settings: Any) -> Any:
        class _Fake:
            async def chat(self, *args: Any, **kwargs: Any) -> LLMResponse:
                return LLMResponse(content="Switch B has more ports.", tool_calls=[])

        return _Fake()

    monkeypatch.setattr(product_intelligence_module, "get_llm_client", _fake_get_llm_client)

    try:
        product_a = uuid.uuid4()
        product_b = uuid.uuid4()
        async for session in get_db_session():
            await session.execute(
                text(
                    "INSERT INTO products (id, tenant_id, name, brand, category) "
                    "VALUES (:id, :tenant_id, :name, 'Acme', 'switch')"
                ),
                {"id": product_a, "tenant_id": tenant_id, "name": "Switch A"},
            )
            await session.execute(
                text(
                    "INSERT INTO products (id, tenant_id, name, brand, category) "
                    "VALUES (:id, :tenant_id, :name, 'Acme', 'switch')"
                ),
                {"id": product_b, "tenant_id": tenant_id, "name": "Switch B"},
            )
            await session.execute(
                text(
                    "INSERT INTO product_specs (product_id, tenant_id, spec_key, spec_value) "
                    "VALUES (:pid, :tenant_id, 'ports', :value)"
                ),
                {"pid": product_a, "tenant_id": tenant_id, "value": "24"},
            )
            await session.execute(
                text(
                    "INSERT INTO product_specs (product_id, tenant_id, spec_key, spec_value) "
                    "VALUES (:pid, :tenant_id, 'ports', :value)"
                ),
                {"pid": product_b, "tenant_id": tenant_id, "value": "48"},
            )

        session_context = _session_context(tenant_id)
        context = ExecutionContext(
            retrieve_products=ToolExecutionResult(
                step="retrieve_products", success=True, result_summary="[]", product_ids=[product_a, product_b]
            )
        )

        result = await product_intelligence_module.compare_products_tool(session_context, context)

        assert result.success is True
        assert "Switch A" in result.result_summary
        assert "Switch B" in result.result_summary
        assert "24" in result.result_summary
        assert "48" in result.result_summary
    finally:
        await _cleanup(tenant_id)


@pytest.mark.asyncio
async def test_check_compatibility_tool_end_to_end(monkeypatch: pytest.MonkeyPatch) -> None:
    await _check_db_available()
    await _ensure_tables()
    tenant_id = uuid.uuid4()

    def _fake_get_llm_client(settings: Any) -> Any:
        # Constructing a client is cheap/harmless in real code (no I/O); what
        # must never happen when an explicit rule exists is an actual chat() call.
        class _Fake:
            async def chat(self, *args: Any, **kwargs: Any) -> Any:
                raise AssertionError("LLM should not be called when an explicit rule exists")

        return _Fake()

    monkeypatch.setattr(product_intelligence_module, "get_llm_client", _fake_get_llm_client)

    try:
        product_a = uuid.uuid4()
        product_b = uuid.uuid4()
        async for session in get_db_session():
            for pid, name in ((product_a, "UPS A"), (product_b, "Battery B")):
                await session.execute(
                    text(
                        "INSERT INTO products (id, tenant_id, name, brand, category) "
                        "VALUES (:id, :tenant_id, :name, 'Acme', 'ups')"
                    ),
                    {"id": pid, "tenant_id": tenant_id, "name": name},
                )
            await session.execute(
                text(
                    "INSERT INTO compatibility_rules "
                    "(tenant_id, primary_product_id, secondary_product_id, compatibility_type, is_compatible, notes) "
                    "VALUES (:tenant_id, :primary, :secondary, 'ups', true, 'Confirmed by vendor')"
                ),
                {"tenant_id": tenant_id, "primary": product_a, "secondary": product_b},
            )

        session_context = _session_context(tenant_id, message="Is this UPS compatible with the battery?")
        context = ExecutionContext(
            retrieve_products=ToolExecutionResult(
                step="retrieve_products", success=True, result_summary="[]", product_ids=[product_a, product_b]
            )
        )

        result = await product_intelligence_module.check_compatibility_tool(session_context, context)

        assert result.success is True
        assert "Compatible" in result.result_summary
        assert "Confirmed by vendor" in result.result_summary
    finally:
        await _cleanup(tenant_id)
