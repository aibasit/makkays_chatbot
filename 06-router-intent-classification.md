# Module 06 — Router & Hybrid Intent Classification

## 1. Module Name
`router` — Tier 1 deterministic rules + Tier 2 LLM `classify_intent`, confidence gating, Orchestrator entrypoint.

## 2. Goal
Implement the two-tier intent classification pipeline and the top-level
`on_turn(session, message)` Orchestrator function that everything else (Planner,
Tool Executor, Turns logging) hangs off of.

## 3. Purpose
This is the entrypoint of the whole system per turn. It decides *what the user
wants* (intent) with a hybrid deterministic-then-LLM approach, before handing off
to the Task Planner (Module 07) for *how* to satisfy it — the architecture's core
"Router decides what, Planner decides how" separation.

## 4. Dependencies
Module 03 (session/state — read Facts and ConversationState at turn start, write State at turn end), Module 04 (Turns — record each turn after execution), Module 05 (LLM — Tier 2 classification and intent confidence scoring), Module 07 (Planner — Orchestrator calls `TaskPlanner.build_plan`), Module 08 (Prompt Manager — system prompt and Tier 2 classification prompt), Module 09 (Feature Flags — resolved once per turn by the Orchestrator), Module 10 (Tool Executor — Orchestrator calls `ToolExecutor.execute_plan`), Module 13 (Clarification Flow — Orchestrator calls `ClarificationFlow.run` on low-confidence intents), Module 16 (MetricsRegistry — intent classification and confidence metrics emitted after Tier 2).

## 5. Folder Structure
```
app/
├── router/
│   ├── __init__.py
│   ├── classifier.py
│   ├── rules.py
│   └── exceptions.py
├── orchestrator/
│   ├── __init__.py
│   └── orchestrator.py
├── shared/
│   ├── __init__.py
│   └── intent_context.py
tests/
├── unit/
│   ├── test_tier1_rules.py
│   └── test_tier2_classifier.py
└── integration/
    └── test_orchestrator_on_turn.py
```

## 6. Files to Create
`app/router/classifier.py`, `app/router/rules.py`, `app/router/exceptions.py`, `app/orchestrator/orchestrator.py`, `app/shared/intent_context.py`.

## 7. Responsibility of Every File
| File | Responsibility |
|---|---|
| `app/orchestrator/orchestrator.py` | `Orchestrator` — top-level per-turn control flow, imports Router, Planner, Tool Executor, and Turns. Depends on `LLMClientProtocol` and `PromptProvider` abstractions. |
| `app/router/rules.py` | `Tier1RuleEngine` — deterministic keyword/regex/lookup rules producing an `(intent, confidence=1.0)` |
| `app/router/classifier.py` | `Tier2Classifier` — builds intent classifier LLM call and parses structured output. Depends on `LLMClientProtocol`. |
| `app/shared/intent_context.py` | `IntentResult`, `ClassifyIntentArguments` Pydantic models. Shared across Router, Orchestrator, and Planner to avoid circular dependency cycles. |
| `app/router/exceptions.py` | `ClassificationFailedError` |

## 8. Classes
- `Tier1RuleEngine` — `match(message: str) -> IntentResult | None`.
- `Tier2Classifier` — `async classify(session_context, llm_client: LLMClientProtocol, prompt_provider: PromptProvider) -> IntentResult`.
- `Router` — `async classify(session, message, llm_client: LLMClientProtocol, prompt_provider: PromptProvider) -> IntentResult`, orchestrates Tier1→Tier2 fallback.
- `Orchestrator` — `async on_turn(tenant_id, session_id, message, llm_client: LLMClientProtocol, prompt_provider: PromptProvider) -> OrchestratorResult`. Exposes `Orchestrator` inside `app/orchestrator/orchestrator.py`.
- `IntentResult` — imported from `app.shared.intent_context`.

