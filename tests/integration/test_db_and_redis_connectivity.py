"""Integration tests for database and Redis infrastructure."""

from __future__ import annotations

import uuid
from collections.abc import AsyncGenerator

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

from app.cache.redis_client import close_redis, get_redis, initialize_redis
from app.db.engine import dispose_database, get_db_session, initialize_database
from app.dependencies import get_settings
from app.main import create_app


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


async def _drop_table(table_name: str) -> None:
    async for session in get_db_session():
        await session.execute(text(f'DROP TABLE IF EXISTS "{table_name}"'))


async def _scratch_table() -> AsyncGenerator[str, None]:
    table_name = f"scratch_{uuid.uuid4().hex}"
    async for session in get_db_session():
        await session.execute(
            text(
                f"""
                CREATE TABLE "{table_name}" (
                    id INTEGER PRIMARY KEY,
                    tenant_id UUID NOT NULL,
                    value TEXT NOT NULL
                )
                """,
            ),
        )
    try:
        yield table_name
    finally:
        await _drop_table(table_name)


@pytest.fixture(autouse=True)
async def _infra_cleanup() -> AsyncGenerator[None, None]:
    yield
    await close_redis()
    await dispose_database()
    get_settings.cache_clear()


@pytest.mark.asyncio
async def test_db_session_commits_on_success() -> None:
    """A successful session dependency should commit writes."""
    await _check_db_available()
    settings = get_settings()
    async for table_name in _scratch_table():
        async for session in get_db_session():
            await session.execute(
                text(f'INSERT INTO "{table_name}" (id, tenant_id, value) VALUES (1, :tenant_id, :value)'),
                {"tenant_id": settings.db.default_tenant_id, "value": "committed"},
            )

        async for session in get_db_session():
            result = await session.execute(text(f'SELECT value FROM "{table_name}" WHERE id = 1'))
            assert result.scalar_one() == "committed"


@pytest.mark.asyncio
async def test_db_session_rolls_back_on_exception() -> None:
    """A failing session dependency should roll back pending writes."""
    await _check_db_available()
    settings = get_settings()
    async for table_name in _scratch_table():
        session_generator = get_db_session()
        session = await session_generator.__anext__()
        await session.execute(
            text(f'INSERT INTO "{table_name}" (id, tenant_id, value) VALUES (1, :tenant_id, :value)'),
            {"tenant_id": settings.db.default_tenant_id, "value": "rolled-back"},
        )
        with pytest.raises(RuntimeError):
            await session_generator.athrow(RuntimeError("force rollback"))

        async for verification_session in get_db_session():
            result = await verification_session.execute(text(f'SELECT COUNT(*) FROM "{table_name}"'))
            assert result.scalar_one() == 0


@pytest.mark.asyncio
async def test_redis_set_get_roundtrip() -> None:
    """Redis should round-trip string values through the shared client."""
    await _check_redis_available()
    redis = get_redis()
    key = f"test:{uuid.uuid4()}"

    await redis.set(key, "ok", ex=30)
    try:
        assert await redis.get(key) == "ok"
    finally:
        await redis.delete(key)


def test_health_db_and_redis_endpoints() -> None:
    """DB and Redis health endpoints should return readiness payloads."""
    get_settings.cache_clear()
    with TestClient(create_app(), raise_server_exceptions=False) as client:
        db_response = client.get("/health/db")
        redis_response = client.get("/health/redis")

    assert db_response.status_code == 200
    assert redis_response.status_code == 200
    assert db_response.json()["status"] in {"ok", "error"}
    assert redis_response.json()["status"] in {"ok", "error"}


@pytest.mark.asyncio
async def test_insert_without_tenant_id_raises_integrity_error() -> None:
    """TenantMixin-style NOT NULL tenant_id enforcement should reject omitted tenants."""
    await _check_db_available()
    async for table_name in _scratch_table():
        async for session in get_db_session():
            with pytest.raises(IntegrityError):
                await session.execute(
                    text(f'INSERT INTO "{table_name}" (id, value) VALUES (1, :value)'),
                    {"value": "missing tenant"},
                )
            await session.rollback()
