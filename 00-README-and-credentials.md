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
| `OLLAMA_MODEL` | LLM Engine (M05) | Pulled locally: `ollama pull qwen3:4b` | Yes |
| `RESEND_API_KEY` | Email Notifications (M14) | resend.com → API Keys | Yes (for lead/quote email notifications) |
| `RESEND_FROM_EMAIL` | Email Notifications (M14) | A domain verified in Resend | Yes |
| `CRM_API_BASE_URL` | CRM Integration (M14) | Your CRM provider's API docs | Yes (stub/mock acceptable for local dev) |
| `CRM_API_KEY` | CRM Integration (M14) | CRM provider dashboard | Yes (stub/mock acceptable for local dev) |
| `SITE_API_KEY` | Public API (M15) | Self-generated (`openssl rand -hex 32`) — this is a key **you** issue to your own frontend widget, not a third-party key | Yes |
| `DEFAULT_TENANT_ID` | Multi-tenancy foundation, all tables | Self-defined UUID, e.g. `00000000-0000-0000-0000-000000000001` | Yes |
| `OLLAMA_TIMEOUT_SECONDS` | LLM Engine (M05) | Integer seconds; default `30`. Increase on slow hardware. | No (has safe default) |
| `CLASSIFICATION_CONFIDENCE_THRESHOLD` | Router (M06) | Float threshold; default `0.70`. | No (has safe default) |
| `CONVERSATION_STATE_TTL_SECONDS` | Session State (M03) | Integer seconds; default `1800`. | No (has safe default) |
| `MAX_CLARIFICATION_ROUNDS` | Clarification (M13) | Integer rounds; default `2`. | No (has safe default) |
| `RAG_SEARCH_LIMIT_DEFAULT` / `RAG_SEARCH_LIMIT_MAX` | RAG (M11) | Integers; defaults `5` and `10`. | No (has safe defaults) |
| `CRM_MAX_RETRY_ATTEMPTS` / `CRM_RETRY_WORKER_INTERVAL_SECONDS` | CRM (M14) | Integers; defaults `5` and `60`. | No (has safe defaults) |
| `CHAT_RATE_LIMIT_PER_MINUTE` / `MAX_MESSAGE_LENGTH` | Public API (M15) | Integers; defaults `20` and `4000`. | No (has safe defaults) |
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
OLLAMA_MODEL=qwen3:4b

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
CLASSIFICATION_CONFIDENCE_THRESHOLD=0.70

# --- Path Overrides (optional — safe defaults apply) ---
PROMPT_LIBRARY_PATH=./prompt_library
SECURITY_POLICY_DIR=./security_policies

# --- CORS (development only) ---
CORS_ALLOW_ORIGINS=http://localhost:5173

# --- Logging ---
LOG_LEVEL=INFO

# --- Runtime Defaults (optional - safe defaults apply) ---
CONVERSATION_STATE_TTL_SECONDS=1800
MAX_CLARIFICATION_ROUNDS=2
RAG_SEARCH_LIMIT_DEFAULT=5
RAG_SEARCH_LIMIT_MAX=10
CRM_MAX_RETRY_ATTEMPTS=5
CRM_RETRY_WORKER_INTERVAL_SECONDS=60
CHAT_RATE_LIMIT_PER_MINUTE=20
MAX_MESSAGE_LENGTH=4000
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

---

## 4. Canonical Intent Taxonomy

This table is authoritative. Router, Planner, Tool Executor, Clarification,
Prompt Manager, security policies, and tests must use these exact intent names.

