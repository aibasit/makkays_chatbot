# Module 09 — Feature Flags

## 1. Module Name
`feature_flags` — Config-driven capability toggles, consulted by Planner and tool registration.

## 2. Goal
Implement env-var-backed defaults plus an optional `feature_flags` Postgres table
for runtime toggling without a restart, exposing a single `FeatureFlags` object
consumed by the Task Planner (Module 07) and Tool Executor's tool registration
(Module 10).

## 3. Purpose
Lets capabilities (RAG, quotes, CRM, tickets, image upload, LLM clarification
rewrite) be turned on/off without a redeploy — used for staged rollout and to gate
incomplete/untested pipelines, per architecture §2.15.

## 4. Dependencies
Module 01 (env defaults), Module 02 (DB, if the runtime-toggle table is used).

## 5. Folder Structure
```
app/
├── flags/
│   ├── __init__.py
│   ├── models.py
│   ├── schemas.py
│   ├── repository.py
│   └── service.py
tests/
├── unit/
│   └── test_feature_flags_service.py
└── integration/
    └── test_feature_flags_db_override.py
```

## 6. Files to Create
`models.py`, `schemas.py`, `repository.py`, `service.py`.

## 7. Responsibility of Every File
| File | Responsibility |
|---|---|
| `models.py` | ORM model for the optional `feature_flags` table |
| `schemas.py` | `FeatureFlags` Pydantic model — the object actually consumed by Planner/Tool Executor |
| `repository.py` | `FeatureFlagsRepository.get_all(tenant_id) -> dict[str, bool]` |
| `service.py` | `FeatureFlagsService.resolve(tenant_id) -> FeatureFlags` — merges env defaults with DB overrides |

## 8. Classes
- `FeatureFlags { enable_rag, enable_quotes, enable_crm, enable_tickets, enable_image_upload, enable_llm_clarification_rewrite: bool }`.
- `FeatureFlagsRepository` — thin read (and admin-only write, out of HTTP scope for v4.1) over the `feature_flags` table.
- `FeatureFlagsService` — resolves precedence: DB row (if present for a given tenant+flag) overrides the env-var default.

## 9. Data Models
`FeatureFlag` (ORM, table `feature_flags`, optional but recommended to build from day one per Build Order step 9): `tenant_id: UUID`, `flag_name: str`, `enabled: bool`, `updated_at: timestamptz` — composite PK `(tenant_id, flag_name)`.

## 10. Pydantic Schemas
`FeatureFlags` — flat boolean fields as listed above; this is what `TaskPlanner.build_plan` and Tool Executor's registration step actually receive (never the raw DB rows or env object directly, keeping both callers decoupled from the storage mechanism).

## 11. Repository Layer
`FeatureFlagsRepository.get_all(tenant_id) -> dict[str, bool]` — one query, all overrides for the tenant, empty dict if none set (pure env-default behavior).

## 12. Service Layer
`FeatureFlagsService.resolve(tenant_id) -> FeatureFlags`:
1. Start from `Settings.flags` (env defaults, Module 01).
2. Fetch DB overrides via repository.
3. For each flag present in the DB result, override the env default.
4. Return the merged `FeatureFlags` object.

Cached in-process per tenant for a short period (e.g., 60s local in-memory cache) to avoid a DB round trip on every single turn — acceptable staleness for a local-dev, single-tenant setup; documented as a tunable, not a hard requirement.

## 13. Internal Interfaces
- `resolve(tenant_id) -> FeatureFlags` — called once per turn by the Orchestrator (Module 06), result passed into both `TaskPlanner.build_plan` (Module 07) and Tool Executor's registration check (Module 10).

## 14. Database Tables
```sql
CREATE TABLE feature_flags (
  tenant_id UUID NOT NULL,
  flag_name TEXT NOT NULL,
  enabled BOOLEAN NOT NULL,
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  PRIMARY KEY (tenant_id, flag_name)
);
```

## 15. Redis Keys
None required (in-process cache is sufficient at local-dev scale; a Redis-backed cache is a listed future extension only if multi-process deployment requires shared cache coherency).

