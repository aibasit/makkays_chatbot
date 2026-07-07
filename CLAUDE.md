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
| - | - | - |
| 01 | Foundation & Configuration (`app/config.py`, `app/main.py`, `app/dependencies.py`, `app/exceptions.py`, `app/logging_config.py`) | ✅ Done |
| 02 | Database & Cache Layer (`app/db/`, `app/cache/`) | ✅ Done |
| 03 | Session & State Management — Facts vs Conversation State (`app/session/`) | ✅ Done |
| 04 | Conversation Turns & Structured Logging (`app/turns/`) | ✅ Done |
| 05 | LLM Engine (`app/llm/`) — dual-provider, see below | ✅ Done |
| 06 | Router & Hybrid Intent Classification (`app/router/`) | ✅ Core done — see caveat below |
| 07 | Task Planner (`app/planner/`) | ✅ Done |
| 08 | Prompt Manager (`app/prompts/`, `prompt_library/`) | ✅ Done |
| 09 | Feature Flags (`app/flags/`) | ✅ Done |
| 10 | Security Policy Registry & Tool Executor (`app/tools/`, `security_policies/`) | ✅ Done |
| 11 | RAG Engine (BGE-M3, Qdrant) | ⬅️ **Next / not started** |
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

Alembic migrations so far: `0001_session_state`, `0002_conversation_turns`,
`0003_feature_flags`, `0004_tool_audit_log`.

**Start here next session:** implement Module 11 (RAG Engine) per
[md files/11-rag-engine.md](md%20files/11-rag-engine.md) — it's the next unblocked
module. It's not one of the five things `Orchestrator.on_turn` is still waiting on
(only M13 Clarification and M16 Metrics remain for that), but it's next in build order
and it's what will let `retrieve_products`/`retrieve_docs` become real registered tools
instead of absent from `ToolRegistry`.

### Module 06/07/08/09/10 detail and the Orchestrator caveat

`app/router/` (Tier1RuleEngine, Tier2Classifier, FactsExtractor, `Router.classify`) and
`app/planner/` (`TaskPlanner.build_plan`) are fully implemented and tested — both are
self-contained given only M03/M04/M05 (already built). `Router`/`FactsExtractor` depend
on a narrow `PromptProvider` protocol (`app/shared/intent_context.py`, `.get` only)
rather than importing Module 08's `PromptManager` directly.

Module 08 (`app/prompts/`) is now implemented: `PromptManager.get(category, name,
version)` / `get_latest(category, name)`, filesystem-backed with a process-lifetime
cache, singleton at `app.prompts.manager.prompt_manager` (constructed from
`settings.prompts.library_path`, path resolved to absolute at construction time —
don't change that back to a bare relative `Path`, it broke two existing tests that
`monkeypatch.chdir` before booting the app). `app/prompts/manager.PromptProvider` is
the richer protocol (`get` + `get_latest`) real future callers should type-hint
against; Router's own narrower one-method protocol is intentionally kept separate
(interface segregation) and is structurally satisfied by the same `PromptManager`.
`prompt_library/` has real content for all nine prompts Module 08's startup self-check
requires; `app.main`'s lifespan now runs that self-check and **hard-fails startup** if
any referenced prompt is missing — this is intentional (packaging bug, not a transient
outage, unlike the LLM health check which only warns).

Module 09 (`app/flags/`) is now implemented: `FeatureFlagsService.resolve(tenant_id) ->
FeatureFlags` merges `Settings.flags` env defaults with optional per-tenant overrides in
the `feature_flags` table (migration `0003_feature_flags`), TTL-cached 60s per tenant via
`cachetools.TTLCache` (added as a new dependency). `FeatureFlags` now lives at
`app.flags.schemas.FeatureFlags` with all 18 v4.1+v4.2 flags — this **replaced** the
`app/shared/feature_flags.py` seed from the M07 session (deleted; Planner's
`build_plan` signature was unaffected). `enable_voice_chat`/`enable_image_understanding`
are always forced `False` regardless of any override, per spec.

Module 10 (`app/tools/`) is now implemented: `ToolExecutor.execute_plan`/`execute_step`
enforce plan-conformance (`PlanViolationError` if a step isn't in the current plan) then
the step's Security Policy (intent → `required_state` predicates → `required_slots` →
Redis fixed-window rate limit, in that order) before ever calling the tool. Critical
steps (`generate_quote`, `create_lead`) abort the rest of the plan on denial/exception;
others degrade gracefully. `security_policies/*.yaml` has one file per tool, loaded by
`PolicyRegistry` and self-checked at boot (`app.main` hard-fails if any *registered*
tool lacks a policy — note this seeded a `request_missing_slots.yaml` not in the
module's own file list, since it's registered as a built-in but the spec's example
listing only had 6 files, not 7). `app.quotes.schemas.quote_slots_complete` is now
Module 10's authoritative definition (`company`, `product_interest`, `quantity`,
`budget` all non-None) and takes `(facts, state)` — this **changed from the M07-session
placeholder**, which checked different fields; Planner call sites and tests were
updated to match. Only 3 tools are actually registered right now (`respond`, `compare`,
`request_missing_slots`, all built into `executor.py`) — `retrieve_products`,
`retrieve_docs`, `generate_quote`, `create_lead` have policies waiting but no
implementation until M11/M12/M14 register themselves via `tool_registry.register(...)`
in their own `__init__.py`.

`Orchestrator.on_turn` (`app/orchestrator/orchestrator.py`) is a **documented
placeholder that raises `NotImplementedError`** — its real spec (readme.md §12/13)
calls directly into `FeatureFlagsService` (M09), `ToolExecutor` (M10) — both now
available — plus `ClarificationFlow` (M13) and `MetricsRegistry` (M16), still pending.
Wire it up once those two land, in build order. One more seed file still exists purely
so Planner/Tool Executor could be built ahead of their real owners:
`app/quotes/schemas.py` (`quote_slots_complete` — M12 owns the full Quote Builder).

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

Source is baked into the image at build time (no volume mount), so **rebuild before
testing** whenever app code changes: `docker compose build backend` first, then run
the command above (or `docker compose up -d backend` to also refresh the live container).

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
- GitHub repo: <https://github.com/aibasit/makkays_chatbot>
