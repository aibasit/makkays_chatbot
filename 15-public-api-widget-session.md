# Module 15 — Public API & Widget Session

## 1. Module Name
`public_api` — The `/chat` HTTP surface, widget session cookie strategy, local-dev site-key auth, rate limiting.

## 2. Goal
Expose the Orchestrator (Module 06) as an HTTP API consumable by the React
frontend (Module 17), with a session-cookie-based `session_id`, a simple site-key
header check appropriate for local dev, and basic per-session rate limiting.

## 3. Purpose
This is the seam between the frontend widget and the FastAPI "brain." Everything
built in Modules 01–14 is only reachable through this module's endpoints.
Deployment-grade concerns (origin/referrer validation hardening, reverse-proxy
trust, production rate-limit tuning) are explicitly out of scope per the
local-development-only instruction; this module implements the **application-level**
auth/session mechanics only.

## 4. Dependencies
Module 03 (session/state), Module 06 (Orchestrator), Module 14 (lead/contact capture, indirectly via Orchestrator).

## 5. Folder Structure
```
app/
├── api/
│   ├── __init__.py
│   ├── chat_router.py
│   ├── session_cookie.py
│   ├── auth.py
│   ├── rate_limit.py
│   └── schemas.py
tests/
├── unit/
│   ├── test_session_cookie.py
│   └── test_site_key_auth.py
└── integration/
    └── test_chat_endpoint.py
```

## 6. Files to Create
`chat_router.py`, `session_cookie.py`, `auth.py`, `rate_limit.py`, `schemas.py`.

