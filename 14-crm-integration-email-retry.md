# Module 14 — CRM Integration, Retry Queue & Email Notifications (Resend)

## 1. Module Name
`crm_and_notifications` — Lead creation, CRM sync with retry, and Resend-backed email notifications.

## 2. Goal
Implement `create_lead()` → Postgres (`crm_synced=false`) → `retry_queue` →
APScheduler background job → CRM API, unchanged from v3/v4, now carrying
`tenant_id`; plus Resend email notifications for new leads/quotes (new in this
tech-stack pass, not in the original architecture doc but required per the
person's tech stack additions).

## 3. Purpose
Leads are the platform's primary business outcome. CRM sync must never block the
user-facing conversation and must be resilient to CRM downtime — hence the
durable retry queue pattern. Email notifications give the sales team immediate
visibility into new leads/quotes without polling the CRM.

## 4. Dependencies
Module 01 (lifespan hooks — `register_hooks(app, settings)` registers the APScheduler scheduler), Module 02 (DB), Module 03 (Facts — `contact_name`, `contact_email`, `contact_phone` carried into the lead record from `session_facts`), Module 09 (`ENABLE_CRM` flag), Module 10 (registered as `create_lead` tool + policy), Module 12 (`notify_quote_generated` called by Module 12's `QuoteBuilder.build` as a fire-and-forget task), Module 16 (Observability & Metrics — CRM and lead creation metrics).

## 5. Folder Structure
```
app/
├── crm/
│   ├── __init__.py
│   ├── models.py
│   ├── schemas.py
│   ├── repository.py
│   ├── service.py
│   ├── client.py
│   ├── retry_worker.py
│   └── exceptions.py
├── notifications/
│   ├── __init__.py
│   ├── resend_client.py
│   ├── templates.py
│   └── service.py
tests/
├── unit/
│   ├── test_lead_service.py
│   └── test_notification_service.py
└── integration/
    ├── test_crm_retry_flow.py
    └── test_email_send.py
```

## 6. Files to Create
`crm/models.py`, `crm/schemas.py`, `crm/repository.py`, `crm/service.py`, `crm/client.py`, `crm/retry_worker.py`, `crm/exceptions.py`, `notifications/resend_client.py`, `notifications/templates.py`, `notifications/service.py`.

## 7. Responsibility of Every File
| File | Responsibility |
|---|---|
| `crm/models.py` | ORM models for `leads`, `retry_queue` |
| `crm/schemas.py` | `LeadCreate`, `LeadRecord` |
| `crm/repository.py` | CRUD for `leads` and `retry_queue` |
| `crm/service.py` | `LeadService.create_lead(...)` — the `create_lead` plan-step entrypoint |
| `crm/client.py` | Thin HTTP wrapper over the external CRM API (`CRM_API_BASE_URL`) |
| `crm/retry_worker.py` | APScheduler job definition — periodically drains `retry_queue` |
| `notifications/resend_client.py` | Thin wrapper over the Resend API |
| `notifications/templates.py` | Plain-text/HTML email templates for "new lead" and "quote generated" |
| `notifications/service.py` | `NotificationService.notify_new_lead(...)`, `.notify_quote_generated(...)` |

## 8. Classes
- `Lead` (ORM), `RetryQueueEntry` (ORM).
- `LeadRepository`, `RetryQueueRepository`.
- `LeadService` — creates the lead, enqueues sync, triggers notification.
- `CrmClient` — `async push_lead(lead: LeadRecord) -> bool`.
- `RetryWorker` — APScheduler-invoked function, drains due retries.
- `ResendClient` — `async send(to, subject, html) -> bool`.
- `NotificationService` — composes templates + calls `ResendClient`.

## 9. Data Models
`Lead` (ORM, table `leads`): `id: UUID`, `tenant_id: UUID`, `session_id: str`,
`company: str`, `contact_name: str | None`, `contact_email: str | None`,
`contact_phone: str | None`, `facts_snapshot: JSONB` (copy of Facts at lead-creation time — durable even if Facts later change), `crm_synced: bool = false`,
`crm_contact_id: str | None`, `created_at: timestamptz`.

`RetryQueueEntry` (ORM, table `retry_queue`): `id: UUID`, `tenant_id: UUID`,
`lead_id: UUID (fk)`, `attempt_count: int = 0`, `next_attempt_at: timestamptz`,
`last_error: text | None`, `status: str` (`pending`/`succeeded`/`failed_permanently`), `created_at`, `updated_at`.

## 10. Pydantic Schemas
- `LeadCreate { company: str, contact_name: str | None, contact_email: str | None, contact_phone: str | None }`.
- `LeadRecord` — full read model including `crm_synced`, `crm_contact_id`.

## 11. Repository Layer
`LeadRepository`: `create(tenant_id, session_id, data) -> Lead`, `get(tenant_id, lead_id)`, `mark_synced(lead_id, crm_contact_id)`.
`RetryQueueRepository`: `enqueue(tenant_id, lead_id, next_attempt_at)`, `get_due(limit) -> list[RetryQueueEntry]`, `mark_succeeded(id)`, `mark_failed(id, error, next_attempt_at)`, `mark_permanently_failed(id)`.

## 12. Service Layer
`LeadService.create_lead(session: SessionContext, context: ExecutionContext) -> ToolExecutionResult`:
1. Validate `contact_info_complete(session.facts)` (predicate from Module 10's `PREDICATE_REGISTRY`): at least one of `facts.contact_email` or `facts.contact_phone` must be non-None. If not, raise `IncompleteLeadDataError` — log `WARNING('create_lead_missing_contact', session_id=session.session_id)` before raising.
2. If `facts.contact_email` present, validate with Pydantic `EmailStr` — raise `ValidationError` on failure.
3. Build `contact = LeadCreate(company=session.facts.company or '', contact_name=session.facts.contact_name, contact_email=session.facts.contact_email, contact_phone=session.facts.contact_phone)`.
4. `lead = await LeadRepository.create(session.tenant_id, session.session_id, data=contact, facts_snapshot=session.facts.model_dump_json())`.
5. `await RetryQueueRepository.enqueue(session.tenant_id, lead.id, next_attempt_at=datetime.utcnow())`.
6. `asyncio.create_task(NotificationService.notify_new_lead(lead))` — fire-and-forget; failures swallowed and logged at `WARNING`.
7. `MetricsRegistry.increment_lead_created()`.
8. Return `ToolExecutionResult(step='create_lead', success=True, result_summary=f'Lead created for {contact.company}', product_ids=None)`.

`RetryWorker.run()` (APScheduler interval job, every `settings.crm.retry_worker_interval_seconds` seconds, default 60):
1. `due = await RetryQueueRepository.get_due(limit=20)` — `SELECT ... WHERE status = 'pending' AND next_attempt_at <= now() FOR UPDATE SKIP LOCKED` (SKIP LOCKED prevents double-processing if multiple workers were ever added).
2. For each entry:
   a. `lead = await LeadRepository.get(entry.tenant_id, entry.lead_id)`.
   b. `success = await CrmClient.push_lead(lead)` — raises on network errors, returns `False` on non-2xx CRM response.
   c. If success: `await LeadRepository.mark_synced(lead.id, crm_contact_id=response.contact_id)`, `await RetryQueueRepository.mark_succeeded(entry.id)`.
   d. If failure: `new_count = entry.attempt_count + 1`. If `new_count < settings.crm.max_retry_attempts` (default 5): `backoff_minutes = 2 ** new_count` (exponential: 2min, 4min, 8min, 16min, 32min), `await RetryQueueRepository.mark_failed(entry.id, error=str(e), next_attempt_at=now() + timedelta(minutes=backoff_minutes))`. Else: `await RetryQueueRepository.mark_permanently_failed(entry.id)`, log `ERROR('crm_sync_permanently_failed', lead_id=lead.id)`.

**APScheduler registration** (in `crm/retry_worker.py`, exposed via `register_hooks`):
```python
def register_hooks(app: FastAPI, settings: Settings) -> None:
    scheduler = AsyncIOScheduler()
    scheduler.add_job(
        RetryWorker.run,
        trigger='interval',
        seconds=settings.crm.retry_worker_interval_seconds,
        id='crm_retry_worker',
        max_instances=1,
        coalesce=True,
    )
    app.state.scheduler = scheduler
    # lifespan in Module 01 calls scheduler.start() on startup
    # and scheduler.shutdown(wait=False) in the finally block
```
Module 01's `register_lifecycle_hooks` imports and calls this function.

**Tool registration** (in `crm/__init__.py`):
```python
ToolRegistry.register('create_lead', LeadService.create_lead)
```

## 13. Internal Interfaces
- `create_lead` registered as a Tool Executor (Module 10) step. Tool function signature: `async def create_lead_tool(session: SessionContext, context: ExecutionContext) -> ToolExecutionResult`. Policy: `allowed_intents: [sales_inquiry, quote_request]`, `required_state: [contact_info_complete]`, `required_slots: []`, `rate_limit: "3/min"`, `audit_log: true`.
- Contact fields (`contact_name`, `contact_email`, `contact_phone`) are read from `session.facts` — they are stored in `session_facts` (Module 03 §14) and populated by the LLM during normal conversation via Facts extraction. The Orchestrator (Module 06) sets `conversation_state.contact_info_captured = true` when it detects that at least one contact field has become non-None for the first time.
- `RetryWorker.run` registered via `register_hooks(app, settings)` called from Module 01's `register_lifecycle_hooks`. Scheduler class: `AsyncIOScheduler` from `apscheduler.schedulers.asyncio`. Parameters: `trigger='interval'`, `seconds=settings.crm.retry_worker_interval_seconds`, `max_instances=1`, `coalesce=True` (skips a missed fire if a previous run is still executing).
- `NotificationService.notify_new_lead` and `.notify_quote_generated` are async functions called as `asyncio.create_task(...)` from their respective callers (LeadService and QuoteBuilder). Failures are swallowed after being logged at `WARNING`.

## 14. Database Tables
```sql
CREATE TABLE leads (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant_id UUID NOT NULL,
  session_id TEXT NOT NULL,
  company TEXT NOT NULL,
  contact_name TEXT,
  contact_email TEXT,
  contact_phone TEXT,
  facts_snapshot JSONB NOT NULL,
  crm_synced BOOLEAN NOT NULL DEFAULT false,
  crm_contact_id TEXT,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE TABLE retry_queue (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant_id UUID NOT NULL,
  lead_id UUID NOT NULL REFERENCES leads(id),
  attempt_count INTEGER NOT NULL DEFAULT 0,
  next_attempt_at TIMESTAMPTZ NOT NULL,
  last_error TEXT,
  status TEXT NOT NULL DEFAULT 'pending',
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX idx_retry_queue_due ON retry_queue (status, next_attempt_at) WHERE status = 'pending';
```

## 15. Redis Keys
`rate_limit:tool:{tenant_id}:{session_id}:create_lead` — reused rate-limit pattern from Module 10, backing `"3/min per session"`.

## 16. API Endpoints
None public — `create_lead` invoked only via the plan step inside `/chat`. No standalone `/leads` HTTP endpoint in v4.1 scope.

## 17. Request Models
N/A (internal tool invocation).

## 18. Response Models
`LeadRecord`, folded into `ToolExecutionResult.result_summary`.

## 19. Business Logic
- **Lead creation never blocks on CRM**: the CRM push always happens asynchronously via the retry queue, never inline in the request/response cycle — this is the core resilience property from v3/v4, unchanged.
- **Exponential backoff**: `2^attempt_count` minutes between retries, capped at `MAX_RETRY_ATTEMPTS` before giving up and flagging for manual follow-up.
- **`facts_snapshot`** exists because Facts (Module 03) can keep evolving after a lead is created (the conversation may continue) — the lead's snapshot is what was true *at creation time*, not a live join.
- **Email is best-effort**: a Resend outage must never prevent a lead from being created or synced — notification failures are logged and swallowed, not retried via the same queue (a separate, simpler concern from CRM sync).

## 20. Validation Rules
- At least one of `contact_email` / `contact_phone` must be present to create a lead (can't follow up on a lead with zero contact method) — enforced in `LeadService.create_lead`, not just at the Security Policy layer.
- `contact_email`, if present, must pass basic email format validation (Pydantic `EmailStr`).

## 21. Error Handling
| Error | Handling |
|---|---|
| CRM API down at push time | `CrmClient.push_lead` returns `False`/raises; `RetryWorker` schedules backoff retry — never surfaced to the user in real time |
| CRM permanently unreachable (max attempts exceeded) | `mark_permanently_failed`, log `ERROR` — lead still exists in Postgres regardless, nothing is lost, just not synced |
| Resend API failure | Logged at `WARNING`, swallowed — does not affect lead/CRM flow at all |
| Missing contact info | Raise `IncompleteLeadDataError` at the service layer before even attempting `LeadRepository.create` |

## 22. Logging Strategy
- Log lead creation at `INFO` (company, session_id, tenant_id — not full contact PII in the general log stream; full detail lives in the `leads` table itself, access-controlled at the DB level).
- Log every retry attempt (success/failure) at `INFO`/`WARNING` respectively.
- Log permanent failures at `ERROR` with `lead_id` for manual CRM follow-up.
- Log email send failures at `WARNING`.

## 23. Unit Tests
- `test_create_lead_requires_email_or_phone`
- `test_create_lead_rejects_invalid_email_format`
- `test_create_lead_snapshots_facts_at_creation_time`
- `test_create_lead_reads_contact_from_session_facts`
- `test_retry_worker_backoff_formula` (assert attempt 1 → 2min, attempt 2 → 4min, attempt 3 → 8min)
- `test_retry_worker_marks_permanently_failed_at_max_attempts`
- `test_retry_worker_skip_locked_prevents_double_processing`
- `test_notification_failure_does_not_raise`
- `test_scheduler_starts_and_stops_cleanly` (verify `scheduler.start()` / `scheduler.shutdown()` called in lifespan)
- `test_lead_metric_incremented_on_creation`

## 24. Integration Tests
- `test_create_lead_enqueues_retry_entry`
- `test_retry_worker_drains_due_entries_and_syncs`
- `test_retry_worker_reschedules_on_crm_failure`
- `test_email_notification_sent_on_lead_creation` (mocked Resend call, assert correct template/recipient)

## 25. Configuration
```
crm:
  base_url: str            # CRM_API_BASE_URL
  api_key: str              # CRM_API_KEY
  max_retry_attempts: int = 5
  retry_worker_interval_seconds: int = 60
resend:
  api_key: str
  from_email: str
```

## 26. Environment Variables
`CRM_API_BASE_URL`, `CRM_API_KEY`, `CRM_MAX_RETRY_ATTEMPTS`, `CRM_RETRY_WORKER_INTERVAL_SECONDS`, `RESEND_API_KEY`, `RESEND_FROM_EMAIL` (defined in Module 00).

## 27. Sequence Diagram
```
ToolExecutor step: create_lead
        │
        ▼
LeadService.create_lead(tenant_id, session_id, facts, contact)
        │
   LeadRepository.create(...)  (crm_synced=false)
        │
   RetryQueueRepository.enqueue(...)
        │
   NotificationService.notify_new_lead(lead)  (fire-and-forget)
        │
        ▼
   LeadRecord  ──► turn completes, user sees confirmation

  ── separately, every 60s ──
APScheduler → RetryWorker.run()
        │
   RetryQueueRepository.get_due()
        │
   for entry: CrmClient.push_lead(lead)
        │
   success → mark_synced + mark_succeeded
   failure → backoff + mark_failed (or mark_permanently_failed)
```

## 28. Request Lifecycle
`create_lead` step: synchronous within the `/chat` request (fast — just two inserts + a fire-and-forget email call). CRM sync itself: fully asynchronous, decoupled from any HTTP request, driven by APScheduler.

## 29. Data Flow
`Facts` (Module 03) + contact info (captured from conversation) → `leads` table → `retry_queue` table → `RetryWorker` → external CRM API. Separately: `leads`/`quotes` → `NotificationService` → Resend API → sales team inbox.

## 30. Example Workflow
1. User provides email during a `sales_inquiry` conversation; Planner adds `create_lead` (contact info newly captured).
2. `LeadService.create_lead` persists the lead, enqueues a sync, fires a "new lead" email via Resend.
3. `RetryWorker` picks it up within 60s, pushes to CRM successfully, marks synced.
4. If CRM had been down: retried at 2min, 4min, 8min, 16min, 32min before being flagged for manual follow-up — lead data itself was never at risk since it's Postgres-durable from step 2.

## 31. Future Extension Points
- Standalone CRM worker process (separate from the API process) — explicitly deferred per architecture's Build Order closing note.
- Two-way CRM sync (pulling status updates back) — not in v4.1 scope.

## 32. Completion Checklist
- [ ] `create_lead` never blocks on the CRM API
- [ ] Retry queue backoff and permanent-failure threshold implemented
- [ ] `facts_snapshot` correctly captured at creation time, not live-joined
- [ ] Email notifications are best-effort and never block lead/CRM flow
- [ ] Tests above pass

## 33. Hardening Update: Scheduler and Error Contract
Module 14 exposes `register_hooks(app, settings) -> None`, but Module 01 is the only caller and the sole owner of startup/shutdown ordering (Module 00 §12). CRM sync failure is never user-visible as a failed chat turn: the lead remains durable in Postgres and retry status is logged/metriced. User-visible behavior follows Module 00 §14.
