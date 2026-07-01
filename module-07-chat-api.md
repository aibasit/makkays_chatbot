# Module 7 — Chat API

**Project:** Makkays AI Assistant (RAG Chatbot v4)
**Depends on:** Module 5 (Retrieval Engine), Module 6 (LLM Integration), Module 2
(Supabase + Redis clients)
**Blocks:** Module 8 (Website Widget), Module 9 (Lead & Support System)

---

## 1. Overview

This module exposes the actual `/api/chat` endpoint the widget talks to: session
management, orchestration of Modules 5+6 into one request/response cycle, Redis
response caching, streaming, and basic rate limiting. This is where the RAG pipeline
becomes an actual product surface.

---

## 2. Goals / Success Criteria

- `POST /api/chat` accepts a message (+ session id), runs the full retrieve → rerank →
  confidence → generate → groundedness pipeline, persists the turn, returns the answer.
- Sessions are tracked (`chat_sessions`/`chat_messages` in Supabase) so multi-turn
  context works across requests.
- Identical/near-identical repeated questions hit Upstash Redis cache instead of
  re-running the full pipeline (short TTL — this is a cost/latency optimization, not
  a correctness feature).
- Responses can stream token-by-token to the widget (better perceived latency).
- Basic rate limiting protects against abuse (per-session and/or per-IP).

---

## 3. Folder/File Additions

```
backend/app/
├── api/
│   └── chat.py                 # POST /api/chat, GET /api/chat/{session_id}/history
└── services/
    └── chat_service.py          # orchestration: session + pipeline + cache + persistence
```

---

## 4. Implementation Tasks

### 4.1 Request/response schema (`api/chat.py`)

```python
from pydantic import BaseModel

class ChatRequest(BaseModel):
    session_id: str | None = None   # None → new session created
    message: str
    visitor_id: str | None = None    # anonymous widget-side identifier

class ChatResponse(BaseModel):
    session_id: str
    answer: str
    confidence_band: str            # normal | hedged | fallback
    provider: str                    # groq | ollama
    grounded: bool
    cached: bool
```

### 4.2 Session management (`services/chat_service.py`)

```python
async def get_or_create_session(supabase, session_id: str | None, visitor_id: str | None) -> str:
    if session_id:
        existing = supabase.table("chat_sessions").select("id").eq("id", session_id).execute()
        if existing.data:
            return session_id
    new_session = supabase.table("chat_sessions").insert({"visitor_id": visitor_id}).execute()
    return new_session.data[0]["id"]

async def get_recent_history(supabase, session_id: str, limit: int = 8) -> list[dict]:
    rows = (supabase.table("chat_messages")
            .select("role, content")
            .eq("session_id", session_id)
            .order("created_at", desc=True)
            .limit(limit)
            .execute())
    return list(reversed(rows.data))   # chronological order for the LLM

async def persist_message(supabase, session_id, role, content, confidence_score=None, chunk_ids=None):
    supabase.table("chat_messages").insert({
        "session_id": session_id, "role": role, "content": content,
        "confidence_score": confidence_score, "retrieved_chunk_ids": chunk_ids,
    }).execute()
```

### 4.3 Redis response caching (`services/chat_service.py`)

```python
import hashlib, json

def cache_key(query: str) -> str:
    normalized = query.strip().lower()
    return f"chat:response:{hashlib.sha256(normalized.encode()).hexdigest()}"

async def get_cached_response(redis, query: str) -> dict | None:
    raw = redis.get(cache_key(query))
    return json.loads(raw) if raw else None

async def cache_response(redis, query: str, response: dict, ttl_seconds: int = 3600) -> None:
    redis.set(cache_key(query), json.dumps(response), ex=ttl_seconds)
```