## 9. Data Models
No new persisted tables (writes to `conversation_state`/`conversation_turns` owned by Modules 03/04).

## 10. Pydantic Schemas
- `IntentResult` (owned by `app/shared/intent_context.py`): `{ intent: str, confidence: float, source: Literal["tier1","tier2"], candidates: list[str] = [], spec_question_detected: bool = False }` — `spec_question_detected` is populated by `Tier1RuleEngine.match`. The Router sets this field; the Planner (Module 07) imports it from `app.shared.intent_context` and reads it from the `IntentResult` passed into `build_plan`.
- `ClassifyIntentArguments` (owned by `app/shared/intent_context.py`): `{ intent: str, confidence: float, candidates: list[str] }` — JSON schema for Tier 2 structured tool call output.
- `OrchestratorResult { assistant_message: str, intent: str, awaiting_clarification: bool, plan: Plan | None, tool_calls: list[ToolExecutionResult] }` — uses typed references to `Plan` (Module 07) and `ToolExecutionResult` (Module 10). `plan` is `None` when the clarification flow ran instead of the Planner.

## 11. Repository Layer
None new — uses `SessionStateService` (Module 03) and `TurnsService` (Module 04).

## 12. Service Layer
`Orchestrator.on_turn(tenant_id, session_id, user_message) -> OrchestratorResult`:
1. Load `facts = await SessionStateService.get_facts(tenant_id, session_id)` and `state = await SessionStateService.get_conversation_state(tenant_id, session_id)` from Module 03.
2. Load `recent_turns = await TurnsService.get_recent_turns(tenant_id, session_id, limit=8)` from Module 04.
3. Run `facts_patch = await FactsExtractor.extract(user_message, facts, state, recent_turns, prompt_manager, llm_client)` and persist any non-empty patch through `SessionStateService.update_facts`; use the returned updated `facts` for all later steps.
4. Resolve `flags = await FeatureFlagsService.resolve(tenant_id)` from Module 09; the resolved `FeatureFlags` object is passed to Planner, Clarification, and Tool Executor.
5. Route: `intent_result = await Router.classify(user_message, facts, state, recent_turns, prompt_manager, llm_client)` (Tier 1 then Tier 2, see §8).
6. Call `MetricsRegistry.increment_intent_classification(source=intent_result.source, intent=intent_result.intent)` and `MetricsRegistry.record_intent_confidence(intent_result.confidence)` from Module 16.
7. Update `ConversationState` with the new intent and confidence (`ConversationStateRepository.upsert`).
8. Compute `turn_number` by delegating to `TurnsService.get_next_turn_number(tenant_id, session_id)`.
9. Low-confidence branch: if `intent_result.confidence < settings.router.classification_confidence_threshold`, call `ClarificationFlow.run(tenant_id, session_id, intent_result, facts, state, flags)` from Module 13; on `MaxClarificationRoundsExceededError`, override `intent_result.intent = 'escalation_request'` and fall through to step 10.
10. Build plan: `plan = TaskPlanner.build_plan(intent_result, facts, state, flags)` from Module 07.
11. Persist `current_plan` and `current_plan_step=0` through `SessionStateService.update_conversation_state`.
12. Execute plan: `tool_results = await ToolExecutor.execute_plan(plan, SessionContext(tenant_id, session_id, facts, state), flags)` from Module 10.
13. Assemble `assistant_message`: if the clarification flow ran (not overridden), use `clarification_result.question_text`; if the plan executed, use the `result_summary` from the `respond` step in `tool_results`.
14. Record turn: `await TurnsService.record_turn(tenant_id, session_id, turn_number, user_message, intent_result, plan, tool_results, assistant_message)` from Module 04.
15. Return `OrchestratorResult(assistant_message=..., intent=intent_result.intent, awaiting_clarification=clarification_ran, plan=plan, tool_calls=tool_results)`.
Clarification branch return path: when `ClarificationFlow.run` is called (not via the `MaxClarificationRoundsExceededError` catch), set `result.awaiting_clarification = True`, `result.assistant_message = clarification_result.question_text`, `result.plan = None`, `result.tool_calls = []`. Record the turn and return.

