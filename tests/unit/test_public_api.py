"""Unit tests for Module 15 public chat API helpers."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
import pytest
from fastapi import HTTPException, Response

from app.api.chat import check_site_api_key, enforce_chat_rate_limit, get_or_create_session_id
from app.config import Settings


class FakeRedis:
    def __init__(self) -> None:
        self.counts: dict[str, int] = {}
        self.expired: list[tuple[str, int]] = []

    async def incr(self, key: str) -> int:
        self.counts[key] = self.counts.get(key, 0) + 1
        return self.counts[key]

    async def expire(self, key: str, seconds: int) -> None:
        self.expired.append((key, seconds))


def _settings(tmp_path: Path) -> Settings:
    values = {
        "SUPABASE_DB_URL": "postgresql+asyncpg://postgres:secret@test:6543/postgres",
        "DEFAULT_TENANT_ID": "00000000-0000-0000-0000-000000000001",
        "QDRANT_URL": "https://qdrant.example.com",
        "QDRANT_API_KEY": "qdrant-secret",
        "REDIS_URL": "redis://localhost:6379/0",
        "OLLAMA_HOST": "http://localhost:11434",
        "OLLAMA_MODEL": "qwen2.5:3b",
        "LLM_PROVIDER": "groq",
        "GROQ_API_KEY": "groq-secret",
        "EMBEDDING_MODEL": "BAAI/bge-m3",
        "RESEND_API_KEY": "test-resend-secret",
        "RESEND_FROM_EMAIL": "sales@example.com",
        "CRM_API_BASE_URL": "http://crm.local",
        "CRM_API_KEY": "crm-secret",
        "SITE_API_KEY": "site-secret",
        "CHAT_RATE_LIMIT_PER_MINUTE": "2",
    }
    env_path = tmp_path / ".env"
    env_path.write_text("\n".join(f"{key}={value}" for key, value in values.items()), encoding="utf-8")
    return Settings(_env_file=env_path)


def test_site_api_key_check_accepts_only_exact_secret(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    expected = settings.site.site_api_key.get_secret_value()

    check_site_api_key(expected, settings)

    with pytest.raises(HTTPException) as exc_info:
        check_site_api_key("wrong", settings)
    assert exc_info.value.status_code == 401


def test_session_cookie_is_reused_or_created(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    response = Response()
    request = SimpleNamespace(cookies={})

    session_id = get_or_create_session_id(request, response, settings)  # type: ignore[arg-type]

    assert session_id
    assert settings.site.session_cookie_name in response.headers["set-cookie"]
    reused = get_or_create_session_id(
        SimpleNamespace(cookies={settings.site.session_cookie_name: "existing"}),
        Response(),
        settings,
    )
    assert reused == "existing"


@pytest.mark.asyncio
async def test_chat_rate_limit_uses_redis_counter(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    redis = FakeRedis()

    await enforce_chat_rate_limit(redis, "site-secret", settings)  # type: ignore[arg-type]
    await enforce_chat_rate_limit(redis, "site-secret", settings)  # type: ignore[arg-type]

    with pytest.raises(HTTPException) as exc_info:
        await enforce_chat_rate_limit(redis, "site-secret", settings)  # type: ignore[arg-type]
    assert exc_info.value.status_code == 429
    assert redis.expired[0][1] == 60
