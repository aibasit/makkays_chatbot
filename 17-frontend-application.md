# Module 17 — Frontend Application (React / TypeScript / Vite Chat Widget)

## 1. Module Name
`frontend` — The chat widget UI consuming the `/chat` API from Module 15.

## 2. Goal
Build a React + TypeScript + Vite single-page chat widget styled with Tailwind
CSS, using React Router (for a minimal multi-view shell), TanStack Query (for
request state), and Axios (as the HTTP client), that talks to the backend's
`POST /chat` endpoint.

## 3. Purpose
This is the only user-facing surface in v4.1 scope. It must handle session
cookie continuity transparently (the browser does this automatically for
same-origin cookies), display clarification questions and assistant responses,
and degrade gracefully on rate-limit/error responses — all without embedding any
business logic that belongs server-side (the frontend never decides intent,
plans, or policy; it only renders what the backend returns).

## 4. Dependencies
Module 15 (Public API) must be running and reachable at a known base URL for local dev (e.g. `http://localhost:8000`).

## 5. Folder Structure
```
frontend/
├── index.html
├── vite.config.ts
├── tailwind.config.ts
├── tsconfig.json
├── package.json
├── src/
│   ├── main.tsx
│   ├── App.tsx
│   ├── api/
│   │   ├── client.ts
│   │   └── chat.ts
│   ├── hooks/
│   │   └── useChat.ts
│   ├── components/
│   │   ├── ChatWindow.tsx
│   │   ├── MessageBubble.tsx
│   │   ├── MessageInput.tsx
│   │   ├── ClarificationOptions.tsx
│   │   └── RateLimitNotice.tsx
│   ├── routes/
│   │   ├── ChatPage.tsx
│   │   └── NotFoundPage.tsx
│   ├── types/
│   │   └── chat.ts
│   └── styles/
│       └── index.css
tests/
├── unit/
│   └── useChat.test.tsx
└── integration/
    └── chat-flow.test.tsx
```

## 6. Files to Create
All files listed in §5.

## 7. Responsibility of Every File
| File | Responsibility |
|---|---|
| `main.tsx` | React root mount, wraps `App` in `QueryClientProvider` + `BrowserRouter` |
| `App.tsx` | Route definitions (`/` → `ChatPage`, `*` → `NotFoundPage`) |
| `api/client.ts` | Axios instance with: `baseURL: import.meta.env.VITE_API_BASE_URL` (default `http://localhost:8000`), `headers: {'X-Site-Api-Key': import.meta.env.VITE_SITE_API_KEY}`, `withCredentials: true` (required so the browser sends/receives the `HttpOnly` session cookie cross-port in local dev — without this, the cookie is silently dropped and every request gets a new session), `timeout: 30000` (30s, matching `OLLAMA_TIMEOUT_SECONDS` + overhead) |
| `api/chat.ts` | `postChatMessage(message: string): Promise<ChatResponse>` — typed Axios POST to `/chat` |
| `hooks/useChat.ts` | TanStack Query `useMutation` wrapper around `postChatMessage`, plus local message-list state |
| `components/ChatWindow.tsx` | Scrollable message list container, auto-scrolls to bottom on new message |
| `components/MessageBubble.tsx` | Single message rendering (user vs assistant styling) |
| `components/MessageInput.tsx` | Text input + send button; disabled while `isLoading === true` or `messages.length === 0` (empty message guard); character counter shown at 80% of max |
| `components/ClarificationOptions.tsx` | Renders clarification options. Parsing: splits `assistant_message` on `\n` and collects lines starting with `- ` or `* ` or matching `/^\d+\.\s/` as individual option strings. Renders each as a clickable chip/button that, when clicked, calls `sendMessage(optionText)` — no interpretation of option content |
| `components/RateLimitNotice.tsx` | Shown when a 429 is received; includes a client-side countdown timer (default 30s) after which the input re-enables |
| `routes/ChatPage.tsx` | Composes `ChatWindow` + `MessageInput`, owns the message list via `useChat` |
| `types/chat.ts` | `ChatMessage`, `ChatResponse` TypeScript types mirroring the backend's Pydantic schemas exactly |

## 8. Classes
Not applicable in the OOP sense (React functional components + hooks only, per the stated stack — no class components).

## 9. Data Models
Client-side only, in `types/chat.ts`:
```ts
type ChatMessage = { role: "user" | "assistant"; content: string; awaitingClarification?: boolean };
type ChatResponse = { assistant_message: string; intent: string; awaiting_clarification: boolean };
```

