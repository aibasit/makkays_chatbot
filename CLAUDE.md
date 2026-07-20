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
2. **Wizard/comparison intents leaked outside Interconnect Solutions' catalog
   domain.** "Help me choose a MacBook" matched `product_recommendation_wizard`'s
   Tier2 description; "compare MacBook Air vs Pro" matched Tier1's bare
   `\bcompare\b` keyword. Both confidently misrouted into plans for a product
   Interconnect Solutions doesn't sell. Fixed: `classify_intent_v1.md` now
   explicitly scopes every intent except `out_of_scope`/`human_handoff` to
   Interconnect Solutions' product categories, and
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

### i-power catalog rebuilt from a corrected source, company rebrand, and a third round of bug fixes

The company's actual name is **Interconnect Solutions**, not "Makkays" — every
customer-facing and business-logic reference to "Makkays" (the system prompt's
self-identification, the classification prompt's domain scoping, the frontend
widget header/avatar, the quote PDF footer, the `brand` column ingestion scripts
write, and `app/router/rules.py`'s domain-keyword list) has been renamed. Existing
`products.brand`/`products.description` rows were fixed in place with a `UPDATE`
rather than a full re-ingest. "Makkays" only remains where it's a literal
identifier, not a business-name claim: the repo/package name `makkays_chatbot`,
Docker container/image names, the `RAG Knowledge/makkays_{domain}_*` file naming
convention, and the GitHub URL.

`RAG Knowledge/makkays_ipower_products.csv`/`makkays_ipower_models.csv`/
`makkays_ipower_products.md` were rebuilt from a new, more authoritative source,
`ipower_products_standard.csv` (a direct i-sol.co.uk product-page export, ~480
columns of raw spec-sheet data, 63 rows) via a new **`RAG Knowledge/build_ipower_from_standard.py`**
(kept for provenance alongside `convert_products_v3.py`) — raising the ingested
i-power catalog from 43 to 66 products. Highlights: `display_name` is now always
the row's full, unique product name (the old data's generic "{series} {phase}
({capacity})" label let 6 different T-4001 variants collide under one name);
`capacity_range` is computed from each product's actual Model/Capacity columns
(with a same-script disjoint-Model(2)/Capacity(2) merge for the handful of rows
where the primary table only covers part of the real range, e.g. T-4101
"(1-15KVA)" needed both tables to reach 15kVA) instead of a separately curated
label that could drift out of sync; a literal scrape-artifact duplicate row
("... - copy") is detected and dropped; and four entire categories the old data
never had are now included — Line Interactive Series, Lithium Battery UPS Series,
Inverter Solutions as its own product line (not folded into "UPS Solutions"),
Customized Power Solutions, and the full Battery Storage / Accessories ranges.
Narrative fields (`short_description`/`product_info`/`applications`) are carried
over from the old catalog wherever a product's model codes overlap with an old
row; the standard export has no marketing copy at all, so genuinely new products
get a short factual description generated from structured fields instead.
**One caveat inherited from the standard file itself**: a few AVR products'
declared name-range is wider than the models that row actually lists (e.g.
"AVR-1002 Servo 3-Phase (100-3000KVA)" only lists the top-5 models, 1000-3000KVA)
— `capacity_range` is grounded in the real listed models, not the name, so it can
legitimately read narrower than the title.

**A genuine content gap found via live testing**: the standard file's "Lithium
Battery Pack" rows only cover 2 variants (RB-LI-192-100, RB-LI-48-25) — it silently
drops 3 higher-voltage packs (512VDC/100Ah, 480VDC/100Ah, 512VDC/200Ah) that a
prior, richer source had captured and that were live in the catalog before this
rebuild. A customer asking about a 512VDC battery got told outright it didn't
exist. `build_ipower_from_standard.py`'s `_LEGACY_BATTERY_SUPPLEMENT` restores
these 4 products (with their real model codes/descriptions preserved from git
history) rather than silently dropping them — this is the one place the script
merges in data the standard export itself doesn't have, since it's a partial
snapshot for this one sub-range, not a correction of it. **If you re-run
`build_ipower_from_standard.py` against a future, more complete standard export,
re-check whether this supplement is still needed** — don't assume it always will be.

**Two more bugs found via live testing this round, unrelated to the catalog rebuild:**

1. A bare greeting ("Hello") had no product-domain keyword for Tier2's
   domain-scoping instructions to recognize, so it was reasonably classified
   `out_of_scope` — which then triggered the "decline, don't engage" out-of-scope
   prompt rule and produced an oddly curt "that seems off-topic" reply to a
   simple hello. Fixed with a `_GREETING_ONLY_PATTERN` short-circuit at the very
   top of `Tier1RuleEngine.match()` (`app/router/rules.py`) that classifies a
   bare hi/hello/hey/salam/good-morning-style message as `sales_inquiry` before
   Tier2 is ever called — keeps the existing first-turn-greeting instruction in
   play without the false off-topic framing, and saves an LLM call besides.
2. `ENABLE_MULTI_LANGUAGE` was `false` in `.env` (the code default), so Module
   21's Urdu/Arabic translation path was never actually reachable in this dev
   environment despite being fully implemented — flipped to `true`.

**Not a code bug, but the dominant symptom during this round's live testing**:
a Groq 429 rate-limit storm (`groq_http_error`, `status_code: 429`) starting
mid-session caused `Tier2Classifier`/`FactsExtractor` to fail and fall back to
their safe defaults repeatedly — this alone explains the "keeps asking the same
clarification question," "I could not complete that request," and "doesn't
translate to Urdu" symptoms far more than any of the above; always check
`docker logs makkays-chatbot-backend` for recent 429s before chasing a
classification/language bug. `GROQ_API_KEY` was rotated to a fresh key.

### The wizard hallucinating competitor products, and wiring in the model-level UPS/Battery/AVR catalog

**A severe bug found via live testing**: the Solution Builder Wizard's "suggest
me a UPS" flow invented entirely fictional competitor products (Eaton, APC,
Vertiv model numbers with fabricated specs) instead of using the real catalog.
Root cause: `BOMService.category_quantities` always required both a "switch"
and a "ups" line item (a leftover from the original spec's networking+power
catalog assumption), but this tenant's catalog has no "switch" category at
all — so the wizard's `run_wizard` step always failed, and since its plan
(`["run_wizard", "respond"]`) has no `retrieve_products` step for `respond` to
fall back on, the LLM had zero real product data and filled the gap itself.
Fixed in two layers: `BOMService` now skips a category with no real match
instead of failing the whole solution (`app/solution_builder/bom_service.py`),
with a category-name alias chain (try the literal generic name first, then a
real-catalog name like `"UPS Solutions"`) so it works against both a
literally-named test catalog and this tenant's real one; and `_respond_tool`
(`app/tools/executor.py`) now injects an explicit "no real match was found —
don't invent one" notice into context whenever any grounding step fails, as a
defense-in-depth measure for any future case like this. The wizard also never
asked for a capacity/kVA figure directly — `WizardRequirements` gained
`capacity_requirement`/`capacity_unit`, recovered from the conversation via
the same `app.rag.capacity.parse_capacity_requirement` the plain sales_inquiry
path already uses (`wizard_service._recover_capacity_requirement`), so the BOM
line item is now sized to what the visitor actually asked for.

