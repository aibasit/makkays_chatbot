# Module 08 — Prompt Manager

## 1. Module Name
`prompt_manager` — Versioned, categorized prompt library loader/cache.

## 2. Goal
Implement `PromptManager.get(name, version) -> str` over a filesystem-backed,
versioned prompt library (`system/`, `intents/`, `rag/`, `tools/`, `clarification/`),
replacing the undifferentiated "Prompt Builder" from v4.

## 3. Purpose
Every LLM call in the system needs prompt text. Without versioning, editing one
intent's prompt risks silently affecting another, and there's no way to answer
"why did behavior change on turn 47" without knowing exactly which prompt file
was active. This module makes every prompt a named, independently-versioned file.

## 4. Dependencies
Module 01 (config — prompt directory path), Module 04 (logging).

## 5. Folder Structure
```
app/
├── prompts/
│   ├── __init__.py
│   ├── manager.py
│   ├── schemas.py
│   └── exceptions.py
prompt_library/
├── system/
│   └── base_v1.md
├── intents/
│   ├── sales_inquiry_v2.md
│   ├── technical_support_v1.md
│   └── quote_request_v1.md
├── rag/
│   └── context_v1.md
├── tools/
│   └── tool_instructions_v1.md
└── clarification/
    ├── sales_vs_support_vs_quote.md
    └── generic_fallback.md
tests/
└── unit/
    └── test_prompt_manager.py
```

## 6. Files to Create
`manager.py`, `schemas.py`, `exceptions.py`, plus the initial `prompt_library/` file set above (migrated from v3/v4 prompts per Build Order step 7).

## 7. Responsibility of Every File
| File | Responsibility |
|---|---|
| `manager.py` | `PromptManager` class — resolves `(category, name, version)` to a file path, loads and in-memory-caches content |
| `schemas.py` | `PromptRef { category: str, name: str, version: str }`, `PromptVersionTag` (used to build `conversation_turns.prompt_version` JSON) |
| `exceptions.py` | `PromptNotFoundError` |

## 8. Classes
- `PromptManager` — `get(category, name, version) -> str`, `get_latest(category, name) -> str` (convenience for dev, resolves highest version file present), internal `_cache: dict[str, str]`.

## 9. Data Models
None — prompts are files on disk, not database rows, in v4.1 scope (a `feature_flags`-style DB-backed override table is a listed future extension, not required now).

## 10. Pydantic Schemas
- `PromptRef { category: Literal["system","intents","rag","tools","clarification"], name: str, version: str }`.
- `PromptVersionTag` — a `dict[str, str]` builder helper, e.g. `{"system": "base_v1", "intent": "sales_inquiry_v2", "rag": "context_v1"}`, assembled by the Orchestrator per turn and passed to Module 04's `record_turn`.

## 11. Repository Layer
N/A — filesystem-backed, not database-backed.

## 12. Service Layer
`PromptManager.get(category, name, version)`:
1. Build cache key `f"{category}/{name}_{version}"`.
2. Return from `_cache` if present.
3. Else read `prompt_library/{category}/{name}_{version}.md` from disk, raise `PromptNotFoundError` if missing.
4. Cache and return content.

Cache is process-lifetime (no TTL) — prompt files don't change without a deploy/restart in v4.1 scope (no hot-reload requirement given local-dev-only focus, though `reload()` is listed as a future extension for dev convenience).

## 13. Internal Interfaces
- `get(category, name, version) -> str` — called by Router (Module 06, for `system/base` and `intents/*`), RAG Engine (Module 11, for `rag/context_v1`), Tool Executor (Module 10, for `tools/tool_instructions_v1`), Clarification (Module 13, optionally for the LLM-rewrite prompt).
- Every caller is responsible for recording which `PromptRef`s it used into the `PromptVersionTag` dict threaded through to `record_turn` (Module 04) — this module does not itself write to `conversation_turns`.

## 14. Database Tables
None.

## 15. Redis Keys
None (in-memory cache only, per-process).

## 16. API Endpoints
None — internal module.

## 17. Request Models
N/A.

## 18. Response Models
N/A (returns plain `str`).

