# Module 01 — Foundation & Configuration

## 1. Module Name
`foundation` — Project skeleton, settings, app factory, exception handling base.

## 2. Goal
Stand up the FastAPI application shell, centralized configuration via Pydantic
Settings, and the shared cross-cutting primitives (exception base classes, app
factory, dependency-injection container) that every later module builds on.

## 3. Purpose
Nothing else can be built until there is a single, typed, validated source of
configuration and a running FastAPI instance to attach routers, middleware, and
startup/shutdown hooks to. This module has zero business logic — it exists purely
so every subsequent module has a stable foundation to import from.

## 4. Dependencies
None (this is the root module). Consumes the `.env` file described in Module 00.

## 5. Folder Structure
```
app/
├── main.py
├── config.py
├── dependencies.py
├── exceptions.py
├── logging_config.py          (wired fully in Module 04; stubbed here)
└── __init__.py
tests/
├── unit/
│   └── test_config.py
└── integration/
    └── test_app_startup.py
.env
.env.example
pyproject.toml / requirements.txt
```

## 6. Files to Create
- `app/main.py`
- `app/config.py`
- `app/dependencies.py`
- `app/exceptions.py`
- `app/logging_config.py` (placeholder, extended in Module 04)
- `.env.example`

## 7. Responsibility of Every File
| File | Responsibility |
|---|---|
| `main.py` | App factory (`create_app()`), registers routers/middleware/exception handlers from all modules, defines lifespan (startup/shutdown) hooks |
| `config.py` | `Settings` class (Pydantic `BaseSettings`), single source of truth for all env vars across all modules |
| `dependencies.py` | Shared FastAPI `Depends()` providers (e.g., `get_settings`), extended by later modules with `get_db`, `get_redis`, etc. |
| `exceptions.py` | Base exception hierarchy (`AppError`, `NotFoundError`, `ValidationError`, `ExternalServiceError`) that all module-specific exceptions subclass |
| `logging_config.py` | `configure_logging(settings)` entrypoint called at startup; full JSON formatter added in Module 04 |

## 8. Classes
- `Settings(BaseSettings)` — all env-derived configuration, typed and validated at boot.
- `AppError(Exception)` — base for all domain errors; carries `code: str`, `message: str`, `http_status: int`.
- `NotFoundError(AppError)`, `ValidationError(AppError)`, `ExternalServiceError(AppError)`, `PolicyViolationError(AppError)` (used from Module 10 onward).

## 9. Data Models
None (no persistence in this module).

## 10. Pydantic Schemas
- `Settings` doubles as the schema for configuration; fields grouped by module (db, redis, qdrant, ollama, resend, crm, site, flags, logging) matching the `.env` skeleton in Module 00.

## 11. Repository Layer
N/A — no data access in this module.

## 12. Service Layer
N/A — no business logic in this module.

## 13. Internal Interfaces
- `get_settings() -> Settings` — cached (`functools.lru_cache`) provider used as a FastAPI dependency everywhere.
- `create_app() -> FastAPI` — called by `uvicorn app.main:create_app --factory` for local dev.

## 14. Database Tables
None.

## 15. Redis Keys
None.

## 16. API Endpoints
| Method | Path | Purpose |
|---|---|---|
| GET | `/health` | Liveness check — returns `{"status": "ok"}` if the process is up (no dependency checks) |

## 17. Request Models
None beyond the empty `GET /health`.

## 18. Response Models
- `HealthResponse { status: Literal["ok"] }`

## 19. Business Logic
- On startup: load `Settings`, call `configure_logging`, register all module routers (imported lazily to avoid circular imports), register the global exception handler mapping `AppError` subclasses to JSON error responses using their `http_status`.
- On shutdown: no-op in this module (later modules add DB/Redis connection teardown here).

