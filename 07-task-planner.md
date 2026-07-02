# Module 07 — Task Planner

## 1. Module Name
`task_planner` — Deterministic, code-driven step planner sitting between Router and Tool Executor.

## 2. Goal
Implement `build_plan(intent, facts, conversation_state, feature_flags) -> Plan`
as a standalone, independently testable module, per architecture §2.4 and Build
Order step 6.

## 3. Purpose
Separates *what* the user wants (Router's job) from *how* to satisfy it (this
module's job), so one intent can map to a variable set of steps depending on
what's already known, without hardcoding every combination into the intent
taxonomy itself.

## 4. Dependencies
Module 03 (Facts/Conversation State schemas), Module 09 (Feature Flags — consulted to skip disabled steps).

## 5. Folder Structure
```
app/
├── planner/
│   ├── __init__.py
│   ├── planner.py
│   ├── rules.py
│   ├── schemas.py
│   └── exceptions.py
tests/
└── unit/
    └── test_planner_rules.py   (this module is pure/deterministic — unit tests are the primary coverage; no integration test needed beyond a thin wiring check)
```

## 6. Files to Create
`planner.py`, `rules.py`, `schemas.py`, `exceptions.py`.

## 7. Responsibility of Every File
| File | Responsibility |
|---|---|
| `planner.py` | `TaskPlanner.build_plan(...)` — orchestrates rule evaluation into an ordered `Plan` |
| `rules.py` | Per-intent rule tables (the condition → step mapping from architecture §2.4), one function per intent, e.g. `plan_sales_inquiry(facts, state, flags) -> list[str]` |
| `schemas.py` | `Plan`, `PlanStep` |
| `exceptions.py` | `UnknownIntentError` (raised if `build_plan` is called with an intent that has no registered rule function — a configuration bug, not a runtime user error) |

## 8. Classes
- `TaskPlanner` — `build_plan(intent, facts, state, flags) -> Plan`; dispatches to the correct per-intent rule function via a registry dict.
- `Plan { intent: str, steps: list[str] }` (matches architecture's JSON shape exactly).

## 9. Data Models
No persistence of its own — `Plan` is stored by the *caller* into `conversation_state.current_plan` (Module 03's table), not by this module directly. This module is a pure function boundary: same inputs always produce the same plan.

## 10. Pydantic Schemas
- `Plan { intent: str, steps: list[str] }`.
- `PlanStep` — not a separate object in v4.1 (steps are plain strings per the architecture's plan shape); reserved as a future extension point if steps need per-step metadata.

## 11. Repository Layer
N/A — stateless, pure function module.

## 12. Service Layer
`TaskPlanner.build_plan(intent, facts, state, flags) -> Plan`:
1. Look up the rule function for `intent` in the registry; raise `UnknownIntentError` if missing.
2. Call the rule function, which evaluates the ordered condition table (architecture §2.4) and returns an ordered list of step names.
3. Filter out any step whose corresponding feature flag is off (belt-and-suspenders with Module 09's tool-registration-level gating).
4. Wrap into `Plan(intent=intent, steps=steps)` and return.

## 13. Internal Interfaces
- `build_plan(intent, facts, state, flags) -> Plan` — the only public entrypoint, called by `Orchestrator.on_turn` (Module 06) immediately after intent acceptance.
- Rule functions follow a fixed signature `(facts: FactsSchema, state: ConversationStateSchema, flags: FeatureFlags) -> list[str]` so new intents can be added by writing one new function + one registry entry, without touching `TaskPlanner` itself.

## 14. Database Tables
None — this module never touches the database directly.

## 15. Redis Keys
None.

## 16. API Endpoints
None — internal module only.

## 17. Request Models
N/A.

## 18. Response Models
`Plan` (above), returned in-process to the Orchestrator, then passed to Tool Executor (Module 10) and persisted into `conversation_state.current_plan` via Module 03.

## 19. Business Logic
Reproduces architecture §2.4's condition table verbatim for `sales_inquiry` as the reference implementation; the same pattern (ordered condition checks over `facts`/`state`/`flags`) is used for other intents (`quote_request`, `technical_support`, `escalation_request`):

**`plan_sales_inquiry(facts, state, flags)`**, evaluated in order:
1. `facts.product_interest is None` → append `retrieve_products`.
2. `flags.enable_rag and message_has_spec_question` → append `retrieve_docs`. *(`message_has_spec_question` is a simple heuristic flag threaded in from the Router's Tier 1 pass — not a fresh LLM call.)*
3. `len(candidate_products) > 1` → append `compare`.
4. `flags.enable_quotes and quote_slots_complete(facts)` → append `generate_quote`.
5. `flags.enable_quotes and not quote_slots_complete(facts)` → append `request_missing_slots`.
6. `contact_info_newly_captured(state)` → append `create_lead`.
7. If no step appended yet → append `respond` (fallback: LLM explains/asks using only already-retrieved context).

`quote_slots_complete(facts) -> bool` checks `company`, `product_interest` (mapped to `products`), a `quantity` slot (tracked in Facts — **note**: `quantity` is not in the v4.1 `session_facts` DDL as shown in architecture §2.5; this module treats it as an additional Facts column to be added via a small additive migration owned by Module 03 when Quote Builder, Module 12, is implemented — flagged explicitly here rather than silently assumed), and `budget`.

## 20. Validation Rules
- Rule functions must always return a **non-empty** list — if no condition matches, `respond` is always the guaranteed fallback (enforced by an assertion at the end of every rule function, not left implicit).
- Step names returned must exactly match the tool names registered in Module 10 (Tool Executor) and Module 09 (Feature Flags) — a mismatch is a build-time/test-time bug to catch via the unit tests below, not a runtime concern.

## 21. Error Handling
| Error | Handling |
|---|---|
| Unknown intent (no rule function registered) | Raise `UnknownIntentError`; Orchestrator catches this, logs at `ERROR` as a Planner/taxonomy mismatch, falls back to `escalation_request` plan |
| Rule function returns empty list (bug) | Defensive check in `TaskPlanner.build_plan` — if empty, log `ERROR` and substitute `Plan(intent=intent, steps=["respond"])` rather than propagate an invalid empty plan downstream |

## 22. Logging Strategy
- Log every built plan at `DEBUG`: `intent`, `steps` (the plan itself is small and non-sensitive, safe to log in full, unlike raw user messages).
- Log `UnknownIntentError` and empty-plan fallbacks at `ERROR` — both indicate a code/taxonomy mismatch worth investigating.

## 23. Unit Tests
- `test_plan_sales_inquiry_no_product_identified_includes_retrieve_products`
- `test_plan_sales_inquiry_rag_flag_off_skips_retrieve_docs`
- `test_plan_sales_inquiry_multiple_candidates_includes_compare`
- `test_plan_sales_inquiry_quote_slots_complete_includes_generate_quote`
- `test_plan_sales_inquiry_quote_slots_incomplete_includes_request_missing_slots`
- `test_plan_sales_inquiry_fallback_is_respond_when_nothing_else_matches`
- `test_build_plan_unknown_intent_raises`
- `test_build_plan_never_returns_empty_steps`
- Synthetic fact/state combinations per intent, per architecture Build Order step 6 ("Test with synthetic fact/state combinations per intent") — a parametrized test matrix covering every row of the condition table independently and in combination.

## 24. Integration Tests
None required beyond a single thin wiring test (`test_orchestrator_calls_build_plan_with_correct_args`), since this module is pure/deterministic and fully covered by unit tests — matches the architecture's explicit instruction to build and test it standalone *before* wiring to the Tool Executor.

## 25. Configuration
No new settings — consumes `FeatureFlags` (Module 09) passed in as a parameter, never reads env vars directly (keeps it a pure function for testability).

## 26. Environment Variables
None directly (flags flow in via Module 09).

## 27. Sequence Diagram
```
Orchestrator (post intent-acceptance)
        │
        ▼
TaskPlanner.build_plan(intent, facts, state, flags)
        │
   registry lookup → rule_fn = RULES[intent]
        │
   steps = rule_fn(facts, state, flags)
        │
   filter steps by flags (defense in depth)
        │
        ▼
   Plan(intent, steps) ──► ToolExecutor.execute_plan(plan, session)
```

## 28. Request Lifecycle
Purely in-process, one call per turn, sandwiched between Router (Module 06) and Tool Executor (Module 10) inside `Orchestrator.on_turn`.

## 29. Data Flow
`(intent, Facts, ConversationState, FeatureFlags)` → `Plan` → written to `conversation_state.current_plan` (via Module 03) → read by Tool Executor (Module 10) to drive execution.

## 30. Example Workflow
See architecture §2.4 example: `sales_inquiry` with no product yet identified and a spec question present → `["retrieve_products", "retrieve_docs", "compare", "respond"]` (assuming multiple candidates surface after retrieval — note the plan is built *before* retrieval runs, so `compare` here reflects the pre-retrieval expectation from candidate count already known this turn from prior turns' Facts, not the not-yet-executed retrieval result; if retrieval surfaces unexpected additional candidates, that's a Tool Executor / Orchestrator re-planning concern documented as a future extension point below, not handled by re-invoking the Planner mid-plan in v4.1).

## 31. Future Extension Points
- LLM-assisted planning for more open-ended multi-step reasoning — explicitly deferred per architecture §2.4's closing note.
- Mid-plan re-planning when tool execution surfaces information that changes the plan (e.g., retrieval returns more candidates than expected) — not in v4.1 scope; current behavior completes the originally built plan.

## 32. Completion Checklist
- [ ] `build_plan` is a pure, deterministic function (no I/O, no LLM calls)
- [ ] Every registered intent has a rule function returning a non-empty step list in all cases
- [ ] Feature-flag filtering applied as defense in depth
- [ ] Full synthetic fact/state test matrix per intent
- [ ] Built and unit-tested standalone before Tool Executor wiring (per Build Order step 6)
