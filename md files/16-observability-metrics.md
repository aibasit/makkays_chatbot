# Module 16 — Observability (Logs vs Metrics, Local)

## 1. Module Name
`observability` — `/metrics` endpoint with aggregated counters/gauges, explicitly separated from the per-turn Logs implemented in Module 04.

## 2. Goal
Implement the Metrics half of architecture §2.12's explicit Logs-vs-Metrics
split: aggregated, low-cardinality counters and gauges exposed at `/metrics`,
suitable for local trend-watching — without any production monitoring
infrastructure (no Prometheus server, no alerting, no external uptime monitor;
those are deployment-phase concerns excluded from this scope).

## 3. Purpose
Logs (Module 04) answer "what happened on this specific turn." Metrics answer
"how is the system trending over time" — latency percentiles, classification
confidence distribution, RAG hit rate, quote/CRM success rates. Conflating the
two (as v3/v4 implicitly did) makes both harder to use well.

## 4. Dependencies
Every module that produces a metric-worthy event (Modules 06, 10, 11, 12, 14) emits into this module's counters; this module itself only depends on Module 01 (app wiring).

## 5. Folder Structure
```
app/
├── observability/
│   ├── __init__.py
│   ├── registry.py
│   ├── router.py
│   └── schemas.py
tests/
├── unit/
│   └── test_metrics_registry.py
└── integration/
    └── test_metrics_endpoint.py
```

## 6. Files to Create
`registry.py`, `router.py`, `schemas.py`.

## 7. Responsibility of Every File
| File | Responsibility |
|---|---|
| `registry.py` | In-process counter/gauge/histogram registry (wraps `prometheus_client` library in its default in-memory mode — no external Prometheus server required, `/metrics` just exposes the text format for optional local scraping) |
| `router.py` | `GET /metrics`, `GET /health`, `GET /ready` |
| `schemas.py` | `ReadyResponse` (checks DB + Redis + Ollama reachability, distinct from the liveness-only `/health` in Module 01) |

## 8. Classes
- `MetricsRegistry` — thin wrapper exposing typed increment/observe methods so callers never touch `prometheus_client` directly:
  - `increment_intent_classification(source: str, intent: str)`
  - `increment_intent_classification(source: Literal['tier1','tier2'], intent: str)`
  - `record_intent_confidence(confidence: float)`
  - `increment_rag_hit(hit: bool)`
  - `increment_quote_result(success: bool)`
  - `increment_crm_sync_result(success: bool)`
  - `increment_lead_created()`
  - `observe_chat_latency(seconds: float)`

## 9. Data Models
None — metrics are in-memory counters, not persisted (matches architecture §2.12: "short/medium retention," appropriate for an in-process registry that resets on restart in local dev; a persistent metrics backend is a deployment-phase concern).

## 10. Pydantic Schemas
`ReadyResponse { status: Literal["ready","not_ready"], checks: dict[str, bool] }`.

## 11. Repository Layer
N/A.

## 12. Service Layer
`MetricsRegistry` methods (§8) are called inline by other modules at the relevant point in their own logic — e.g., Module 06's `Router.classify` calls `increment_intent_classification` and `record_intent_confidence` right after computing `IntentResult`; Module 11's `RetrievalService` calls `increment_rag_hit`; Module 12's `QuoteBuilder`/`QuoteExplainer` boundary calls `increment_quote_result`; Module 14's `RetryWorker` calls `increment_crm_sync_result`.

## 13. Internal Interfaces
- `MetricsRegistry` is a process-wide singleton — module-level instance created in `app/observability/registry.py` as `metrics_registry = MetricsRegistry()`. Other modules import it as `from app.observability.registry import metrics_registry`. No `Depends()` injection needed since metrics have no per-request state. **Test isolation**: in unit tests, modules under test should patch `app.observability.registry.metrics_registry` with a `MagicMock()` or a `FakeMetricsRegistry` that no-ops all calls — this prevents test runs from polluting the global Prometheus registry.
- `GET /metrics` returns `prometheus_client.generate_latest()` output — human/tool-readable Prometheus text format, consumable via `curl localhost:8000/metrics`.
- `GET /ready`: performs three checks (see §19), returns HTTP 200 with `status: "ready"` when all pass, HTTP 503 with `status: "not_ready"` and per-check detail when any fail. HTTP 503 is chosen so `curl -f` and load-balancer health gates work without parsing the response body.

