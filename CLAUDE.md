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
| 11 | RAG Engine (BGE-M3, Qdrant) (`app/rag/`, `scripts/ingest_products_and_docs.py`) | ✅ Done |
| 12 | Quote Builder & PDF Export (`app/quotes/`, `scripts/seed_pricing.py`) | ✅ Done |
| 13 | Clarification Template Library (`app/clarification/`, `prompt_library/clarification/`) | ✅ Done |
| 14 | CRM Integration, Retry Queue & Email (Resend) (`app/crm/`) | Done |
| 15 | Public API & Widget Session (`app/api/chat.py`) | Done |
| 16 | Observability (`app/observability/`) | Done |
| 17 | Frontend (React/TS/Vite widget) (`frontend/`) | ✅ Done |
| 18 | Product Intelligence Service (`app/product_intelligence/`) | ✅ Done |
| 19 | Solution Builder & Recommendation Wizard (`app/solution_builder/`) | ✅ Done |
| 20 | Human Handoff & Extended Lead Qualification (`app/handoff/`) | ✅ Done |
| 21 | Multi-language (EN/UR/AR) (`app/language/`) | ✅ Done |
| 22 | Availability & ERP Bridge (`app/availability/`) | ✅ Done |

Alembic migrations so far: `0001_session_state`, `0002_conversation_turns`,
`0003_feature_flags`, `0004_tool_audit_log`, `0005_rag_catalog`, `0006_quotes`,
`0007_crm_leads`, `0008_product_intelligence`, `0009_solution_builder`,
`0010_handoff_requests`, `0011_language_support`, `0012_availability`.

**All 22 modules are now implemented, tested, ingested with real catalog data, and
committed.** There is no "next module" — the backend, frontend, and RAG catalog are all
in a testable state. If resuming work, start by running the full Docker test suite
(`docker compose build backend` then the pytest command below) to reconfirm the 210
passed / 8 skipped baseline, then check `git log --oneline -10` to see the latest work.
Module 16 provides `app.observability`, `/metrics`, `/ready`, Prometheus counters/
histograms, and inline metrics from routing, tools, RAG, quotes, CRM, and `/chat`
latency. Module 21 adds language detection, explicit `/chat/language` session
preference, translation prompt support, `conversation_state.language_code`, and
final-response translation for Urdu/Arabic when `ENABLE_MULTI_LANGUAGE=true`. Module 22
adds the DB-backed local availability service, ERP stub, `product_availability` table,
`check_availability` tool, and `GET /products/{product_id}/availability`.

### Module 18/19 detail (Product Intelligence + Solution Builder)

Module 18 (`app/product_intelligence/`) adds five tools: `compare_products`,
`check_compatibility`, `recommend_accessories`, `find_alternatives`,
`explain_specification` — each gated by its own `enable_*` flag from Module 09 except
`find_alternatives`/`explain_specification` (ungated). `CompatibilityService` checks
`compatibility_rules` (migration `0008_product_intelligence`) first, falling back to LLM
inference (`is_compatible: bool | None`, `None` on LLM failure) only on a rule miss.
`_infer_compatibility_type` in `app/product_intelligence/__init__.py` scans the current
message for keywords in a **fixed, explicit order**
(`("ups", "battery", "controller", "sfp", "rack")`) rather than iterating the
`COMPATIBILITY_TYPES` frozenset directly — the frozenset's iteration order is
hash-dependent, which caused non-deterministic rule lookups when a message mentioned two
keywords at once (e.g. "Is this UPS compatible with the battery?").