| Intent | Description | Planner Behavior | Clarification Behavior | Default Response Behavior |
|---|---|---|---|---|
| `sales_inquiry` | Product discovery, recommendations, specs, availability, compatibility, or general buying help. | `retrieve_products`; add `retrieve_docs` for spec/doc questions; add `compare` when prior or retrieved candidates make comparison useful; add `generate_quote` only when quote slots are complete and quotes are enabled; add `create_lead` when contact info is newly captured; always end with `respond`. | Candidate in mixed commercial/support ambiguity. | Answer with product recommendations and next-step guidance. |
| `quote_request` | Explicit pricing, quotation, estimate, or proposal request. | `retrieve_products`; if quote slots are complete, `generate_quote`; otherwise `request_missing_slots`; always end with `respond`. | Candidate when pricing intent is unclear versus general product inquiry. | Provide the quote when possible or ask for missing quote slots. |
| `technical_support` | Existing-product fault, error, setup, configuration, or troubleshooting request. | `retrieve_docs`, then `respond`. | Candidate when "help" could mean support or sales. | Provide support guidance grounded in retrieved documentation. |
| `escalation_request` | User asks for a human or clarification exceeded maximum rounds. | `respond`. | Not used as a normal clarification candidate except after max rounds. | Acknowledge handoff and ask for/confirm contact details. |
| `out_of_scope` | Request unrelated to supported sales/support work. | `respond`. | Generic fallback if classifier cannot map to supported work. | Politely state supported capabilities. |

Adding an intent requires one new taxonomy row, Router rule/schema coverage, one
Planner rule function, policy updates if tools are allowed, prompt coverage where
needed, and tests. v4.1 does not support per-tenant taxonomies.

---

## 5. Canonical Internal Interfaces

All module documents must use these exact exported service/repository signatures.
Return values are Pydantic v2 schemas unless explicitly marked ORM.

| Owner | Interface |
|---|---|
| M03 `FactsRepository` | `async get(tenant_id: UUID, session_id: str) -> SessionFacts | None`; `async upsert(tenant_id: UUID, session_id: str, patch: FactsUpdate) -> SessionFacts` |
| M03 `ConversationStateRepository` | `async get(tenant_id: UUID, session_id: str) -> ConversationState | None`; `async upsert(tenant_id: UUID, session_id: str, patch: ConversationStateUpdate) -> ConversationState`; `async update_clarification_state(tenant_id: UUID, session_id: str, question_text: str) -> ConversationState`; `async increment_clarification_round(tenant_id: UUID, session_id: str) -> int` |
| M03 `SessionStateService` | `async get_facts(tenant_id, session_id) -> FactsSchema`; `async update_facts(tenant_id, session_id, patch: FactsUpdate) -> FactsSchema`; `async get_conversation_state(tenant_id, session_id) -> ConversationStateSchema`; `async update_conversation_state(tenant_id, session_id, patch: ConversationStateUpdate) -> ConversationStateSchema`; `async update_clarification_state(tenant_id, session_id, question_text) -> ConversationStateSchema`; `async reset_conversation_state(tenant_id, session_id) -> ConversationStateSchema` |
| M04 `TurnsService` | `async get_next_turn_number(tenant_id: UUID, session_id: str) -> int`; `async get_recent_turns(tenant_id: UUID, session_id: str, limit: int = 8) -> list[ConversationTurnRead]`; `async record_turn(...) -> None` |
| M05 `LLMClientProtocol` | `async chat(messages: list[ChatMessage], tools: list[dict] | None = None, response_format: dict | None = None, temperature: float = 0.0) -> LLMResponse` |
| M05 context helper | `build_llm_messages(system_prompt: str, facts: FactsSchema | None, state: ConversationStateSchema | None, recent_turns: list[ConversationTurnRead], tool_results: list[ToolExecutionResult] = [], planner_metadata: dict | None = None, retrieved_sources: list[dict] = [], quote_summary: dict | None = None, latest_user_message: str | None = None, max_context_chars: int = 24000) -> tuple[list[ChatMessage], ContextBuildMetadata]` |
| M06 `FactsExtractor` | `async extract(message: str, facts: FactsSchema, state: ConversationStateSchema, recent_turns: list[ConversationTurnRead], prompt_manager: PromptManager, llm_client: LLMClientProtocol) -> FactsUpdate` |
| M06 `Router` | `async classify(message: str, facts: FactsSchema, state: ConversationStateSchema, recent_turns: list[ConversationTurnRead], prompt_manager: PromptManager, llm_client: LLMClientProtocol) -> IntentResult` |
| M06 `Orchestrator` | `async on_turn(tenant_id: UUID, session_id: str, message: str) -> OrchestratorResult` |
| M07 `TaskPlanner` | `build_plan(intent_result: IntentResult, facts: FactsSchema, state: ConversationStateSchema, flags: FeatureFlags) -> Plan` |
| M08 `PromptManager` | `get(category: PromptCategory, name: str, version: str) -> str`; `get_latest(category: PromptCategory, name: str) -> str`; `startup_self_check(references: list[PromptRef]) -> None` |
| M10 `ToolExecutor` | `async execute_plan(plan: Plan, session: SessionContext, flags: FeatureFlags) -> list[ToolExecutionResult]` |
| M11 `RetrievalService` | `async retrieve_products(session: SessionContext, context: ExecutionContext) -> ToolExecutionResult`; `async retrieve_docs(session: SessionContext, context: ExecutionContext) -> ToolExecutionResult` |
| M12 `QuoteBuilder` | `async build(session: SessionContext, context: ExecutionContext) -> QuoteResult` |
| M13 `ClarificationFlow` | `async run(tenant_id: UUID, session_id: str, intent_result: IntentResult, facts: FactsSchema, state: ConversationStateSchema, flags: FeatureFlags) -> ClarificationResult` |
| M14 `LeadService` | `async create_lead(session: SessionContext, context: ExecutionContext) -> ToolExecutionResult` |
| M16 `MetricsRegistry` | `increment_intent_classification(source, intent)`, `record_intent_confidence(confidence)`, `increment_rag_hit(hit)`, `increment_quote_result(success)`, `increment_crm_sync_result(success)`, `increment_lead_created()`, `increment_tool_result(tool_name, success)`, `observe_chat_latency(seconds)` |

