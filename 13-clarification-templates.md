# Module 13 — Clarification Template Library

## 1. Module Name
`clarification` — Template-first clarification question flow with optional constrained LLM rewrite.

## 2. Goal
Implement the template-library lookup that produces clarification questions
verbatim by default, plus the optional `ENABLE_LLM_CLARIFICATION_REWRITE`-gated
LLM rewording pass that can change wording but never the option set.

## 3. Purpose
Closes the v4 gap where the LLM authored clarification question content directly
(risking invented/incorrect options). This module guarantees consistent,
testable, screenshot-able UX for the single highest-friction moment in the
conversation — when the system isn't sure what the user wants.

## 4. Dependencies
Module 03 (Conversation State — `clarification_candidates`, `clarification_rounds`), Module 05 (LLM engine, only if rewrite flag is on), Module 08 (Prompt Manager, template storage), Module 09 (`ENABLE_LLM_CLARIFICATION_REWRITE` flag).

## 5. Folder Structure
```
app/
├── clarification/
│   ├── __init__.py
│   ├── flow.py
│   ├── template_lookup.py
│   ├── schemas.py
│   └── exceptions.py
prompt_library/
└── clarification/
    ├── sales_vs_support_vs_quote.md
    ├── generic_fallback.md
    └── llm_rewrite_instructions_v1.md
tests/
├── unit/
│   └── test_template_lookup.py
└── integration/
    └── test_clarification_flow.py
```

## 6. Files to Create
`flow.py`, `template_lookup.py`, `schemas.py`, `exceptions.py`, plus template `.md` files under `prompt_library/clarification/` (already scaffolded in Module 08, populated here with real content).

## 7. Responsibility of Every File
| File | Responsibility |
|---|---|
| `flow.py` | `ClarificationFlow.run(session, candidates) -> str` — the full flow: lookup → optional rewrite → increment round → persist |
| `template_lookup.py` | Maps a `frozenset` of candidate intents to the correct template file name, with a generic fallback |
| `schemas.py` | `ClarificationTemplate`, `ClarificationResult` |
| `exceptions.py` | `MaxClarificationRoundsExceededError` |

## 8. Classes
- `TemplateLookup` — `resolve(candidates: list[str]) -> str` (template filename).
- `ClarificationFlow` — the orchestrating class called directly by `Orchestrator.on_turn` (Module 06) when confidence is below threshold.

## 9. Data Models
No new tables — reuses `conversation_state.clarification_candidates`, `.clarification_rounds`, `.awaiting_clarification`, `.last_question` (Module 03).

## 10. Pydantic Schemas
- `ClarificationTemplate { candidate_key: frozenset[str] | None, filename: str }` — the lookup table entry shape (`None` key = generic fallback).
- `ClarificationResult { question_text: str, source: Literal["template","template+llm_rewrite"] }`.

## 11. Repository Layer
None new — uses `ConversationStateRepository`/`SessionStateService` (Module 03) to read/increment `clarification_rounds` and persist `last_question`.

## 12. Service Layer
`ClarificationFlow.run(tenant_id, session_id, candidates: list[str]) -> ClarificationResult`:
1. `rounds = SessionStateService.get_conversation_state(...).clarification_rounds`.
2. If `rounds >= MAX_CLARIFICATION_ROUNDS` (config, default 2): raise `MaxClarificationRoundsExceededError` — caller (Orchestrator) catches this and falls back to `escalation_request`, per architecture §3 ("Clarification loops beyond max rounds — unchanged from v4 — falls back to escalation_request").
3. `template_name = TemplateLookup.resolve(candidates)`.
4. `template_text = PromptManager.get("clarification", template_name, "latest")` (Module 08).
5. If `flags.enable_llm_clarification_rewrite`: call `OllamaClient.chat` (Module 05) with `llm_rewrite_instructions_v1.md` as system prompt + the template as the fixed content to reword — the prompt explicitly instructs the model it may **only** reword, never add/remove/alter options; response validated post-hoc (see §20) to contain the same option set as the original template.
6. Else: `question_text = template_text` verbatim.
7. `SessionStateService.update_conversation_state(..., awaiting_clarification=True, last_question=question_text)`, increment `clarification_rounds`.
8. Return `ClarificationResult`.

## 13. Internal Interfaces
- `run(tenant_id, session_id, candidates) -> ClarificationResult` — the sole entrypoint, called by `Orchestrator.on_turn` (Module 06) in place of Planner/Tool Executor when confidence is below threshold.
- `TemplateLookup.resolve(candidates) -> str` — usable independently in tests without needing the full flow or an LLM.

## 14. Database Tables
None new.

## 15. Redis Keys
None new — reuses `conv:{tenant_id}:{session_id}` (Module 03).

## 16. API Endpoints
None — internal, surfaced to the user only as the `assistant_message` of a `/chat` response (Module 15).

## 17. Request Models
N/A.

## 18. Response Models
`ClarificationResult`, folded into `OrchestratorResult.assistant_message` (Module 06).

