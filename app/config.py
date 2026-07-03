"""Typed application configuration loaded from environment variables."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any
from uuid import UUID

from dotenv import dotenv_values
from pydantic import BaseModel, Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from app.exceptions import MissingConfigurationError

SENSITIVE_KEY_PARTS = ("PASSWORD", "SECRET", "TOKEN", "API_KEY", "KEY")

REQUIRED_ENV_VARS: tuple[str, ...] = (
    "SUPABASE_DB_URL",
    "DEFAULT_TENANT_ID",
    "QDRANT_URL",
    "QDRANT_API_KEY",
    "REDIS_URL",
    "OLLAMA_HOST",
    "OLLAMA_MODEL",
    "EMBEDDING_MODEL",
    "RESEND_API_KEY",
    "RESEND_FROM_EMAIL",
    "CRM_API_BASE_URL",
    "CRM_API_KEY",
    "SITE_API_KEY",
)


def _is_sensitive_name(name: str) -> bool:
    return any(part in name.upper() for part in SENSITIVE_KEY_PARTS)


def _redact_value(field_name: str, value: Any) -> Any:
    if isinstance(value, SecretStr):
        return "***REDACTED***"
    if _is_sensitive_name(field_name):
        return "***REDACTED***"
    if isinstance(value, RedactedModel):
        return value.redacted_dict()
    if isinstance(value, list):
        return [_redact_value(field_name, item) for item in value]
    return value


def _split_csv(value: str | list[str]) -> list[str]:
    if isinstance(value, list):
        return value
    return [item.strip() for item in value.split(",") if item.strip()]


class RedactedModel(BaseModel):
    """Base model whose string representation never exposes secret values."""

    model_config = {"frozen": True}

    def redacted_dict(self) -> dict[str, Any]:
        """Return model data with sensitive fields redacted."""
        return {
            name: _redact_value(name, getattr(self, name))
            for name in type(self).model_fields
        }

    def __repr__(self) -> str:
        return f"{self.__class__.__name__}({self.redacted_dict()!r})"

    def __str__(self) -> str:
        return repr(self)


class DbSettings(RedactedModel):
    """Database configuration."""

    supabase_db_url: SecretStr
    default_tenant_id: UUID


class RedisSettings(RedactedModel):
    """Redis configuration."""

    redis_url: SecretStr


class QdrantSettings(RedactedModel):
    """Qdrant vector store configuration."""

    url: str
    api_key: SecretStr


class OllamaSettings(RedactedModel):
    """Ollama LLM runtime configuration."""

    host: str
    model: str
    timeout_seconds: int = 30


class EmbeddingSettings(RedactedModel):
    """Embedding model configuration."""

    model_name: str


class ResendSettings(RedactedModel):
    """Resend email configuration."""

    api_key: SecretStr
    from_email: str


class CrmSettings(RedactedModel):
    """CRM integration configuration."""

    provider: str = "local"
    base_url: str
    api_key: SecretStr
    max_retry_attempts: int = 5
    retry_worker_interval_seconds: int = 60


class SiteSettings(RedactedModel):
    """Public widget and site configuration."""

    site_api_key: SecretStr
    cors_allow_origins: list[str] = Field(default_factory=lambda: ["http://localhost:5173"])
    session_cookie_name: str = "sales_engineer_session_id"
    chat_rate_limit_per_minute: int = 20
    max_message_length: int = 4000

    @field_validator("cors_allow_origins", mode="before")
    @classmethod
    def parse_cors_origins(cls, value: str | list[str]) -> list[str]:
        """Parse comma-separated CORS origins from the environment."""
        return _split_csv(value)


class RouterSettings(RedactedModel):
    """Intent router configuration."""

    classification_confidence_threshold: float = 0.70


class SessionSettings(RedactedModel):
    """Conversation session configuration."""

    conversation_state_ttl_seconds: int = 1800


class ClarificationSettings(RedactedModel):
    """Clarification flow configuration."""

    max_rounds: int = 2


class RagSettings(RedactedModel):
    """RAG retrieval configuration."""

    search_limit_default: int = 5
    search_limit_max: int = 10


class PromptSettings(RedactedModel):
    """Prompt library configuration."""

    library_path: str = "./prompt_library"


class ToolSettings(RedactedModel):
    """Tool policy configuration."""

    policy_directory: str = "./security_policies"


class LoggingSettings(RedactedModel):
    """Logging configuration."""

    log_level: str = "INFO"


class FeatureFlagDefaults(RedactedModel):
    """Default feature-flag values loaded at startup."""

    enable_rag: bool = True
    enable_quotes: bool = True
    enable_crm: bool = True
    enable_tickets: bool = True
    enable_image_upload: bool = False
    enable_llm_clarification_rewrite: bool = False

    def active_flags(self) -> list[str]:
        """Return names of enabled feature flags."""
        return [name for name in type(self).model_fields if bool(getattr(self, name))]


class _FlatSettings(BaseSettings):
    """Flat env-var schema used to construct grouped Settings."""

    model_config = SettingsConfigDict(env_file=".env", case_sensitive=False, extra="ignore")

    supabase_db_url: SecretStr = Field(validation_alias="SUPABASE_DB_URL")
    default_tenant_id: UUID = Field(validation_alias="DEFAULT_TENANT_ID")
    qdrant_url: str = Field(validation_alias="QDRANT_URL")
    qdrant_api_key: SecretStr = Field(validation_alias="QDRANT_API_KEY")
    redis_url: SecretStr = Field(validation_alias="REDIS_URL")
    ollama_host: str = Field(validation_alias="OLLAMA_HOST")
    ollama_model: str = Field(validation_alias="OLLAMA_MODEL")
    embedding_model: str = Field(validation_alias="EMBEDDING_MODEL")
    resend_api_key: SecretStr = Field(validation_alias="RESEND_API_KEY")
    resend_from_email: str = Field(validation_alias="RESEND_FROM_EMAIL")
    crm_provider: str = Field(default="local", validation_alias="CRM_PROVIDER")
    crm_api_base_url: str = Field(validation_alias="CRM_API_BASE_URL")
    crm_api_key: SecretStr = Field(validation_alias="CRM_API_KEY")
    site_api_key: SecretStr = Field(validation_alias="SITE_API_KEY")
    enable_rag: bool = Field(default=True, validation_alias="ENABLE_RAG")
    enable_quotes: bool = Field(default=True, validation_alias="ENABLE_QUOTES")
    enable_crm: bool = Field(default=True, validation_alias="ENABLE_CRM")
    enable_tickets: bool = Field(default=True, validation_alias="ENABLE_TICKETS")
    enable_image_upload: bool = Field(default=False, validation_alias="ENABLE_IMAGE_UPLOAD")
    enable_llm_clarification_rewrite: bool = Field(
        default=False,
        validation_alias="ENABLE_LLM_CLARIFICATION_REWRITE",
    )
    ollama_timeout_seconds: int = Field(default=30, validation_alias="OLLAMA_TIMEOUT_SECONDS")
    classification_confidence_threshold: float = Field(
        default=0.70,
        validation_alias="CLASSIFICATION_CONFIDENCE_THRESHOLD",
    )
    prompt_library_path: str = Field(default="./prompt_library", validation_alias="PROMPT_LIBRARY_PATH")
    security_policy_dir: str = Field(default="./security_policies", validation_alias="SECURITY_POLICY_DIR")
    cors_allow_origins: str = Field(
        default="http://localhost:5173",
        validation_alias="CORS_ALLOW_ORIGINS",
    )
    log_level: str = Field(default="INFO", validation_alias="LOG_LEVEL")
    conversation_state_ttl_seconds: int = Field(
        default=1800,
        validation_alias="CONVERSATION_STATE_TTL_SECONDS",
    )
    max_clarification_rounds: int = Field(default=2, validation_alias="MAX_CLARIFICATION_ROUNDS")
    rag_search_limit_default: int = Field(default=5, validation_alias="RAG_SEARCH_LIMIT_DEFAULT")
    rag_search_limit_max: int = Field(default=10, validation_alias="RAG_SEARCH_LIMIT_MAX")
    crm_max_retry_attempts: int = Field(default=5, validation_alias="CRM_MAX_RETRY_ATTEMPTS")
    crm_retry_worker_interval_seconds: int = Field(
        default=60,
        validation_alias="CRM_RETRY_WORKER_INTERVAL_SECONDS",
    )
    chat_rate_limit_per_minute: int = Field(default=20, validation_alias="CHAT_RATE_LIMIT_PER_MINUTE")
    max_message_length: int = Field(default=4000, validation_alias="MAX_MESSAGE_LENGTH")


class Settings(BaseSettings):
    """Application settings grouped by subsystem."""

    model_config = SettingsConfigDict(env_file=".env", case_sensitive=False, extra="ignore")

    db: DbSettings
    redis: RedisSettings
    qdrant: QdrantSettings
    ollama: OllamaSettings
    embedding: EmbeddingSettings
    resend: ResendSettings
    crm: CrmSettings
    site: SiteSettings
    router: RouterSettings
    session: SessionSettings
    clarification: ClarificationSettings
    rag: RagSettings
    prompts: PromptSettings
    tools: ToolSettings
    logging: LoggingSettings
    flags: FeatureFlagDefaults

    def __init__(self, **values: Any) -> None:
        env_file = values.pop("_env_file", ".env")
        if values:
            super().__init__(**values)
            return

        _raise_for_missing_required_env(env_file)
        flat = _FlatSettings(_env_file=env_file)
        super().__init__(
            db=DbSettings(
                supabase_db_url=flat.supabase_db_url,
                default_tenant_id=flat.default_tenant_id,
            ),
            redis=RedisSettings(redis_url=flat.redis_url),
            qdrant=QdrantSettings(url=flat.qdrant_url, api_key=flat.qdrant_api_key),
            ollama=OllamaSettings(
                host=flat.ollama_host,
                model=flat.ollama_model,
                timeout_seconds=flat.ollama_timeout_seconds,
            ),
            embedding=EmbeddingSettings(model_name=flat.embedding_model),
            resend=ResendSettings(api_key=flat.resend_api_key, from_email=flat.resend_from_email),
            crm=CrmSettings(
                provider=flat.crm_provider,
                base_url=flat.crm_api_base_url,
                api_key=flat.crm_api_key,
                max_retry_attempts=flat.crm_max_retry_attempts,
                retry_worker_interval_seconds=flat.crm_retry_worker_interval_seconds,
            ),
            site=SiteSettings(
                site_api_key=flat.site_api_key,
                cors_allow_origins=_split_csv(flat.cors_allow_origins),
                chat_rate_limit_per_minute=flat.chat_rate_limit_per_minute,
                max_message_length=flat.max_message_length,
            ),
            router=RouterSettings(
                classification_confidence_threshold=flat.classification_confidence_threshold,
            ),
            session=SessionSettings(
                conversation_state_ttl_seconds=flat.conversation_state_ttl_seconds,
            ),
            clarification=ClarificationSettings(max_rounds=flat.max_clarification_rounds),
            rag=RagSettings(
                search_limit_default=flat.rag_search_limit_default,
                search_limit_max=flat.rag_search_limit_max,
            ),
            prompts=PromptSettings(library_path=flat.prompt_library_path),
            tools=ToolSettings(policy_directory=flat.security_policy_dir),
            logging=LoggingSettings(log_level=flat.log_level),
            flags=FeatureFlagDefaults(
                enable_rag=flat.enable_rag,
                enable_quotes=flat.enable_quotes,
                enable_crm=flat.enable_crm,
                enable_tickets=flat.enable_tickets,
                enable_image_upload=flat.enable_image_upload,
                enable_llm_clarification_rewrite=flat.enable_llm_clarification_rewrite,
            ),
        )

    def redacted_dict(self) -> dict[str, Any]:
        """Return grouped settings with sensitive values redacted."""
        return {
            name: _redact_value(name, getattr(self, name))
            for name in type(self).model_fields
        }

    def __repr__(self) -> str:
        return f"{self.__class__.__name__}({self.redacted_dict()!r})"

    def __str__(self) -> str:
        return repr(self)


def _raise_for_missing_required_env(env_file: str | os.PathLike[str] | None) -> None:
    file_values: dict[str, str | None] = {}
    if env_file is not None:
        env_path = Path(env_file)
        if env_path.exists():
            file_values = dict(dotenv_values(env_path))

    missing_keys: list[str] = []
    for key in REQUIRED_ENV_VARS:
        value = os.environ.get(key, file_values.get(key))
        if value is None or str(value).strip() == "":
            missing_keys.append(key)

    if missing_keys:
        raise MissingConfigurationError(missing_keys)
