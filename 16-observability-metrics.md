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
├── metrics/
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
  - `record_intent_confidence(confidence: float)`
  - `increment_rag_hit(hit: bool)`
  - `increment_quote_result(success: bool)`
  - `increment_crm_sync_result(success: bool)`
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
- `MetricsRegistry` is a process-wide singleton (module-level instance), imported directly by other modules — no `Depends()` injection needed since metrics have no per-request state.
- `GET /metrics` returns `prometheus_client.generate_latest()` output — a human/tool-readable text format, consumable locally via `curl localhost:8000/metrics` even with no Prometheus server running.

## 14. Database Tables
None.

## 15. Redis Keys
None.

## 16. API Endpoints
| Method | Path | Purpose |
|---|---|---|
| GET | `/metrics` | Aggregated counters/gauges in Prometheus text format |
| GET | `/ready` | Readiness check — DB + Redis + Ollama all reachable |

## 17. Request Models
None (both are parameterless GETs).

## 18. Response Models
`/metrics`: raw Prometheus text (not JSON — standard for this format). `/ready`: `ReadyResponse`.

## 19. Business Logic
Metrics tracked, matching architecture §2.12's examples:
- `intent_classification_total{source, intent}` (counter)
- `intent_low_confidence_rate` (derived: track `intent_confidence_total` histogram, compute rate of sub-threshold observations)
- `rag_hit_total{hit}` (counter, "hit" = at least one result above a relevance floor)
- `quote_result_total{success}` (counter)
- `crm_sync_result_total{success}` (counter)
- `chat_latency_seconds` (histogram, p50/p95 derivable from bucket data)

`/ready` performs three lightweight checks: `SELECT 1` (DB), `PING` (Redis), a cheap Ollama `/api/tags` call (confirms the model server is up, without a full inference call) — all three must pass for `status: "ready"`.

## 20. Validation Rules
None (read-only endpoints, no user input).

## 21. Error Handling
| Error | Handling |
|---|---|
| One or more `/ready` checks fail | Returns `status: "not_ready"` with per-check detail, HTTP 200 (readiness endpoints conventionally return 200 with a status field, or optionally 503 — document the chosen convention and keep it consistent; recommend 503 when not ready, so a naive `curl -f` check works too) |
| Metrics registry somehow errors during scrape | Should not happen with `prometheus_client`'s in-memory registry; if it does, return 500 and log `ERROR` |

## 22. Logging Strategy
This module doesn't add new logging beyond what Module 04 already provides; it exists specifically to keep aggregated trend data **out** of the log stream, per the architecture's explicit separation. No log line should ever be a substitute for a metric here.

## 23. Unit Tests
- `test_metrics_registry_increment_and_read_back`
- `test_metrics_registry_confidence_histogram_buckets`

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
