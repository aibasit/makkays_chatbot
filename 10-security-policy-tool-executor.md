# Module 10 — Security Policy Registry & Tool Executor

## 1. Module Name
`tool_executor` — Declarative per-tool Security Policy + plan-constrained execution engine.

## 2. Goal
Implement the formalized replacement for v4's ad hoc "intent gate": every tool has
a declarative policy (allowed intents, required state/slots, rate limit, audit
log), loaded at startup and enforced before any execution, on top of an executor
that only ever runs steps present in the current Task Planner plan.

## 3. Purpose
This is the system's defense-in-depth safety boundary for tool execution: the
Planner's plan says a step *should* run; the Security Policy says it's *allowed*
to run given current state/slots/intent. A mismatch on either axis is rejected
and logged, never silently skipped — this is what "prevents accidental or
malicious execution" means concretely in this architecture.

## 4. Dependencies
Module 03 (Facts/Conversation State), Module 05 (LLM engine, for the tool-calling loop), Module 07 (Plan shape), Module 09 (Feature Flags, for tool registration gating).

## 5. Folder Structure
```
app/
├── tools/
│   ├── __init__.py
│   ├── executor.py
│   ├── registry.py
│   ├── policy.py
│   ├── schemas.py
│   └── exceptions.py
security_policies/
├── generate_quote.yaml
├── create_ticket.yaml
├── retrieve_products.yaml
├── retrieve_docs.yaml
├── compare.yaml
├── create_lead.yaml
└── respond.yaml
tests/
├── unit/
│   ├── test_policy_loader.py
│   └── test_tool_executor_enforcement.py
└── integration/
    └── test_tool_executor_end_to_end.py
```

## 6. Files to Create
`executor.py`, `registry.py`, `policy.py`, `schemas.py`, `exceptions.py`, plus one YAML file per tool under `security_policies/`.

## 7. Responsibility of Every File
| File | Responsibility |
|---|---|
| `executor.py` | `ToolExecutor.execute_plan(plan, session)` — the plan-constrained execution loop |
| `registry.py` | Maps step names to actual tool implementations (functions from Modules 11/12/14, etc.); builds the LLM tool schema, filtered by feature flags |
| `policy.py` | Loads YAML policies at startup, `SecurityPolicy.check(tool_name, intent, state, facts) -> PolicyCheckResult` |
| `schemas.py` | `SecurityPolicySchema`, `PolicyCheckResult`, `ToolExecutionResult` |
| `exceptions.py` | `PolicyViolationError`, `PlanViolationError`, `RateLimitExceededError` |

## 8. Classes
- `SecurityPolicy` — one instance per tool, fields matching architecture §2.14 YAML shape.
- `PolicyRegistry` — loads all YAML files at startup into `dict[str, SecurityPolicy]`.
- `ToolRegistry` — `dict[str, ToolImplementation]`, filtered by `FeatureFlags` before being exposed to the LLM's tool schema.
- `ToolExecutor` — `async execute_plan(plan: Plan, session) -> list[ToolExecutionResult]`.

