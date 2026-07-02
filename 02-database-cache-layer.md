# Module 02 — Database & Cache Layer

## 1. Module Name
`infra_db_cache` — Postgres (Supabase) and Redis connection management, migration tooling.

## 2. Goal
Provide a single, reusable async connection layer to Supabase Postgres and Redis
that every later module's repository layer depends on, plus a migration workflow
for creating tables incrementally as modules are built.

## 3. Purpose
Every module from Module 03 onward needs a database session and/or a Redis client.
Centralizing connection pooling, migrations, and teardown here avoids each module
reinventing engine setup and prevents connection-leak bugs.

## 4. Dependencies
Module 01 (Foundation & Configuration).

## 5. Folder Structure
```
app/
├── db/
│   ├── __init__.py
│   ├── engine.py
│   ├── base.py
│   └── migrations/
│       ├── env.py
│       └── versions/            (Alembic-style migration files, one per module)
├── cache/
│   ├── __init__.py
│   └── redis_client.py
alembic.ini
tests/
├── unit/
│   └── test_engine_config.py
└── integration/
    └── test_db_and_redis_connectivity.py
```

## 6. Files to Create
- `app/db/engine.py`
- `app/db/base.py`
- `app/cache/redis_client.py`
- `alembic.ini` + `app/db/migrations/env.py`

## 7. Responsibility of Every File
| File | Responsibility |
|---|---|
| `engine.py` | Creates the async SQLAlchemy engine + `async_sessionmaker`; exposes `get_db_session()` async generator for FastAPI `Depends` |
| `base.py` | Declarative `Base` class all ORM models inherit from; shared `TimestampMixin` (`created_at`, `updated_at`) and `TenantMixin` (`tenant_id`) |
| `redis_client.py` | Creates a single `redis.asyncio.Redis` client from `REDIS_URL`; exposes `get_redis()` dependency |
| `alembic.ini` / `env.py` | Migration runner config pointed at `SUPABASE_DB_URL` (direct, non-pooled connection for DDL) |

## 8. Classes
- `TimestampMixin` — `created_at`, `updated_at` columns with server defaults.
- `TenantMixin` — `tenant_id: UUID` column, indexed, not nullable, defaults to `DEFAULT_TENANT_ID` in local dev seed data only (never as a DB-level default in general, to force every insert to be tenant-aware).

## 9. Data Models
No business tables yet — this module only defines mixins reused by every later module's ORM models.

## 10. Pydantic Schemas
None (infra-only module).

## 11. Repository Layer
N/A — base module; later modules' repositories depend on `get_db_session`.

## 12. Service Layer
N/A.

## 13. Internal Interfaces
- `get_db_session() -> AsyncGenerator[AsyncSession, None]` — yields a session, commits on success, rolls back on exception, always closes.
- `get_redis() -> Redis` — returns the shared client (connection-pooled internally by `redis.asyncio`).
- `run_migrations()` — CLI entrypoint wrapping `alembic upgrade head`, documented in README for manual local invocation (no CI automation per scope).

## 14. Database Tables
None created directly by this module. It establishes the migration *mechanism* that every later module uses to create its own tables (e.g., Module 03 adds a migration for `session_facts` and `conversation_state`).

## 15. Redis Keys
None directly — this module only provides the client. Namespacing convention documented here for all later modules to follow:
```
{namespace}:{tenant_id}:{entity_id}
e.g. facts:00000000-...:sess_abc123
```

## 16. API Endpoints
| Method | Path | Purpose |
|---|---|---|
| GET | `/health/db` | Checks a live DB connection (`SELECT 1`) |
| GET | `/health/redis` | Checks a live Redis `PING` |

## 17. Request Models
None.

## 18. Response Models
- `DbHealthResponse { status: Literal["ok","error"], detail: str | None }`
- `RedisHealthResponse { status: Literal["ok","error"], detail: str | None }`

## 19. Business Logic
- Engine created once at import time using `create_async_engine(settings.db.supabase_db_url, pool_size=5, max_overflow=5, pool_pre_ping=True)`.
- `pool_pre_ping=True` is required because Supabase pooled connections can be recycled server-side; this avoids stale-connection errors on the first query after idle time.
- Redis client created with `decode_responses=True` so all later modules work with `str`, not `bytes`.

## 20. Validation Rules
- `SUPABASE_DB_URL` must use the `postgresql+asyncpg://` scheme (validated in Module 01's `Settings`, enforced again here at engine construction).
- Redis URL must specify a DB index explicitly (e.g., `/0`) to avoid ambiguity across modules sharing one Redis instance.

## 21. Error Handling
| Error | Handling |
|---|---|
| DB unreachable at startup | Log critical error, `/health/db` returns `status: error` with detail; app still boots (so `/health` liveness isn't coupled to DB readiness — standard liveness/readiness separation) |
| Redis unreachable | Same pattern as DB — `/health/redis` reports error, does not crash app |
| Query raised inside `get_db_session` | Session rolled back automatically, exception re-raised for the calling repository to translate into a domain `AppError` |

## 22. Logging Strategy
- Log engine/pool creation once at startup (pool size, DB host with credentials redacted).
- Log every Redis/DB connectivity failure at `ERROR` with the underlying driver exception message.
- Do not log query text or query parameters at this layer (that belongs to Module 04's structured per-turn logging, not infra logging).

## 23. Unit Tests
- `test_engine_uses_asyncpg_scheme` — asserts connection string scheme.
- `test_redis_client_decode_responses_true`.
- `test_tenant_mixin_column_not_nullable`.

## 24. Integration Tests
- `test_db_session_commits_on_success` — insert + query round-trip against a scratch table.
- `test_db_session_rolls_back_on_exception`.
- `test_redis_set_get_roundtrip`.
- `test_health_db_and_redis_endpoints`.

## 25. Configuration
Reuses `Settings.db` and `Settings.redis` from Module 01. No new settings fields.

## 26. Environment Variables
`SUPABASE_DB_URL`, `REDIS_URL` (already defined in Module 00).

## 27. Sequence Diagram
```
App startup
   │
   ├─ engine.py: create_async_engine(SUPABASE_DB_URL)
   ├─ redis_client.py: Redis.from_url(REDIS_URL)
   └─ routers register /health/db, /health/redis
Request → GET /health/db
   │
   ▼
get_db_session() → SELECT 1 → ok/error → DbHealthResponse
```

## 28. Request Lifecycle
`GET /health/db`: dependency-injected session → raw `SELECT 1` → success/failure mapped to response model → session closed in `finally`.

## 29. Data Flow
Connection pool (engine) ↔ per-request `AsyncSession` ↔ repository layer (Module 03+) ↔ Postgres. Redis client is a long-lived singleton shared across requests (Redis client itself is connection-pooled internally, unlike SQLAlchemy sessions which are per-request).

## 30. Example Workflow
1. Developer runs `alembic upgrade head` after pulling latest code (applies any new module's migration).
2. Starts the app; `/health/db` and `/health/redis` both return `ok`.
3. Module 03 onward can now safely `Depends(get_db_session)` / `Depends(get_redis)`.

## 31. Future Extension Points
- Read replica routing (not needed at current scale).
- Redis cluster mode (single-node sufficient for local dev and initial prod).

## 32. Completion Checklist
- [ ] Async engine connects to Supabase with `pool_pre_ping=True`
- [ ] Redis client connects and round-trips a test key
- [ ] `TimestampMixin` / `TenantMixin` available for import
- [ ] Alembic configured against direct (non-pooled) connection string
- [ ] `/health/db`, `/health/redis` implemented
- [ ] Tests above pass