## 13. Internal Interfaces
- `Router.classify(message, facts, state, recent_turns, prompt_manager, llm_client) -> IntentResult` — sole entrypoint used by the Orchestrator; Tier1/Tier2 internals are not called directly by anything else.
- `FactsExtractor.extract(message, facts, state, recent_turns, prompt_manager, llm_client) -> FactsUpdate` — sole facts extraction entrypoint; runs before routing.
- `Orchestrator.on_turn(tenant_id, session_id, message) -> OrchestratorResult` — sole entrypoint used by Module 15's `/chat` endpoint.

## 14. Database Tables
None new — reads/writes `conversation_state` (Module 03) and `conversation_turns` (Module 04).

## 15. Redis Keys
None new — uses Module 03's `conversation:state:{tenant_id}:{session_id}`.

## 16. API Endpoints
None directly — `Orchestrator.on_turn` is called from Module 15's `POST /chat`.

## 17. Request Models
N/A at this layer (HTTP request parsing owned by Module 15).

## 18. Response Models
`OrchestratorResult` (above), consumed by Module 15 to build the HTTP response.

## 19. Business Logic
- **Tier 1 rules**: exact/near-exact keyword matches for unambiguous cases (e.g., "quote", "pricing" → `quote_request`; "not working", "broken", "error" → `technical_support`). Only fires when unambiguous — any overlap with multiple rule sets falls through to Tier 2 rather than guessing.
- **Tier 2 (`classify_intent`)**: single bundled LLM call, given the full conversation context and the fixed intent taxonomy, **mandatory as the first tool call of the turn** (unchanged from v4) — this guarantees the model always classifies before anything else can happen, even if it also wants to call other tools in the same turn.
- **Confidence gate**: `CLASSIFICATION_CONFIDENCE_THRESHOLD` (config, default `0.7`). Below threshold → clarification flow, **discard-on-uncertainty** (unchanged from v4: a low-confidence guess is never silently accepted).
- **On acceptance**: hands off to Task Planner, not directly to Tool Executor (the v4.1 change) — see architecture §2.3 pseudocode, reproduced structurally in `Orchestrator.on_turn`.

## 20. Validation Rules
- `confidence` from Tier 2 must be in `[0.0, 1.0]`; out-of-range values are clamped and logged as a classifier anomaly, not trusted blindly.
- `intent` from Tier 2 must be one of the fixed taxonomy values (`sales_inquiry`, `technical_support`, `quote_request`, `escalation_request`, ...); an unrecognized value is treated as classification failure (low confidence), never passed through.

## 21. Error Handling
| Error | Handling |
|---|---|
| LLM fails to classify (per Module 05 exceptions) | Treated as confidence `0.0` → clarification flow (unchanged from v4, per architecture §3) |
| Malformed `classify_intent` tool-call arguments | Same as above — classification failure, not a crash |
| Confidence below threshold | Route to clarification flow (Module 13), not an error — this is expected control flow |

## 22. Logging Strategy
- Every classification attempt logged at `INFO`: `tier`, `intent`, `confidence` (values only, not full message text — full text goes to `conversation_turns` via Module 04, not duplicated here).
- Tier 1 vs Tier 2 hit-rate is a Metrics concern (Module 16), not logged repeatedly here beyond the per-call `INFO` line.

## 23. Unit Tests
- `test_tier1_matches_unambiguous_keywords`
- `test_tier1_returns_none_on_ambiguous_message`
- `test_tier2_parses_valid_classify_intent_call`
- `test_tier2_raises_on_llm_failure_treated_as_low_confidence`
- `test_router_prefers_tier1_when_confident`
- `test_router_falls_back_to_tier2_when_tier1_uncertain`