Module 19 (`app/solution_builder/`) adds the 5-step `run_wizard` multi-turn flow
(`WizardService.advance`, steps: use_case → device_count → auto-classified
project_size → location → brand_preference), `build_use_case_solution` (seeded
use-case profiles via `scripts/seed_use_case_profiles.py`), and `build_solution` (a
direct one-shot BOM build when `facts.product_interest`/`facts.quantity` are already
known — mirrors the `quote_slots_complete` pattern via the new
`solution_slots_complete(facts, state)` predicate in `app/solution_builder/schemas.py`).
`Orchestrator.on_turn` special-cases an **active wizard session**: before Router
classification, it checks `WizardSessionRepository.get_active` and force-routes to the
`product_recommendation_wizard` intent if one exists — without this, a wizard follow-up
answer like "200 devices" would get reclassified from scratch and the wizard would
silently stall after its first question. The ORM model for a built solution is named
`SolutionRecord` (not `Solution`) to avoid colliding with the `Solution` Pydantic schema.
`app/planner/rules.py`'s `RULE_REGISTRY` maps three intents to these tools:
`product_recommendation_wizard` → `run_wizard`; `use_case_recommendation` →
`build_use_case_solution`; `solution_builder` → `build_solution` if
`solution_slots_complete`, else falls back to `run_wizard`.

### Module 20/21/22 detail (Handoff, Multi-language, Availability)

These three modules' code, migrations (`0010`–`0012`), security policies, and tests were
already complete going into this session; verification here consisted of a full code
read-through plus the green 210-test/8-skipped Docker suite — no functional gaps found.
`app/handoff/handoff_service.py`'s `infer_target_team` resolves the target team from
`conversation_state.handoff_target` first, then keyword-scans the current message
("technical"/"engineer" → technical, "support"/"issue"/"problem" → support, else sales).
`escalation_request` (clarification-exceeded-rounds) and `human_handoff` (user asked for
a person) are deliberately separate intents with separate plans — `escalation_request`
still just returns `["respond"]` per the original v4.1 spec table, it is **not** meant to
route through `initiate_handoff`.

### RAG catalog data (Module 11, refreshed this session)

The original `I power documents/` folder (ipower only, ~43 products) was replaced by
[RAG Knowledge/](RAG%20Knowledge/), which adds a second product line (i-Connect, 3
products) alongside a regenerated i-Power set — 46 products total, sourced from
`makkays_{ipower,iconnect}_{products,models}.csv` plus two full-catalog `.md` files.
Since the CSV schema is richer than `IngestionService.ingest_products`'s generic JSON
format, a new **`scripts/ingest_rag_knowledge.py`** builds `ProductIngestRecord`s
directly from the CSVs (folding each model-code/capacity row into a `specs` entry) and
also seeds a **placeholder price** per product (`_capacity_price`: derived from the top
of the capacity range × a flat per-kVA rate) via `ProductPricingRepository`, since no
real price list exists for this catalog yet. Run it with:

```bash
docker compose run --rm --no-deps backend python -m scripts.ingest_rag_knowledge --source-dir "RAG Knowledge" --tenant-id $DEFAULT_TENANT_ID
```

**Must use `python -m scripts.ingest_rag_knowledge`, not `python scripts/ingest_rag_knowledge.py`**
— the latter fails with `ModuleNotFoundError: No module named 'app'` because Python only
puts the script's own directory on `sys.path`, not `/app`; `-m` runs it as a module from
the working directory instead. The same applies to `scripts/ingest_products_and_docs.py`.
Ingestion is **not idempotent** — re-running it inserts duplicate rows (`ProductRepository.create`
always creates, never upserts-by-name). If you need to re-ingest, first
`DELETE FROM products WHERE tenant_id = ...` (cascades to `product_specs`/`product_pricing`)
and `DELETE` the `products_v1` Qdrant collection, then run the script exactly once.
Ingest the two markdown docs separately via the existing M11 script:

```bash
docker compose run --rm --no-deps backend python -m scripts.ingest_products_and_docs --type docs --source "RAG Knowledge" --tenant-id $DEFAULT_TENANT_ID --doc-type datasheet
```

### Three real bugs found and fixed while wiring up the RAG catalog end-to-end

1. **`app/rag/embeddings.py`** — `BgeM3Embedder` hardcoded `use_fp16=True` regardless of
   device. PyTorch's CPU backend has poor/unoptimized fp16 kernel support, so on this
   CPU-only dev container this made encoding *catastrophically* slow (43 short product
   texts took 30+ minutes and once appeared to hang for 15 hours). This same code path
   runs on every live `/chat` request that hits `retrieve_products`/`retrieve_docs`, so
   it was a real production-facing bug, not just a script problem. Fixed: `use_fp16`
   is now only `True` when `torch.cuda.is_available()`.