**Separately, the user supplied three JSONL RAG exports** (`Updated Knowledge
files/ipower_{UPS,Battery,AVR}_RAG.jsonl` — pre-chunked, one JSON object per
model/series/overview, with rich per-model metadata: `capacity_kva`, `phase`,
`form_factor`, `power_factor`, `battery_configuration`, and equivalents for
battery/AVR). First ingested into three **standalone** Qdrant collections
(`ipower_ups_v1`/`_battery_v1`/`_avr_v1`, via new `scripts/ingest_jsonl_knowledge.py`)
with payload indexes on every filterable field, purely to prove exact-metadata
filtering + vector search work together — validated with real queries against
all three collections, including confirming a genuine data quirk (15 UPS model
codes are legitimately cross-listed under two different series; a naive
`uuid5(model_code)` point ID would have collided and silently dropped one of
each pair — fixed by keying on `(doc_type, id, series_id)` instead).

**Then wired into the live chatbot** (this is what `retrieve_products` and
every other tool actually reads from) via new
**`scripts/ingest_ipower_model_catalog.py`**, which replaced the old 56
series-level UPS/Battery/AVR products in Postgres + `products_v1` with **239
model-level** ones (181 UPS + 6 Battery + 52 AVR) — one row per real SKU
instead of one per series range. This is what makes an *exact* `capacity_kva
== 6` match possible: a series-level row only ever had a range (e.g.
"1-10kVA"); a model-level row's `capacity_range` spec is a single point value,
which `ProductRepository.create()` already auto-parses into `capacity_min ==
capacity_max`, turning the existing range-based capacity filter into an exact
match for free — no schema change needed. `phase`/`form_factor`/etc. ride on
the existing generic `spec_filters` EXISTS mechanism in
`ProductRepository.find_by_filters`; `FilterExtractor` gained phase detection
("single phase"/"three phase" wording → `spec_filters["phase"]"`) to drive it.
The `Battery Storage Power Solutions` category was renamed to `Battery
Solutions` to match the new source's own naming (nothing in the code hardcoded
the old name). The standalone `ipower_*_v1` collections from the first pass
are untouched and remain a validated reference; they aren't what the live
chatbot queries.