## 7. Responsibility of Every File
| File | Responsibility |
|---|---|
| `chat_router.py` | `POST /chat` — the main endpoint, calls `Orchestrator.on_turn` |
| `session_cookie.py` | Issues/reads a `session_id` cookie; generates a new one if absent |
| `auth.py` | `require_site_api_key` dependency — validates the `X-Site-Api-Key` header against `Settings.site.site_api_key` |
| `rate_limit.py` | Simple Redis-backed per-session request rate limiter (distinct from Module 10's per-tool rate limits — this one caps overall `/chat` call frequency) |
| `schemas.py` | `ChatRequest`, `ChatResponse` |

## 8. Classes
- `SessionCookieManager` — `get_or_create(request, response) -> str` (session_id).
- `SiteKeyAuth` — FastAPI dependency callable.
- `ChatRateLimiter` — `async check(tenant_id, session_id) -> None` (raises if exceeded).

## 9. Data Models
No new tables — `session_id ⇄ lead_id ⇄ crm_contact_id` linkage (architecture Build Order step 14) is satisfied by `leads.session_id` (Module 14) plus `leads.crm_contact_id`; no separate linkage table needed since both fields already live on `leads`.

## 10. Pydantic Schemas
- `ChatRequest { message: str }` (session_id comes from the cookie, not the body — prevents a client from spoofing another session's id via payload).
- `ChatResponse { assistant_message: str, intent: str, awaiting_clarification: bool }` — deliberately minimal; internal fields like `tool_calls`/`plan` are not exposed to the frontend in v4.1 scope (debugging detail stays server-side in `conversation_turns`).

## 11. Repository Layer
None new — this module is a thin HTTP adapter over Module 06.

## 12. Service Layer
None new beyond the small helper classes in §8 — business logic lives entirely in the Orchestrator; this module's job is strictly request/response translation plus auth/session/rate-limit concerns.

## 13. Internal Interfaces
`POST /chat` handler:
1. `require_site_api_key` dependency validates header.
2. `session_id = SessionCookieManager.get_or_create(request, response)`.
3. `ChatRateLimiter.check(tenant_id=DEFAULT_TENANT_ID, session_id)`.
4. `result = await Orchestrator.on_turn(tenant_id, session_id, chat_request.message)`.
5. Build and return `ChatResponse` from `result`.

## 14. Database Tables
None new.

## 15. Redis Keys
| Key Pattern | TTL | Purpose |
|---|---|---|
| `ratelimit:chat:{tenant_id}:{session_id}` | 60s window | Caps `/chat` calls per session (e.g., 20/min) — distinct from Module 10's per-tool limits, this is the outer request-level guard |

## 16. API Endpoints
| Method | Path | Purpose |
|---|---|---|
| POST | `/chat` | Main conversational endpoint |
| GET | `/health` | (Module 01, re-listed for completeness of the public surface) |

## 17. Request Models
`ChatRequest { message: str }` — validated non-empty, max length (e.g. 4000 chars) to bound LLM context/cost.

## 18. Response Models
`ChatResponse { assistant_message: str, intent: str, awaiting_clarification: bool }`.

## 19. Business Logic
- **Session cookie**: `HttpOnly`, `SameSite=Lax`, `Secure=False` for local dev (documented explicitly as a local-dev setting — production cookie hardening is a deployment concern, out of scope). Cookie name: `sales_engineer_session_id`. If absent, a new UUID4 is generated and set on the response.
- **Site API key**: for local dev, a single static key from `.env` (`SITE_API_KEY`), checked via header equality — intentionally simple; production-grade key rotation/per-client keys are out of scope per the local-dev-only instruction.
- **Tenant resolution**: `DEFAULT_TENANT_ID` (Module 00) used for every request in v4.1 — no per-request tenant resolution logic yet (multi-tenancy is foundational-only per architecture §2.16).

## 20. Validation Rules
- `message` non-empty after trim, max 4000 characters.
- `X-Site-Api-Key` header required; missing or mismatched → 401.
- Session cookie, if present, must be a well-formed UUID4 string; malformed cookies are treated as absent (a new session is issued) rather than rejected outright.

## 21. Error Handling
| Error | Handling |
|---|---|
| Missing/invalid site API key | 401 `{"code": "unauthorized"}` |
| Rate limit exceeded | 429 `{"code": "rate_limited"}` |
| `message` empty or too long | 422 (standard FastAPI/Pydantic validation error) |
| Orchestrator raises an unexpected `AppError` | Mapped by the global handler (Module 01) to the appropriate status/body |
| Orchestrator raises an unhandled exception | Global 500 handler (Module 01), generic body, full detail logged server-side only |

## 22. Logging Strategy
- Log every `/chat` call at `INFO`: `tenant_id`, `session_id`, `intent` (post-classification), latency — never log raw `message` content at this layer (that's `conversation_turns`' responsibility, Module 04, which has the full per-turn record already).
- Log 401/429 occurrences at `WARNING` (potential abuse signal, though full abuse-prevention infra is out of scope).

## 23. Unit Tests
- `test_session_cookie_created_when_absent`
- `test_session_cookie_reused_when_present_and_valid`
- `test_malformed_session_cookie_treated_as_absent`
- `test_site_key_auth_rejects_missing_header`
- `test_site_key_auth_rejects_wrong_key`
- `test_site_key_auth_accepts_correct_key`

## 24. Integration Tests
- `test_chat_endpoint_full_roundtrip_returns_expected_shape`
- `test_chat_endpoint_rate_limited_after_threshold`
- `test_chat_endpoint_session_persists_across_two_calls` (assert the second call's Facts reflect the first call's captured budget, using the returned `Set-Cookie`)

## 25. Configuration
```
site:
  site_api_key: str
  session_cookie_name: str = "sales_engineer_session_id"
  chat_rate_limit_per_minute: int = 20
  max_message_length: int = 4000
```

## 26. Environment Variables
`SITE_API_KEY` (already defined in Module 00).

## 27. Sequence Diagram
```
Frontend (Module 17)
        │  POST /chat  { message }  + X-Site-Api-Key header + session cookie
        ▼
require_site_api_key  ── fail ──► 401
        │ pass
SessionCookieManager.get_or_create  → session_id (+ Set-Cookie if new)
        │
ChatRateLimiter.check  ── exceeded ──► 429
        │ pass
Orchestrator.on_turn(tenant_id, session_id, message)
        │
        ▼
ChatResponse  ──► JSON response (+ Set-Cookie)
```

## 28. Request Lifecycle
The full lifecycle described in §27 — this module is the outermost layer of every user-facing request in the system.

## 29. Data Flow
Frontend → `POST /chat` → auth/session/rate-limit checks → `Orchestrator.on_turn` (Module 06, which fans out to every other module) → `ChatResponse` → frontend.

## 30. Example Workflow
1. Widget loads, no cookie present → first `/chat` call issues a new `session_id`, sets the cookie.
2. Subsequent calls from the same browser tab reuse the cookie → same `session_id` → Facts/Conversation State continuity (Module 03) across the whole conversation.
3. 21st call within a minute → 429, frontend shows a "please slow down" message (frontend behavior specified in Module 17).

## 31. Future Extension Points
- Origin/referrer validation, per-client site keys, production rate-limit tuning, Caddy/TLS — all explicitly deferred as deployment/production concerns per the local-dev-only scope of this documentation set.
- WebSocket/streaming response support (currently a single request/response cycle per turn).

## 32. Completion Checklist
- [ ] `/chat` requires a valid site API key
- [ ] Session cookie issued/reused correctly, `HttpOnly`
- [ ] Rate limiting enforced independently of Module 10's per-tool limits
- [ ] `ChatResponse` never leaks internal fields (plan, tool_calls, raw prompt text)
- [ ] Tests above pass
