# makkays_chatbot — AI Sales Engineer RAG Chatbot

FastAPI backend for a multi-tenant RAG-based AI Sales Engineer chatbot (architecture
version v4.1/v4.2, "final, not to be redesigned"). Stack: FastAPI + Postgres (Supabase
in prod, local Postgres container in dev) + Redis + Qdrant + a swappable LLM provider
(Groq Cloud now, Ollama later).

The full spec is 22 independently-buildable modules, each documented in
[md files/](md%20files/) (`NN-name.md`, e.g. `06-router-intent-classification.md`).
[readme.md](readme.md) is the master index: required env vars, module table, canonical
intent taxonomy, canonical interfaces, Redis key registry, DB table registry, startup/
shutdown lifecycle, request lifecycle, logging contract, and test-consistency contract.
**Read readme.md section for a module, then that module's own `md files/NN-*.md`,
before implementing it** — don't improvise interfaces, they're pinned across modules.

## Build order and current status

Modules are built strictly in dependency order. Do not jump ahead or build M06+ logic
inside an earlier module.

| # | Module | Status |
|---|---|---|
| 01 | Foundation & Configuration (`app/config.py`, `app/main.py`, `app/dependencies.py`, `app/exceptions.py`, `app/logging_config.py`) | ✅ Done |
| 02 | Database & Cache Layer (`app/db/`, `app/cache/`) | ✅ Done |
| 03 | Session & State Management — Facts vs Conversation State (`app/session/`) | ✅ Done |
| 04 | Conversation Turns & Structured Logging (`app/turns/`) | ✅ Done |
| 05 | LLM Engine (`app/llm/`) — dual-provider, see below | ✅ Done |
| 06 | Router & Hybrid Intent Classification (`app/router/`) | ⬅️ **Next / not started** |
| 07 | Task Planner | Not started |
| 08 | Prompt Manager | Not started |
| 09 | Feature Flags | Not started |
| 10 | Security Policy Registry & Tool Executor | Not started |
| 11 | RAG Engine (BGE-M3, Qdrant) | Not started |
| 12 | Quote Builder & PDF Export | Not started |
| 13 | Clarification Template Library | Not started |
| 14 | CRM Integration, Retry Queue & Email (Resend) | Not started |
| 15 | Public API & Widget Session | Not started |
| 16 | Observability | Not started |
| 17 | Frontend (React/TS/Vite widget) | Not started |
| 18 | Product Intelligence Service | Not started |
| 19 | Solution Builder & Recommendation Wizard | Not started |
| 20 | Human Handoff & Extended Lead Qualification | Not started |
| 21 | Multi-language (EN/UR/AR) | Not started |
| 22 | Availability & ERP Bridge | Not started |

Alembic migrations so far: `0001_session_state`, `0002_conversation_turns`.

**Start here next session:** implement Module 06 per
[md files/06-router-intent-classification.md](md%20files/06-router-intent-classification.md),
using the `FactsExtractor`, `Router`, and `Orchestrator` interfaces pinned in
readme.md §5 and the facts-extraction contract in readme.md §6.

## LLM provider (Module 05 detail)

MVP runs against **Groq Cloud** (`api.groq.com`, OpenAI-compatible), not local Ollama —
chosen to avoid multi-GB model downloads before validating the RAG pipeline. Ollama
code path is kept fully alive so switching is a config change only, no rewrite.

- `LLM_PROVIDER` env var: `"groq"` (default) or `"ollama"`.
- `app/llm/factory.py` → `get_llm_client(settings)` returns `GroqClient` or
  `OllamaClient`, both implementing `LLMClientProtocol` (`app/llm/schemas.py`).
- `app/llm/_shared.py` holds validation/parsing logic shared by both clients.
- `app/llm/health.py` → `verify_llm_status(settings)` dispatches per provider; used in
  `app/main.py` startup logging.
- **Always obtain the client via `get_llm_client(settings)`** in new modules (M06+) —
  never instantiate `GroqClient`/`OllamaClient` directly — so modules stay
  provider-agnostic.
- Naming gotcha: API key prefix `gsk_` is **Groq Cloud**, not xAI **Grok**
  (api.x.ai) — different companies. Code/env vars use `GROQ_*` only.
- Known quirk: Groq's `/v1/models` occasionally omits a model that appears moments
  later (edge-cache lag) — logged as a warning, non-fatal, `/chat/completions` unaffected.

## Docker

Two compose files, both with `ollama` gated behind `profiles: ["ollama"]` (not started
by default):

- `docker-compose.yml` — dev stack: `postgres`, `redis`, `qdrant`, `ollama` (profile-gated),
  `backend`. Backend runs `alembic upgrade head` then uvicorn on `:8000`.
  Standard bring-up: `docker compose up -d --build postgres redis qdrant backend`.
- `docker-compose.test.yml` — same minus qdrant (mock URL), `LLM_PROVIDER=groq` with a
  mock key for config validation.

Service URL overrides live in `docker-compose.yml`'s `environment:` block (Postgres,
Redis, Qdrant all point at containers, not the `.env` values). `.env` has a real cloud
Qdrant URL for reference but it's overridden locally — remove the override lines in
compose if you ever want the backend to hit cloud Qdrant directly.

Switching to Ollama: `docker compose --profile ollama up -d ollama` then
`docker exec -it ollama ollama pull qwen2.5:3b` (persists in `ollama_data` volume).

**Run tests inside Docker, not the host Python** — the host interpreter doesn't have
project deps installed:
```bash
docker compose run --rm --no-deps backend python -m pytest -q
```

## Conventions (binding across all modules — from readme.md §3)

- Every table/query is tenant-scoped via `tenant_id`; local dev uses `DEFAULT_TENANT_ID`.
- All repository/service methods touching DB/Redis/network/LLM are `async def`.
- Pydantic v2 only (`model_config = ConfigDict(...)`, never v1 `class Config`).
- Each module defines its own exceptions in that module's `exceptions.py`; caught
  centrally by the Module 01 FastAPI exception handler.
- All logging goes through the shared structured JSON logger from Module 04 — never
  configure a per-module logger.
- Canonical intents (must match exactly, see readme.md §4): `sales_inquiry`,
  `quote_request`, `technical_support`, `escalation_request`, `out_of_scope`.
- `create_ticket` is a reserved future tool gated by `ENABLE_TICKETS` — no planner rule
  may emit it until its module is documented.

## Other project docs

- [system_flowchart.md](system_flowchart.md) — architecture flowchart.
- [I power documents/](I%20power%20documents/) — real product/model data
  (`makkays_ipower_products.csv`, `makkays_ipower_models.csv`, `.md`) used by RAG once
  M11 is built.

## User preferences

- Prefers being told exactly what to do next in sequence, not a menu of options.
- GitHub repo: https://github.com/aibasit/makkays_chatbot