## 16. API Endpoints
None public in v4.1 (no admin UI for toggling flags via HTTP — direct SQL update to `feature_flags` is the documented local-dev workflow: `UPDATE feature_flags SET enabled=false WHERE tenant_id=... AND flag_name='enable_rag';`).

## 17. Request Models
N/A.

## 18. Response Models
N/A (internal `FeatureFlags` object only).

## 19. Business Logic
- **Two consultation points**, per architecture §2.15:
  1. **Planner** (Module 07) — skips plan steps gated by a disabled flag.
  2. **Tool registration** (Module 10) — a disabled tool is not exposed to the LLM's tool schema at all, so it cannot even be speculatively called. This is stricter than the Planner check alone (belt-and-suspenders with the Security Policy in Module 10).
- Env defaults exist so the system works correctly with **zero rows** in `feature_flags` — the DB table is purely an override mechanism, never a required source of truth.

## 20. Validation Rules
- `flag_name` must be one of the six fixed names — an unrecognized `flag_name` in the DB is ignored with a `WARNING` log (defensive against typos), not applied.

## 21. Error Handling
| Error | Handling |
|---|---|
| DB unreachable when resolving flags | Fall back to env defaults only, log `WARNING` — flags must never block a turn from proceeding |
| Unrecognized `flag_name` row in DB | Ignored, logged at `WARNING`, does not raise |

## 22. Logging Strategy
- Log the resolved `FeatureFlags` at `DEBUG` once per cache refresh (not every turn, to avoid log spam).
- Log any DB-fallback event at `WARNING`.

## 23. Unit Tests
- `test_resolve_uses_env_defaults_when_no_db_rows`
- `test_resolve_db_override_takes_precedence`
- `test_resolve_falls_back_to_env_on_db_error`
- `test_unrecognized_flag_name_ignored`

## 24. Integration Tests
- `test_planner_skips_generate_quote_step_when_enable_quotes_false`
- `test_tool_executor_does_not_register_disabled_tool_in_llm_schema`

## 25. Configuration
`Settings.flags` (Module 01) provides the six env-driven defaults listed in Module 00 §1.1.

## 26. Environment Variables
`ENABLE_RAG`, `ENABLE_QUOTES`, `ENABLE_CRM`, `ENABLE_TICKETS`, `ENABLE_IMAGE_UPLOAD`, `ENABLE_LLM_CLARIFICATION_REWRITE` (already defined in Module 00).

## 27. Sequence Diagram
```
Orchestrator.on_turn(...)
        │
        ▼
FeatureFlagsService.resolve(tenant_id)
        │
   Settings.flags (env defaults)
        │
   FeatureFlagsRepository.get_all(tenant_id)  → DB overrides
        │
   merge (DB wins per-flag)
        │
        ▼
   FeatureFlags  ──► TaskPlanner.build_plan(..., flags)
                 ──► ToolExecutor tool registration
```

## 28. Request Lifecycle
In-process, resolved once near the start of `Orchestrator.on_turn`, threaded through to both consumers for that turn.

## 29. Data Flow
`.env` (defaults) + `feature_flags` table (overrides) → `FeatureFlagsService.resolve` → `FeatureFlags` object → Planner + Tool Executor.

## 30. Example Workflow
1. `ENABLE_QUOTES=true` in `.env` (default).
2. Developer wants to test disabling quotes without restarting: `UPDATE feature_flags SET enabled=false WHERE tenant_id='<default>' AND flag_name='enable_quotes';`.
3. Next turn: `resolve()` picks up the DB override; Planner no longer adds `generate_quote`/`request_missing_slots` steps; Tool Executor no longer exposes `generate_quote` in the LLM's tool schema.

## 31. Future Extension Points
- Percentage-based rollout (e.g., "RAG on for 10% of sessions") — architecture explicitly names this as the primary value of flags being config-driven; not implemented in v4.1, would extend `FeatureFlag` with a `rollout_percentage` column and a session-id hash bucketing rule.
- Redis-backed shared cache if the app ever runs as multiple local processes.

## 32. Completion Checklist
- [ ] Six flags resolvable from env with correct defaults
- [ ] DB override table created and takes precedence when present
- [ ] Planner and Tool Executor both consult flags independently (defense in depth)
- [ ] DB failure never blocks a turn (falls back to env)
- [ ] Tests above pass