**Two more duplicate-name bugs found and fixed while wiring this in** — same
family of issue as the earlier catalog rebuilds, new instance each time
because a fresh source has its own naming quirks:

1. The JSONL `title` field encodes series/capacity/phase/form_factor but not
   `battery_configuration` or `power_factor`, so up to 8 real, distinct SKUs
   (e.g. "built-in battery" vs "long back-up" variants of the same T-4001
   6kVA tower) shared the exact same title — confirmed live when `respond`
   fell back to showing raw `product_id` UUIDs in a comparison table because
   it had no distinguishing name to use.
2. Appending just the model code wasn't enough either: the same 15
   cross-series model codes from the standalone-collection work above are
   *also* cross-listed in this pass, with identical titles each time (e.g.
   `OH1010T91607S` under both T-4001 series 1 and series 5).
Fixed by appending `"{model_code} · series {series_id}"` to the title,
verified unique across all 239 records before re-ingesting.

Live-verified after wiring: "single-phase UPS rated for 6kVA" and "three phase
AVR for 30kVA" both return correctly-filtered real products with readable
names; the wizard's "power / 20 / London / no" flow now recommends a real,
exactly-20kVA product instead of hallucinating or saying "no match"; "list all
your UPS Solutions products" summarizes sensibly against the much larger
181-product category instead of dumping all of them. Full suite: 297 passed,
8 skipped.

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

### Exact model-code lookups: model_code spec, and four more real bugs found chasing it live

A user bug report gave three exact failing queries (their literal phrasing) with
known-correct expected specs: "What are the complete specifications of UPS model
OH1005T10400S?", "...battery model RB-LI-512-200?", "What are the technology, capacity,
phase, and voltage class of AVR model T300140240S?". All three now return correct,
grounded answers — but getting there required five separate fixes, not the one
originally diagnosed, because each fix uncovered the next failure underneath it once
tested with the user's literal wording rather than a rephrased version.

1. **No queryable model-code field at all.** A model code only ever existed inside
   `products.name`/`description` (unsearchable/unreliable for vector search) — dense
   embeddings can't reliably pinpoint one exact alphanumeric code among many
   near-identical descriptions. Fixed: every ingested UPS/AVR/Battery product now also
   gets a dedicated `model_code` spec (`{"key": "model_code", "value": metadata["id"]}`
   in `scripts/ingest_ipower_model_catalog.py`); `ProductRepository.get_distinct_model_codes`
   (new) fetches the live vocabulary; `FilterExtractor._first_model_code_match` (single
   combined regex, longest-code-first to avoid substring collisions) sets
   `spec_filters["model_code"]` whenever the current message mentions one, which
   `find_by_filters`'s existing generic EXISTS-based spec matching then narrows on for
   free. All 239 UPS/Battery/AVR products were deleted and re-ingested to add this spec.
