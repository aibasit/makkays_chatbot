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
`POST /chat` handler — full request lifecycle:
1. **OPTIONS preflight**: handled automatically by FastAPI's `CORSMiddleware` (registered in Module 01 §19). No explicit OPTIONS route needed here.
2. `require_site_api_key` dependency: reads `X-Site-Api-Key` header, compares to `settings.site.site_api_key` using `hmac.compare_digest` (constant-time). Raises `HTTPException(status_code=401)` on mismatch or absence.
3. `session_id = SessionCookieManager.get_or_create(request, response)`: reads cookie `settings.site.session_cookie_name`. If absent or not a valid UUID4 string, generates `str(uuid4())`, sets response cookie `HttpOnly=True, SameSite='Lax', Secure=False, max_age=86400` (24 hours). Returns the session_id string in either case.
4. `tenant_id = UUID(settings.db.default_tenant_id)` — injected at this layer; the Orchestrator and all downstream modules receive a typed `UUID`, never the raw string.
5. `ChatRateLimiter.check(tenant_id, session_id)`: issues Redis `INCR rate_limit:chat:{tenant_id}:{session_id}`; if return value == 1, immediately pipeline `EXPIRE rate_limit:chat:{tenant_id}:{session_id} 60`; if counter exceeds `settings.site.chat_rate_limit_per_minute`, raise `HTTPException(status_code=429, detail={"code": "rate_limited"})`.
6. Validate `chat_request.message.strip()` non-empty, len `<= settings.site.max_message_length` — raise 422 via Pydantic if either fails.
7. `result = await orchestrator.on_turn(tenant_id, session_id, chat_request.message.strip())`.
8. Return `ChatResponse(assistant_message=result.assistant_message, intent=result.intent, awaiting_clarification=result.awaiting_clarification)` with the session cookie set on the response.

## 14. Database Tables
None new.

## 15. Redis Keys
| Key Pattern | TTL | Purpose |
|---|---|---|
| `rate_limit:chat:{tenant_id}:{session_id}` | 60s window | Caps `/chat` calls per session (e.g., 20/min) — distinct from Module 10's per-tool limits, this is the outer request-level guard |

## 16. API Endpoints
| Method | Path | Purpose | Owner |
|---|---|---|---|
| POST | `/chat` | Main conversational endpoint | This module (M15) |

Note: `GET /health` is owned by Module 01. `GET /metrics` and `GET /ready` are owned by Module 16. They are not owned or re-implemented by this module.

## 17. Request Models
`ChatRequest { message: str }` — validated non-empty, max length (e.g. 4000 chars) to bound LLM context/cost.

## 18. Response Models
`ChatResponse { assistant_message: str, intent: str, awaiting_clarification: bool }`.

## 19. Business Logic
- **Session cookie**: `HttpOnly`, `SameSite=Lax`, `Secure=False` for local dev (documented explicitly as a local-dev setting — production cookie hardening is a deployment concern, out of scope). Cookie name: `sales_engineer_session_id`. If absent, a new UUID4 is generated and set on the response.
- **Site API key**: for local dev, a single static key from `.env` (`SITE_API_KEY`), checked via header equality — intentionally simple; production-grade key rotation/per-client keys are out of scope per the local-dev-only instruction.
- **Tenant resolution**: `DEFAULT_TENANT_ID` (Module 00) used for every request in v4.1 — no per-request tenant resolution logic yet (multi-tenancy is foundational-only per architecture §2.16).
- **TypeScript Contract Generation**: To prevent API response/request drift between the FastAPI backend and React frontend, a CLI script is created at **`scripts/generate_typescript_types.py`**. The script uses the `pydantic2ts` tool (or Python introspection of Pydantic models) to parse `ChatRequest`, `ChatResponse`, and associated schemas, generating the frontend typed file **`frontend/src/types/chat.ts`** automatically on any backend schema edit. Run as `python scripts/generate_typescript_types.py`.

## 20. Validation Rules
- `message`, after `.strip()`, must be non-empty — 422 `{"detail": [{"loc": ["body", "message"], "msg": "message is empty"}]}`.
- `message` length must be `<= settings.site.max_message_length` (default `4000` characters, measured after strip) — 422 with appropriate detail.
- `X-Site-Api-Key` header required; missing or mismatched → 401 `{"code": "unauthorized"}`.
- Session cookie, if present, must be parseable as `UUID(cookie_value)` without raising `ValueError`. If parsing fails, treat as absent and issue a new session. Never return a 4xx for a malformed cookie.

## 21. Error Handling
| Error | Handling |
|---|---|
| Missing/invalid site API key | 401 `{"code": "unauthorized"}` |
| Rate limit exceeded | 429 `{"code": "rate_limited"}` |
| `message` empty or too long | 422 (standard FastAPI/Pydantic validation error) |
| Orchestrator raises an unexpected `AppError` | Mapped by the global handler (Module 01) to the appropriate status/body |
| Orchestrator raises an unhandled exception | Global 500 handler (Module 01), generic body, full detail logged server-side only |

## 22. Logging Strategy
- Log every `/chat` call at `INFO`: `tenant_id`, `session_id`, `intent` (post-classification), latency — never log raw `message` content at this layer.
- Log 401/429 occurrences at `WARNING` (potential abuse signal).

## 23. Unit Tests
- `test_chat_requires_site_api_key`
- `test_chat_rejects_missing_api_key_with_401`
- `test_chat_rejects_wrong_api_key_with_401`
- `test_chat_empty_message_returns_422`
- `test_chat_message_too_long_returns_422`
- `test_chat_rate_limit_returns_429_after_threshold`
- `test_session_cookie_created_on_first_request`
- `test_session_cookie_reused_on_subsequent_request`
- `test_malformed_session_cookie_issues_new_session`
- `test_tenant_id_is_injected_as_uuid_not_string`
- `test_rate_limiter_uses_fixed_window_incr_expire`

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
`SITE_API_KEY`, `CHAT_RATE_LIMIT_PER_MINUTE`, `MAX_MESSAGE_LENGTH` (defined in Module 00).

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

## 33. Hardening Update: Correlation and Request Lifecycle
Module 15 creates or accepts a `correlation_id` per HTTP request and makes it available to downstream structured logs. The canonical end-to-end request lifecycle is Module 00 §13; this module owns only authentication, session cookie, request-level rate limiting, request validation, latency measurement, and HTTP response mapping. Redis key names are authoritative in Module 00 §9.