## 14. Database Tables
None.

## 15. Redis Keys
None.

## 16. API Endpoints
| Method | Path | Purpose | Owner |
|---|---|---|---|
| GET | `/metrics` | Aggregated counters/gauges in Prometheus text format | This module (M16) |
| GET | `/ready` | Readiness check — DB + Redis + Ollama all reachable | This module (M16) |

Note: `GET /health` is owned exclusively by Module 01 (`main.py`). `POST /chat` is owned by Module 15. This module does not own or re-implement those endpoints.

## 17. Request Models
None (both are parameterless GETs).

## 18. Response Models
`/metrics`: raw Prometheus text (not JSON — standard for this format). `/ready`: `ReadyResponse`.

## 19. Business Logic
Metrics tracked, matching architecture §2.12's examples:
- `intent_classification_total{source, intent}` (counter)
- `intent_confidence_histogram` (histogram, track `confidence: float` observations per call, p50/p95 derivable from bucket data; bucket boundaries: `[0.0, 0.3, 0.5, 0.7, 0.9, 1.0]`)
- `rag_hit_total{hit}` (counter, "hit" = at least one result returned by Qdrant)
- `quote_result_total{success}` (counter)
- `crm_sync_result_total{success}` (counter)
- `lead_created_total` (counter)
- `chat_latency_seconds` (histogram, measured at Module 15 from request start to response end)

`/ready` performs three lightweight checks:
1. `SELECT 1` via the SQLAlchemy engine (DB check). Timeout: 2s.
2. Redis `PING` via the shared Redis client (Module 02). Timeout: 2s.
3. `GET {OLLAMA_HOST}/api/tags` — a cheap Ollama endpoint that lists loaded models, confirming the server is up without running a full inference call. Timeout: 3s.

All three must pass for `status: "ready"`. If any fails, `status: "not_ready"` with a `checks` dict `{"db": bool, "redis": bool, "ollama": bool}`. HTTP response code: **200** when ready, **503** when not ready.

## 20. Validation Rules
None (read-only endpoints, no user input).

## 21. Error Handling
| Error | Handling |
|---|---|
| One or more `/ready` checks fail | Returns `status: "not_ready"` with `checks: {db, redis, ollama}` booleans, **HTTP 503** (so `curl -f` and load-balancer checks fail automatically without parsing response body) |
| Metrics registry errors during scrape | Should not happen with `prometheus_client`'s in-memory registry; if it does, return 500 and log `ERROR` |

## 22. Logging Strategy
This module doesn't add new logging beyond what Module 04 already provides; it exists specifically to keep aggregated trend data **out** of the log stream, per the architecture's explicit separation. No log line should ever be a substitute for a metric here.

## 23. Unit Tests
- `test_metrics_registry_increment_and_read_back`
- `test_metrics_registry_confidence_histogram_buckets`
- `test_increment_lead_created_increments_correct_counter`
- `test_metrics_registry_is_no_op_when_patched_with_mock` (demonstrates test isolation pattern)
- `test_ready_returns_200_when_all_checks_pass`
- `test_ready_returns_503_when_db_unreachable`
- `test_ready_returns_503_when_redis_unreachable`
- `test_ready_returns_503_when_ollama_unreachable`

## 24. Integration Tests
- `test_metrics_endpoint_returns_prometheus_text_format`
- `test_ready_endpoint_all_checks_pass`
- `test_ready_endpoint_reports_not_ready_when_redis_down`
- `test_chat_request_increments_relevant_counters` (thin wiring check: call `/chat`, then assert `/metrics` output changed)

## 25. Configuration
No new settings beyond reusing DB/Redis/Ollama config already defined.

## 26. Environment Variables
None new.

## 27. Sequence Diagram
```
Any module event (e.g., Router.classify completes)
        │
        ▼
MetricsRegistry.increment_intent_classification(source, intent)
        │
   (in-memory counter incremented)

  ── separately, on demand ──
GET /metrics
        │
        ▼
prometheus_client.generate_latest()  → text response
```

## 28. Request Lifecycle
`/metrics` and `/ready` are simple, dependency-light GET endpoints; metric increments themselves happen inline within other modules' request lifecycles, not as a separate lifecycle of their own.

## 29. Data Flow
Every module → `MetricsRegistry` (in-memory) → `/metrics` text output, read locally by the developer (`curl`) or, later, an external scraper (out of scope to configure here).