## 20. Validation Rules
- All required env vars in Module 00 §1 must be present and non-empty at startup, or the app must fail fast with a clear `MissingConfigurationError` listing every missing key (not just the first one found).
- `OLLAMA_MODEL` must match the pattern of a pulled Ollama tag (validated lazily in Module 05, not here).

## 21. Error Handling
| Error | Handling |
|---|---|
| Missing/invalid env var | Raise `MissingConfigurationError` at import time of `config.py`; process exits with non-zero code before `uvicorn` binds a port |
| Unhandled exception in any route | Global handler catches `Exception`, logs full traceback, returns generic 500 JSON `{"code": "internal_error"}` (never leaks stack trace to client) |
| `AppError` subclass raised | Global handler returns `{"code": err.code, "message": err.message}` with `err.http_status` |

## 22. Logging Strategy
- Placeholder logger configured to stdout at `INFO` level with a plain formatter; replaced by the structured JSON formatter in Module 04.
- Startup log line records which feature flags are active and which env vars were loaded (values redacted for anything containing `KEY`, `SECRET`, `PASSWORD`, `TOKEN`).

## 23. Unit Tests
- `test_settings_loads_from_env` — asserts all fields populate from a fixture `.env`.
- `test_settings_missing_required_var_raises` — removes one required var, asserts `MissingConfigurationError`.
- `test_settings_redacts_secrets_in_repr` — asserts `str(settings)` never contains raw secret values.

## 24. Integration Tests
- `test_app_starts_and_health_check_returns_ok` — boots the app via `TestClient`, hits `/health`, asserts 200.
- `test_unhandled_exception_returns_generic_500` — forces an exception in a dummy route, asserts response body has no stack trace.

## 25. Configuration
`Settings` fields (grouped, all typed):
```
db: DbSettings (supabase_db_url, default_tenant_id)
redis: RedisSettings (redis_url)
qdrant: QdrantSettings (url, api_key)
ollama: OllamaSettings (host, model)
embedding: EmbeddingSettings (model_name)
resend: ResendSettings (api_key, from_email)
crm: CrmSettings (base_url, api_key)
site: SiteSettings (site_api_key)
flags: FeatureFlagDefaults (enable_rag, enable_quotes, enable_crm, enable_tickets, enable_image_upload, enable_llm_clarification_rewrite)
logging: LoggingSettings (log_level)
```

## 26. Environment Variables
All variables from Module 00 §1.1 are declared here as the canonical `Settings` schema. No new variables introduced by this module.

## 27. Sequence Diagram
```
uvicorn --factory app.main:create_app
        │
        ▼
  create_app()
        │
        ├─ get_settings()  ──► Settings() reads .env, validates
        ├─ configure_logging(settings)
        ├─ register exception handlers
        ├─ register routers (health; later modules append theirs)
        └─ return FastAPI instance
```

## 28. Request Lifecycle
`GET /health` → FastAPI routing → handler returns static dict → response middleware → JSON response. No dependencies, no DB/Redis calls.

## 29. Data Flow
None — configuration is read once at process start and held in memory via `lru_cache`.

## 30. Example Workflow
1. Developer copies `.env.example` to `.env`, fills in credentials from Module 00.
2. Runs `uvicorn app.main:create_app --factory --reload`.
3. App fails fast with a clear list if any required var is missing; otherwise binds and logs "Startup complete, N feature flags active."
4. `curl localhost:8000/health` → `{"status": "ok"}`.

## 31. Future Extension Points
- Admin-only settings reload endpoint (out of scope for v4.1).
- Per-tenant configuration overrides (multi-tenancy is foundation-only in v4.1, per architecture §2.16).

## 32. Completion Checklist
- [ ] `Settings` loads and validates all Module 00 env vars
- [ ] Missing var fails startup with a complete (not first-only) list of missing keys
- [ ] `/health` returns 200
- [ ] Global exception handler maps `AppError` subclasses correctly
- [ ] Secrets never appear in logs or `repr(settings)`
- [ ] Unit + integration tests above pass