2. **`specification_explainer`'s plan never retrieved products, only docs.** The exact
   phrasing above reads, to the classifier, like "explain a spec term" rather than
   "sales_inquiry" — but its plan (`plan_specification_explainer`) and tool
   (`explain_specification_tool`) only ever consulted `retrieve_docs`, so an exact
   model-code question landed in a code path with zero product data to ground an answer
   in. Fixed: the plan now retrieves products too; `explain_specification_tool` gained
   `_product_context_from_result()` and combines product + doc context;
   `SpecificationService`'s system prompt now explicitly requires admitting "I don't
   have that model's specifications" for a named model with no matching context,
   instead of treating it as generic industry knowledge to answer from confidence alone.
3. **`retrieve_products`'s security policy never allowed `specification_explainer` to
   call it at all.** Even after fix #2 added the step to the plan, Module 10's policy
   layer (`security_policies/retrieve_products.yaml`) denied it outright
   (`tool_policy_denied`, `clause_failed: "intent"`) since that intent was never in
   `allowed_intents` — a plan can only ever do what its steps' policies permit. Fixed:
   added `specification_explainer` to the policy file's `allowed_intents`.
4. **All five Module 18 tools were never actually registered in the live app, ever.**
   `compare_products`, `check_compatibility`, `recommend_accessories`,
   `find_alternatives`, and `explain_specification` all self-register via
   `tool_registry.register(...)` as a side effect of importing `app.product_intelligence`
   — but `app/tools/__init__.py`'s `register_hooks` (called once at FastAPI startup,
   the single place that's supposed to trigger every module's tool self-registration)
   only ever imported `app.rag`/`app.availability`/`app.crm`/`app.handoff`/`app.quotes`,
   never `app.product_intelligence`. This silently affected the live app from the moment
   Module 18 was built — the only reason it wasn't caught by the test suite is that
   `tests/integration/test_product_intelligence_tools.py` imports
   `app.product_intelligence` directly, polluting the shared `tool_registry` singleton
   and masking the gap for every test that ran after it. Product comparison and
   compatibility checking had, as far as can be determined, never actually worked in a
   live conversation before this fix. Fixed: `register_hooks` now also
   `from app import product_intelligence  # noqa: F401`. Regression test added:
   `test_app_startup_registers_all_module18_product_intelligence_tools` in
   `tests/integration/test_app_startup.py`, which boots the real app via `TestClient`
   (not a direct import of `app.product_intelligence`) so it actually catches a missing
   registration rather than being fooled by the same pollution that hid the original bug.
