# Module 1 — Project Foundation

**Project:** Makkays AI Assistant (RAG Chatbot v4)
**Depends on:** Nothing (first module)
**Blocks:** All other modules — every subsequent module imports config, logging, and DI patterns established here.

---

## 1. Overview

This module lays the skeleton the entire backend runs on: the FastAPI app instance,
project structure, environment/config loading, logging, and the dependency-injection
pattern used to hand services (DB clients, Redis, Qdrant, LLM providers) to route
handlers. Nothing here talks to Supabase, Qdrant, or Groq yet — those are Module 2+.
The goal is a backend that boots cleanly, serves a health check, and has every seam in
place for later modules to plug into without refactoring.

---

## 2. Goals / Success Criteria

- `uvicorn app.main:app` boots with zero errors on a fresh clone + `.env`.
- `GET /health` returns `200 {"status": "ok"}`.
- Config is loaded once, typed, validated at startup (fail fast on missing env vars).
- Logging is structured (JSON in prod, readable in dev) and used consistently — no
  stray `print()` calls anywhere in the codebase from this point forward.
- Every service (to be added in later modules) is provided via FastAPI `Depends()`,
  never imported and instantiated ad-hoc inside route handlers.

---

## 3. Tech Components

| Component | Choice |
|---|---|
| Web framework | FastAPI |
| ASGI server | Uvicorn (dev), Gunicorn+Uvicorn workers (prod) |
| Config/validation | `pydantic-settings` (`BaseSettings`) |
| Logging | Python `logging` + `python-json-logger` for prod JSON output |
| Env management | `.env` + `python-dotenv` (dev only; prod uses real env vars from Render) |

---

## 4. Environment Variables (defined here, consumed everywhere)

Create `.env.example` at repo root — never commit `.env` itself.

```env
# App
APP_ENV=development            # development | staging | production
APP_NAME=makkays-ai-assistant
APP_DEBUG=true
APP_HOST=0.0.0.0
APP_PORT=8000
LOG_LEVEL=INFO                 # DEBUG | INFO | WARNING | ERROR
CORS_ORIGINS=http://localhost:3000,https://makkays.com

# Placeholders for later modules — declare now so config.py validates the full shape
SUPABASE_URL=
SUPABASE_SERVICE_ROLE_KEY=
SUPABASE_ANON_KEY=
QDRANT_URL=
QDRANT_API_KEY=
UPSTASH_REDIS_REST_URL=
UPSTASH_REDIS_REST_TOKEN=
GROQ_API_KEY=
OLLAMA_BASE_URL=http://localhost:11434
RESEND_API_KEY=
SMTP_HOST=
SMTP_PORT=
SMTP_USER=
SMTP_PASSWORD=
JWT_SECRET_KEY=
```

> Module 1 only *declares* the full env shape so `config.py` validates everything the
> project will ever need up front. Modules 2, 6, 9 etc. are the ones that actually
> *use* their respective values — Module 1 just makes sure a missing var fails loudly
> at boot instead of silently at 2am in Module 9.

---

## 5. Project Structure (established in this module)

```
makkays-ai-assistant/
├── backend/
│   ├── app/
│   │   ├── __init__.py
│   │   ├── main.py                 # FastAPI app factory, startup/shutdown events
│   │   ├── config.py                # pydantic-settings, singleton via lru_cache
│   │   ├── logging_config.py        # structured logging setup
│   │   ├── dependencies.py          # shared Depends() providers (grows every module)
│   │   ├── api/
│   │   │   ├── __init__.py
│   │   │   └── health.py            # GET /health
│   │   ├── core/
│   │   │   ├── __init__.py
│   │   │   └── exceptions.py        # custom exception classes + handlers
│   │   ├── rag/                     # Module 3–5 populate this
│   │   ├── llm/                     # Module 6 populates this
│   │   ├── db/                      # Module 2 populates this
│   │   ├── cache/                   # Module 2 populates this
│   │   ├── templates/               # Module 10 populates this
│   │   └── services/                # Module 7+ populate this
│   ├── tests/
│   │   ├── __init__.py
│   │   └── test_health.py
│   ├── .env.example
│   ├── requirements.txt
│   └── pyproject.toml               # ruff/black/mypy config
├── widget/                          # Module 8
└── docs/
    └── modules/                     # this file and its siblings live here
```

---

## 6. Implementation Tasks

### 6.1 `config.py` — typed settings singleton

