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
| `api/client.ts` | Axios instance — base URL, `X-Site-Api-Key` header, `withCredentials: true` (required for the session cookie to be sent/received cross-port in local dev) |
| `api/chat.ts` | `postChatMessage(message: string): Promise<ChatResponse>` — typed Axios call |
| `hooks/useChat.ts` | TanStack Query `useMutation` wrapper around `postChatMessage`, plus local message-list state |
| `components/ChatWindow.tsx` | Scrollable message list container |
| `components/MessageBubble.tsx` | Single message rendering (user vs assistant styling) |
| `components/MessageInput.tsx` | Text input + send button, disabled while a request is in flight |
| `components/ClarificationOptions.tsx` | Renders bullet options from a clarification response distinctly (visually) from a normal answer |
| `components/RateLimitNotice.tsx` | Shown when a 429 is received |
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
- `useChat()` hook returns `{ messages, sendMessage(text), isLoading, isRateLimited, error }` — the single interface `ChatPage` and any future embeddable widget variant consumes.
- `postChatMessage(message) -> Promise<ChatResponse>` — the single interface `useChat` consumes.

## 14. Database Tables
N/A (frontend has no database).

## 15. Redis Keys
N/A.

## 16. API Endpoints
Consumes (does not define): `POST /chat` (Module 15).

## 17. Request Models
`ChatRequest { message: string }` sent as the Axios POST body; `X-Site-Api-Key` sent as a header (value baked in at build time via a Vite env var for local dev — `VITE_SITE_API_KEY` — acceptable for local dev only; production key handling is out of scope).

## 18. Response Models
`ChatResponse` as defined in §9, parsed directly from the Axios response.

## 19. Business Logic
- **Optimistic UI**: user's message is appended to `messages` immediately on send, before the network response returns; the assistant's reply is appended only once the response arrives (or an error/rate-limit notice is shown in its place).
- **Clarification rendering**: when `awaiting_clarification: true`, `ClarificationOptions` renders the bullet list distinctly (e.g., a lightly bordered card) rather than as a plain chat bubble, making the template's bullet structure visually obvious to the user — this is purely presentational; the frontend does not parse or interpret the option text, it just renders whatever the backend sent.
- **No client-side intent/plan logic**: the frontend never inspects `intent` to change its own behavior beyond passing `awaiting_clarification` through for styling — all decision-making stays server-side, matching the "FastAPI is the brain" principle end to end.

## 20. Validation Rules
- Empty/whitespace-only messages are not sent (send button disabled).
- Message length capped client-side at the same 4000-character limit as the backend (Module 15 §20), to give immediate feedback rather than waiting for a 422.

## 21. Error Handling
| Error | Handling |
|---|---|
| 401 (bad/missing site key) | Should not occur in normal operation (key is build-time baked); if it does, show a generic "configuration error" notice, log to browser console |
| 429 (rate limited) | Show `RateLimitNotice`, disable input for a short cooldown period (client-side timer, purely cosmetic — actual enforcement is server-side) |
| 5xx / network error | Show a generic "something went wrong, please try again" message; the optimistically-appended user message remains visible so nothing is lost from the user's perspective; a retry button re-sends the same text |
| Request timeout | Same as 5xx handling; Axios timeout configured at e.g. 35s (slightly above the backend's `LLM_TIMEOUT_SECONDS`, Module 05, so the frontend doesn't time out before the backend has a chance to) |

## 22. Logging Strategy
Browser `console.error` for unexpected failures only (no client-side structured logging pipeline in v4.1 scope — no analytics/telemetry infrastructure, matching the exclusion of monitoring infra from this local-dev-only documentation set).

## 23. Unit Tests
- `useChat.test.tsx`: `sendMessage appends optimistic user message immediately`
- `useChat.test.tsx`: `sendMessage appends assistant message on success`
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