5. **An exact model-code question false-triggered "list all" and silently dropped the
   model_code filter.** `_LIST_ALL_PATTERN` matches "complete/full/all/every"
   within ~30 chars of "products/options/models/...". "complete specifications of
   **battery model** RB-LI-512-200" matches on "complete ... model" — a coincidental
   keyword collision, not an actual listing request — and the list-all branch bypasses
   `find_by_filters` (and therefore the model_code filter) entirely, dumping up to
   `list_all_limit` (50) unrelated products instead of the one exact match. This is why
   the UPS query (#1 above) happened to work — the right product was coincidentally
   inside the first 50 results — while the battery query didn't. Fixed: an exact
   model-code match now unconditionally overrides list-all detection
   (`list_all = model_code is None and bool(_LIST_ALL_PATTERN.search(...))`) in
   `app/rag/filter_extraction.py`, since a specific model code always means one specific
   product, never a listing request.
6. **`_query_from_session` raised and skipped retrieval entirely when the LLM facts
   extractor didn't populate `product_interest`.** The AVR query (#3) has no
   generic "I need a..." phrasing for the LLM extractor to latch onto, so
   `facts.product_interest` and `conversation_state.last_question` were both `None` —
   `_query_from_session` (`app/rag/retrieval_service.py`, shared by both
   `retrieve_products` and `retrieve_docs`) treated that as a hard error rather than
   falling back to the literal current message, even though the message itself (which
   is always present) carries everything the model-code filter needs. Fixed: falls back
   to `session.message` before raising.

Net effect: re-ingested the 239-product UPS/Battery/AVR catalog with `model_code` specs,
6 separate code fixes across 5 files, 4 new regression tests, full test suite re-verified
green (306 passed / 8 skipped) after every change, and all three of the user's original
exact bug-report queries plus prior scenarios (capacity+phase exact match, list-all,
AVR category resolution, the wizard flow, and — for the first time ever — live product
comparison and compatibility checking) re-verified working end to end.

### A stale-fact bug the isolated tests above didn't catch, and a formatting gap

All three exact bug-report queries above were re-verified with a **fresh session per
query** (a new `session_id`, no conversation history) — which is exactly why a real bug
survived that verification: the user then asked all three questions **in the same
continuing conversation** (one browser session, one after another) and the third answer
(AVR T300140240S) came back as a verbatim repeat of the second answer's battery specs.
Reproducing with a shared cookie jar across all three requests (rather than one-off
`curl` calls) confirmed it immediately — a gap in verification methodology, not just
in the code, and a reminder that a model-code fix must always be re-tested as a
multi-turn conversation, not just as isolated single-turn requests.

Root cause: `facts.product_interest` is only overwritten when the LLM facts extractor
recognizes an explicit conflict, so after asking about UPS OH1005T10400S then battery
RB-LI-512-200, `product_interest` was still `"RB-LI-512-200"` on the third turn (the
AVR question never explicitly contradicted it in a way the extractor caught). Two
places then used that stale value in a way that pointed everything at the wrong
product:

1. **`FilterExtractor._first_model_code_match`** was called on `combined_text =
   f"{query} {raw_message}"`, and since the (stale) `query` came first in the string,
   the regex's `.search()` matched the leftover `"RB-LI-512-200"` before it ever
   reached `"T300140240S"` later in `raw_message` — silently retrieving 5 battery
   products instead of the one AVR product actually asked about. Fixed in
   `app/rag/filter_extraction.py`: the model-code check now searches `raw_message`
   (this turn's literal text) *first*, only falling back to `combined_text` if
   `raw_message` has no match — `raw_message` is always the true current-turn text,
   never stale.
2. **`explain_specification_tool`** (`app/product_intelligence/__init__.py`) built its
   `spec_term` — the literal question handed to the LLM — from
   `facts.product_interest or conversation_state.last_question`, completely ignoring
   `session.message`. Even after fix #1 correctly retrieved the AVR product's specs
   into context, the LLM was still asked to explain `"RB-LI-512-200"` and (correctly,
   per its own honesty instruction) said it had no data for that — for the wrong
   product. Fixed: `spec_term` now prioritizes `session.message` (this turn's literal
   text) over the stored facts.

**Separately, a formatting complaint**: exact-spec answers were single narrative
paragraphs ("The X is a Y kVA... it's designed for... it can also...") instead of a
scannable spec list — traced to `SpecificationService._SYSTEM_PROMPT`
(`app/product_intelligence/specification_service.py`) capping every answer at "2-4
sentences", a constraint written for short generic-term explanations ("what is PoE")
that was wrongly also governing exact model-spec lookups. Fixed: the prompt now
instructs a Markdown heading + one bullet per spec field when the question names a
specific product, keeping the short-prose style only for genuine generic-term
questions with no product context.

Re-verified end to end with a real shared-cookie multi-turn session (not three
isolated requests): all three original queries now return correct, per-product,
cleanly bulleted specs in sequence, with no cross-question bleed. Full suite: 307
passed, 8 skipped.

### Category-aware constraint system: replacing the flat capacity filter with typed, operator-bearing fields

The user supplied a detailed design doc (a "category-aware constraint system with
proper units, operators, exclusions, and controlled fallback behavior") calling out
the flat `capacity_requirement`/`capacity_unit` pair as unable to safely tell kVA, A,
Ah, and kWh apart, or express "at least"/"between"/"not"/"nearest" style requests.
Implemented as an **additive** layer alongside the old mechanism (not a replacement)
— `ExtractedFilters` keeps `capacity_requirement`/`capacity_unit` (still used directly
by `app/solution_builder/bom_service.py`) and gains a new `constraints: list[Constraint]`
field.

**Storage**: migration `0014_structured_product_specs` added typed columns to
`products` — `capacity_kva`, `rated_power_kw`, `power_factor`, `current_a`,
`phase_input_count`, `phase_output_count`, `voltage_class_v`, `nominal_voltage_vdc`,
`capacity_ah`, `energy_kwh`, `max_discharge_power_kw`, `max_parallel_units`,
`service_life_years` — alongside the existing EAV `product_specs` table, which stays
the store for genuinely categorical fields (`technology_key`, `form_factor_key`,
`battery_mode`, `chemistry_key`, `series`). Typed columns exist because the old EAV
`spec_value: TEXT` can't safely support `gte`/`lte`/`between` without per-key casting;
EAV stays for `eq`/`not_eq`/`in` string matching, which needs no schema change per field.

**`Constraint`** (`app/rag/schemas.py`): `{field, operator, value, value_max, values,
unit, hard, source_text}`, operators `eq/gte/lte/between/in/not_eq/nearest`. `nearest`
is deliberately *not* a `WHERE` clause — `ProductRepository`'s `_apply_nearest_ordering`
applies it as `ORDER BY ABS(column - value)` (with a capped candidate limit, so an
unconstrained "nearest" doesn't hand Qdrant the entire category to re-rank).

**Category-aware allowlists** (`app/rag/filter_extraction.py`'s
`_ALLOWED_CONSTRAINT_FIELDS`): category is resolved *before* any constraint is
attempted, and each field only fires for its own category's allowlist (ups/avr/
battery) — an unresolved category means every category-scoped detector stays silent
rather than guessing which category's units a bare number belongs to. This needed a
third category abbreviation entry (`"battery"` → `"Battery Solutions"`, alongside the
existing UPS/AVR ones) since a bare "battery" mention doesn't literally contain the
full stored category name — found live: "a 410V battery" produced zero constraints
until this was added, the exact same bootstrapping gap the UPS/AVR abbreviations were
originally added to fix.

**Battery voltage tolerance**: "410V battery" must match a real 409.6V product; "512V
battery" must match 512V exactly. Implemented as a fixed table of known nominal
families (48/96/192/230/400/409.6/480/512V, ±2%) rather than a blanket percentage —
snaps to the nearest known family only within tolerance, so it can't drift two
genuinely distinct voltage classes together.

**`ProductRepository`** gained `_build_conditions` (shared by `find_by_filters` and
`list_products`, so the two SQL paths can't silently drift apart on what "matches"
means — this is what let `list_products` finally respect constraints, not just
category/brand: "list all tower UPS" used to list the entire UPS category), a
`_CONSTRAINT_COLUMNS`/`_CATEGORICAL_SPEC_KEYS` dispatch table, and
`get_distinct_spec_value_map` (one batched query for all live categorical vocabularies,
not one query per field).

**Zero-result relaxation** (`RetrievalService._relax_and_retry`): when the full hard
constraint set matches zero rows, drops the *lowest-priority* constraint (a fixed
`_RELAXATION_PRIORITY` order — sub-category/battery-mode/form-factor relax before
phase/capacity/voltage, since those are the more defining requirements) and retries,
one at a time, stopping at the first constraint whose removal produces results — never
silently drops straight to an unscoped search. The dropped constraint surfaces as a
`{"notice": "..."}` sentinel appended to `retrieve_products`' own JSON result list —
`app.tools.executor._retrieved_sources` already flattens any dict in that list into the
`respond`/`explain_specification` LLM context as-is (the same channel the existing
"no real match, don't invent one" notice uses), so this needed zero new plumbing.

**Removed** `port_count`/`poe` detection entirely — leftover from the original
hypothetical networking-catalog spec; this power catalog has no such fields, and a
dead detector risked confusing zero-result queries for no benefit.

**New ingestion**: `scripts/ingest_ipower_refined_catalog.py` reads
`Updated Knowledge files/ipower_{UPS,AVR,Battery}_refined.xlsx`'s "RAG Chunks" sheet
(the same 239 model-level products as the JSONL pipeline it supersedes, but sourced
from real typed spreadsheet columns instead of only free-text spec strings) and
populates *both* the typed columns (what filtering reads) and the EAV specs (what
grounds the final LLM answer — `ProductRepository.get_specs_for_products` only ever
reads `product_specs`, never the typed columns, so a field that's only a typed column
would filter correctly but never appear in a spec-explainer/comparison answer). Each
row's `RAG Chunk Text` column — pre-authored, self-contained prose fusing specs +
series description + applications — is used directly as both `description` and the
embedding input text, rather than reconstructing prose from specs like the old script
did. `pandas`/`openpyxl` added to `requirements.txt` for this.

**Two real bugs found only via live multi-turn testing, not the test suite** (the same
lesson as the earlier model-code work: isolated unit/integration tests can't catch a
conflict between two mechanisms that only collide when combined at the SQL layer):

1. **The AVR sheet has no "Product Title" column** (unlike UPS) — a first version of
   `_build_avr_row` copied the UPS row-builder's `row['Product Title']` access
   verbatim and crashed with a `KeyError` partway through ingestion. Fixed: AVR's
   title is the first line of its `RAG Chunk Text` (already a well-formed product
   name). Caught before any data was committed — the script's single end-of-run
   `commit()` meant the crash rolled back cleanly, but the Qdrant upsert for the
   already-processed UPS rows had already happened (Qdrant writes aren't part of the
   Postgres transaction) — those 181 orphaned points had to be deleted by category
   filter before re-running.
2. **The legacy `capacity_requirement`/`capacity_unit` field and the new
   `capacity_kva` constraint silently combined into an impossible condition.**
   `extract()` unconditionally computed the legacy field from the same message text
   regardless of what the new constraint system produced, and `find_by_filters` ANDs
   every condition together — the legacy field only ever means "capacity_min <= x <=
   capacity_max" (exact containment), so "at least 50 kVA" resolved a correct
   `capacity_kva gte 50` constraint *plus* a legacy "exactly 50" condition; since no
   product is exactly 50kVA, the two ANDed together always returned zero real
   candidates, and the response confidently claimed "no exact match" while quietly
   mixing in an unscoped vector-search product that didn't actually satisfy the
   constraint. Fixed: the legacy field is now skipped whenever the new constraint
   system already produced a `capacity_kva`/`current_a` constraint for the same
   message, since they represent the same client-stated figure.

An unrelated environment incident during this work: Docker Desktop's engine crashed
mid-ingestion (no code involved — `docker ps`/`docker version` stopped responding
entirely), losing the in-flight `docker compose run` container. Restarting Docker
Desktop and `docker compose up -d` recovered every container from its existing volume
with no data loss (the crash happened before the ingestion script's single `commit()`,
so nothing partial had been written to Postgres) — worth remembering that a
long-running `docker compose run` job can be silently killed by the *host* Docker
Desktop crashing, independent of anything in the container.

Full suite green (332 passed / 14 skipped) after every fix; live-verified end to end:
`gte`/`lte`/`between`/`not_eq` on UPS capacity, battery voltage tolerance (exact and
snapped), `list_all` now respecting a `form_factor_key` constraint, `parallel_capable`
filtering, and — to confirm nothing broke — the exact-model-code lookup and wizard
flow both still work unchanged.

### One more category-resolution gap found asking whether list-all still worked

Asked directly whether the deterministic list-all-with-features filter still worked,
live-tested with "List all your Automatic Voltage Regulator products with all their
features" (singular "Regulator") — got back UPS/accessory products, no AVR products at
all, despite 52 real ones in the catalog. Root cause: `_first_vocabulary_match`
requires the *exact* stored category string ("Automatic Voltage Regulators", plural)
to appear as a literal substring; a client writing the category out in full but in
singular form never literally contains the plural form, so category resolution failed
entirely and the request silently fell through to an unscoped, all-category
`list_products` call — none of the 52 AVR products happened to sort into the first 50
results alphabetically across the whole catalog. Fixed with
`_first_singular_category_match` in `app/rag/filter_extraction.py`: a final fallback
(after the exact match and the UPS/AVR/battery abbreviation table) that strips one
trailing "s" from each stored category name and matches against that — same class of
gap as the original UPS/AVR/battery abbreviation fixes, just triggered by a singular
form instead of an abbreviation. Full suite green (333 passed / 14 skipped);
re-verified live that the exact query now returns real, correctly-featured AVR
products, and that the existing "list all tower UPS" (plural, already-working) path is
unaffected.

## User preferences

- Prefers being told exactly what to do next in sequence, not a menu of options.
- GitHub repo: <https://github.com/aibasit/makkays_chatbot>
