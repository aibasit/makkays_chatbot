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
│   ├── orchestrator.py
│   ├── tier1_rules.py
│   ├── tier2_classifier.py
│   ├── schemas.py
│   └── exceptions.py
tests/
├── unit/
│   ├── test_tier1_rules.py
│   └── test_tier2_classifier.py
└── integration/
    └── test_orchestrator_on_turn.py
```

## 6. Files to Create
`orchestrator.py`, `tier1_rules.py`, `tier2_classifier.py`, `schemas.py`, `exceptions.py`.

## 7. Responsibility of Every File
| File | Responsibility |
|---|---|
| `orchestrator.py` | `on_turn(...)` — top-level per-turn control flow, ties Router → Planner → Tool Executor → Turns |
| `tier1_rules.py` | Deterministic keyword/regex/lookup rules producing an `(intent, confidence=1.0)` when a rule matches unambiguously |
| `tier2_classifier.py` | Builds the bundled `classify_intent` LLM call (system + intent taxonomy + full conversation context), parses the structured tool-call result |
| `schemas.py` | `IntentResult`, `ClassifyIntentArguments` |
| `exceptions.py` | `ClassificationFailedError` |

## 8. Classes
- `Tier1RuleEngine` — `match(message: str) -> IntentResult | None`.
- `Tier2Classifier` — `async classify(session_context) -> IntentResult`.
- `Router` — `async classify(session, message) -> IntentResult`, orchestrates Tier1→Tier2 fallback.
- `Orchestrator` — `async on_turn(tenant_id, session_id, message) -> OrchestratorResult`.

## 9. Data Models
No new persisted tables (writes to `conversation_state`/`conversation_turns` owned by Modules 03/04).

## 10. Pydantic Schemas
- `IntentResult { intent: str, confidence: float, source: Literal["tier1","tier2"], candidates: list[str] = [], spec_question_detected: bool = False }` — `spec_question_detected` is populated by `Tier1RuleEngine.match` when the message contains a spec-like pattern (port count, dimensions, compatibility queries, detailed technical specifications). The Router sets this field; the Planner (Module 07) reads it from the `IntentResult` passed into `build_plan`.
- `ClassifyIntentArguments { intent: str, confidence: float, candidates: list[str] }` — the shape the LLM tool call must produce (JSON-schema-constrained via Module 05's structured output).
- `OrchestratorResult { assistant_message: str, intent: str, awaiting_clarification: bool, plan: Plan | None, tool_calls: list[ToolExecutionResult] }` — uses typed references to `Plan` (Module 07) and `ToolExecutionResult` (Module 10). `plan` is `None` when the clarification flow ran instead of the Planner.

## 11. Repository Layer
None new — uses `SessionStateService` (Module 03) and `TurnsService` (Module 04).

## 12. Service Layer
`Orchestrator.on_turn(tenant_id, session_id, user_message) -> OrchestratorResult`:
1. Load `facts, state = await SessionStateService.get(tenant_id, session_id)` from Module 03.
2. Resolve `flags = await FeatureFlagsService.resolve(tenant_id)` from Module 09 — called once here; the resolved `FeatureFlags` object is passed to both Planner and Tool Executor.
3. Route: `intent_result = Router.classify(user_message, facts, state)` (Tier 1 then Tier 2, see §8).
4. Call `MetricsRegistry.increment_intent_classification(source=intent_result.source, intent=intent_result.intent)` and `MetricsRegistry.record_intent_confidence(intent_result.confidence)` from Module 16.
5. Update `ConversationState` with the new intent and confidence (`ConversationStateRepository.upsert`).
6. Compute `turn_number` by delegating to `TurnsService.get_next_turn_number(tenant_id, session_id)` (a single `SELECT COALESCE(MAX(turn_number),0)+1 ... FOR UPDATE` inside a transaction).
7. Low-confidence branch: if `intent_result.confidence < settings.ollama.classification_confidence_threshold`, call `ClarificationFlow.run(tenant_id, session_id, intent_result, facts, state)` from Module 13 — wrap in `try/except MaxClarificationRoundsExceededError`; on catch, override `intent_result.intent = 'escalation_request'` and fall through to step 8.
8. Build plan: `plan = TaskPlanner.build_plan(intent_result, facts, state, flags)` from Module 07.
9. Execute plan: `tool_results = await ToolExecutor.execute_plan(plan, tenant_id, session_id, facts, state, flags)` from Module 10.
10. Assemble `assistant_message`: if the clarification flow ran (not overridden), use `clarification_result.question_text`; if the plan executed, use the `result_summary` from the `respond` step in `tool_results`.
11. Record turn: `await TurnsService.record_turn(tenant_id, session_id, turn_number, user_message, intent_result, plan, tool_results, assistant_message)` from Module 04.
12. Return `OrchestratorResult(assistant_message=..., intent=intent_result.intent, awaiting_clarification=clarification_ran, plan=plan, tool_calls=tool_results)`.

Clarification branch return path: when `ClarificationFlow.run` is called (not via the `MaxClarificationRoundsExceededError` catch), set `result.awaiting_clarification = True`, `result.assistant_message = clarification_result.question_text`, `result.plan = None`, `result.tool_calls = []`. Record the turn and return.

## 13. Internal Interfaces
- `Router.classify(session, message) -> IntentResult` — sole entrypoint used by the Orchestrator; Tier1/Tier2 internals are not called directly by anything else.
- `Orchestrator.on_turn(...) -> OrchestratorResult` — sole entrypoint used by Module 15's `/chat` endpoint.

## 14. Database Tables
None new — reads/writes `conversation_state` (Module 03) and `conversation_turns` (Module 04).

## 15. Redis Keys
None new — uses Module 03's `conv:{tenant_id}:{session_id}`.

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
None new (threshold is a code-level constant per architecture's "unchanged from v4" note, not currently env-driven; documented here as a candidate for promotion to an env var only if tuning is needed later).

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
