# Module 05 — LLM Engine (Ollama / Qwen2.5 Tool-Calling Loop)

## 1. Module Name
`llm_engine` — Local Ollama client wrapper, tool-calling loop primitives, structured-output parsing.

## 2. Goal
Provide a single, typed interface over the local Ollama `qwen2.5:3b` model
supporting tool calling and structured (JSON-schema-constrained) outputs, used by
every module that needs an LLM call (Router's Tier 2, RAG explanation, Quote
explanation, optional Clarification rewrite).

## 3. Purpose
Architecture principle: "FastAPI is the brain" — the LLM only classifies, explains,
or reworks language; it never decides control flow directly. This module is the
narrow, well-tested boundary through which every LLM call passes, so that
contract is enforced in one place rather than reimplemented per caller.

## 4. Dependencies
Module 01 (config), Module 04 (logging).

## 5. Folder Structure
```
app/
├── llm/
│   ├── __init__.py
│   ├── client.py
│   ├── schemas.py
│   ├── tool_schema.py
│   ├── context.py
│   └── exceptions.py
tests/
├── unit/
│   └── test_llm_client_parsing.py
└── integration/
    └── test_llm_ollama_roundtrip.py
```

## 6. Files to Create
`client.py`, `schemas.py`, `tool_schema.py`, `context.py`, `exceptions.py`.

## 7. Responsibility of Every File
| File | Responsibility |
|---|---|
| `client.py` | `OllamaClient` — thin async wrapper over Ollama's `/api/chat` endpoint with tool-calling and JSON-mode support |
| `schemas.py` | `ChatMessage`, `ToolCall`, `ToolResult`, `LLMResponse` Pydantic models |
| `tool_schema.py` | Helpers to build the JSON tool-schema payload Ollama expects from a Python function signature/description registry |
| `context.py` | Canonical `build_llm_messages(...)` helper shared by Router, respond, Quote Explainer, RAG response composition, and Clarification rewrite |
| `exceptions.py` | `LLMTimeoutError`, `LLMMalformedOutputError`, `LLMUnavailableError` |

## 8. Classes
- `LLMClientProtocol(Protocol)` — PEP 544 structural protocol defining the standard async interface for LLM client operations:
  ```python
  class LLMClientProtocol(Protocol):
      async def chat(
          self,
          messages: list[ChatMessage],
          tools: list[dict] | None = None,
          response_format: dict | None = None,
          temperature: float = 0.0
      ) -> LLMResponse:
          ...
  ```
  All callers (Router, Quote Explainer, Clarification Rewrite, built-in tools) type-hint against `LLMClientProtocol` rather than referencing `OllamaClient` directly.
- `OllamaClient` — concrete class implementing `LLMClientProtocol`. Exposes `async chat(messages, tools=None, response_format=None, temperature=0.0) -> LLMResponse`.
- `ChatMessage { role: Literal["system","user","assistant","tool"], content: str, tool_call_id: str | None }`.
- `ToolCall { id: str, name: str, arguments: dict }`.
- `LLMResponse { content: str | None, tool_calls: list[ToolCall], raw: dict }`.
- `ContextBuildMetadata { included_turn_count: int, included_source_ids: list[str], truncated_turn_count: int, truncated_source_count: int, prompt_refs: dict[str, str] }`.

## 9. Data Models
No persistence — this module is a stateless outbound-call wrapper.

## 10. Pydantic Schemas
`ChatMessage`, `ToolCall`, `ToolResult`, `LLMResponse` as above; `StructuredOutputRequest { schema: dict, messages: list[ChatMessage] }` for the JSON-mode path used by `classify_intent` (Module 06) and quote explanation (Module 12).

`ToolResult` full definition: `{ role: Literal["tool"], content: str, tool_call_id: str }` — the message appended to the conversation after executing a tool call, sent back to the LLM in a follow-up `chat` call. `tool_call_id` must match the `ToolCall.id` of the original request; Ollama requires this pairing for multi-turn tool loops.

## 11. Repository Layer
N/A — no persistence.

## 12. Service Layer
`OllamaClient` itself functions as the service boundary; no separate service layer needed since this module has a single external dependency (Ollama) and no business decisions of its own.

