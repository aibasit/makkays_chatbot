# Module 20 — Human Handoff & Extended Lead Qualification

## 1. Module Name
`handoff` — Structured human-transfer workflow for Sales, Technical Engineer, and Support queues. Extended lead qualification facts collection.

## 2. Goal
Implement the `initiate_handoff` tool step that: records the handoff request with full conversation history, sends a notification email to the selected team, and generates a user-facing acknowledgement. Also owns the extended lead qualification schema that enriches Module 14's `CRMLeadCreate` with business-context fields.

## 3. Purpose
Human handoff is a distinct bounded context from simple lead capture (Module 14). It requires exporting a structured conversation transcript, routing to a team, assigning a reference ID, and confirming to the user. Mixing this into Module 14 (CRM/retry/email) would couple unrelated concerns.

## 4. Dependencies
Module 02 (DB), Module 04 (Turns — `TurnsService.get_recent_turns` for conversation export), Module 09 (`FeatureFlags.enable_human_handoff`), Module 10 (tool registration), Module 14 (email via `NotificationService`), Module 16 (metrics).

## 5. Folder Structure
```
app/
├── handoff/
│   ├── __init__.py
│   ├── handoff_service.py
│   ├── schemas.py
│   ├── models.py
│   ├── repository.py
│   └── exceptions.py
tests/
├── unit/
│   └── test_handoff_service.py
└── integration/
    └── test_handoff_creates_record_and_sends_email.py
```

## 6. Files to Create
`handoff_service.py`, `schemas.py`, `models.py`, `repository.py`, `exceptions.py`.

## 7. Responsibility of Every File
| File | Responsibility |
|---|---|
| `handoff_service.py` | `HandoffService.initiate(session, target_team) -> HandoffResult` |
| `schemas.py` | `HandoffRequest`, `HandoffResult`, `ExtendedLeadQualification` |
| `models.py` | `HandoffRecord` ORM model |
| `repository.py` | `HandoffRepository.create`, `.get`, `.list_by_session` |
| `exceptions.py` | `HandoffAlreadyInitiatedError`, `InvalidHandoffTeamError` |

## 8. Classes

### `HandoffService`
```python
async def initiate(
    session: SessionContext,
    target_team: Literal['sales', 'technical', 'support'],
    llm_client: LLMClientProtocol,
) -> HandoffResult:
    """
    1. Validate target_team is in VALID_TEAMS.
    2. Check HandoffRepository.get_active(tenant_id, session_id) — if already initiated, raise HandoffAlreadyInitiatedError.
    3. Export conversation: turns = await TurnsService.get_recent_turns(tenant_id, session_id, limit=50).
    4. Build conversation_export: list of {role, content, turn_number, timestamp} dicts.
    5. Build HandoffRecord and persist to DB.
    6. Dispatch email via asyncio.create_task(NotificationService.send_handoff_notification(handoff_record)).
    7. Return HandoffResult with reference_id and acknowledgement_text.
    """
```

`VALID_TEAMS: frozenset[str] = frozenset({'sales', 'technical', 'support'})`

### `HandoffRepository`
- `async create(tenant_id, session_id, target_team, conversation_export) -> HandoffRecord`
- `async get_active(tenant_id, session_id) -> HandoffRecord | None` — returns record where `status = 'pending'` or `'in_progress'`
- `async update_status(handoff_id, status) -> HandoffRecord`

## 9. Data Models

### `HandoffRecord` (ORM, table `handoff_requests`)
```sql
CREATE TABLE handoff_requests (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant_id UUID NOT NULL,
  session_id TEXT NOT NULL,
  target_team TEXT NOT NULL,
  status TEXT NOT NULL DEFAULT 'pending',
  conversation_export JSONB NOT NULL,
  contact_name TEXT,
  contact_email TEXT,
  contact_phone TEXT,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX idx_handoff_session ON handoff_requests (tenant_id, session_id, status);
```

Status lifecycle: `pending` → `in_progress` → `resolved` | `cancelled`.

### Extended Lead Qualification (applied to `session_facts` table — via M14 migration)
```sql
-- Migration added to M14's migration sequence
ALTER TABLE session_facts ADD COLUMN industry TEXT;
ALTER TABLE session_facts ADD COLUMN project_size TEXT;
ALTER TABLE session_facts ADD COLUMN location TEXT;
ALTER TABLE session_facts ADD COLUMN timeline TEXT;
ALTER TABLE session_facts ADD COLUMN is_decision_maker BOOLEAN;
```

These fields are populated by `FactsExtractor` (Module 06) during conversation. When `initiate_handoff` runs, these fields are included in the handoff notification email as lead qualification context.

## 10. Pydantic Schemas
```python
class HandoffResult(BaseModel):
    handoff_id: UUID
    reference_id: str   # Human-readable: e.g., "HO-20260703-001"
    target_team: str
    status: str
    acknowledgement_text: str  # Message shown to user: "I've connected you with our Sales team. Reference: HO-20260703-001. Someone will contact you shortly."

class ExtendedLeadQualification(BaseModel):
    industry: str | None = None
    project_size: str | None = None
    location: str | None = None
    timeline: str | None = None
    is_decision_maker: bool | None = None
```

## 11. Repository Layer
See §8 `HandoffRepository`.

