# AI Sales Engineer — Implementation Documentation Set (v4.1, Local Development)

This document set converts the **v4.1 architecture** (final, not to be redesigned) into
implementation-ready engineering documentation, broken into independently buildable
modules. Scope is **local development only** — no Docker, Kubernetes, cloud hosting,
reverse proxies, CI/CD, GPU servers, monitoring infra, or scaling strategy is included
anywhere in this set.

---

## 1. Required Credentials & API Keys (read this first)

Every module below references a subset of these. Collect all of them before starting
Module 01, and store them in a single local `.env` file at the project root (never
committed — add `.env` to `.gitignore` on day one).

| Key | Used By | Where To Get It | Required For Local Dev? |
|---|---|---|---|
| `SUPABASE_DB_URL` | All modules touching Postgres | Supabase project → Settings → Database → Connection string (use the **pooled** connection string for the app, direct string for migrations) | Yes |
| `SUPABASE_SERVICE_ROLE_KEY` | Optional, only if using Supabase client SDK instead of raw `asyncpg`/SQLAlchemy | Supabase project → Settings → API | Only if using Supabase SDK |
| `QDRANT_URL` | RAG Engine (M11) | Qdrant Cloud console → Cluster → Endpoint | Yes |
| `QDRANT_API_KEY` | RAG Engine (M11) | Qdrant Cloud console → API Keys | Yes |
| `REDIS_URL` | Session/State (M03), Rate limiting (M15) | Local Redis (Docker or native install), e.g. `redis://localhost:6379/0` | Yes |
| `OLLAMA_HOST` | LLM Engine (M05) | Local Ollama install, default `http://localhost:11434` | Yes |
| `OLLAMA_MODEL` | LLM Engine (M05) | Pulled locally: `ollama pull qwen3:8b-instruct` | Yes |
| `RESEND_API_KEY` | Email Notifications (M14) | resend.com → API Keys | Yes (for lead/quote email notifications) |
| `RESEND_FROM_EMAIL` | Email Notifications (M14) | A domain verified in Resend | Yes |
| `CRM_API_BASE_URL` | CRM Integration (M14) | Your CRM provider's API docs | Yes (stub/mock acceptable for local dev) |
| `CRM_API_KEY` | CRM Integration (M14) | CRM provider dashboard | Yes (stub/mock acceptable for local dev) |
| `SITE_API_KEY` | Public API (M15) | Self-generated (`openssl rand -hex 32`) — this is a key **you** issue to your own frontend widget, not a third-party key | Yes |
| `DEFAULT_TENANT_ID` | Multi-tenancy foundation, all tables | Self-defined UUID, e.g. `00000000-0000-0000-0000-000000000001` | Yes |
| `OLLAMA_TIMEOUT_SECONDS` | LLM Engine (M05) | Integer seconds; default `30`. Increase on slow hardware. | No (has safe default) |
| `PROMPT_LIBRARY_PATH` | Prompt Manager (M08) | Path to the `prompt_library/` directory; default `./prompt_library` relative to project root. | No (has safe default) |
| `SECURITY_POLICY_DIR` | Tool Executor (M10) | Path to the `security_policies/` directory; default `./security_policies` relative to project root. | No (has safe default) |
| `CORS_ALLOW_ORIGINS` | Foundation (M01) | Comma-separated list of allowed frontend origins, e.g. `http://localhost:5173`. | No (has safe default) |
| `JWT_SECRET` (optional, if internal admin auth is added later) | Not used in v4.1 scope | N/A | No — not in current architecture |

### 1.1 `.env` file skeleton (project root)

