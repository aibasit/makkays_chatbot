"""Typed application configuration loaded from environment variables."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Literal
from urllib.parse import urlparse
from uuid import UUID

from dotenv import dotenv_values
from pydantic import BaseModel, Field, SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from app.exceptions import MissingConfigurationError

SENSITIVE_KEY_PARTS = ("PASSWORD", "SECRET", "TOKEN", "API_KEY", "KEY")

BASE_INTENT_TAXONOMY: tuple[str, ...] = (
    "sales_inquiry",
    "quote_request",
    "technical_support",
    "escalation_request",
    "out_of_scope",
)

V42_INTENT_TAXONOMY: tuple[str, ...] = (
    "product_comparison",
    "product_compatibility",
    "accessory_recommendation",
    "product_finder_by_problem",
    "product_alternative",
    "specification_explainer",
    "product_recommendation_wizard",
    "use_case_recommendation",
    "installation_guidance",
    "troubleshooting",
    "warranty_information",
    "pdf_documentation_search",
    "availability_inquiry",
    "solution_builder",
    "human_handoff",
)

INTENT_TAXONOMY: tuple[str, ...] = BASE_INTENT_TAXONOMY + V42_INTENT_TAXONOMY

REQUIRED_ENV_VARS: tuple[str, ...] = (
    "SUPABASE_DB_URL",
    "DEFAULT_TENANT_ID",
    "QDRANT_URL",
    "QDRANT_API_KEY",
    "REDIS_URL",
    "OLLAMA_HOST",
    "OLLAMA_MODEL",
    "GROQ_API_KEY",
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
        return {name: _redact_value(name, getattr(self, name)) for name in type(self).model_fields}

    def __repr__(self) -> str:
        return f"{self.__class__.__name__}({self.redacted_dict()!r})"

    def __str__(self) -> str:
        return repr(self)


class DbSettings(RedactedModel):
    """Database configuration."""

    supabase_db_url: SecretStr
    default_tenant_id: UUID
    supabase_db_url_async: SecretStr
    supabase_db_url_sync: SecretStr

    @model_validator(mode="before")
    @classmethod
    def populate_urls(cls, data: Any) -> Any:
        """Automatically populate async and sync URL fields based on supabase_db_url."""
        if isinstance(data, dict):
            db_url = data.get("supabase_db_url")
            if db_url is not None:
                raw_url = (
                    db_url.get_secret_value()
                    if hasattr(db_url, "get_secret_value")
                    else str(db_url)
                )
                if raw_url.startswith("postgresql+asyncpg://"):
                    async_url = raw_url
                    sync_url = raw_url.replace("postgresql+asyncpg://", "postgresql://", 1)
                elif raw_url.startswith("postgresql://"):
                    sync_url = raw_url
                    async_url = raw_url.replace("postgresql://", "postgresql+asyncpg://", 1)
                else:
                    raise ValueError(
                        "SUPABASE_DB_URL must use postgresql:// or postgresql+asyncpg:// scheme"
                    )

                data.setdefault("supabase_db_url_async", async_url)
                data.setdefault("supabase_db_url_sync", sync_url)
        return data

    @field_validator("supabase_db_url")
    @classmethod
    def validate_supabase_db_url(cls, value: SecretStr) -> SecretStr:
        """Ensure the database URL uses either postgresql:// or postgresql+asyncpg:// scheme."""
        raw_url = value.get_secret_value()
        if not (raw_url.startswith("postgresql://") or raw_url.startswith("postgresql+asyncpg://")):
            raise ValueError(
                "SUPABASE_DB_URL must use postgresql:// or postgresql+asyncpg:// scheme"
            )
        return value

    @field_validator("supabase_db_url_async")
    @classmethod
    def validate_supabase_db_url_async(cls, value: SecretStr) -> SecretStr:
        """Ensure the async database URL uses postgresql+asyncpg:// scheme."""
        if not value.get_secret_value().startswith("postgresql+asyncpg://"):
            raise ValueError("supabase_db_url_async must use the postgresql+asyncpg:// scheme")
        return value

    @field_validator("supabase_db_url_sync")
    @classmethod
    def validate_supabase_db_url_sync(cls, value: SecretStr) -> SecretStr:
        """Ensure the sync database URL uses postgresql:// scheme."""
        if not value.get_secret_value().startswith("postgresql://"):
            raise ValueError("supabase_db_url_sync must use the postgresql:// scheme")
        return value


class RedisSettings(RedactedModel):
    """Redis configuration."""

    redis_url: SecretStr

    @field_validator("redis_url")
    @classmethod
    def validate_redis_url(cls, value: SecretStr) -> SecretStr:
        """Ensure Redis URL includes an explicit database index."""
        parsed = urlparse(value.get_secret_value())
        if parsed.scheme not in {"redis", "rediss"}:
            raise ValueError("REDIS_URL must use redis:// or rediss://")
        if not parsed.path or parsed.path == "/" or not parsed.path.lstrip("/").isdigit():
            raise ValueError("REDIS_URL must include an explicit numeric DB index such as /0")
        return value