- Cache is keyed on **normalized query text only**, not session — this deliberately
  lets identical questions from different visitors share a cache hit (this is a
  company-FAQ-style bot; that's the correct tradeoff, not a bug).
- Skip caching for `fallback`-band responses — no point caching "I don't know."
- Respect Upstash's 10k commands/day free tier: one `GET` + one conditional `SET` per
  uncached request is the budget; don't add extra Redis round trips per turn without
  reason.

### 4.4 Full orchestration (`chat_service.py`)

```python
async def handle_chat_message(request: ChatRequest, supabase, qdrant_client, redis, llm_router) -> ChatResponse:
    session_id = await get_or_create_session(supabase, request.session_id, request.visitor_id)

    cached = await get_cached_response(redis, request.message)
    if cached:
        await persist_message(supabase, session_id, "user", request.message)
        await persist_message(supabase, session_id, "assistant", cached["answer"], cached.get("confidence_score"))
        return ChatResponse(session_id=session_id, cached=True, **cached)

    history = await get_recent_history(supabase, session_id)
    rewritten_query = rewrite_query(request.message, history)                      # Module 5
    ranked_chunks = rerank(rewritten_query, hybrid_search(qdrant_client, rewritten_query))  # Module 5
    confidence = score_confidence(ranked_chunks)                                    # Module 5

    if confidence["band"] == "fallback":
        answer_payload = {
            "answer": "I couldn't find a confident answer to that in our materials — "
                      "would you like to leave your contact details so our team can follow up?",
            "confidence_band": "fallback", "provider": "none", "grounded": False,
        }
        # Module 9 hooks in here to trigger lead-capture UI state
    else:
        result = await generate_grounded_answer(                                    # Module 6
            rewritten_query, ranked_chunks, confidence["band"], history, llm_router
        )
        answer_payload = {
            "answer": result["answer"], "confidence_band": confidence["band"],
            "provider": result["provider"], "grounded": result["grounded"],
        }

    await persist_message(supabase, session_id, "user", request.message)
    await persist_message(
        supabase, session_id, "assistant", answer_payload["answer"],
        confidence["score"], [c["id"] for c in ranked_chunks],
    )

    if confidence["band"] != "fallback":
        await cache_response(redis, request.message, {**answer_payload, "confidence_score": confidence["score"]})

    return ChatResponse(session_id=session_id, cached=False, **answer_payload)
```

### 4.5 Streaming responses

- FastAPI `StreamingResponse` over Server-Sent Events (SSE) for the widget to render
  tokens progressively.
- Groq's SDK supports `stream=True`; Ollama's `/api/chat` supports
  `"stream": true` with newline-delimited JSON chunks — both providers in Module 6
  need a `generate_stream()` variant, or this module wraps the non-streaming
  `generate()` and simulates chunked delivery at minimum for v1 if true streaming
  through both providers adds complexity beyond this phase's scope.
- Non-streaming JSON response remains the default/fallback endpoint shape for
  simplicity in early testing; add `/api/chat/stream` as a second endpoint once the
  non-streaming path is solid.

### 4.6 Rate limiting

- Use Upstash Redis for a simple sliding-window counter per `visitor_id` (or IP if
  `visitor_id` absent): e.g. max 20 messages/5 minutes.

```python
async def check_rate_limit(redis, identifier: str, limit: int = 20, window_seconds: int = 300) -> bool:
    key = f"ratelimit:{identifier}"
    count = redis.incr(key)
    if count == 1:
        redis.expire(key, window_seconds)
    return count <= limit
```

- On limit exceeded, return `429` with a friendly message — never a bare error.

### 4.7 Routes (`api/chat.py`)

```python
@router.post("/api/chat", response_model=ChatResponse)
async def chat(request: ChatRequest, supabase: SupabaseDep, qdrant: QdrantDep,
                redis: RedisDep, llm: LLMProviderDep):
    identifier = request.visitor_id or request.session_id or "anonymous"
    if not await check_rate_limit(redis, identifier):
        raise RateLimitExceeded()   # → 429, Module 1's exception handler pattern
    return await handle_chat_message(request, supabase, qdrant, redis, llm)

@router.get("/api/chat/{session_id}/history")
async def get_history(session_id: str, supabase: SupabaseDep):
    return await get_recent_history(supabase, session_id, limit=50)
```

---

## 5. Testing & Validation Checklist

- [ ] New session created on first message (no `session_id` sent); returned
      `session_id` reused correctly on the next request from the same widget instance.
- [ ] Multi-turn conversation: a follow-up question is correctly resolved using
      history (ties to Module 5's query rewrite).
- [ ] Identical question sent twice returns `cached: true` on the second call, and
      response time is visibly faster.
- [ ] Fallback-band query returns the fixed message without any Groq/Ollama call
      (check logs — zero LLM calls for that request).
- [ ] Rate limit triggers correctly after the configured threshold and returns `429`.
- [ ] `GET /api/chat/{session_id}/history` returns messages in chronological order.
- [ ] All persisted `chat_messages` rows have correct `role`, `confidence_score`, and
      `retrieved_chunk_ids`.

---

## 6. Deliverable

A session-aware, cache-aware `/api/chat` endpoint that runs the full RAG pipeline
end-to-end, persists conversation history, and enforces basic rate limiting — ready
for Module 8's widget to consume.

---

## 7. Handoff Notes for Claude Code

- Keep `chat_service.py` as the single orchestration point — `api/chat.py` stays a
  thin route layer (parse request → call service → return response), consistent with
  Module 1's DI-first pattern.
- Streaming is the one part of this module reasonable to defer/simplify if time-
  constrained — a solid non-streaming `/api/chat` is a complete, demoable deliverable
  on its own; streaming is a UX polish layer, not a correctness requirement.
- Module 9 (Lead & Support) hooks into the `confidence["band"] == "fallback"` branch
  and into intent-detection on **any** band — don't hardcode lead-capture logic here,
  expose a clean extension point (e.g. return `should_offer_lead_capture: bool` in
  the response) for Module 9 to build on.