## 10. Pydantic Schemas
N/A (frontend uses TypeScript types, not Pydantic; kept in exact field-name parity with Module 15's `ChatResponse`/`ChatRequest` to avoid mapping bugs).

## 11. Repository Layer
N/A (frontend has no persistence layer of its own; all state is either in-memory React state or server-persisted via the backend).

## 12. Service Layer
`api/chat.ts` functions as the frontend's thin "service layer" — the only place Axios is called directly; components and hooks never call Axios themselves.

## 13. Internal Interfaces
- `useChat(): { messages: ChatMessage[], sendMessage(text: string): void, isLoading: boolean, isRateLimited: boolean, rateLimitCooldownSeconds: number, error: string | null, retryLastMessage(): void }` — the single interface `ChatPage` consumes.
  - `messages`: the current ordered list of all user and assistant messages for display.
  - `sendMessage(text)`: validates non-empty/non-whitespace, appends a user `ChatMessage` optimistically, calls `postChatMessage`, on success appends the assistant reply; on error removes the optimistically-appended user message and sets `error`.
  - `isLoading`: `true` while a `postChatMessage` request is in flight; controls input/button disabled state.
  - `isRateLimited`: `true` when the last call returned 429; drives `RateLimitNotice` visibility.
  - `rateLimitCooldownSeconds`: counts down from 30 to 0 when `isRateLimited` is `true`; managed by `setInterval` inside `useChat`; resets `isRateLimited` to `false` when it reaches 0.
  - `error`: a human-readable error string (not a raw HTTP error); `null` when no error.
  - `retryLastMessage()`: re-sends the last user message text. The retry button in the `MessageBubble` error state calls this.
- `postChatMessage(message: string) -> Promise<ChatResponse>` — the single interface `useChat` consumes.

## 14. Database Tables
N/A (frontend has no database).

## 15. Redis Keys
N/A.

## 16. API Endpoints
Consumes (does not define): `POST /chat` (Module 15).

## 17. Request Models
`ChatRequest { message: string }` sent as the Axios POST body; `X-Site-Api-Key` sent as a header (value baked in via `import.meta.env.VITE_SITE_API_KEY`). The `.env.local` file (gitignored) must contain:
```
VITE_API_BASE_URL=http://localhost:8000
VITE_SITE_API_KEY=<value from .env SITE_API_KEY>
```
`VITE_` prefix is required by Vite to expose env vars to browser code. Never put these in `vite.config.ts` directly; always use the `.env.local` file.

## 18. Response Models
`ChatResponse` as defined in §9, parsed directly from the Axios response.

## 19. Business Logic
- **Optimistic UI**: user's message is appended to `messages` immediately on send via `useChat.sendMessage`; the assistant's reply is appended only once the response arrives. On error, the optimistically-appended user message is **removed** from `messages` so the user can see the exact text they sent is no longer "in flight", and `error` is set to display an error bubble with a retry button.
- **Retry button**: rendered inside the error message bubble by `MessageBubble` when `error` is non-null. The retry button calls `useChat.retryLastMessage()`, which re-sends `lastUserMessageText: string | null` stored in the hook's `useRef`. If `lastUserMessageText` is null (no prior message), the button is not rendered.
- **Clarification rendering**: when `awaiting_clarification === true`, `ClarificationOptions` is rendered instead of `MessageBubble` for the assistant reply. It splits `assistant_message` on `\n`, filters to lines matching `^[-*]\s` or `^\d+\.\s`, and renders each as a clickable button that calls `sendMessage(line.replace(/^[-*\d.]+\s/, '').trim())`.
- **No client-side intent/plan logic**: the frontend never inspects `intent` to change its own behavior beyond the `awaiting_clarification` boolean — all decision-making stays server-side.

## 20. Validation Rules
- Empty/whitespace-only messages are not sent (send button disabled).
- Message length capped client-side at the same 4000-character limit as the backend (Module 15 §20), to give immediate feedback rather than waiting for a 422.

## 21. Error Handling
| Error | Handling |
|---|---|
| 401 (bad/missing site key) | Should not occur in normal operation (key is build-time baked); if it does, show a generic "configuration error" notice, log to browser console |
| 429 (rate limited) | Show `RateLimitNotice`, disable input for a short cooldown period (client-side timer, purely cosmetic — actual enforcement is server-side) |
| 5xx / network error | Show a generic "something went wrong, please try again" message; the optimistically-appended user message remains visible so nothing is lost from the user's perspective; a retry button re-sends the same text |
| 401 | Configuration error notice. |
| 429 | `RateLimitNotice` + input disabled for 30s. |
| 5xx/Network | Keep optimistic user message in list, set `error`, show retry button. |
| Timeout | Set to 30s in Axios config; handle like 5xx. |

## 22. Logging Strategy
Browser `console.error` for unexpected failures only (no client-side structured logging pipeline in v4.1 scope — no analytics/telemetry infrastructure, matching the exclusion of monitoring infra from this local-dev-only documentation set).

## 23. Unit Tests
- `test_useChat_appends_user_message_optimistically_before_response`
- `test_useChat_removes_optimistic_message_on_error`
- `test_useChat_sets_error_string_on_network_failure`
- `test_useChat_sets_is_rate_limited_on_429`
- `test_useChat_cooldown_timer_resets_is_rate_limited`
- `test_useChat_retry_last_message_resends_last_text`
- `test_clarification_options_parses_bullet_lines_correctly`
- `test_clarification_options_clickable_chip_calls_send_message`
- `test_message_input_disabled_while_loading`
- `test_message_input_disabled_when_empty`
- `test_axios_instance_sends_site_api_key_header`
- `test_axios_instance_has_with_credentials_true`
- `useChat.test.tsx`: `sendMessage sets isRateLimited on 429`
- `MessageBubble.test.tsx`: `renders user vs assistant styling correctly`
- `ClarificationOptions.test.tsx`: `renders bullet options distinctly from plain text`

## 24. Integration Tests
- `chat-flow.test.tsx` (using a mocked backend, e.g. MSW): full send → optimistic render → response → final render round-trip.
- `chat-flow.test.tsx`: rate-limit path shows notice and disables input.
- `chat-flow.test.tsx`: network error path preserves the user's message and offers retry.

## 25. Configuration
```
vite.config.ts:
  server.port = 5173 (default)
  server.proxy: not required if VITE_API_BASE_URL points directly at localhost:8000 (CORS must be enabled on the backend for localhost:5173, configured in Module 01's app factory — flagged here as a cross-module dependency: Module 01's CORS middleware must allow the frontend's local origin)
```

## 26. Environment Variables
Frontend-specific (Vite convention, `.env` in `frontend/`):
```
VITE_API_BASE_URL=http://localhost:8000
VITE_SITE_API_KEY=<same value as backend's SITE_API_KEY>
```

## 27. Sequence Diagram
```
User types message, hits Send
        │
        ▼
useChat.sendMessage(text)
        │
   append optimistic ChatMessage{role:"user"} to local state
        │
   TanStack Query mutation → api/chat.ts postChatMessage(text)
        │
   Axios POST /chat  (withCredentials: true, X-Site-Api-Key header)
        │
   ┌─── 200 ───┐            ┌─── 429 ───┐          ┌─── 5xx/network ───┐
   ▼                        ▼                       ▼
append assistant       show RateLimitNotice     show retry notice,
ChatMessage,            disable input briefly    keep optimistic msg
render Clarification
Options if applicable
```

## 28. Request Lifecycle
Browser → `POST /chat` (cross-origin to `localhost:8000` in local dev, cookie carried via `withCredentials`) → Module 15 → ... → `ChatResponse` → rendered.

## 29. Data Flow
User input → local optimistic state → Axios → backend → `ChatResponse` → merged into local message list → re-render.

## 30. Example Workflow
1. Widget loads at `localhost:5173`; no prior cookie.
2. User types "Do you have a 48-port Cisco switch?", hits send.
3. Optimistic bubble appears immediately; loading indicator shows on `MessageInput`.
4. Backend responds within a few seconds; assistant bubble appears with the answer.
5. Browser now holds the session cookie set by the backend; the next message continues the same conversation server-side.

## 31. Future Extension Points
- Embeddable widget bundle (iframe/script-tag distribution) for use on an actual client website — the current SPA shell is the foundation for that, not the final distribution form.
- Streaming token-by-token responses (would require Module 15 to add an SSE/WebSocket path).
- Image upload UI, gated behind `ENABLE_IMAGE_UPLOAD` once that capability exists server-side.

## 32. Completion Checklist
- [ ] Site key + cookie-based session correctly round-trip with the backend
- [ ] Optimistic user-message rendering with graceful error/rate-limit/timeout handling
- [ ] Clarification responses rendered distinctly from normal answers
- [ ] No business/intent logic duplicated client-side
- [ ] Tests above pass
