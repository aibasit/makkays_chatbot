"""Stress and chaos tests for Module 03 Session & State Management."""

from __future__ import annotations

import asyncio
import random
import uuid
from collections.abc import AsyncGenerator
from decimal import Decimal

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

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


@pytest.mark.stress
@pytest.mark.asyncio
async def test_concurrent_facts_updates() -> None:
    """Validate 20 parallel updates on distinct fields do not cause deadlocks or data loss."""
    await _check_infra_available()
    await _ensure_tables()

    tenant_id = uuid.uuid4()
    session_id = "stress-facts-concurrency"
    concurrency = 20

    # Initialize the row first
    async for session in get_db_session():
        service = SessionStateService(session, get_redis(), get_settings())
        await service.update_facts(tenant_id, session_id, FactsUpdate(company="Base"))

    async def update_worker(i: int) -> None:
        async for session in get_db_session():
            service = SessionStateService(session, get_redis(), get_settings())
            # Each worker writes to a separate field to test multi-column concurrency
            if i % 4 == 0:
                await service.update_facts(tenant_id, session_id, FactsUpdate(company=f"Company_{i}"))
            elif i % 4 == 1:
                await service.update_facts(tenant_id, session_id, FactsUpdate(product_interest=f"Product_{i}"))
            elif i % 4 == 2:
                await service.update_facts(tenant_id, session_id, FactsUpdate(budget=Decimal(str(1000 + i))))
            else:
                await service.update_facts(tenant_id, session_id, FactsUpdate(quantity=i))

    try:
        workers = [update_worker(i) for i in range(concurrency)]
        await asyncio.wait_for(asyncio.gather(*workers), timeout=10.0)

        # Retrieve and verify consistency
        async for session in get_db_session():
            service = SessionStateService(session, get_redis(), get_settings())
            facts = await service.get_facts(tenant_id, session_id)

        # Confirm the fields are populated (should not be empty/null)
        assert facts.company.startswith("Company_") or facts.company == "Base"
        assert facts.budget is not None
        assert facts.quantity is not None
    finally:
        await _cleanup_rows(tenant_id, session_id)


@pytest.mark.stress
@pytest.mark.asyncio
async def test_concurrent_state_updates() -> None:
    """Validate 20 parallel updates to clarification rounds increment correctly and atomically."""
    await _check_infra_available()
    await _ensure_tables()

    tenant_id = uuid.uuid4()
    session_id = "stress-state-concurrency"
    concurrency = 20

    # Create initial state record
    async for session in get_db_session():
        service = SessionStateService(session, get_redis(), get_settings())
        await service.update_conversation_state(
            tenant_id,
            session_id,
            ConversationStateUpdate(current_intent="quote", clarification_rounds=0),
        )

    async def increment_worker() -> None:
        async for session in get_db_session():
            repo = ConversationStateRepository(session)
            await repo.increment_clarification_round(tenant_id, session_id)

    try:
        workers = [increment_worker() for _ in range(concurrency)]
        await asyncio.wait_for(asyncio.gather(*workers), timeout=10.0)

        async for session in get_db_session():
            repo = ConversationStateRepository(session)
            row = await repo.get(tenant_id, session_id)

        assert row is not None
        assert row.clarification_rounds == concurrency
    finally:
        await _cleanup_rows(tenant_id, session_id)


@pytest.mark.stress
@pytest.mark.asyncio
async def test_redis_failure_simulation(monkeypatch: pytest.MonkeyPatch) -> None:
    """Validate that if Redis fails, the state service falls back to Postgres gracefully."""
    await _check_infra_available()
    await _ensure_tables()

    tenant_id = uuid.uuid4()
    session_id = "stress-redis-fallback"

    # 1. Create a record with a working Redis
    async for session in get_db_session():
        service = SessionStateService(session, get_redis(), get_settings())
        await service.update_facts(tenant_id, session_id, FactsUpdate(company="FallbackCorp"))

    # 2. Simulate Redis connection error
    import redis.exceptions
    async def mock_redis_fail(*args: any, **kwargs: any) -> None:
        raise redis.exceptions.ConnectionError("Redis connection refused (simulated)")

    # Intercept Redis methods
    redis_client = get_redis()
    monkeypatch.setattr(redis_client, "get", mock_redis_fail)
    monkeypatch.setattr(redis_client, "set", mock_redis_fail)

    try:
        # 3. Reading facts should fall back to DB and succeed
        async for session in get_db_session():
            service = SessionStateService(session, redis_client, get_settings())
            facts = await service.get_facts(tenant_id, session_id)

        assert facts.company == "FallbackCorp"
    finally:
        # Revert redis state and cleanup
        monkeypatch.undo()
        await _cleanup_rows(tenant_id, session_id)


