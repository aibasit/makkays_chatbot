"""Integration tests for Module 09 feature flag DB overrides against a real Postgres."""

from __future__ import annotations

import uuid
from collections.abc import AsyncGenerator

import pytest
from sqlalchemy import text

from app.cache.redis_client import close_redis
from app.db.engine import dispose_database, get_db_session, initialize_database
from app.dependencies import get_settings
from app.flags.service import FeatureFlagsService
from app.planner.planner import TaskPlanner
from app.session.schemas import ConversationStateSchema, FactsSchema
from app.shared.intent_context import IntentResult


async def _check_db_available() -> None:
    settings = get_settings()
    initialize_database(settings)
    try:
        async for session in get_db_session():
            await session.execute(text("SELECT 1"))
    except Exception as exc:
        pytest.skip(f"Configured database is not reachable: {exc}")


async def _ensure_feature_flags_table() -> None:
    async for session in get_db_session():
        await session.execute(
            text(
                """
                CREATE TABLE IF NOT EXISTS feature_flags (
                  tenant_id UUID NOT NULL,
                  flag_name TEXT NOT NULL,
                  enabled BOOLEAN NOT NULL,
                  updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
                  PRIMARY KEY (tenant_id, flag_name)
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


async def _cleanup_rows(tenant_id: uuid.UUID) -> None:
    async for session in get_db_session():
        await session.execute(
            text("DELETE FROM feature_flags WHERE tenant_id = :tenant_id"),
            {"tenant_id": tenant_id},
        )


@pytest.mark.asyncio
async def test_resolve_reads_db_override_row() -> None:
    await _check_db_available()
    await _ensure_feature_flags_table()
    tenant_id = uuid.uuid4()
    try:
        async for session in get_db_session():
            await session.execute(
                text(
                    "INSERT INTO feature_flags (tenant_id, flag_name, enabled) "
                    "VALUES (:tenant_id, 'enable_quotes', false)"
                ),
                {"tenant_id": tenant_id},
            )

        async for session in get_db_session():
            service = FeatureFlagsService(session, get_settings())
            flags = await service.resolve(tenant_id)

        assert flags.enable_quotes is False
        assert flags.enable_rag is True
    finally:
        await _cleanup_rows(tenant_id)


@pytest.mark.asyncio
async def test_planner_skips_generate_quote_step_when_enable_quotes_false() -> None:
    await _check_db_available()
    await _ensure_feature_flags_table()
    tenant_id = uuid.uuid4()
    try:
        async for session in get_db_session():
            await session.execute(
                text(
                    "INSERT INTO feature_flags (tenant_id, flag_name, enabled) "
                    "VALUES (:tenant_id, 'enable_quotes', false)"
                ),
                {"tenant_id": tenant_id},
            )

        async for session in get_db_session():
            service = FeatureFlagsService(session, get_settings())
            flags = await service.resolve(tenant_id)

        facts = FactsSchema(
            tenant_id=tenant_id,
            session_id="s1",
            product_interest="switch",
            quantity=5,
            contact_email="buyer@example.com",
        )
        state = ConversationStateSchema(tenant_id=tenant_id, session_id="s1")
        intent_result = IntentResult(intent="quote_request", confidence=0.9, source="tier2")

        plan = TaskPlanner().build_plan(intent_result, facts, state, flags)

        assert "generate_quote" not in plan.steps
        assert "request_missing_slots" not in plan.steps
    finally:
        await _cleanup_rows(tenant_id)