## 24. Integration Tests
- `test_on_turn_high_confidence_routes_to_planner`
- `test_on_turn_low_confidence_routes_to_clarification`
- `test_on_turn_persists_intent_to_conversation_state`
- `test_on_turn_records_turn_with_correct_intent_source`

## 25. Configuration
```
router:
  classification_confidence_threshold: float = 0.7
  intent_taxonomy: list[str]   # fixed list, defined here, referenced by Tier2 schema and Task Planner
```

## 26. Environment Variables
`CLASSIFICATION_CONFIDENCE_THRESHOLD` (optional, default `0.70`) from Module 00 §10.

## 27. Sequence Diagram
```
POST /chat  (Module 15)
      │
      ▼
Orchestrator.on_turn(tenant_id, session_id, message)
      │
      ├─ SessionStateService.get_facts / get_conversation_state
      │
      ├─ Router.classify(session, message)
      │       ├─ Tier1RuleEngine.match()  ── confident? ──► return
      │       └─ Tier2Classifier.classify()  (LLM, bundled classify_intent call)
      │
      ├─ persist intent/confidence → conversation_state
      │
      ├─ confidence >= threshold?
      │     yes → TaskPlanner.build_plan(...) → ToolExecutor.execute_plan(...)
      │     no  → ClarificationFlow.run(...)
      │
      └─ TurnsService.record_turn(...)
```

## 28. Request Lifecycle
Described fully in §27 — this module *is* the request lifecycle's spine for a chat turn.

## 29. Data Flow
`message` → Tier1/Tier2 → `IntentResult` → `conversation_state` (write) → Planner/Clarification → `OrchestratorResult` → `conversation_turns` (write) → HTTP response (Module 15).

## 30. Example Workflow
1. User: "how much for 10 units of the X200?"
2. Tier 1 matches "how much" → ambiguous with both `quote_request` and `sales_inquiry` rule sets → falls through.
3. Tier 2 `classify_intent` call returns `{"intent": "quote_request", "confidence": 0.88, "candidates": ["quote_request", "sales_inquiry"]}`.
4. Confidence ≥ 0.7 → Planner builds a plan for `quote_request`.

## 31. Future Extension Points
- Per-tenant intent taxonomy (deferred — taxonomy is global in v4.1, tenancy is foundational-only per architecture §2.16).
- Confidence threshold tuning via feature-flag-style runtime config (currently a code constant).

## 32. Completion Checklist
- [ ] Tier 1 rules implemented and unit-tested for the full taxonomy
- [ ] Tier 2 `classify_intent` is the mandatory first bundled tool call
- [ ] Confidence gate enforces discard-on-uncertainty
- [ ] `Orchestrator.on_turn` hands off to Planner, never directly to Tool Executor
- [ ] All classification attempts persisted to `conversation_state` and `conversation_turns`
- [ ] Tests above pass

## 33. Hardening Update: Facts Extraction, Taxonomy, and Canonical Turn Flow
Module 06 owns facts extraction through `app/router/facts_extractor.py` and `FactsExtractor.extract(...)`, as specified in Module 00 §6. Facts extraction runs after facts/state/recent turns are loaded and before intent classification. It returns a `FactsUpdate`, which is persisted through `SessionStateService.update_facts`; Router classifies using the updated facts.

Canonical interfaces and the full Orchestrator sequence are defined in Module 00 sections 5 and 13. Implementers must call `get_facts`, `get_conversation_state`, and `TurnsService.get_recent_turns` explicitly. After planning, Module 06 persists `conversation_state.current_plan` and `current_plan_step=0` before invoking Module 10.

The authoritative intent taxonomy is Module 00 §4. Tier 2 output must validate against that registry only. The Router does not own a separate taxonomy list.

`FactsExtractor` uses `classification/extract_facts_v1.md` only for optional structured extraction; deterministic extraction runs first. The LLM never decides routing, planning, or business-tool execution.