## 13. Internal Interfaces
- `LLMClientProtocol` (above) — structural protocol defining the standard async interface for LLM operations. Exported from `app/llm/__init__.py`.
- `async chat(messages, tools, response_format, temperature) -> LLMResponse` — concrete Ollama implementation.
- `build_tool_schema(name, description, parameters: dict) -> dict` — used by Module 10 (Tool Executor) to register tool schemas that get passed into `chat(tools=...)`.
- `build_llm_messages(...) -> tuple[list[ChatMessage], ContextBuildMetadata]` — canonical context assembly helper defined in Module 00 §7. Every LLM caller uses this helper before calling `OllamaClient.chat`; callers do not hand-roll message ordering, truncation, or source formatting.
- Timeout enforced via `asyncio.wait_for` wrapping the HTTP call — default value read from `settings.ollama.timeout_seconds` (env var `OLLAMA_TIMEOUT_SECONDS`, default `30`).
- HTTP transport: `httpx.AsyncClient` with a shared instance created once at module level (not per-call). Configure with `timeout=httpx.Timeout(connect=5.0, read=settings.ollama.timeout_seconds, write=5.0, pool=2.0)`. The client is closed in the app's shutdown lifespan hook (Module 01 §19).
- Ollama request shapes (both use `stream: false`):
  - Tool-calling mode: `{"model": settings.ollama.model, "messages": [...], "tools": [...], "stream": false}`
  - Structured output mode: `{"model": settings.ollama.model, "messages": [...], "format": <json-schema-dict>, "stream": false}`
- If `tools` are provided but `LLMResponse.tool_calls` is empty and `content` is non-empty: return the `LLMResponse` as-is. An empty `tool_calls` list is a valid Ollama response; the caller treats it as a classification failure. Do NOT raise an error.

## 14. Database Tables
None.

## 15. Redis Keys
None (no caching of LLM responses in v4.1 scope — every call is fresh; caching is a future extension point).

## 16. API Endpoints
None public — internal client only.

## 17. Request Models
N/A (Python-level interface, not HTTP-exposed).

## 18. Response Models
`LLMResponse` as above, consumed in-process by Router/RAG/Quote/Clarification modules.

## 19. Business Logic
- All calls use `temperature=0.0` by default for deterministic-as-possible classification/tool-calling behavior; explanation-generation calls (RAG answer, quote explanation) may override with a small positive temperature (e.g., `0.3`), passed explicitly by the caller — this module does not choose temperature itself.
- Tool-calling loop pattern (used by the Orchestrator, Module 06): call `chat(messages, tools=[classify_intent_schema, ...])` → if `LLMResponse.tool_calls` is non-empty, the caller (not this module) decides what to do with each call — this module never executes a tool itself, it only relays the model's requested call back to the caller (separation from Module 10's Tool Executor, which does the executing).
- Structured output path: when `response_format` is provided (JSON schema), the request is sent using Ollama's `format` parameter; the response is validated against the schema before being returned — malformed JSON raises `LLMMalformedOutputError` rather than silently returning a string.

## 20. Validation Rules
- `messages` must contain exactly one `system` message (first position) — validated before the call, not left to Ollama to reject.
- If `response_format` is set, the returned content must parse as JSON and satisfy the given schema (checked with `jsonschema.validate` or Pydantic dynamic model construction) — failure raises rather than returning unvalidated text.

## 21. Error Handling
| Error | Handling |
|---|---|
| Ollama unreachable (connection refused) | Raise `LLMUnavailableError`; caller (e.g., Router) falls back per architecture §3 ("LLM fails to classify" — unchanged from v4: treat as low confidence, run clarification flow) |
| Timeout (> `LLM_TIMEOUT_SECONDS`) | Raise `LLMTimeoutError`; same fallback as above |
| Malformed JSON in structured-output mode | Raise `LLMMalformedOutputError`; caller treats as classification failure |
| Model returns tool call with arguments that don't match the declared schema | Raise `LLMMalformedOutputError` at this layer (schema-level check) — deeper semantic/business validation of arguments happens in Module 10, not here |