Async/sync rule: repository, DB, Redis, network, LLM, and tool execution methods
are async. Pure planner, predicate, prompt path resolution, and schema validation
helpers are sync.

---

## 6. Facts Extraction Contract

Ownership: Module 06 owns facts extraction as part of Orchestrator processing.
Module 03 owns persistence only. This preserves the existing module boundaries.

Per-turn sequence:
1. Module 15 calls `Orchestrator.on_turn`.
2. Module 06 loads facts, conversation state, and recent turns.
3. Module 06 runs `FactsExtractor.extract(...)` before intent classification.
4. Module 06 validates and merges the returned `FactsUpdate`.
5. Module 03 persists the update to SQL and Redis via write-through.
6. Module 06 classifies intent using the updated facts and state.

Extraction method: deterministic extraction first for email, phone, quantity,
budget, company, and product-interest phrases. The LLM may be used only as a
structured-output extractor through Module 05 when deterministic extraction is
insufficient; it returns a `FactsUpdate`, never control-flow decisions.

Merge/update strategy:
- Empty or all-`None` updates are no-ops.
- Non-null new values fill missing facts.
- Same normalized value is ignored.
- A conflicting value replaces the old value only when explicit in the latest
  user message; otherwise the existing value is kept and
  `facts_conflict_preserved` is logged.
- Contact fields set `conversation_state.contact_info_captured = true` only when
  email or phone changes from `None` to non-null for the first time this session.

Validation:
- `budget >= 0`, normalized to Decimal.
- `quantity > 0`, integer only.
- `contact_email` passes `EmailStr`.
- `contact_phone` is normalized where possible; invalid fragments are ignored.
- String slots are stripped and capped at 500 characters.

Persistence/retry:
- SQL is the durability source. If Redis fails on write, SQL still commits and
  Redis is repopulated on the next read. If SQL fails, raise
  `FactsCheckpointError` and fail the turn.
- Facts extraction is not retried independently; callers retry the whole HTTP
  request if needed.

---

## 7. Context Assembly Contract

No new module is introduced. The canonical helper lives in Module 05 at
`app/llm/context.py` and is used by every caller before an LLM call.