```
# --- Database ---
SUPABASE_DB_URL=postgresql+asyncpg://postgres:<password>@<host>:6543/postgres
DEFAULT_TENANT_ID=00000000-0000-0000-0000-000000000001

# --- Vector DB ---
QDRANT_URL=https://<cluster-id>.qdrant.io
QDRANT_API_KEY=

# --- Cache ---
REDIS_URL=redis://localhost:6379/0

# --- LLM ---
OLLAMA_HOST=http://localhost:11434
OLLAMA_MODEL=qwen3:8b-instruct

# --- Embeddings ---
EMBEDDING_MODEL=BAAI/bge-m3

# --- Email ---
RESEND_API_KEY=
RESEND_FROM_EMAIL=sales@yourdomain.com

# --- CRM ---
CRM_API_BASE_URL=
CRM_API_KEY=

# --- Public API / Widget ---
SITE_API_KEY=

# --- Feature Flags (defaults; can be overridden by feature_flags table at runtime) ---
ENABLE_RAG=true
ENABLE_QUOTES=true
ENABLE_CRM=true
ENABLE_TICKETS=true
ENABLE_IMAGE_UPLOAD=false
ENABLE_LLM_CLARIFICATION_REWRITE=false

# --- LLM Tuning (optional — safe defaults apply) ---
OLLAMA_TIMEOUT_SECONDS=30

# --- Path Overrides (optional — safe defaults apply) ---
PROMPT_LIBRARY_PATH=./prompt_library
SECURITY_POLICY_DIR=./security_policies

# --- CORS (development only) ---
CORS_ALLOW_ORIGINS=http://localhost:5173

# --- Logging ---
LOG_LEVEL=INFO
```

Every module's "Environment Variables" section references this same file — nothing is
duplicated or redefined per module; each module simply lists which subset of the above
it consumes.

---

## 2. Module Index (dependency / build order)

Matches architecture §4 "Build Order," collapsed into engineering-functionality units
rather than folders.

| # | Module | File |
|---|---|---|
| 01 | Foundation & Configuration | `01-foundation-configuration.md` |
| 02 | Database & Cache Layer | `02-database-cache-layer.md` |
| 03 | Session & State Management (Facts vs Conversation State) | `03-session-state-management.md` |
| 04 | Conversation Turns & Structured Logging | `04-conversation-turns-logging.md` |
| 05 | LLM Engine (Ollama / Qwen3 Tool-Calling Loop) | `05-llm-engine-ollama.md` |
| 06 | Router & Hybrid Intent Classification | `06-router-intent-classification.md` |
| 07 | Task Planner | `07-task-planner.md` |
| 08 | Prompt Manager | `08-prompt-manager.md` |
| 09 | Feature Flags | `09-feature-flags.md` |
| 10 | Security Policy Registry & Tool Executor | `10-security-policy-tool-executor.md` |
| 11 | RAG Engine (Layered Retrieval, BGE-M3, Qdrant) | `11-rag-engine.md` |
| 12 | Quote Builder | `12-quote-builder.md` |
| 13 | Clarification Template Library | `13-clarification-templates.md` |
| 14 | CRM Integration, Retry Queue & Email (Resend) | `14-crm-integration-email-retry.md` |
| 15 | Public API & Widget Session | `15-public-api-widget-session.md` |
| 16 | Observability (Logs vs Metrics, local) | `16-observability-metrics.md` |
| 17 | Frontend Application (React/TS/Vite widget) | `17-frontend-application.md` |

Each module document uses the same 32-section template so any engineer can jump into
any module file and know exactly where to find a given piece of information.

## 3. Cross-Module Conventions

- **Tenancy**: every table/query includes `tenant_id`; local dev uses `DEFAULT_TENANT_ID` for all requests until multi-tenant auth exists.
- **Async everywhere**: all repository/service methods are `async def`, using `asyncpg`/SQLAlchemy async engine and `redis.asyncio`.
- **Pydantic v2**: all schemas use `model_config = ConfigDict(...)`, not the v1 `class Config`.
- **Errors**: every module raises a small set of module-specific exceptions (defined in that module's `exceptions.py`), caught centrally by a FastAPI exception handler registered in Module 01.
- **Logging**: every module logs through the shared structured JSON logger from Module 04 — no module configures its own logger.
- **No implementation code** is included in these documents per instruction; only interfaces, signatures (as text, not code bodies), schemas, and structure.