## 22. Logging Strategy
- Log every call at `DEBUG`: model name, message count, whether tools/response_format were used, latency — **never log full prompt/response content at this layer** (that's `conversation_turns`' job, populated by the caller who has the full context, not by this generic client).
- Log timeouts/failures at `WARNING` (expected/recoverable) vs `ERROR` (repeated failures suggesting Ollama is down).

## 23. Unit Tests
- `test_chat_requires_leading_system_message`
- `test_structured_output_validates_against_schema`
- `test_malformed_json_raises_llm_malformed_output_error`
- `test_tool_schema_builder_produces_valid_ollama_format`

## 24. Integration Tests
- `test_chat_roundtrip_against_local_ollama` (requires local Ollama with `qwen2.5:3b` pulled; skipped/marked if unavailable)
- `test_tool_calling_roundtrip_returns_tool_calls`
- `test_timeout_raises_llm_timeout_error` (simulate with a very low timeout override)

## 25. Configuration
```
ollama:
  host: str            # OLLAMA_HOST
  model: str           # OLLAMA_MODEL
  timeout_seconds: int = 30   # OLLAMA_TIMEOUT_SECONDS (defined in Module 00 and Module 01 Settings)
  default_temperature: float = 0.0
```

## 26. Environment Variables
`OLLAMA_HOST`, `OLLAMA_MODEL`, `OLLAMA_TIMEOUT_SECONDS` (all defined in Module 00 §1.1).

## 27. Sequence Diagram
```
Caller (Router / RAG / Quote / Clarification)
        │
        ▼
OllamaClient.chat(messages, tools?, response_format?, temperature)
        │
   asyncio.wait_for( POST {OLLAMA_HOST}/api/chat , timeout=30s )
        │
   ┌─── success ───┐          ┌─── failure ───┐
   ▼                          ▼
parse + validate          raise LLMTimeoutError /
   │                        LLMUnavailableError /
   ▼                        LLMMalformedOutputError
return LLMResponse
```

## 28. Request Lifecycle
In-process only — no HTTP endpoint of its own. Invoked as a step within a larger request lifecycle owned by Module 06 (Router) or Module 11/12/13.

## 29. Data Flow
Caller builds `messages` (using Prompt Manager, Module 08) → `OllamaClient.chat` → Ollama local server → `LLMResponse` → caller interprets `tool_calls`/`content` per its own logic (this module has no opinion on what the response *means*).

## 30. Example Workflow
1. Router builds `messages` = [system prompt (from Prompt Manager), conversation history, latest user message] plus `tools=[classify_intent_schema]`.
2. Calls `OllamaClient.chat(messages, tools=tools, response_format=None, temperature=0.0)`.
3. Receives `LLMResponse.tool_calls = [ToolCall(name="classify_intent", arguments={...})]`.
4. Router (not this module) parses `arguments` into an intent + confidence.

## 31. Future Extension Points
- Response caching for identical structured-output calls (e.g., repeated `classify_intent` calls with near-identical recent history) — explicitly deferred.
- Swapping `OLLAMA_HOST` to a remote/production endpoint requires no code change, only env var (mentioned here only as a design note; deployment itself is out of scope).

## 32. Completion Checklist
- [ ] `OllamaClient.chat` supports messages, tools, response_format, temperature
- [ ] Structured output validated against schema before return
- [ ] Timeout and unavailability produce distinct, catchable exceptions
- [ ] No prompt/response content logged at this layer (only at the caller/turns layer)
- [ ] Tests above pass

## 33. Hardening Update: Context Assembly and Tool-Calling Scope
The canonical Context Builder contract is Module 00 §7 and is implemented in this module as `app/llm/context.py`. Router, FactsExtractor, Clarification rewrite, Quote Explainer, and the built-in `respond` tool must call `build_llm_messages` before invoking `OllamaClient.chat`.

Tool calling in Module 05 is a transport capability only. It does not mean the LLM decides business tool execution. Business tools are emitted by Module 07 Planner and executed deterministically by Module 10 after policy checks. The `classify_intent` and `extract_facts` structured calls are classification/extraction contracts owned by Module 06, not executable business tools.
