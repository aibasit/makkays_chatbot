"""Integration tests for append-only conversation turn persistence."""

from __future__ import annotations

import asyncio
import uuid
from collections.abc import AsyncGenerator

import pytest
from sqlalchemy import text

from app.cache.redis_client import close_redis
from app.db.engine import (
    create_sessionmaker,
    dispose_database,
    get_db_session,
    get_engine,
    initialize_database,
)
from app.dependencies import get_settings
from app.turns.repository import TurnsRepository
from app.turns.service import TurnsService


async def _check_db_available() -> None:
    settings = get_settings()
    initialize_database(settings)
    try:
        async for session in get_db_session():
            await session.execute(text("SELECT 1"))
    except Exception as exc:
        pytest.skip(f"Configured database is not reachable: {exc}")


async def _ensure_turns_table() -> None:
    async for session in get_db_session():
        await session.execute(text("CREATE EXTENSION IF NOT EXISTS pgcrypto"))
        await session.execute(
            text(
                """
                CREATE TABLE IF NOT EXISTS conversation_turns (
                  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                  tenant_id UUID NOT NULL,
                  session_id TEXT NOT NULL,
                  turn_number INTEGER NOT NULL,
                  user_message TEXT NOT NULL,
                  assistant_message TEXT,
                  intent TEXT,
                  intent_confidence REAL,
                  intent_source TEXT,
                  candidate_intents TEXT[] DEFAULT '{}',
                  prompt_version JSONB,
                  tool_calls JSONB,
                  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
                )
                """,
            ),
        )
        await session.execute(
            text(
                """
                CREATE INDEX IF NOT EXISTS idx_conversation_turns_session
                ON conversation_turns (tenant_id, session_id, turn_number)
                """,
            ),
        )
        await session.execute(
            text(
                """
                CREATE UNIQUE INDEX IF NOT EXISTS uidx_turns_session_number
                ON conversation_turns (tenant_id, session_id, turn_number)
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
            text(
                "DELETE FROM conversation_turns WHERE tenant_id = :tenant_id AND session_id = :session_id"
            ),
            {"tenant_id": tenant_id, "session_id": session_id},
        )


@pytest.mark.asyncio
async def test_record_turn_inserts_row_with_correct_turn_number() -> None:
    await _check_db_available()
    await _ensure_turns_table()
    tenant_id = uuid.uuid4()
    session_id = "module04-insert"
    try:
        async for session in get_db_session():
            service = TurnsService(session)
            await service.record_turn(
                tenant_id,
                session_id,
                None,
                "Do you have a Cisco switch?",
                "Yes.",
                {"intent": "sales_inquiry", "confidence": 0.92, "source": "tier1"},
                {"system": "base_v1"},
                [{"tool": "retrieve_products", "args": {"q": "Cisco switch"}}],
            )

        async for session in get_db_session():
            result = await session.execute(
                text(
                    """
                    SELECT turn_number, user_message, assistant_message, intent, intent_confidence
                    FROM conversation_turns
                    WHERE tenant_id = :tenant_id AND session_id = :session_id
                    """,
                ),
                {"tenant_id": tenant_id, "session_id": session_id},
            )
            row = result.one()

        assert row.turn_number == 1
        assert row.user_message == "Do you have a Cisco switch?"
        assert row.assistant_message == "Yes."
        assert row.intent == "sales_inquiry"
        assert row.intent_confidence == pytest.approx(0.92)
    finally:
        await _cleanup_rows(tenant_id, session_id)


@pytest.mark.asyncio
async def test_record_turn_sequential_numbering_per_session() -> None:
    await _check_db_available()
    await _ensure_turns_table()
    tenant_id = uuid.uuid4()
    session_id = "module04-sequential"
    try:
        async for session in get_db_session():
            service = TurnsService(session)
            await service.record_turn(tenant_id, session_id, None, "First", "A")
            await service.record_turn(tenant_id, session_id, None, "Second", "B")

        async for session in get_db_session():
            service = TurnsService(session)
            recent = await service.get_recent_turns(tenant_id, session_id, limit=8)

        assert [turn.turn_number for turn in recent] == [1, 2]
        assert [turn.user_message for turn in recent] == ["First", "Second"]
    finally:
        await _cleanup_rows(tenant_id, session_id)


@pytest.mark.asyncio
async def test_record_turn_failure_does_not_raise() -> None:
    class FailingRepository:
        async def get_next_turn_number(self, tenant_id: uuid.UUID, session_id: str) -> int:
            return 1

        async def create(self, turn: object) -> object:
            raise RuntimeError("database unavailable")

    class FakeSession:
        async def rollback(self) -> None:
            return None

    service = TurnsService(FakeSession())  # type: ignore[arg-type]
    service.repository = FailingRepository()  # type: ignore[assignment]

    await service.record_turn(uuid.uuid4(), "s1", None, "Still answer the user", "Done")


@pytest.mark.asyncio
async def test_concurrent_turns_for_same_session_have_unique_turn_numbers() -> None:
    await _check_db_available()
    await _ensure_turns_table()
    tenant_id = uuid.uuid4()
    session_id = "module04-concurrent"
    engine = get_engine()
    sessionmaker = create_sessionmaker(engine)

    async def record(message: str) -> None:
        async with sessionmaker() as session:
            async with session.begin():
                service = TurnsService(session)
                await service.record_turn(tenant_id, session_id, None, message, "ok")

    try:
        await asyncio.gather(record("First concurrent"), record("Second concurrent"))

        async for session in get_db_session():
            repo = TurnsRepository(session)
            rows = await repo.get_recent_turns(tenant_id, session_id, limit=8)

        assert sorted(row.turn_number for row in rows) == [1, 2]
        assert len({row.turn_number for row in rows}) == 2
    finally:
        await _cleanup_rows(tenant_id, session_id)