## 19. Business Logic
- **Template selection**: `TemplateLookup` matches on the *set* of candidate intents (e.g., `{sales_inquiry, technical_support, quote_request}` → `sales_vs_support_vs_quote.md`), falling back to `generic_fallback.md` ("here's what I can help with") when no specific match exists for the given candidate combination.
- **Verbatim by default**: the template is sent to the user exactly as written unless the rewrite flag is on — this is deliberate for UX consistency and testability (architecture §2.13).
- **Constrained rewrite**: when enabled, the LLM may reword sentence structure and reference what the user just said, but the enumerated option list itself is fixed by the template — the same "LLM explains, never decides" boundary applied specifically to clarification.

## 20. Validation Rules
- If LLM rewrite is enabled, the rewritten text is validated post-hoc: every bullet/option string present in the original template must appear (allowing minor casing/punctuation normalization) in the rewritten text — if validation fails, **discard the rewrite and fall back to the verbatim template** rather than risk an altered option set reaching the user. This validation is a simple substring/fuzzy-match check, not another LLM call.
- `clarification_rounds` increment is atomic with the read-check in step 2 above (uses the same write-through update path as Module 03, no separate race-prone read-then-write outside the service).

## 21. Error Handling
| Error | Handling |
|---|---|
| `clarification_rounds >= MAX_CLARIFICATION_ROUNDS` | Raise `MaxClarificationRoundsExceededError`; Orchestrator catches, sets intent to `escalation_request`, proceeds through Planner/Tool Executor as normal for that intent (unchanged from v4) |
| Template file missing (`PromptNotFoundError` from Module 08) | Falls back to `generic_fallback.md`; if that too is missing, this is a startup-time configuration bug caught by Module 08's self-check, not a runtime path to handle further here |
| LLM rewrite fails validation (option set altered) or the LLM call itself fails/times out (Module 05 exceptions) | Discard rewrite, use verbatim template — never block the user on a rewrite failure |

## 22. Logging Strategy
- Log every clarification event at `INFO`: `candidates`, `template_name`, `rewrite_used: bool`, `round_number`.
- Log rewrite validation failures at `WARNING` (expected occasional occurrence, not an error).
- Log `MaxClarificationRoundsExceededError` at `WARNING` — signals the user is stuck, worth watching in aggregate (a Metrics concern too, Module 16).

## 23. Unit Tests
- `test_template_lookup_matches_known_candidate_set`
- `test_template_lookup_falls_back_to_generic`
- `test_clarification_flow_verbatim_when_rewrite_disabled`
- `test_clarification_flow_raises_after_max_rounds`
- `test_rewrite_validation_rejects_altered_option_set`
- `test_rewrite_validation_accepts_reworded_but_option_preserving_text`

## 24. Integration Tests
- `test_clarification_flow_persists_round_increment`
- `test_clarification_flow_with_llm_rewrite_enabled_end_to_end`
- `test_orchestrator_falls_back_to_escalation_after_max_rounds`

## 25. Configuration
```
clarification:
  max_clarification_rounds: int = 2
```

## 26. Environment Variables
`ENABLE_LLM_CLARIFICATION_REWRITE` (already defined in Module 00).

## 27. Sequence Diagram
```
Orchestrator: confidence < threshold
        │
        ▼
ClarificationFlow.run(tenant_id, session_id, candidates)
        │
   rounds >= MAX? ── yes ──► MaxClarificationRoundsExceededError → escalation_request
        │ no
   TemplateLookup.resolve(candidates) → template_name
        │
   PromptManager.get("clarification", template_name, "latest") → template_text
        │
   enable_llm_clarification_rewrite? ── yes ──► OllamaClient.chat(...) → validate option-preservation
        │                                              │ fail → discard, use verbatim
        │ no                                           │ pass → use rewritten text
        ▼                                              ▼
   update_conversation_state(awaiting_clarification=True, last_question=...)
        │
        ▼
   ClarificationResult
```

## 28. Request Lifecycle
Invoked once per turn, in place of Planner/Tool Executor, whenever `Router.classify` returns confidence below threshold (Module 06).

## 29. Data Flow
`candidate_intents` (from Router) → `TemplateLookup` → `prompt_library/clarification/*.md` (Module 08) → optional LLM rewrite (Module 05) → `conversation_state` (round increment, last_question) → `OrchestratorResult.assistant_message`.

## 30. Example Workflow
Matches architecture §2.13 exactly:
1. User: "I need help" (ambiguous).
2. Router candidates: `[sales_inquiry, technical_support, quote_request]`, confidence 0.4.
3. `TemplateLookup.resolve` → `sales_vs_support_vs_quote.md`.
4. Verbatim (rewrite flag off): *"Are you looking for: • Product recommendations • Technical support • A quotation"*.
5. `clarification_rounds` incremented to 1.

## 31. Future Extension Points
- Multi-turn clarification chains with progressively narrower templates (currently flat, one template per candidate-set).
- A/B testing template wording via Module 09's flag-rollout extension.

## 32. Completion Checklist
- [ ] Template lookup covers the primary candidate-set combinations plus a generic fallback
- [ ] Verbatim path works with zero LLM calls when rewrite flag is off
- [ ] Rewrite path validates option-set preservation and falls back safely on failure
- [ ] `clarification_rounds` correctly gates escalation fallback
- [ ] Tests above pass