class QdrantSettings(RedactedModel):
    """Qdrant vector store configuration."""

    url: str
    api_key: SecretStr


class OllamaSettings(RedactedModel):
    """Ollama LLM runtime configuration."""

    host: str
    model: str
    timeout_seconds: float = 30.0
    default_temperature: float = 0.0


class GroqSettings(RedactedModel):
    """Groq Cloud LLM configuration."""

    api_key: SecretStr
    model: str = "llama-3.3-70b-versatile"
    base_url: str = "https://api.groq.com/openai/v1"
    timeout_seconds: float = 30.0
    default_temperature: float = 0.0


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
    intent_taxonomy: tuple[str, ...] = INTENT_TAXONOMY


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
    qdrant_collection_products: str = "products_v1"
    qdrant_collection_documents: str = "documents_v1"


class SolutionBuilderSettings(RedactedModel):
    """Solution Builder wizard scale-classification thresholds."""

    large_device_threshold: int = 500
    enterprise_device_threshold: int = 1000


class LanguageSettings(RedactedModel):
    """Multi-language detection and translation configuration."""

    default_language: str = "en"
    supported_languages: list[str] = Field(default_factory=lambda: ["en", "ur", "ar"])
    translation_prompt_template: str = "translation/translate_response_v1.md"


class AvailabilitySettings(RedactedModel):
    """Availability/ERP provider configuration."""

    provider: Literal["local", "erp"] = "local"
    erp_api_base_url: str = ""
    erp_api_key: SecretStr = SecretStr("")


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
    """Default feature-flag values loaded at startup (env-driven; Module 09 owns DB overrides)."""

    # v4.1
    enable_rag: bool = True
    enable_quotes: bool = True
    enable_crm: bool = True
    enable_tickets: bool = True
    enable_image_upload: bool = False
    enable_llm_clarification_rewrite: bool = False
    # v4.2 — Product Intelligence
    enable_product_comparison: bool = True
    enable_compatibility_check: bool = True
    enable_accessory_recommendation: bool = True
    enable_pdf_search: bool = True
    # v4.2 — Solution & Wizard
    enable_solution_builder: bool = True
    enable_wizard: bool = True
    enable_use_case_recommendation: bool = True
    # v4.2 — Transactional & Ops
    enable_human_handoff: bool = True
    enable_availability_check: bool = False
    enable_multi_language: bool = False
    # v4.2 — Future Extension Stubs (always False, enforced again by FeatureFlagsService)
    enable_voice_chat: bool = False
    enable_image_understanding: bool = False

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
    ollama_default_temperature: float = Field(
        default=0.0,
        validation_alias="OLLAMA_DEFAULT_TEMPERATURE",
    )
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
    enable_product_comparison: bool = Field(default=True, validation_alias="ENABLE_PRODUCT_COMPARISON")
    enable_compatibility_check: bool = Field(default=True, validation_alias="ENABLE_COMPATIBILITY_CHECK")
    enable_accessory_recommendation: bool = Field(
        default=True, validation_alias="ENABLE_ACCESSORY_RECOMMENDATION"
    )
    enable_pdf_search: bool = Field(default=True, validation_alias="ENABLE_PDF_SEARCH")
    enable_solution_builder: bool = Field(default=True, validation_alias="ENABLE_SOLUTION_BUILDER")
    enable_wizard: bool = Field(default=True, validation_alias="ENABLE_WIZARD")
    enable_use_case_recommendation: bool = Field(
        default=True, validation_alias="ENABLE_USE_CASE_RECOMMENDATION"
    )
    enable_human_handoff: bool = Field(default=True, validation_alias="ENABLE_HUMAN_HANDOFF")
    enable_availability_check: bool = Field(default=False, validation_alias="ENABLE_AVAILABILITY_CHECK")
    enable_multi_language: bool = Field(default=False, validation_alias="ENABLE_MULTI_LANGUAGE")
    enable_voice_chat: bool = Field(default=False, validation_alias="ENABLE_VOICE_CHAT")
    enable_image_understanding: bool = Field(
        default=False, validation_alias="ENABLE_IMAGE_UNDERSTANDING"
    )
    ollama_timeout_seconds: float = Field(default=30.0, validation_alias="OLLAMA_TIMEOUT_SECONDS")
    llm_provider: Literal["groq", "ollama"] = Field(default="groq", validation_alias="LLM_PROVIDER")
    groq_api_key: SecretStr = Field(validation_alias="GROQ_API_KEY")
    groq_model: str = Field(default="llama-3.3-70b-versatile", validation_alias="GROQ_MODEL")
    groq_base_url: str = Field(
        default="https://api.groq.com/openai/v1", validation_alias="GROQ_BASE_URL"
    )
    groq_timeout_seconds: float = Field(default=30.0, validation_alias="GROQ_TIMEOUT_SECONDS")
    classification_confidence_threshold: float = Field(
        default=0.70,
        validation_alias="CLASSIFICATION_CONFIDENCE_THRESHOLD",
    )
    prompt_library_path: str = Field(
        default="./prompt_library", validation_alias="PROMPT_LIBRARY_PATH"
    )
    security_policy_dir: str = Field(
        default="./security_policies", validation_alias="SECURITY_POLICY_DIR"
    )
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
    qdrant_collection_products: str = Field(
        default="products_v1",
        validation_alias="QDRANT_COLLECTION_PRODUCTS",
    )
    qdrant_collection_documents: str = Field(
        default="documents_v1",
        validation_alias="QDRANT_COLLECTION_DOCUMENTS",
    )
    large_device_threshold: int = Field(default=500, validation_alias="LARGE_DEVICE_THRESHOLD")
    enterprise_device_threshold: int = Field(default=1000, validation_alias="ENTERPRISE_DEVICE_THRESHOLD")
    default_language: str = Field(default="en", validation_alias="DEFAULT_LANGUAGE")
    supported_languages: str = Field(default="en,ur,ar", validation_alias="SUPPORTED_LANGUAGES")
    translation_prompt_template: str = Field(
        default="translation/translate_response_v1.md",
        validation_alias="TRANSLATION_PROMPT_TEMPLATE",
    )
    availability_provider: Literal["local", "erp"] = Field(
        default="local",
        validation_alias="AVAILABILITY_PROVIDER",
    )
    erp_api_base_url: str = Field(default="", validation_alias="ERP_API_BASE_URL")
    erp_api_key: SecretStr = Field(default=SecretStr(""), validation_alias="ERP_API_KEY")
    crm_max_retry_attempts: int = Field(default=5, validation_alias="CRM_MAX_RETRY_ATTEMPTS")
    crm_retry_worker_interval_seconds: int = Field(
        default=60,
        validation_alias="CRM_RETRY_WORKER_INTERVAL_SECONDS",
    )
    chat_rate_limit_per_minute: int = Field(
        default=20, validation_alias="CHAT_RATE_LIMIT_PER_MINUTE"
    )
    max_message_length: int = Field(default=4000, validation_alias="MAX_MESSAGE_LENGTH")


