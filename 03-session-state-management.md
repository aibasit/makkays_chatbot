# Module 03 — Session & State Management (Facts vs Conversation State)

## 1. Module Name
`session_state` — Durable Facts and short-lived Conversation State, per architecture §2.5.

## 2. Goal
Implement the split between **Facts** (durable, slot-like, CRM-bound) and
**Conversation State** (short-lived, per-turn mechanics), each with its own SQL
table, Redis namespace, and independent checkpoint/recovery path.

## 3. Purpose
This is the architecture's core correctness fix over v4: mixing durable and
short-lived data in one blob meant a clarification-round reset could erase a
user's already-given budget. Splitting them — and giving each its own cache +
checkpoint path — guarantees that losing one Redis key never implies losing the
other.

## 4. Dependencies
Module 01 (config), Module 02 (DB/Redis clients).

## 5. Folder Structure
```
app/
├── session/
│   ├── __init__.py
│   ├── models.py            (SessionFacts, ConversationState ORM models)
│   ├── schemas.py            (Pydantic schemas)
│   ├── repository.py         (FactsRepository, ConversationStateRepository)
│   ├── service.py            (SessionStateService)
│   └── exceptions.py
tests/
├── unit/
│   └── test_session_state_service.py
└── integration/
    └── test_facts_and_state_persistence.py
```

## 6. Files to Create
`models.py`, `schemas.py`, `repository.py`, `service.py`, `exceptions.py`.

## 7. Responsibility of Every File
| File | Responsibility |
|---|---|
| `models.py` | ORM models for `session_facts` and `conversation_state` tables |
| `schemas.py` | `FactsSchema`, `ConversationStateSchema`, update/patch variants |
| `repository.py` | Raw CRUD against Postgres for both tables, scoped by `tenant_id` |
| `service.py` | Cache-aside logic: read/write Redis first, checkpoint to SQL, recover from SQL on cache miss |
| `exceptions.py` | `SessionNotFoundError`, `FactsCheckpointError`, `StateCheckpointError` |

## 8. Classes
- `SessionFacts` (ORM) — mirrors architecture §2.5 SQL definition.
- `ConversationState` (ORM) — mirrors architecture §2.5 SQL definition.
- `FactsRepository` — `get(tenant_id, session_id)`, `upsert(...)`.
- `ConversationStateRepository` — `get(...)`, `upsert(...)`.
- `SessionStateService` — orchestrates cache-aside reads/writes for both, independently.

## 9. Data Models
**`SessionFacts`** (ORM, table `session_facts`):
`tenant_id: UUID`, `session_id: str`, `budget: Numeric | None`, `company: str | None`,
`industry: str | None`, `product_interest: str | None`, `project_size: str | None`,
`updated_at: datetime` — composite PK `(tenant_id, session_id)`.

**`ConversationState`** (ORM, table `conversation_state`):
`tenant_id: UUID`, `session_id: str`, `current_intent: str | None`,
`intent_confidence: float | None`, `awaiting_clarification: bool = False`,
`clarification_candidates: list[str] = []`, `clarification_rounds: int = 0`,
`current_plan: dict | None` (JSONB), `current_plan_step: int | None`,
`last_question: str | None`, `updated_at: datetime` — composite PK `(tenant_id, session_id)`.

## 10. Pydantic Schemas
- `FactsSchema` — read model, all fields optional except keys.
- `FactsUpdate` — partial update (only changed slots sent by the caller).
- `ConversationStateSchema` — read model.
- `ConversationStateUpdate` — partial update, primarily used internally by Router (M06)/Planner (M07)/Tool Executor (M10).

## 11. Repository Layer
`FactsRepository`:
- `async get(tenant_id, session_id) -> SessionFacts | None`
- `async upsert(tenant_id, session_id, patch: FactsUpdate) -> SessionFacts`

`ConversationStateRepository`:
- `async get(tenant_id, session_id) -> ConversationState | None`
- `async upsert(tenant_id, session_id, patch: ConversationStateUpdate) -> ConversationState`
- `async increment_clarification_round(tenant_id, session_id) -> int`

## 12. Service Layer
`SessionStateService`:
- `async get_facts(tenant_id, session_id) -> FactsSchema` — Redis `GET facts:{tenant_id}:{session_id}` → on miss, `FactsRepository.get` → repopulate Redis (no TTL — Facts are durable) → return.
- `async update_facts(tenant_id, session_id, patch) -> FactsSchema` — write Redis, then `FactsRepository.upsert` (write-through, not write-behind, to avoid losing a Fact on process crash between the two writes — SQL write is the durability guarantee).
- `async get_conversation_state(...) -> ConversationStateSchema` — Redis `GET conv:{tenant_id}:{session_id}` (30-min TTL) → on miss, `ConversationStateRepository.get` → repopulate Redis with TTL → return.
- `async update_conversation_state(...) -> ConversationStateSchema` — same write-through pattern, TTL re-applied on every write.
- `async reset_conversation_state(tenant_id, session_id)` — clears `awaiting_clarification`, `clarification_candidates`, `current_plan`, `current_plan_step`; **does not touch Facts**.

## 13. Internal Interfaces
Consumed by: Router (M06) reads/writes `ConversationState`; Task Planner (M07) reads `Facts` + `ConversationState`; Tool Executor (M10) reads both, writes `current_plan_step`; CRM Integration (M14) reads `Facts` when creating a lead.