## 9. Data Models
No new database tables for policies themselves (YAML files, loaded at startup — matches architecture's "loaded at startup and enforced by the Tool Executor"). An **audit log** table is required for policies with `audit_log: true`:
```sql
CREATE TABLE tool_audit_log (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant_id UUID NOT NULL,
  session_id TEXT NOT NULL,
  tool_name TEXT NOT NULL,
  intent TEXT,
  allowed BOOLEAN NOT NULL,
  denial_reason TEXT,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
```

## 10. Pydantic Schemas
- `SecurityPolicySchema { tool_name: str, allowed_intents: list[str], required_state: list[str], required_slots: list[str], rate_limit: str | None, audit_log: bool }`.
- `PolicyCheckResult { allowed: bool, reason: str | None, clause_failed: Literal["intent","state","slots","rate_limit"] | None }`.
- `ToolExecutionResult { step: str, success: bool, result_summary: str, error: str | None }`.

## 11. Repository Layer
`ToolAuditLogRepository.create(entry) -> None` — append-only, mirrors `TurnsRepository`'s pattern (Module 04).

## 12. Service Layer
`ToolExecutor.execute_plan(plan, session)`:
1. For each `step` in `plan.steps`, in order:
   a. Confirm `step` is a registered tool in `ToolRegistry` (feature-flag-filtered) — if not, this is a config bug, log `ERROR`, skip.
   b. `policy = PolicyRegistry.get(step)`.
   c. `result = policy.check(intent=plan.intent, state=session.conversation_state, facts=session.facts)`.
   d. If not allowed: raise/record `PolicyViolationError` with `clause_failed`; if `policy.audit_log`, write to `tool_audit_log`; **do not execute** the tool; continue to next step or abort per step criticality (see §19).
   e. If allowed: execute the tool implementation, capture `ToolExecutionResult`; if `audit_log`, write an "allowed" audit entry too.
2. Return the list of `ToolExecutionResult` for the Orchestrator to fold into `conversation_turns.tool_calls`.

**Plan-conformance check** (separate from Security Policy, per architecture §2.4/§3): if the LLM, during its response generation, emits a tool call for a step **not present in the current plan**, that call is rejected and logged as a `PlanViolationError` — distinct from a policy failure, flagging a Planner/prompt mismatch worth investigating (architecture §3).

## 13. Internal Interfaces
- `execute_plan(plan, session) -> list[ToolExecutionResult]` — called by the Orchestrator (Module 06) immediately after `TaskPlanner.build_plan`.
- `ToolRegistry.get_llm_tool_schema(flags) -> list[dict]` — called before every `OllamaClient.chat` invocation that might involve tool calling, so disabled tools are never even offered to the model.
- Each concrete tool (Modules 11/12/14) registers itself via a `@register_tool("retrieve_products")` decorator or equivalent explicit registration call in `registry.py` — this module does not implement RAG/Quote/CRM logic itself, only the dispatch/enforcement layer around them.

## 14. Database Tables
`tool_audit_log` (above). Reads (does not own) `conversation_state`, `session_facts` (Module 03).

## 15. Redis Keys
| Key Pattern | TTL | Purpose |
|---|---|---|
| `ratelimit:{tenant_id}:{session_id}:{tool_name}` | matches the rate window (e.g., 60s for "5/min") | Sliding/fixed-window counter backing the `rate_limit` policy clause |

## 16. API Endpoints
None public — internal execution engine, invoked from the Orchestrator.

## 17. Request Models
N/A.

## 18. Response Models
`ToolExecutionResult` list, folded into `OrchestratorResult.tool_calls` (Module 06) and `conversation_turns.tool_calls` (Module 04).

## 19. Business Logic
- **Step criticality**: `respond` and steps that are purely informational (`retrieve_products`, `retrieve_docs`, `compare`) failing policy is logged but does not abort the whole plan — the Orchestrator degrades gracefully (fewer facts to answer with). A **mutating** step (`generate_quote`, `create_lead`, `create_ticket`) failing policy **does** abort further execution of that step's downstream dependents in the plan (e.g., no point running a hypothetical "send quote email" step if `generate_quote` itself was denied) — this criticality classification is a small static lookup table in `executor.py`, not a policy field.
- **Rate limiting**: implemented as a Redis `INCR` + `EXPIRE` counter per `(tenant_id, session_id, tool_name)`; parsed from the `"N/unit"` string format in the YAML (e.g., `"5/min"` → window 60s, limit 5).
- **Policy vs Plan are independently checked** — a step can be in-plan but policy-denied, or (should never happen given Module 07's correctness, but is still checked) policy-allowed yet not in-plan; both are rejected, logged with distinct error types, per architecture §3.

## 20. Validation Rules
- Every YAML policy file must specify all five fields (`allowed_intents`, `required_state`, `required_slots`, `rate_limit`, `audit_log`) — a startup self-check (mirroring Module 08's prompt self-check) verifies every registered tool has a corresponding policy file, and vice versa; a tool with no policy file fails startup rather than defaulting to "allow everything."
- `required_state` values must correspond to real, checkable predicates over `ConversationStateSchema`/computed facts (e.g., `quote_slots_complete`) — implemented as a small named-predicate registry in `policy.py`, not arbitrary string eval.

## 21. Error Handling
| Error | Handling |
|---|---|
| Tool call not present in current plan | Raise `PlanViolationError`, log `ERROR` (Planner/prompt mismatch), reject the call, do not execute |
| Tool call present in plan but fails Security Policy | Raise `PolicyViolationError` with `clause_failed` populated, log `WARNING` with which clause failed, write audit entry if `audit_log: true` |
| Rate limit exceeded | Raise `RateLimitExceededError`, treated as a policy failure (`clause_failed="rate_limit"`) |
| Tool implementation itself throws (e.g., Qdrant unreachable) | Caught per-step, recorded as `ToolExecutionResult(success=False, error=...)`, does not crash the whole turn — Orchestrator responds with whatever succeeded plus a graceful degradation message |
| No policy file found for a registered tool | Startup failure (fail fast), per validation rule above |

## 22. Logging Strategy
- Every policy check logged at `DEBUG` (allowed) or `WARNING` (denied) with `tool_name`, `clause_failed` if any.
- Every `PlanViolationError` logged at `ERROR` — always worth investigating per architecture §3.
- Audit log entries are the durable record for `audit_log: true` tools; general logs are supplementary, not a substitute.

## 23. Unit Tests
- `test_policy_check_denies_wrong_intent`
- `test_policy_check_denies_missing_required_state`
- `test_policy_check_denies_missing_required_slots`
- `test_policy_check_denies_over_rate_limit`
- `test_policy_check_allows_when_all_clauses_pass`
- `test_startup_fails_if_tool_missing_policy_file`
- `test_execute_plan_rejects_step_not_in_plan`

## 24. Integration Tests
- `test_execute_plan_runs_generate_quote_when_policy_and_plan_agree`
- `test_execute_plan_denies_generate_quote_when_slots_incomplete_even_if_in_plan`
- `test_rate_limit_enforced_across_repeated_calls_within_window`
- `test_disabled_tool_not_present_in_llm_tool_schema`
- `test_tool_failure_does_not_crash_turn`

## 25. Configuration
```
tools:
  policy_directory: str = "./security_policies"
```

## 26. Environment Variables
Optionally `SECURITY_POLICY_DIR` (defaults as above; not in the required-credentials list since it has a safe default).

## 27. Sequence Diagram
```
Orchestrator: plan = TaskPlanner.build_plan(...)
        │
        ▼
ToolExecutor.execute_plan(plan, session)
        │
   for step in plan.steps:
        │
        ├─ registered? ── no ──► log ERROR, skip
        │
        ├─ PolicyRegistry.get(step).check(intent, state, facts)
        │        │
        │   allowed? ── no ──► PolicyViolationError, audit log, skip/abort per criticality
        │        │ yes
        │        ▼
        │   execute tool implementation
        │        │
        │        ▼
        │   ToolExecutionResult
        │
        ▼
   return list[ToolExecutionResult]
```

## 28. Request Lifecycle
In-process, one call per turn (after Planner, before turn recording), executing 1–N steps sequentially within that single call.

## 29. Data Flow
`Plan` + `ConversationState` + `Facts` + `FeatureFlags` → per-step policy check → tool implementation (Modules 11/12/14) → `ToolExecutionResult` list → `tool_audit_log` (for audited tools) + `conversation_turns.tool_calls` (Module 04).

## 30. Example Workflow
1. Plan: `["retrieve_products", "retrieve_docs", "compare", "generate_quote"]`, intent `sales_inquiry`.
2. `generate_quote` policy requires `allowed_intents: [sales_inquiry, quote_request]` (passes), `required_slots: [company, products, quantity, budget]` — `quantity` missing from Facts.
3. Policy check fails with `clause_failed="slots"`; `generate_quote` is denied and logged; audit entry written (`allowed_intents` policy has `audit_log: true`).
4. Turn completes with quote generation skipped; Orchestrator's `respond` fallback (if also in plan) explains what's still needed — driven by the Clarification template library (Module 13), not free-form LLM text, per architecture §2.13.

## 31. Future Extension Points
- Runtime-editable policies (DB-backed, mirroring Module 09's flag override pattern) — deferred, YAML-at-startup is sufficient for v4.1.
- Per-tenant policy overrides (multi-tenancy is foundational-only in v4.1).

## 32. Completion Checklist
- [ ] Every registered tool has exactly one YAML policy file; startup fails otherwise
- [ ] Plan-conformance and Security-Policy checks are independently enforced and independently logged
- [ ] Rate limiting backed by Redis, correctly windowed
- [ ] Audit log written for every `audit_log: true` tool, allowed or denied
- [ ] Disabled tools (Module 09 flags) never appear in the LLM tool schema
- [ ] Tests above pass