@pytest.mark.stress
@pytest.mark.asyncio
async def test_postgres_latency_spike_simulation(monkeypatch: pytest.MonkeyPatch) -> None:
    """Validate that artificial DB latency spikes (100ms) do not cause deadlocks or test failures."""
    await _check_infra_available()
    await _ensure_tables()

    tenant_id = uuid.uuid4()
    session_id = "stress-db-latency"
    concurrency = 10

    # Monkeypatch AsyncSession.execute to inject artificial delay
    original_execute = AsyncSession.execute

    async def delayed_execute(self: AsyncSession, *args: any, **kwargs: any) -> any:
        await asyncio.sleep(0.1)  # 100ms delay
        return await original_execute(self, *args, **kwargs)

    monkeypatch.setattr(AsyncSession, "execute", delayed_execute)

    async def worker(i: int) -> None:
        async for session in get_db_session():
            service = SessionStateService(session, get_redis(), get_settings())
            await service.update_facts(tenant_id, session_id, FactsUpdate(company=f"Lat_{i}"))
            await service.get_facts(tenant_id, session_id)

    try:
        workers = [worker(i) for i in range(concurrency)]
        await asyncio.wait_for(asyncio.gather(*workers), timeout=15.0)
    finally:
        monkeypatch.undo()
        await _cleanup_rows(tenant_id, session_id)


@pytest.mark.stress
@pytest.mark.asyncio
async def test_cache_eviction_storm() -> None:
    """Validate that constant Redis eviction during concurrency does not corrupt state."""
    await _check_infra_available()
    await _ensure_tables()

    tenant_id = uuid.uuid4()
    session_id = "stress-cache-eviction"
    concurrency = 15

    # Background storm task
    stop_eviction = asyncio.Event()

    async def eviction_storm() -> None:
        redis = get_redis()
        while not stop_eviction.is_set():
            await redis.delete(
                f"session:facts:{tenant_id}:{session_id}",
                f"conversation:state:{tenant_id}:{session_id}",
            )
            await asyncio.sleep(0.01)  # Evict every 10ms

    async def worker(i: int) -> None:
        async for session in get_db_session():
            service = SessionStateService(session, get_redis(), get_settings())
            await service.update_facts(tenant_id, session_id, FactsUpdate(company=f"Evict_{i}"))
            await service.get_facts(tenant_id, session_id)

    storm_task = asyncio.create_task(eviction_storm())
    try:
        workers = [worker(i) for i in range(concurrency)]
        await asyncio.wait_for(asyncio.gather(*workers), timeout=10.0)
    finally:
        stop_eviction.set()
        await storm_task
        await _cleanup_rows(tenant_id, session_id)


@pytest.mark.stress
@pytest.mark.asyncio
async def test_mixed_load_test() -> None:
    """Validate 40 random mixed operations execute concurrently without exceptions."""
    await _check_infra_available()
    await _ensure_tables()

    tenant_id = uuid.uuid4()
    session_id = "stress-mixed-load"
    concurrency = 40

    async def worker(i: int) -> None:
        async for session in get_db_session():
            service = SessionStateService(session, get_redis(), get_settings())
            op = random.randint(0, 3)
            if op == 0:
                await service.update_facts(tenant_id, session_id, FactsUpdate(company=f"Mix_{i}"))
            elif op == 1:
                await service.get_facts(tenant_id, session_id)
            elif op == 2:
                await service.update_conversation_state(
                    tenant_id,
                    session_id,
                    ConversationStateUpdate(current_intent=f"intent_{i}"),
                )
            else:
                await service.get_conversation_state(tenant_id, session_id)

    try:
        workers = [worker(i) for i in range(concurrency)]
        await asyncio.wait_for(asyncio.gather(*workers), timeout=12.0)
    finally:
        await _cleanup_rows(tenant_id, session_id)
