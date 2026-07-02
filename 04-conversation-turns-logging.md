# Module 04 — Conversation Turns & Structured Logging

## 1. Module Name
`conversation_turns` — Per-turn audit log (Postgres) + structured JSON application logging.

## 2. Goal
Persist a full, queryable record of every conversation turn (message, intent,
confidence, prompt versions, tool calls) and wire up the shared structured JSON
logger used by every other module from this point forward.

## 3. Purpose
Architecture §2.12 explicitly separates Logs (per-turn debugging detail, stored in
Postgres/structured sink) from Metrics (aggregated counters, Module 16). This
module implements the Logs half and the shared logging utility every module
imports instead of configuring its own logger.

## 4. Dependencies
Module 01 (config, base logging stub), Module 02 (DB), Module 03 (session_id/tenant_id scoping conventions).

## 5. Folder Structure
```
app/
├── turns/
│   ├── __init__.py
│   ├── models.py
│   ├── schemas.py
│   ├── repository.py
│   └── service.py
├── logging_config.py       (extended from Module 01 stub)
tests/
├── unit/
│   └── test_turns_service.py
└── integration/
    └── test_turns_persistence.py
```

## 6. Files to Create
`turns/models.py`, `turns/schemas.py`, `turns/repository.py`, `turns/service.py`, extend `logging_config.py`.

## 7. Responsibility of Every File
| File | Responsibility |
|---|---|
| `turns/models.py` | ORM model for `conversation_turns` |
| `turns/schemas.py` | `ConversationTurnCreate`, `ConversationTurnRead` |
| `turns/repository.py` | Insert-only repository (turns are append-only, never updated) |
| `turns/service.py` | `record_turn(...)` — the single entrypoint the Orchestrator calls once per turn |
| `logging_config.py` | JSON formatter, log level from `Settings.logging.log_level`, secret redaction filter |

## 8. Classes
- `ConversationTurn` (ORM).
- `TurnsRepository` — `async create(turn: ConversationTurnCreate) -> ConversationTurn`.
- `TurnsService` — thin wrapper adding validation/defaults before insert.
- `JsonFormatter(logging.Formatter)` — renders each log record as one JSON line.
- `SecretRedactionFilter(logging.Filter)` — masks values for keys matching `KEY|SECRET|TOKEN|PASSWORD`.

## 9. Data Models
`ConversationTurn` (ORM, table `conversation_turns`):
`id: UUID (pk, default gen_random_uuid())`, `tenant_id: UUID`, `session_id: str`,
`turn_number: int`, `user_message: text`, `assistant_message: text | None`,
`intent: str | None`, `intent_confidence: float | None`, `intent_source: str | None`
(`"tier1"` / `"tier2"`), `candidate_intents: text[]`, `prompt_version: JSONB`
(e.g. `{"system": "base_v1", "intent": "sales_inquiry_v2"}`), `tool_calls: JSONB`
(list of `{tool, args, result_summary}`), `created_at: timestamptz`.

## 10. Pydantic Schemas
- `ConversationTurnCreate` — all fields required except `assistant_message`, `intent*`, `tool_calls` (populated progressively as the turn is processed).
- `ConversationTurnRead` — full read model, used only for future debugging tooling (no endpoint exposes it in v4.1 scope beyond an optional dev-only query helper).

## 11. Repository Layer
`TurnsRepository.create(turn: ConversationTurnCreate) -> ConversationTurn` — single `INSERT`, no update/delete methods (append-only by design; corrections are new turns, never edits).