2. **`app/rag/qdrant_client.py`** — `QdrantClient(...)` was constructed with no
   `timeout`, so a slow/incompatible server response (this project's qdrant-client
   1.18.0 vs. the pinned `qdrant/qdrant:v1.11.5` server logs a version-mismatch warning
   on every connection) could hang a request **forever** with zero error, rather than
   failing fast. Fixed: explicit `timeout=30`.
3. **`app/orchestrator/orchestrator.py`** — `tool_calls` for the Module 04 turn-audit
   log was built via `result.model_dump(mode="json")` on each raw `ToolExecutionResult`
   (`step`/`success`/`result_summary`/`error`/`product_ids`), but `ConversationTurnCreate.tool_calls`
   requires each item to contain `tool` and `args` keys per the Module 04 spec's
   `{tool, args, result_summary}` shape. Every real turn was silently failing that
   validation and falling back to the spec's designed degradation path
   (`tool_calls: null`, logged as `ERROR`) — meaning the audit log never actually
   captured tool-call data for **any** turn, ever. No existing test caught this since
   nothing exercised `record_turn` with a real multi-step plan result. Fixed: new
   `_tool_call_record(result)` helper builds the correct shape.

Also added a `huggingface_cache` Docker volume (`docker-compose.yml`, mounted at
`/root/.cache/huggingface` on the `backend` service) — without it, every ephemeral
`docker compose run` container had to re-download the ~2.2GB BGE-M3 model from
HuggingFace from scratch, since `docker compose run --rm` containers don't persist
anything outside a named volume.

**Fixed this session:** the Docker image used to install the default PyPI `torch`
wheel, which pulled in the full NVIDIA CUDA toolkit (`nvidia-cudnn`, `nvidia-cusparselt`,
`nvidia-nccl`, `nvidia-cublas`, etc.) as dependencies — multiple GB of downloads this
project never uses, since there's no GPU in this dev environment. The `Dockerfile` now
has a dedicated `RUN pip install --no-cache-dir torch --index-url
https://download.pytorch.org/whl/cpu` step **before** `pip install -r requirements.txt`,
so `FlagEmbedding`'s `torch>=1.6.0` requirement is already satisfied by the CPU-only
build (`2.13.0+cpu`, ~192MB) by the time it's checked — no `nvidia-*` packages get
pulled in at all. Verified: full test suite (210 passed/8 skipped) and a live `/chat`
smoke test both pass unchanged after the switch.

### Module 17 detail (frontend)