## 19. Business Logic
- Filename convention: `{name}_v{N}.md`, e.g. `sales_inquiry_v2.md`. `version` parameter passed to `get()` is the string after `_v` (i.e. `"2"`), or `"latest"` as a dev convenience resolved by scanning the directory for the highest `N`.
- Each intent's prompt is a fully independent file — bumping `sales_inquiry_v2.md` to `sales_inquiry_v3.md` never touches `technical_support_v1.md`, satisfying the architecture's "editing one intent's prompt no longer risks silently editing another's."

## 20. Validation Rules
- Every prompt file must be valid UTF-8 Markdown/plain text; loaded as-is (no templating engine required for v4.1 — RAG context injection and slot interpolation, if needed, are handled by the *caller* via simple `str.format`/f-string composition around the loaded base text, not inside this module).
- `category` must be one of the five fixed directories — an unrecognized category raises `PromptNotFoundError` immediately rather than attempting a filesystem read outside the expected tree.

## 21. Error Handling
| Error | Handling |
|---|---|
| Prompt file missing on disk | Raise `PromptNotFoundError` with the resolved path in the message; caller (e.g., Router) treats this as a startup-time configuration bug — recommend a startup self-check (see §23) that verifies every prompt referenced in code actually exists on disk, rather than discovering this mid-conversation |
| Malformed version string | Raise `PromptNotFoundError` (invalid version treated the same as missing file) |

## 22. Logging Strategy
- Log a cache miss (first load of a given prompt) at `DEBUG` with the resolved path.
- Log `PromptNotFoundError` at `ERROR` — this always indicates a code/library mismatch.

## 23. Unit Tests
- `test_get_loads_and_caches_prompt`
- `test_get_missing_prompt_raises`
- `test_get_latest_resolves_highest_version`
- `test_invalid_category_raises`
- `test_startup_self_check_all_referenced_prompts_exist` — a small startup-time integration-style check (can live in unit tests since it's filesystem-only) that walks every `PromptRef` used in the codebase (Router, RAG, Tool Executor, Clarification) and asserts the corresponding file exists — catches the "referenced but not migrated" bug class the architecture calls out in Build Order step 7.

## 24. Integration Tests
- `test_prompt_manager_wired_into_router_produces_expected_system_message` — thin wiring check that Module 06 actually calls `PromptManager.get` rather than hardcoding prompt text inline.

## 25. Configuration
```
prompts:
  library_path: str = "./prompt_library"
```

## 26. Environment Variables
Optionally `PROMPT_LIBRARY_PATH` (defaults to `./prompt_library` relative to project root; not in the Module 00 required-credentials list since it has a safe default, documented here as an optional override).

## 27. Sequence Diagram
```
Router.classify(...)
        │
        ▼
PromptManager.get("system", "base", "1")
        │
   cache hit? ── yes ──► return cached str
        │ no
   read prompt_library/system/base_v1.md
        │
   cache it, return str
```

## 28. Request Lifecycle
In-process, called multiple times per turn (once per prompt category needed) from within Router/RAG/Tool Executor/Clarification.

## 29. Data Flow
Filesystem (`prompt_library/`) → `PromptManager` in-memory cache → callers compose `messages` for `OllamaClient.chat` (Module 05) → `PromptVersionTag` recorded to `conversation_turns` (Module 04).

## 30. Example Workflow
1. Migration (Build Order step 7): existing v3/v4 prompt strings are extracted from code into `prompt_library/intents/sales_inquiry_v1.md`, etc., verbatim, before any new prompt is added — "so nothing is orphaned outside the system."
2. A prompt tweak for sales inquiries is authored as `sales_inquiry_v2.md` (new file, old one kept for history/rollback).
3. Router is updated to request version `"2"`; `technical_support_v1.md` is untouched.
4. Next turn's `conversation_turns.prompt_version` shows `{"intent": "sales_inquiry_v2", ...}`, making the behavior change traceable via a `WHERE` clause.

## 31. Future Extension Points
- DB-backed prompt overrides for runtime editing without a restart (mirrors the Feature Flags table pattern in Module 09).
- Hot-reload (`PromptManager.reload()`) for local dev convenience — explicitly not required for v4.1 but trivial to add later.

## 32. Completion Checklist
- [ ] All five prompt categories exist with at least one versioned file each
- [ ] `get(category, name, version)` loads and caches correctly
- [ ] All v3/v4 prompts migrated into the library before any new prompt is added
- [ ] Startup self-check confirms every code-referenced prompt exists on disk
- [ ] `conversation_turns.prompt_version` correctly reflects a structured multi-key object
- [ ] Tests above pass