Inputs, in deterministic order:
1. System prompt from Prompt Manager.
2. Planner metadata: accepted intent, confidence, plan steps, current step.
3. Session facts.
4. Conversation state summary.
5. Recent turns from `TurnsService.get_recent_turns`, oldest to newest.
6. Retrieved product/document summaries with source IDs.
7. Tool outputs from `ExecutionContext`, in plan-step order.
8. Quote summary, if present.
9. Latest user message or task-specific user instruction.

Processing:
- Deterministic ordering is mandatory.
- Duplicate product/document IDs are removed, preserving first occurrence.
- Source attribution uses `product_id`, `document_id`, `title`, and `score`
  where available.
- Maximum context size is 24,000 characters unless a caller supplies a smaller
  `max_context_chars`.
- Truncation order: oldest recent turns first, lowest-score docs next, verbose
  tool summaries next. System prompt, latest user message, accepted intent, and
  required policy/quote facts are never truncated.
- Secrets, API keys, credentials, and full raw prompt libraries are never
  included.

Output: `list[ChatMessage]` with exactly one leading `system` message plus a
`ContextBuildMetadata` object containing included turn count, included source
IDs, truncated counts, and prompt refs for Module 04 logging.

---

## 8. Prompt Registry

Canonical prompt categories:

```
system/
classification/
rag/
clarification/
tools/
quotes/
```

File naming is `{name}_v{integer}.md`. `PromptManager.get(category, name,
version)` receives version as `"1"` and resolves `_v1.md`. `get_latest` uses
integer sorting.

Required v4.1 files:
- `system/base_v1.md`
- `classification/classify_intent_v1.md`
- `classification/extract_facts_v1.md`
- `rag/context_inject_v1.md`
- `rag/filter_extract_v1.md`
- `clarification/generic_fallback_v1.md`
- `clarification/sales_vs_support_v1.md`
- `clarification/sales_vs_quote_v1.md`
- `clarification/sales_vs_support_vs_quote_v1.md`
- `clarification/llm_rewrite_instructions_v1.md`
- `clarification/escalation_v1.md`
- `tools/tool_instructions_v1.md`
- `quotes/quote_explanation_v1.md`

Missing required prompts fail startup during `PromptManager.startup_self_check`.
Runtime fallback is allowed only for clarification: a missing specific template
falls back to `clarification/generic_fallback_v1.md`.

---

## 9. Redis Registry

| Key | Owner | Value | Serialization | TTL | Update Rules |
|---|---|---|---|---|---|
| `session:facts:{tenant_id}:{session_id}` | M03 | `FactsSchema` | `model_dump_json()` | None | Updated after successful facts SQL upsert; repopulated from SQL on miss. |
| `conversation:state:{tenant_id}:{session_id}` | M03 | `ConversationStateSchema` | `model_dump_json()` | `CONVERSATION_STATE_TTL_SECONDS` | Updated after state SQL upsert; TTL refreshed on write. |
| `rate_limit:chat:{tenant_id}:{session_id}` | M15 | integer counter | Redis integer | 60s | Fixed-window `INCR` + `EXPIRE` pipeline. |
| `rate_limit:tool:{tenant_id}:{session_id}:{tool_name}` | M10 | integer counter | Redis integer | Policy window | Fixed-window `INCR` + `EXPIRE` pipeline. |
| `rag:filters:{tenant_id}:{query_hash}` | M11 | `ExtractedFilters` | JSON | 300s | Optional optimization only; correctness must not depend on it. |

All UUIDs in keys use lowercase hyphenated `str(uuid)`.

---

## 10. Configuration Registry

All configurable values are declared in Module 01 `Settings` exactly once.