## 14. Database Tables
```sql
CREATE TABLE session_facts (
  tenant_id UUID NOT NULL,
  session_id TEXT NOT NULL,
  budget NUMERIC,
  company TEXT,
  industry TEXT,
  product_interest TEXT,
  project_size TEXT,
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  PRIMARY KEY (tenant_id, session_id)
);

CREATE TABLE conversation_state (
  tenant_id UUID NOT NULL,
  session_id TEXT NOT NULL,
  current_intent TEXT,
  intent_confidence REAL,
  awaiting_clarification BOOLEAN NOT NULL DEFAULT false,
  clarification_candidates TEXT[] NOT NULL DEFAULT '{}',
  clarification_rounds INTEGER NOT NULL DEFAULT 0,
  current_plan JSONB,
  current_plan_step INTEGER,
  last_question TEXT,
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  PRIMARY KEY (tenant_id, session_id)
);
```

## 15. Redis Keys
| Key Pattern | TTL | Contents |
|---|---|---|
| `facts:{tenant_id}:{session_id}` | None (durable, no expiry — checkpointed to SQL on every write) | JSON-serialized `FactsSchema` |
| `conv:{tenant_id}:{session_id}` | 30 min (reset on every write, matching v3 inactivity TTL) | JSON-serialized `ConversationStateSchema` |

## 16. API Endpoints
This module is consumed internally by the Orchestrator; no public HTTP endpoints of its own in v4.1 scope (no admin UI for direct Facts editing).

## 17. Request Models
N/A (internal service, invoked in-process, not via HTTP).

## 18. Response Models
N/A.

## 19. Business Logic
- **Cache-aside with write-through**: every write goes to Redis and Postgres together; every read tries Redis first. This favors read latency (hot path: every turn) while keeping SQL as the recovery source of truth.
- **Independent eviction recovery**: because Facts and Conversation State live under separate Redis keys and separate tables, an eviction of one key does not require rebuilding the other — `get_facts` and `get_conversation_state` are called and recovered independently, never as a joined "session" blob.
- **No cross-writes**: `update_facts` never touches `conversation_state` and vice versa — enforced by keeping them in fully separate repository/service methods, not a shared `SessionRepository`.

## 20. Validation Rules
- `budget` must be a non-negative numeric if present.
- `clarification_rounds` capped at a configurable max (consumed by Router/Planner to trigger `escalation_request` per architecture §3); this module just increments and exposes the counter, it does not itself decide the escalation (that's Router/Planner logic in M06/M07).
- `current_plan_step` must be `>= 0` and `< len(current_plan.steps)` when both are present.

## 21. Error Handling
| Error | Handling |
|---|---|
| Redis unreachable on read | Fall back directly to SQL (log a `WARNING`, do not fail the request) |
| Redis unreachable on write | Write to SQL first (durability), log `WARNING` that cache write failed, continue — next read will repopulate cache from SQL |
| SQL unreachable on write | Raise `FactsCheckpointError` / `StateCheckpointError` — this **does** fail the request since SQL is the durability guarantee |
| Row not found on `get` | Return `None` from repository; service layer returns an empty/default schema (a new session), not an error |

## 22. Logging Strategy
- Log every cache miss (`facts_cache_miss`, `state_cache_miss`) at `DEBUG`.
- Log every SQL checkpoint write at `DEBUG` with `tenant_id`, `session_id`, and which fields changed (not full values, to avoid logging PII like `company` repeatedly at high volume — full values belong in `conversation_turns`, Module 04).
- Log checkpoint failures at `ERROR`.

## 23. Unit Tests
- `test_update_facts_does_not_touch_conversation_state`
- `test_reset_conversation_state_preserves_facts`
- `test_facts_write_through_on_redis_failure_still_persists_to_sql`
- `test_conversation_state_ttl_reapplied_on_write`

## 24. Integration Tests
- `test_facts_survive_conversation_state_redis_eviction` — evict `conv:*` key only, assert `get_facts` still returns full data.
- `test_conversation_state_recovers_from_sql_after_cache_eviction`
- `test_clarification_round_increment_persists`

## 25. Configuration
No new settings beyond `Settings.redis` / `Settings.db` from Module 01. `CONVERSATION_STATE_TTL_SECONDS = 1800` defined as a module-level constant (not env-configurable in v4.1 scope, matches v3 behavior per architecture).

## 26. Environment Variables
None new.

## 27. Sequence Diagram
```
Orchestrator.on_turn(session_id, message)
        │
        ▼
SessionStateService.get_facts(tenant_id, session_id)
        │
   Redis GET facts:{tenant_id}:{session_id}
        │ miss?
        ▼
   FactsRepository.get(tenant_id, session_id)  → Postgres
        │
   Redis SET facts:{...} (no TTL)
        │
        ▼
   return FactsSchema
```

## 28. Request Lifecycle
Not HTTP-triggered directly; invoked once per turn by the Orchestrator (Module 05/06) for both Facts and Conversation State, always as two separate calls.

## 29. Data Flow
```
Redis (hot cache) ⇄ SessionStateService ⇄ Postgres (durability)
        ▲                                          │
        └──────────── independent per table ───────┘
```

## 30. Example Workflow
1. User says "My budget is $50k" → Router extracts this into a Facts patch → `update_facts(tenant_id, session_id, {budget: 50000})`.
2. Redis eviction later clears `conv:{...}` (30-min TTL lapses mid-conversation).
3. Next turn: `get_conversation_state` misses Redis, recovers from Postgres (last known intent/plan state); `get_facts` is unaffected — budget of $50k is still returned instantly from its own, still-live Redis key.

## 31. Future Extension Points
- Facts schema growth (new slots) — additive column migration, no structural change needed.
- Per-tenant Facts schema customization (deferred; out of v4.1 scope).

## 32. Completion Checklist
- [ ] Two separate tables, two separate Redis namespaces
- [ ] Write-through on both, independently
- [ ] Cache-miss recovery works independently for each
- [ ] `reset_conversation_state` never mutates Facts
- [ ] Tests above pass