## 12. Service Layer — Tool Wrapper
```python
async def initiate_handoff_tool(session: SessionContext, context: ExecutionContext) -> ToolExecutionResult:
    # Determine target team from conversation state or default to 'sales'
    target_team = session.conversation_state.handoff_target or 'sales'
    try:
        result = await HandoffService().initiate(session, target_team, llm_client)
        return ToolExecutionResult(
            step='initiate_handoff',
            success=True,
            result_summary=result.model_dump_json(),
        )
    except HandoffAlreadyInitiatedError as e:
        return ToolExecutionResult(
            step='initiate_handoff',
            success=False,
            result_summary=f'Handoff already initiated: {e.reference_id}',
        )
```

**Tool registration:**
```python
ToolRegistry.register('initiate_handoff', initiate_handoff_tool)
```

## 13. Internal Interfaces
- `HandoffService.initiate` is the only public entrypoint; it is never called directly except through the Tool Executor.
- Conversation export is serialized as JSONB in `handoff_requests.conversation_export` — the email notification renders this as a human-readable thread.
- `conversation_state.handoff_target` (`TEXT | None`) is a new field added to the `ConversationState` schema (Module 03) to carry the team selection from the clarification flow (Module 13's `handoff_type_selection.md` template).

## 14. Database Tables
`handoff_requests` — see §9.

`session_facts` — extended with 5 new qualification columns (migration owned by Module 14 but documented here).

## 15. Redis Keys
None. Handoff records are durable DB records.

## 16. API Endpoints
None directly from this module. Future: `GET /handoffs/{handoff_id}` for status tracking.

## 17. Request Models
N/A.

## 18. Response Models
`HandoffResult` — consumed by the `respond` step to generate the user-facing acknowledgement message.

## 19. Business Logic
- **Idempotency**: Only one active handoff (status = `pending` | `in_progress`) allowed per session. Subsequent calls return the existing record.
- **Conversation export**: Always includes the full available turn history (up to 50 turns). Truncated if session has more than 50 turns, with a note in the export.
- **Reference ID**: Generated as `HO-{date}-{sequence}` where sequence is the daily handoff count for the tenant. Collision-safe via DB sequence.
- **Email content**: Notification email includes: customer contact info, handoff team, conversation summary, reference ID, timestamp.

## 20. Validation Rules
- `target_team` must be one of `['sales', 'technical', 'support']`. Invalid value raises `InvalidHandoffTeamError`.
- `HandoffAlreadyInitiatedError` includes the existing `reference_id` in its message so the user can be shown the original reference without creating a duplicate.

## 21. Error Handling
| Error | Handling |
|---|---|
| `HandoffAlreadyInitiatedError` | Return `success=False` with existing reference ID — `respond` step informs user |
| `InvalidHandoffTeamError` | Return `success=False`; default to `'sales'` team if flag allows |
| Email send failure | Swallow, log at `WARNING`; DB record already exists regardless |

## 22. Logging Strategy
- Log handoff creation at `INFO`: `handoff_id`, `tenant_id`, `session_id`, `target_team`.
- Log duplicate handoff attempt at `WARNING`.
- Log email dispatch success/failure at `INFO`/`WARNING`.

## 23. Unit Tests
- `test_initiate_handoff_creates_db_record`
- `test_initiate_handoff_exports_conversation`
- `test_initiate_handoff_raises_on_duplicate`
- `test_invalid_team_raises_error`

## 24. Integration Tests
- `test_handoff_creates_record_and_sends_email`
- `test_handoff_end_to_end_with_orchestrator`

## 25. Configuration
No new settings. `ENABLE_HUMAN_HANDOFF` controls tool registration (Module 09).

## 26. Environment Variables
`ENABLE_HUMAN_HANDOFF` (Module 09).

## 27. Sequence Diagram
```
Orchestrator → ToolExecutor → initiate_handoff_tool
    │
    HandoffService.initiate(session, target_team)
    │   ├─ TurnsService.get_recent_turns(tenant_id, session_id, limit=50)
    │   ├─ HandoffRepository.create(...)
    │   └─ asyncio.create_task(NotificationService.send_handoff_notification(...))
    │
    └─ HandoffResult(handoff_id, reference_id, acknowledgement_text)
           │
           ▼
        respond step → "I've connected you to our [team]. Reference: [ID]. Someone will be in touch shortly."
```

## 28. Request Lifecycle
Single turn: `initiate_handoff` tool runs once and immediately returns a result. No multi-turn state.

## 29. Data Flow
`session.conversation_state.handoff_target` → `HandoffService.initiate` → `HandoffRecord` (DB) + email → `HandoffResult` → `respond` → user acknowledgement.

## 30. Example Workflow
1. User: "Connect me to sales"
2. Intent: `human_handoff`.
3. Clarification: `handoff_type_selection.md` → User selects "Sales Team".
4. Planner: `['initiate_handoff', 'respond']`.
5. `initiate_handoff`: exports last 10 turns, creates `handoff_requests` record, sends email to sales team.
6. `respond`: "I've connected you with our Sales team. Reference: HO-20260703-001. A sales representative will contact you within 24 hours."

## 31. Future Extension Points
- Webhook endpoint for CRM to update handoff status from `pending` → `in_progress`/`resolved`.
- Real-time handoff via WebSocket (live chat transfer) — out of scope for v4.2.
- Admin dashboard for handoff queue management.

## 32. Completion Checklist
- [ ] `handoff_requests` table created
- [ ] Extended `session_facts` columns migrated
- [ ] `initiate_handoff` tool registered in `ToolRegistry`
- [ ] Idempotency guard prevents duplicate handoffs per session
- [ ] Conversation export includes all available turns
- [ ] Email notification dispatched fire-and-forget
- [ ] Tests above pass