| Setting Field | Env Var | Default | Owner |
|---|---|---|---|
| `router.classification_confidence_threshold` | `CLASSIFICATION_CONFIDENCE_THRESHOLD` | `0.70` | M06 |
| `session.conversation_state_ttl_seconds` | `CONVERSATION_STATE_TTL_SECONDS` | `1800` | M03 |
| `clarification.max_rounds` | `MAX_CLARIFICATION_ROUNDS` | `2` | M13 |
| `rag.search_limit_default` | `RAG_SEARCH_LIMIT_DEFAULT` | `5` | M11 |
| `rag.search_limit_max` | `RAG_SEARCH_LIMIT_MAX` | `10` | M11 |
| `crm.max_retry_attempts` | `CRM_MAX_RETRY_ATTEMPTS` | `5` | M14 |
| `crm.retry_worker_interval_seconds` | `CRM_RETRY_WORKER_INTERVAL_SECONDS` | `60` | M14 |
| `site.chat_rate_limit_per_minute` | `CHAT_RATE_LIMIT_PER_MINUTE` | `20` | M15 |
| `site.max_message_length` | `MAX_MESSAGE_LENGTH` | `4000` | M15 |
| `prompts.library_path` | `PROMPT_LIBRARY_PATH` | `./prompt_library` | M08 |
| `tools.policy_directory` | `SECURITY_POLICY_DIR` | `./security_policies` | M10 |

Modules must not redefine these as separate module-level constants.

---

## 11. Database Registry

| Table | Owner | Primary Key / Constraints | Indexes / FKs |
|---|---|---|---|
| `session_facts` | M03 | PK `(tenant_id, session_id)` | tenant/session lookup by PK |
| `conversation_state` | M03 | PK `(tenant_id, session_id)` | tenant/session lookup by PK |
| `conversation_turns` | M04 | PK `id`; unique `(tenant_id, session_id, turn_number)` | `idx_conversation_turns_session` |
| `feature_flags` | M09 | PK `(tenant_id, flag_name)` | none |
| `tool_audit_log` | M10 | PK `id` | none |
| `products` | M11 | PK `id` | tenant-scoped lookups |
| `product_specs` | M11 | PK `id`; FK `product_id -> products.id` | `idx_product_specs_lookup` |
| `documents` | M11 | PK `id`; FK `product_id -> products.id` nullable | tenant/product lookups |
| `quotes` | M12 | PK `id` | tenant/session lookup |
| `product_pricing` | M12 | PK `(product_id, tenant_id)`; FK `product_id -> products.id` | none |
| `leads` | M14 | PK `id` | tenant/session lookup |
| `retry_queue` | M14 | PK `id`; FK `lead_id -> leads.id` | `idx_retry_queue_due` partial on pending due rows |

No module may create or alter a table outside its owner migration.

---

## 12. Startup / Shutdown Lifecycle

Startup owner is Module 01. Hook implementers expose `register_hooks(app,
settings) -> None`; only Module 01 calls those functions.

Startup order:
1. Load and validate `Settings`.
2. Configure structured logging.
3. Initialize DB engine and Redis client.
4. Initialize metrics registry.
5. Load Prompt Manager and run prompt self-check.
6. Import tool-owning modules so tools self-register.
7. Load Security Policy registry and validate registered tools.
8. If RAG enabled, validate Qdrant collections and prepare lazy embedder.
9. Register CRM scheduler hook.
10. Register exception handlers, middleware, and routers.
11. Start APScheduler after dependencies are ready.

Shutdown order:
1. Stop APScheduler with `wait=False`.
2. Close LLM HTTP client.
3. Close Redis client.
4. Dispose SQLAlchemy engine.
5. No metrics flush required in v4.1.

---

## 13. Canonical Request Lifecycle

```
HTTP POST /chat
  -> M15 authenticate site API key
  -> M15 get/create session cookie
  -> M15 request rate limit
  -> M06 Orchestrator.on_turn
  -> M03 load Facts
  -> M03 load ConversationState
  -> M04 load recent turns
  -> M06 FactsExtractor.extract
  -> M03 update Facts and Redis
  -> M09 resolve FeatureFlags
  -> M06 Router.classify
  -> M03 persist intent/confidence state
  -> M13 ClarificationFlow if confidence below threshold
  -> M07 TaskPlanner.build_plan if intent accepted
  -> M03 persist current_plan/current_plan_step
  -> M10 policy evaluation per step
  -> M10 execute deterministic plan steps
  -> M05 build_llm_messages for each LLM call
  -> M05 OllamaClient.chat where needed
  -> M03 persist final ConversationState
  -> M04 record_turn
  -> M16 metrics increments/latency
  -> M15 ChatResponse
```