## 30. Example Workflow
1. Developer runs a handful of test conversations locally.
2. `curl localhost:8000/metrics` shows `intent_classification_total{source="tier1",intent="sales_inquiry"} 4`, `rag_hit_total{hit="true"} 3`, etc.
3. `curl localhost:8000/ready` confirms all three dependencies are reachable before a demo.

## 31. Future Extension Points
- Persistent metrics backend + external uptime monitor + alerting — all explicitly deployment-phase, excluded from this scope per the person's instructions.
- Per-tenant metric labels once multi-tenancy goes live.

## 32. Completion Checklist
- [ ] `/metrics` exposes all six listed metric families
- [ ] `/ready` checks DB, Redis, and Ollama independently and reports per-check status
- [ ] No per-turn detail (prompts, tool call args) ever flows into a metric label (cardinality/privacy hazard) — only low-cardinality dimensions like `source`, `intent`, `success`
- [ ] Tests above pass

## 33. Hardening Update: Package Naming and Metrics Contract
The canonical package name is `app.observability`, not `app.metrics`. Metrics interfaces are listed in Module 00 §5, and allowed labels/logging boundaries are in Module 00 §14. Metrics must never include high-cardinality values such as raw messages, prompt text, session IDs as labels, contact info, or full tool arguments.

## 34. v4.2 Extension: New Metric Counters

The following counters are added to `MetricsRegistry` in `app/observability/registry.py`:

```python
# Product Intelligence (Module 18)
chatbot_comparison_requests_total = Counter(
    'chatbot_comparison_requests_total', 'Number of product comparisons executed',
    ['success']
)
chatbot_compatibility_checks_total = Counter(
    'chatbot_compatibility_checks_total', 'Number of compatibility checks executed',
    ['source', 'is_compatible']   # source: 'rule' | 'llm_inference'
)
chatbot_accessory_recommendations_total = Counter(
    'chatbot_accessory_recommendations_total', 'Number of accessory recommendation tool calls',
    ['success']
)

# Solution Builder (Module 19)
chatbot_solution_builds_total = Counter(
    'chatbot_solution_builds_total', 'Number of BOM solution builds completed',
    ['trigger']   # trigger: 'wizard' | 'use_case' | 'direct'
)
chatbot_wizard_sessions_total = Counter(
    'chatbot_wizard_sessions_total', 'Number of wizard sessions started',
    ['completed']   # 'true' | 'false'
)

# Human Handoff (Module 20)
chatbot_handoff_requests_total = Counter(
    'chatbot_handoff_requests_total', 'Number of human handoff requests initiated',
    ['target_team', 'status']   # target_team: 'sales' | 'technical' | 'support'
)

# Multi-language (Module 21)
chatbot_language_detection_total = Counter(
    'chatbot_language_detection_total', 'Number of language detections performed',
    ['detected_language']   # 'en' | 'ur' | 'ar'
)
chatbot_translation_requests_total = Counter(
    'chatbot_translation_requests_total', 'Number of response translations performed',
    ['target_language', 'success']
)

# Availability / ERP (Module 22)
chatbot_availability_checks_total = Counter(
    'chatbot_availability_checks_total', 'Number of product availability checks',
    ['source', 'in_stock']   # source: 'local_db' | 'mock' | 'erp'
)

# Quote PDF (Module 12 extension)
chatbot_quote_pdf_generated_total = Counter(
    'chatbot_quote_pdf_generated_total', 'Number of quote PDFs generated',
    ['success']
)
```

### MetricsRegistry Method Additions
```python
def increment_comparison_request(self, success: bool) -> None
def increment_compatibility_check(self, source: str, is_compatible: bool | None) -> None
def increment_accessory_recommendation(self, success: bool) -> None
def increment_solution_build(self, trigger: str) -> None
def increment_wizard_session(self, completed: bool) -> None
def increment_handoff_request(self, target_team: str, status: str) -> None
def increment_language_detection(self, detected_language: str) -> None
def increment_translation_request(self, target_language: str, success: bool) -> None
def increment_availability_check(self, source: str, in_stock: bool) -> None
def increment_quote_pdf_generated(self, success: bool) -> None
```

All new counters respect the existing cardinality rule: label values must come from a fixed low-cardinality set (no session IDs, no product names, no raw text as labels).