`frontend/` is a React 18 + TypeScript + Vite + Tailwind + TanStack Query + React
Router + Axios chat widget, run directly on the host with Node (v18+) — it is **not**
part of the Python Docker image and has no Dockerfile of its own. `npm install` then
`npm run dev` (port 5173) or `npm test` (Vitest) from inside `frontend/`.
`frontend/.env.local` (gitignored) must hold `VITE_API_BASE_URL` and
`VITE_SITE_API_KEY` (same value as backend `.env`'s `SITE_API_KEY`) — see
`frontend/.env.example`. `useChat` (`src/hooks/useChat.ts`) owns optimistic send, the
429 cooldown countdown, and error/retry state; `api/client.ts` sets
`withCredentials: true` (required for the cross-port session cookie in local dev) and
the `X-Site-Api-Key` header. `types/generated.ts` is produced by
**`python scripts/generate_typescript_types.py`** (introspects `app.api.chat`'s
`ChatRequest`/`ChatResponse` Pydantic models) — this script didn't exist before this
session even though Module 15's spec called for it; re-run it whenever those models
change. `types/chat.ts` is hand-maintained and re-exports the generated types plus the
frontend-only `ChatMessage` shape, so regeneration never clobbers hand-written code.
Also added a root `.dockerignore` (didn't exist before) once `frontend/node_modules`
started bloating every backend build context by 100+MB.

Redesigned to a white theme this session (branded header with an "Online now" status
dot, avatar bubbles, a typing indicator shown while `isLoading`, a pill-shaped input
with an icon send button, polished clarification chips) — purely visual, no props/API
contracts changed; all `data-testid`s, ARIA labels, and the `/send/i` accessible button
name that the existing tests assert on were preserved. `npm run build` and all 22
Vitest tests pass after the redesign.

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
updated to match. Built-in tools (`respond`, `compare`, `request_missing_slots`) are
registered from `executor.py`; M11 registers `retrieve_products`/`retrieve_docs`; M12
registers `generate_quote`; M14 registers `create_lead`.

`Orchestrator.on_turn` (`app/orchestrator/orchestrator.py`) is now wired for the
public API path: load facts/state/recent turns, extract facts, resolve flags, classify,
clarify when confidence is low, plan, execute tools, record the turn, and commit. Module
16 metrics are wired around this flow without changing its control structure.

**Two critical bugs found via live user testing (fixed, see commit "Fix critical
chatbot bugs"), not caught by the unit/integration suite because those use fakes that
never exercise a real multi-turn conversation:**

1. `FactsExtractor`'s LLM-sourced conflict resolution used to *always* keep the old
   value once a field was set, regardless of how explicitly the user corrected
   themselves later (e.g. "No, I need a UPS" after an earlier camera mention) — the
   bot would get permanently stuck on the first product ever mentioned, for the rest
   of the session. Fixed with `_explicit_in_message()`: a conflicting value now
   replaces the old one when a meaningful word of it appears in the *current*
   message, matching readme.md §6's actual contract ("explicit in the latest user
   message"), not just always preserving.
2. `_respond_tool` (the built-in `respond` step in `app/tools/executor.py`) used to
   call `build_llm_messages` with only `facts`/`conversation_state` — dropping the
   actual current user message, prior turns, and retrieved RAG sources entirely. This
   directly contradicted Module 10's own spec ("`respond` calls the LLM with full
   context"). The practical effect: the LLM composing the final reply couldn't tell
   it had already asked something (repeated questions), couldn't see what the user
   literally said (broke understanding of code-switched/Roman-Urdu input), and had
   no grounding in the real catalog (hallucinated confident answers about products
   never carried). Fixed: `SessionContext` gained a `recent_turns: tuple[ConversationTurnRead, ...]`
   field (populated by the Orchestrator from the same turns it already loads for
   FactsExtractor/Router), and `_respond_tool` now passes `recent_turns`,
   `retrieved_sources` (parsed from `retrieve_products`/`retrieve_docs`' JSON
   `result_summary`), and `latest_user_message=session.message` through.

Also added a first-turn greeting instruction to `prompt_library/system/base_v1.md`
(edited in place — version "1" is pinned at the `app/tools/executor.py:189` call
site, so there's no separate `base_v2.md` to create).

**Known secondary gap, not yet fixed:** `_extract_deterministic`'s quantity regex
(`app/router/facts_extractor.py`) only matches `"<N> units/pcs/pieces/qty/quantity"` —
natural phrasing like "10 computers" or "15 employees" silently fails to extract a
quantity at all (falls through to the LLM extractor, which may or may not catch it).
Low severity compared to the two bugs above; flagged for a future pass if quantity
capture proves unreliable in further testing.

### Four more bugs found via a second round of live user testing

1. **Wizard was inescapable.** An active `product_recommendation_wizard`/
   `solution_builder` session force-routed *every* subsequent message back into
   itself regardless of content — including explicit refusals like "stop talking
   to me." Fixed with `_looks_like_wizard_escape()` in
   `app/orchestrator/orchestrator.py`: a narrow, deterministic check (Tier1's own
   `human_handoff`/`escalation_request` patterns plus explicit cancel/dismiss
   keywords, including a few Roman Urdu equivalents — `bas`, `chup`, `dafa`,
   `khafa`/`lkhafa`) that breaks out via the new
   `WizardSessionRepository.abandon()`. **Do not** use the general LLM intent
   classifier for this check — a first attempt did, and it broke legitimate
   one-word wizard answers ("power", "10") by guessing low-confidence
   `out_of_scope` for them out of context.
2. **Wizard/comparison intents leaked outside Makkays' catalog domain.** "Help
   me choose a MacBook" matched `product_recommendation_wizard`'s Tier2
   description; "compare MacBook Air vs Pro" matched Tier1's bare `\bcompare\b`
   keyword. Both confidently misrouted into plans for a product Makkays doesn't
   sell. Fixed: `classify_intent_v1.md` now explicitly scopes every intent
   except `out_of_scope`/`human_handoff` to Makkays' product categories, and
   `Tier1RuleEngine` (`app/router/rules.py`) defers to Tier2 for
   `_DOMAIN_SENSITIVE_INTENTS` (comparison/compatibility/accessory/alternative/
   spec-explainer) unless the message also contains a catalog-relevant keyword.
3. **No targeted follow-up questions, and out-of-scope replies engaged with the
   off-topic content instead of declining it.** Two new `base_v1.md` rules:
   ask 2-3 specific missing-detail questions (power load, phase, budget, ...)
   when a tailored solution is wanted — never during small talk — and
   explicitly decline (not answer) when `conversation_state.current_intent` is
   `out_of_scope`, since giving the LLM full conversation context (the earlier
   fix) meant it would otherwise happily discuss a competitor's product in
   detail.
4. **Comparison tables/headings rendered as raw text.** The LLM was already
   producing correct Markdown; the frontend just displayed it as plain text
   (literal `|` and `**` characters). Added `react-markdown` + `remark-gfm` to
   `frontend/` with styled component overrides in `MessageBubble.tsx` — user
   messages stay plain text, only assistant messages render Markdown.

**Groq rate limits during heavy manual testing:** each turn makes 2-4 Groq
calls (facts extraction, intent classification, respond, sometimes
translation), so rapid back-to-back manual testing can hit the free-tier rate
limit (`429 Too Many Requests`). This degrades gracefully — `Tier2Classifier`
and `FactsExtractor` both catch the failure and fall back to a safe default
(`out_of_scope`/`confidence=0.0` for the classifier) rather than crashing — but
it can look like a "stuck repeating the same reply" bug when it's actually just
the LLM being unavailable for a few seconds. Check `docker logs
makkays-chatbot-backend` for `groq_http_error`/`status_code: 429` before
assuming a classification/facts bug when live-testing rapidly.

### Structured capacity matching and exhaustive category listing

Two more real gaps found via live testing, both architectural (not prompt/knowledge-doc
issues — deliberately left those alone per the user's explicit request):

1. **"I need a UPS for my 5kVA load" returned wrong products.** Vector similarity search
   has no concept of numeric range containment, and `capacity_range` was stored as an
   unstructured string ("1-10KVA") with no queryable numeric form, so nothing could ever
   check "does 5 fall within 1-10". Fixed with a new `app/rag/capacity.py`:
   `parse_capacity_range` turns the catalog's free-text spec into a `(min, max, unit)`
   tuple; `parse_capacity_requirement` does the same for a client's stated figure in
   free text ("5kVA", "5000VA", "5kW" — kW/W are treated as approximately equal to kVA —
   or "20A"). `Product` gained real `capacity_min`/`capacity_max`/`capacity_unit`
   columns (migration `0013_product_capacity`), auto-derived by
   `ProductRepository.create()` from any `capacity_range` spec entry — no ingestion
   script needs to compute this itself. `scripts/backfill_product_capacity.py` populated
   it for the 46 products already ingested (42 got a value; the 4 battery products have
   no `capacity_range` spec at all — rated in Ah, not kVA/A — and are correctly left
   null, excluded from capacity matching rather than mismatched). `FilterExtractor.extract`
   now takes a `raw_message` param (the current turn's literal text) and parses a
   requirement from it — the reconstructed `query` it used before (often just
   `facts.product_interest`, e.g. "UPS system") may not carry the figure the client
   actually typed this turn. `ProductRepository.find_by_filters` adds a real
   `capacity_min <= requirement <= capacity_max` SQL condition when one is present.
2. **A closely-related, genuinely pre-existing bug this surfaced**: a bare "UPS" mention
   set a `spec_filters["category_hint"] = "ups"` entry, but no product was ever
   ingested with a `category_hint` spec key — the generic `spec_filters` loop in
   `find_by_filters` requires an EXISTS match for every entry, so this made the *entire*
   SQL narrowing query return zero candidates for **any** UPS-related question, silently
   falling back to fully unscoped semantic search the whole time (candidate_ids=[] is
   treated as "no scoping" by `_product_qdrant_filter`). This was actively defeating the
   new capacity fix until caught via direct debugging. Fixed: a bare "UPS" mention now
   resolves directly to the real category name (e.g. "UPS Solutions") via
   `_first_category_containing`, instead of a fake spec filter.
3. **"List all your UPS products" only ever showed 5.** Every retrieval was hard-capped
   at `min(search_limit_default, search_limit_max)` = 5, because retrieval is
   fundamentally "top-K by vector similarity," not "enumerate everything." Fixed:
   `ExtractedFilters.list_all` (detected by `FilterExtractor` via phrasing like "list
   all", "every option", "what products do you have") makes
   `RetrievalService.retrieve_products` bypass Qdrant entirely and call the new
   `ProductRepository.list_products(category=..., brand=..., limit=settings.rag.list_all_limit)`
   (default 50) — a plain SQL query, ordered by name, with no vector-search truncation.
4. **The response LLM never saw specs at all.** `ProductResult` only ever carried
   `product_id/name/brand/category/score`. Now carries a `specs: list[{key, value}]`
   field too (`ProductRepository.get_specs_for_products`, batched), populated in both
   the normal vector-search path and the new list-all path — grounding for
   comparisons/recommendations instead of the LLM inferring numbers from the name string.

Live-verified: "I need a UPS rated for 5kVA" now correctly narrows to the 14 products
whose range actually contains 5, with real spec data in context; "list all your UPS
products" now returns the complete ~20-product category instead of 5.

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

The `backend` service also mounts a `huggingface_cache` volume at
`/root/.cache/huggingface` — this persists the ~2.2GB BGE-M3 embedding model download
across container runs, including ephemeral `docker compose run --rm` invocations (e.g.
ingestion scripts). Without it, every fresh container had to re-download the full model
from HuggingFace from scratch.

**Run tests inside Docker, not the host Python** — the host interpreter doesn't have
project deps installed:

```bash
docker compose run --rm --no-deps backend python -m pytest -q
```

Source is baked into the image at build time (no volume mount), so **rebuild before
testing** whenever app code changes: `docker compose build backend` first, then run
the command above (or `docker compose up -d backend` to also refresh the live container).

Since Module 11, `requirements.txt` pulls in `FlagEmbedding`, which drags in `torch`
(a ~530MB wheel) — a clean `docker compose build backend` can take 30-60+ minutes on a
slow connection, with long stretches of no visible output while pip resolves metadata.
Don't assume a build is hung; check `docker image inspect makkays_chatbot-backend:latest
--format '{{.Created}}'` against the current time before concluding a build never
finished. Never run multiple `docker compose build` invocations concurrently (they
compete for bandwidth and CPU) — use a single backgrounded build and wait for it.

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
- [RAG Knowledge/](RAG%20Knowledge/) — real i-Power + i-Connect product/model data
  (`makkays_{ipower,iconnect}_{products,models}.csv`, `.md` catalogs) ingested via
  `scripts/ingest_rag_knowledge.py` (products, with placeholder pricing) and
  `scripts/ingest_products_and_docs.py` (the two markdown docs) for M11's RAG catalog.
  Replaced the original `I power documents/` folder this session. The two `.py` files
  in that folder (`convert_products_v3.py`, `resolve_flagged.py`) are the external,
  one-off pandas scripts that generated these CSVs from a source spreadsheet — they
  reference `/mnt/user-data/uploads/...` and `/home/claude/...` paths and are not meant
  to be re-run inside this repo; they're kept only for provenance.

## User preferences

- Prefers being told exactly what to do next in sequence, not a menu of options.
- GitHub repo: <https://github.com/aibasit/makkays_chatbot>