## 12. Service Layer
`TurnsService.record_turn(tenant_id, session_id, turn_number, user_message, assistant_message, intent_result, prompt_versions, tool_calls) -> None` — assembles the `ConversationTurnCreate` and calls the repository; called exactly once per turn, at the end of `Orchestrator.on_turn`, after all other modules have contributed their piece of the record (Router's intent, Planner's prompt version, Tool Executor's tool_calls).

## 13. Internal Interfaces
- Every module that has "something worth debugging later" contributes to the turn record by returning a value the Orchestrator threads into `record_turn` — this module does not reach into other modules; it is a pure sink.
- `get_logger(name: str) -> logging.Logger` exported from `logging_config.py`, used by every module (`logger = get_logger(__name__)`), replacing ad hoc `logging.getLogger`.

## 14. Database Tables
```sql
CREATE TABLE conversation_turns (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant_id UUID NOT NULL,
  session_id TEXT NOT NULL,
  turn_number INTEGER NOT NULL,
  user_message TEXT NOT NULL,
  assistant_message TEXT,
  intent TEXT,
  intent_confidence REAL,
  intent_source TEXT,
  candidate_intents TEXT[] DEFAULT '{}',
  prompt_version JSONB,
  tool_calls JSONB,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX idx_conversation_turns_session ON conversation_turns (tenant_id, session_id, turn_number);
```

## 15. Redis Keys
None (turns are Postgres-only, never cached — they are write-once, read-rarely).

## 16. API Endpoints
None public in v4.1. Internal-only module.

## 17. Request Models
N/A.

## 18. Response Models
N/A.

## 19. Business Logic
- `turn_number` is monotonically increasing per `(tenant_id, session_id)`; computed by the Orchestrator as `previous_max + 1` (simplest: `SELECT COALESCE(MAX(turn_number),0)+1 ...` inside the same transaction as the insert, to avoid a race in local single-process dev — acceptable at this scale; documented as a future concern if concurrent requests per session ever occur).
- `prompt_version` is deliberately a small JSON object (not a single tag) per architecture §2.7, so a `WHERE prompt_version->>'intent' = 'sales_inquiry_v2'` query can isolate exactly which prompt was live for any turn.

## 20. Validation Rules
- `user_message` required, non-empty.
- `intent_confidence` if present must be in `[0.0, 1.0]`.
- `tool_calls` if present must be a JSON array of objects each containing at least `tool` and `args` keys.

## 21. Error Handling
| Error | Handling |
|---|---|
| Insert fails (DB down) | Log `ERROR` with full turn payload to the structured log sink (so the turn detail isn't lost even if the DB write fails) — **never raise**, since a logging failure must not break the user-facing conversation |
| Malformed `tool_calls` JSON | Validation error caught at the Pydantic schema layer before reaching the repository; logged and turn still recorded with `tool_calls: null` |

## 22. Logging Strategy
- This module *is* the logging strategy for per-turn detail (Postgres sink) plus the general-purpose structured logger (stdout JSON) used everywhere else.
- Every log line: `{"timestamp", "level", "logger", "message", "tenant_id"?, "session_id"?, ...extra}`.
- `SecretRedactionFilter` applied globally at handler-attach time in `configure_logging`.
- Log level controlled by `LOG_LEVEL` env var (`Settings.logging.log_level`), default `INFO`.

## 23. Unit Tests
- `test_json_formatter_produces_valid_json`
- `test_secret_redaction_filter_masks_key_fields`
- `test_turns_service_builds_correct_create_schema`

## 24. Integration Tests
- `test_record_turn_inserts_row_with_correct_turn_number`
- `test_record_turn_sequential_numbering_per_session`
- `test_record_turn_failure_does_not_raise` (simulate DB error, assert no exception propagates)

## 25. Configuration
`Settings.logging.log_level` (from Module 01). No new settings.

## 26. Environment Variables
`LOG_LEVEL` (already defined in Module 00).

## 27. Sequence Diagram
```
Orchestrator.on_turn() completes all processing
        │
        ▼
TurnsService.record_turn(tenant_id, session_id, ..., tool_calls)
        │
   compute next turn_number
        │
   TurnsRepository.create(...)
        │
        ▼
   INSERT INTO conversation_turns  (Postgres)
```

## 28. Request Lifecycle
Not directly HTTP-triggered; called once at the tail end of every `/chat`-style request handled in Module 15.

## 29. Data Flow
Orchestrator (aggregates data from Router, Planner, Tool Executor) → `TurnsService.record_turn` → `conversation_turns` table. One-directional, write-only from this module's perspective.

## 30. Example Workflow
1. User: "Do you have a 48-port Cisco switch?"
2. Router classifies `sales_inquiry` (confidence 0.92, source `tier1`).
3. Planner builds a plan; Prompt Manager resolves `sales_inquiry_v2`.
4. Tool Executor runs `retrieve_products`.
5. Orchestrator assembles all of the above and calls `record_turn` — one row appended with `intent`, `prompt_version`, `tool_calls` fully populated.

## 31. Future Extension Points
- A read-only internal debugging endpoint (`GET /debug/turns/{session_id}`) — deliberately excluded from v4.1 scope as it borders on admin tooling.
- Long-term retention/archival policy for `conversation_turns` (deferred to a production-phase concern).

## 32. Completion Checklist
- [ ] `conversation_turns` table created via migration
- [ ] `record_turn` called exactly once per turn from the Orchestrator
- [ ] `prompt_version` stored as structured JSONB, not a flat string
- [ ] Shared JSON logger used by all subsequent modules (no module defines its own logger config)
- [ ] Secret redaction verified in logs
- [ ] Tests above pass
