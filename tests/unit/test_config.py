"""Unit tests for application settings."""

from __future__ import annotations

from pathlib import Path

import pytest

from app.config import Settings
from app.exceptions import MissingConfigurationError


def _write_env(path: Path, *, omit: str | None = None) -> Path:
    values = {
        "SUPABASE_DB_URL": "postgresql+asyncpg://postgres:secret-db@test:6543/postgres",
        "DEFAULT_TENANT_ID": "00000000-0000-0000-0000-000000000001",
        "QDRANT_URL": "https://qdrant.example.com",
        "QDRANT_API_KEY": "qdrant-secret",
        "REDIS_URL": "redis://:redis-secret@localhost:6379/0",
        "OLLAMA_HOST": "http://localhost:11434",
        "OLLAMA_MODEL": "qwen2.5:3b",
        "EMBEDDING_MODEL": "BAAI/bge-m3",
        "RESEND_API_KEY": "resend-secret",
        "RESEND_FROM_EMAIL": "sales@example.com",
        "CRM_PROVIDER": "local",
        "CRM_API_BASE_URL": "http://crm.local",
        "CRM_API_KEY": "crm-secret",
        "SITE_API_KEY": "site-secret",
        "ENABLE_RAG": "true",
        "ENABLE_QUOTES": "true",
        "ENABLE_CRM": "true",
        "ENABLE_TICKETS": "true",
        "ENABLE_IMAGE_UPLOAD": "false",
        "ENABLE_LLM_CLARIFICATION_REWRITE": "false",
        "OLLAMA_TIMEOUT_SECONDS": "45",
        "CLASSIFICATION_CONFIDENCE_THRESHOLD": "0.8",
        "PROMPT_LIBRARY_PATH": "./prompts",
        "SECURITY_POLICY_DIR": "./policies",
        "CORS_ALLOW_ORIGINS": "http://localhost:5173,http://localhost:3000",
        "LOG_LEVEL": "DEBUG",
        "CONVERSATION_STATE_TTL_SECONDS": "900",
        "MAX_CLARIFICATION_ROUNDS": "3",
        "RAG_SEARCH_LIMIT_DEFAULT": "6",
        "RAG_SEARCH_LIMIT_MAX": "12",
        "CRM_MAX_RETRY_ATTEMPTS": "7",
        "CRM_RETRY_WORKER_INTERVAL_SECONDS": "30",
        "CHAT_RATE_LIMIT_PER_MINUTE": "25",
        "MAX_MESSAGE_LENGTH": "5000",
    }
    if omit:
        values.pop(omit)
    path.write_text("\n".join(f"{key}={value}" for key, value in values.items()), encoding="utf-8")
    return path


def test_settings_loads_from_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Settings should populate all grouped fields from a fixture env file."""
    monkeypatch.delenv("SITE_API_KEY", raising=False)
    env_file = _write_env(tmp_path / ".env")

    settings = Settings(_env_file=env_file)

    assert settings.db.default_tenant_id.hex == "00000000000000000000000000000001"
    assert settings.qdrant.url == "https://qdrant.example.com"
    assert settings.ollama.timeout_seconds == 45
    assert settings.site.cors_allow_origins == ["http://localhost:5173", "http://localhost:3000"]
    assert settings.router.classification_confidence_threshold == 0.8
    assert settings.session.conversation_state_ttl_seconds == 900
    assert settings.clarification.max_rounds == 3
    assert settings.rag.search_limit_max == 12
    assert settings.prompts.library_path == "./prompts"
    assert settings.tools.policy_directory == "./policies"
    assert settings.logging.log_level == "DEBUG"
    assert settings.flags.enable_rag is True


def test_settings_missing_required_var_raises(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """All missing required values should be reported together."""
    for key in ("CRM_API_KEY", "SITE_API_KEY"):
        monkeypatch.delenv(key, raising=False)
    env_file = _write_env(tmp_path / ".env", omit="CRM_API_KEY")

    with pytest.raises(MissingConfigurationError) as exc_info:
        Settings(_env_file=env_file)

    assert "CRM_API_KEY" in exc_info.value.missing_keys


def test_settings_redacts_secrets_in_repr(tmp_path: Path) -> None:
    """Raw secret values must not appear in string representations."""
    env_file = _write_env(tmp_path / ".env")

    settings = Settings(_env_file=env_file)
    rendered = str(settings)

    assert "secret-db" not in rendered
    assert "qdrant-secret" not in rendered
    assert "resend-secret" not in rendered
    assert "crm-secret" not in rendered
    assert "site-secret" not in rendered

