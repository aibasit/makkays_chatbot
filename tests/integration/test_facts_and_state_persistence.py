"""Integration tests for Module 03 Postgres and Redis persistence."""

from __future__ import annotations

import uuid
from collections.abc import AsyncGenerator
from decimal import Decimal

import pytest
from sqlalchemy import text

from app.cache.redis_client import close_redis, get_redis, initialize_redis
from app.db.engine import dispose_database, get_db_session, initialize_database
from app.dependencies import get_settings
from app.session.repository import ConversationStateRepository
from app.session.schemas import ConversationStateUpdate, FactsUpdate
from app.session.service import SessionStateService


async def _check_infra_available() -> None:
    settings = get_settings()
    initialize_database(settings)
    redis = initialize_redis(settings)
    try:
        async for session in get_db_session():
            await session.execute(text("SELECT 1"))
        await redis.ping()
    except Exception as exc:
        raise RuntimeError(f"Configured Postgres/Redis is not reachable: {exc}. Ensure Docker Compose stack is running.") from exc


async def _ensure_tables() -> None:
    async for session in get_db_session():
        await session.execute(
            text(
                """
                CREATE TABLE IF NOT EXISTS session_facts (
                  tenant_id UUID NOT NULL,
                  session_id TEXT NOT NULL,
                  budget NUMERIC,
                  company TEXT,
                  industry TEXT,
                  product_interest TEXT,
                  project_size TEXT,
                  quantity INTEGER,
                  contact_name TEXT,
                  contact_email TEXT,
                  contact_phone TEXT,
                  updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
                  PRIMARY KEY (tenant_id, session_id)
                )
                """,
            ),
        )
        await session.execute(
            text(
                """
                CREATE TABLE IF NOT EXISTS conversation_state (
                  tenant_id UUID NOT NULL,
                  session_id TEXT NOT NULL,
                  current_intent TEXT,
                  intent_confidence REAL,
                  awaiting_clarification BOOLEAN NOT NULL DEFAULT false,
                  clarification_candidates TEXT[] NOT NULL DEFAULT '{}',
                  clarification_rounds INTEGER NOT NULL DEFAULT 0,
                  current_plan JSONB,
                  current_plan_step INTEGER,
                  last_question TEXT,
                  spec_question_detected BOOLEAN NOT NULL DEFAULT false,
                  contact_info_captured BOOLEAN NOT NULL DEFAULT false,
                  updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
                  PRIMARY KEY (tenant_id, session_id)
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


async def _cleanup_rows(tenant_id: uuid.UUID, session_id: str) -> None:
    async for session in get_db_session():
        await session.execute(
            text("DELETE FROM conversation_state WHERE tenant_id = :tenant_id AND session_id = :session_id"),
            {"tenant_id": tenant_id, "session_id": session_id},
        )
        await session.execute(
            text("DELETE FROM session_facts WHERE tenant_id = :tenant_id AND session_id = :session_id"),
            {"tenant_id": tenant_id, "session_id": session_id},
        )
    redis = get_redis()
    await redis.delete(
        f"session:facts:{tenant_id}:{session_id}",
        f"conversation:state:{tenant_id}:{session_id}",
    )


@pytest.mark.asyncio
async def test_facts_survive_conversation_state_redis_eviction() -> None:
    await _check_infra_available()
    await _ensure_tables()
    tenant_id = uuid.uuid4()
    session_id = "module03-facts-survive"
    try:
        async for session in get_db_session():
            service = SessionStateService(session, get_redis(), get_settings())
            await service.update_facts(tenant_id, session_id, FactsUpdate(company="Makkays", budget=Decimal("50000")))
            await service.update_conversation_state(
                tenant_id,
                session_id,
                ConversationStateUpdate(current_intent="quote", awaiting_clarification=True),
            )

        redis = get_redis()
        await redis.delete(f"conversation:state:{tenant_id}:{session_id}")

        async for session in get_db_session():
            service = SessionStateService(session, redis, get_settings())
            facts = await service.get_facts(tenant_id, session_id)
            state = await service.get_conversation_state(tenant_id, session_id)

        assert facts.company == "Makkays"
        assert facts.budget == Decimal("50000")
        assert state.current_intent == "quote"
    finally:
        await _cleanup_rows(tenant_id, session_id)


@pytest.mark.asyncio
async def test_conversation_state_recovers_from_sql_after_cache_eviction() -> None:
    await _check_infra_available()
    await _ensure_tables()
    tenant_id = uuid.uuid4()
    session_id = "module03-state-recovery"
    try:
        async for session in get_db_session():
            service = SessionStateService(session, get_redis(), get_settings())
            await service.update_conversation_state(
                tenant_id,
                session_id,
                ConversationStateUpdate(
                    current_intent="support",
                    clarification_candidates=["warranty", "availability"],
                ),
            )

        redis = get_redis()
        await redis.delete(f"conversation:state:{tenant_id}:{session_id}")

        async for session in get_db_session():
            service = SessionStateService(session, redis, get_settings())
            state = await service.get_conversation_state(tenant_id, session_id)

        assert state.current_intent == "support"
        assert state.clarification_candidates == ["warranty", "availability"]
        assert await redis.get(f"conversation:state:{tenant_id}:{session_id}") is not None
    finally:
        await _cleanup_rows(tenant_id, session_id)


@pytest.mark.asyncio
async def test_clarification_round_increment_persists() -> None:
    await _check_infra_available()
    await _ensure_tables()
    tenant_id = uuid.uuid4()
    session_id = "module03-atomic-increment"
    try:
        async for session in get_db_session():
            service = SessionStateService(session, get_redis(), get_settings())
            await service.update_conversation_state(
                tenant_id,
                session_id,
                ConversationStateUpdate(current_intent="quote", clarification_rounds=0),
            )
            repo = ConversationStateRepository(session)
            assert await repo.increment_clarification_round(tenant_id, session_id) == 1
            assert await repo.increment_clarification_round(tenant_id, session_id) == 2

        async for session in get_db_session():
            repo = ConversationStateRepository(session)
            row = await repo.get(tenant_id, session_id)

        assert row is not None
        assert row.clarification_rounds == 2
    finally:
        await _cleanup_rows(tenant_id, session_id)