class Settings(BaseSettings):
    """Application settings grouped by subsystem."""

    model_config = SettingsConfigDict(env_file=".env", case_sensitive=False, extra="ignore")

    db: DbSettings
    redis: RedisSettings
    qdrant: QdrantSettings
    llm_provider: Literal["groq", "ollama"]
    ollama: OllamaSettings
    groq: GroqSettings
    embedding: EmbeddingSettings
    resend: ResendSettings
    crm: CrmSettings
    site: SiteSettings
    router: RouterSettings
    session: SessionSettings
    clarification: ClarificationSettings
    rag: RagSettings
    solution_builder: SolutionBuilderSettings
    language: LanguageSettings
    availability: AvailabilitySettings
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
            llm_provider=flat.llm_provider,
            ollama=OllamaSettings(
                host=flat.ollama_host,
                model=flat.ollama_model,
                timeout_seconds=flat.ollama_timeout_seconds,
                default_temperature=flat.ollama_default_temperature,
            ),
            groq=GroqSettings(
                api_key=flat.groq_api_key,
                model=flat.groq_model,
                base_url=flat.groq_base_url,
                timeout_seconds=flat.groq_timeout_seconds,
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
                qdrant_collection_products=flat.qdrant_collection_products,
                qdrant_collection_documents=flat.qdrant_collection_documents,
            ),
            solution_builder=SolutionBuilderSettings(
                large_device_threshold=flat.large_device_threshold,
                enterprise_device_threshold=flat.enterprise_device_threshold,
            ),
            language=LanguageSettings(
                default_language=flat.default_language,
                supported_languages=_split_csv(flat.supported_languages),
                translation_prompt_template=flat.translation_prompt_template,
            ),
            availability=AvailabilitySettings(
                provider=flat.availability_provider,
                erp_api_base_url=flat.erp_api_base_url,
                erp_api_key=flat.erp_api_key,
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
                enable_product_comparison=flat.enable_product_comparison,
                enable_compatibility_check=flat.enable_compatibility_check,
                enable_accessory_recommendation=flat.enable_accessory_recommendation,
                enable_pdf_search=flat.enable_pdf_search,
                enable_solution_builder=flat.enable_solution_builder,
                enable_wizard=flat.enable_wizard,
                enable_use_case_recommendation=flat.enable_use_case_recommendation,
                enable_human_handoff=flat.enable_human_handoff,
                enable_availability_check=flat.enable_availability_check,
                enable_multi_language=flat.enable_multi_language,
                enable_voice_chat=flat.enable_voice_chat,
                enable_image_understanding=flat.enable_image_understanding,
            ),
        )

    def redacted_dict(self) -> dict[str, Any]:
        """Return grouped settings with sensitive values redacted."""
        return {name: _redact_value(name, getattr(self, name)) for name in type(self).model_fields}

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