```python
from functools import lru_cache
from pydantic_settings import BaseSettings, SettingsConfigDict

class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    app_env: str = "development"
    app_name: str = "makkays-ai-assistant"
    app_debug: bool = True
    app_host: str = "0.0.0.0"
    app_port: int = 8000
    log_level: str = "INFO"
    cors_origins: str = ""

    # Declared here, populated/consumed by later modules
    supabase_url: str = ""
    supabase_service_role_key: str = ""
    supabase_anon_key: str = ""
    qdrant_url: str = ""
    qdrant_api_key: str = ""
    upstash_redis_rest_url: str = ""
    upstash_redis_rest_token: str = ""
    groq_api_key: str = ""
    ollama_base_url: str = "http://localhost:11434"
    resend_api_key: str = ""
    smtp_host: str = ""
    smtp_port: int = 587
    smtp_user: str = ""
    smtp_password: str = ""
    jwt_secret_key: str = ""

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]

@lru_cache
def get_settings() -> Settings:
    return Settings()
```

- Fail-fast rule: at startup, `main.py` calls `get_settings()` once and logs
  `app_env`/`app_name`. Do **not** validate the empty placeholder keys (Supabase,
  Qdrant, etc.) as required in Module 1 — they become required only once their
  owning module is implemented. Use per-module "is this configured?" guards there,
  not here.

### 6.2 `logging_config.py`

- `setup_logging(settings: Settings)` called once from `main.py` before the app is
  constructed.
- `app_env == "production"` → JSON formatter (`python-json-logger`), one line per
  event, includes `timestamp`, `level`, `logger`, `message`, and any `extra=` fields.
- Otherwise → human-readable formatter with color if TTY.
- Every module logs via `logging.getLogger(__name__)` — never `print()`.

### 6.3 `main.py` — app factory

```python
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from app.config import get_settings
from app.logging_config import setup_logging
from app.api import health

def create_app() -> FastAPI:
    settings = get_settings()
    setup_logging(settings)

    app = FastAPI(title=settings.app_name, debug=settings.app_debug)

    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origin_list,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    app.include_router(health.router)
    return app

app = create_app()
```

### 6.4 `dependencies.py` — the DI seam

This file is the single place every route handler pulls shared resources from. It
starts nearly empty and grows one `Depends()` provider per module:

```python
from app.config import get_settings, Settings
from fastapi import Depends
from typing import Annotated

SettingsDep = Annotated[Settings, Depends(get_settings)]

# Module 2 adds: SupabaseDep, QdrantDep, RedisDep
# Module 6 adds: LLMProviderDep
# etc. — always append here, never instantiate clients inline in route files.
```

### 6.5 `core/exceptions.py`

- Define `AppException(Exception)` base class with `status_code` + `detail`.
- Register a FastAPI exception handler in `main.py` that catches `AppException` and
  returns a consistent JSON error shape: `{"error": {"code": ..., "message": ...}}`.
- Later modules subclass this (e.g. `RetrievalError`, `LLMProviderError`,
  `GuardrailViolation`) instead of raising raw `HTTPException` everywhere.

### 6.6 `api/health.py`

```python
from fastapi import APIRouter

router = APIRouter(tags=["health"])

@router.get("/health")
async def health_check():
    return {"status": "ok"}
```

---

## 7. Testing & Validation Checklist

- [ ] `pip install -r requirements.txt` succeeds in a clean venv.
- [ ] `uvicorn app.main:app --reload` boots with no traceback.
- [ ] `GET /health` → `200 {"status": "ok"}`.
- [ ] Missing `.env` file → app still boots (all Module-1-owned settings have safe
      defaults); this is intentional so Day 1/2 setup (Module 2) isn't blocked.
- [ ] Setting `APP_ENV=production` switches log format to JSON (visually confirm).
- [ ] `pytest tests/test_health.py` passes.
- [ ] No `print()` statements anywhere under `app/`.

---

## 8. Deliverable

A booting FastAPI backend with a health endpoint, typed/validated config, structured
logging, and an established `dependencies.py` seam — ready for Module 2 to attach real
infrastructure clients without touching `main.py`'s shape.

---

## 9. Handoff Notes for Claude Code

- When implementing Module 2 onward, **extend** `dependencies.py` and `config.py`
  rather than creating parallel config/DI files.
- Keep `requirements.txt` pinned (`==`, not `>=`) once the stack stabilizes — this
  project has no CI yet, so reproducible installs matter now.
- Do not add Supabase/Qdrant/Redis/Groq SDK calls in this module — stub imports only
  if needed, real implementation belongs to Modules 2 and 6.
