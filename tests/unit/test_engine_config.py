"""Unit tests for Module 02 infrastructure configuration."""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy.orm import Mapped, mapped_column

from app.cache.redis_client import initialize_redis, validate_redis_url
from app.config import Settings
from app.db.base import Base, TenantMixin
from app.db.engine import create_engine, dispose_database, validate_asyncpg_url
from app.db.migrations import seed_local_dev
from tests.unit.test_config import _write_env


class TenantOnlyModel(TenantMixin, Base):
    """Minimal concrete model for TenantMixin assertions."""

    __tablename__ = "tenant_only_model"

    id: Mapped[int] = mapped_column(primary_key=True)


def test_engine_uses_asyncpg_scheme(tmp_path, monkeypatch) -> None:
    """Engine validation should require the asyncpg SQLAlchemy scheme even if config uses sync scheme."""
    env_file_async = _write_env(tmp_path / ".env.async")
    settings_async = Settings(_env_file=env_file_async)
    engine_async = create_engine(settings_async)
    assert str(engine_async.url).startswith("postgresql+asyncpg://")

    # Test with sync scheme in env
    env_lines = env_file_async.read_text(encoding="utf-8").split("\n")
    for idx, line in enumerate(env_lines):
        if line.startswith("SUPABASE_DB_URL="):
            env_lines[idx] = "SUPABASE_DB_URL=postgresql://postgres:secret-db@test:6543/postgres"
    env_file_sync = tmp_path / ".env.sync"
    env_file_sync.write_text("\n".join(env_lines), encoding="utf-8")

    settings_sync = Settings(_env_file=env_file_sync)
    engine_sync = create_engine(settings_sync)
    assert str(engine_sync.url).startswith("postgresql+asyncpg://")

    with pytest.raises(ValueError, match="postgresql\\+asyncpg"):
        validate_asyncpg_url("postgresql://user:password@localhost/db")


def test_redis_client_decode_responses_true(tmp_path) -> None:
    """Redis client must decode responses as str, not bytes."""
    env_file = _write_env(tmp_path / ".env")
    settings = Settings(_env_file=env_file)

    redis = initialize_redis(settings)

    assert redis.connection_pool.connection_kwargs["decode_responses"] is True
    validate_redis_url("redis://localhost:6379/0")
    with pytest.raises(ValueError, match="DB index"):
        validate_redis_url("redis://localhost:6379")


def test_tenant_mixin_column_not_nullable() -> None:
    """TenantMixin tenant_id must be indexed and non-nullable."""
    column = TenantOnlyModel.__table__.columns["tenant_id"]

    assert column.nullable is False
    assert column.default is None
    assert column.index is True
    assert column.type.as_uuid is True


def test_seed_local_dev_is_idempotent_and_uses_default_tenant_id() -> None:
    """Seed SQL should be idempotent and parameterized by DEFAULT_TENANT_ID."""
    assert "CREATE TABLE IF NOT EXISTS crm_leads" in seed_local_dev.CREATE_CRM_SCHEMA_SQL
    assert "CREATE INDEX IF NOT EXISTS idx_crm_leads_tenant_status" in (
        seed_local_dev.CREATE_CRM_SCHEMA_SQL
    )
    assert "WHERE NOT EXISTS" in seed_local_dev.INSERT_LOCAL_DEV_LEAD_SQL
    assert ":tenant_id" in seed_local_dev.INSERT_LOCAL_DEV_LEAD_SQL


@pytest.fixture(autouse=True)
async def _cleanup_engine() -> None:
    yield
    await dispose_database()