The LLM never chooses which business tools execute. Only the Planner emits
steps, and only the Tool Executor runs those steps after policy checks.

---

## 14. Logging and Error Response Contracts

Every application log line is JSON with `timestamp`, `level`, `logger`, `event`,
`tenant_id`, `session_id`, `correlation_id`, and optional low-cardinality
metadata.

Allowed metadata: intent, confidence, source, step, tool_name, success,
clause_failed, latency_ms, counts, IDs, and status codes. Forbidden in general
logs: raw user messages, assistant messages, prompt text, API keys, tokens,
passwords, CRM keys, contact email/phone, and full facts snapshots. Those belong
only in owned database tables where documented.

User-visible degradation:
- Planner failure: log `ERROR`, metric failure, fall back to
  `escalation_request` `respond`.
- LLM unavailable during classification: confidence `0.0`, clarification flow.
- LLM unavailable during narration/respond: deterministic fallback from tool
  summaries.
- RAG unavailable: failed tool step; response explains lookup is temporarily
  unavailable.
- Quote unavailable: failed quote step; response asks for retry or missing data
  without inventing pricing.
- CRM failure: lead remains queued; user sees lead captured, not CRM internals.
- Clarification exceeded: route to `escalation_request`.
- Tool timeout: failed step result; critical steps abort remaining steps,
  non-critical steps continue.

---

## 15. Canonical Sequence Diagrams

### Request Lifecycle
```
Frontend -> M15 /chat -> M06 Orchestrator
M06 -> M03 load facts/state
M06 -> M04 recent turns
M06 -> M06 FactsExtractor -> M03 update facts
M06 -> M06 Router -> M07 Planner or M13 Clarification
M07 -> M10 ToolExecutor -> M11/M12/M14 tools
M10 -> M05 Context Builder + LLM respond
M06 -> M04 record turn -> M15 response
```

### Quote Generation
```
M10 generate_quote policy check
  -> M12 QuoteBuilder.build
  -> M12 ProductPricingRepository.get_prices
  -> M12 QuoteRepository.create
  -> M12 QuoteExplainer via M05 Context Builder/Ollama
  -> M10 ToolExecutionResult
```

### RAG Retrieval
```
M10 retrieve_products/retrieve_docs
  -> M11 FilterExtractor
  -> M11 SQL narrowing
  -> M11 BGE-M3 embed in executor
  -> M11 Qdrant filtered search
  -> M10 ExecutionContext
```

### CRM Retry
```
M10 create_lead
  -> M14 LeadRepository.create
  -> M14 RetryQueueRepository.enqueue
  -> M14 NotificationService best effort
  -> APScheduler RetryWorker
  -> CRM API
  -> mark succeeded / reschedule / permanent failure
```

### Clarification Flow
```
M06 low-confidence IntentResult
  -> M13 ClarificationFlow
  -> M13 TemplateLookup
  -> M08 PromptManager
  -> optional M05 rewrite
  -> M03 atomic clarification state update
  -> M06 clarification response
```

---

## 16. Test Consistency Contract

Tests must not assert behavior outside these documents. Required cross-module
tests:
- Golden path: product inquiry -> facts extraction -> sales intent -> retrieval
  -> respond -> turn recorded.
- Quote path: complete slots -> `generate_quote` policy allowed -> quote row.
- Clarification path: low confidence -> template response -> max rounds
  escalates.
- Failure path: RAG unavailable or quote unavailable degrades without crashing.
- Startup self-check: missing prompt or missing policy fails startup.

Planner tests must assert only emitted steps that are registered v4.1 tools:
`retrieve_products`, `retrieve_docs`, `compare`, `generate_quote`,
`request_missing_slots`, `create_lead`, and `respond`. `create_ticket` is a
reserved future tool gated by `ENABLE_TICKETS`; no v4.1 Planner rule may emit it
until a ticket implementation module is documented.
