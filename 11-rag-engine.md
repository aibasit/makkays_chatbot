# Module 11 — RAG Engine (Layered Retrieval: BGE-M3 + Qdrant)

## 1. Module Name
`rag_engine` — Structured-filter-first, SQL-narrowed, Qdrant-scoped retrieval.

## 2. Goal
Implement the layered retrieval pipeline: structured filter extraction → SQL
narrows candidate `product_id`/`doc_id` set → Qdrant search restricted to that
candidate set via payload filter — replacing v3/v4's flat unfiltered semantic
search.

## 3. Purpose
Flat semantic search over the whole corpus is slower and noisier than narrowing
by known structured attributes first (brand, port count, category) via SQL, then
only vector-searching within that narrowed set. This module implements both the
ingestion side (embedding + indexing products/docs) and the query side (layered
retrieval) as the two `retrieve_products` / `retrieve_docs` plan steps.

## 4. Dependencies
Module 01 (config — Qdrant/embedding settings), Module 02 (DB), Module 09 (feature flag `ENABLE_RAG`), Module 10 (registered as tools `retrieve_products`/`retrieve_docs`).

## 5. Folder Structure
```
app/
├── rag/
│   ├── __init__.py
│   ├── embeddings.py
│   ├── filter_extraction.py
│   ├── qdrant_client.py
│   ├── retrieval_service.py
│   ├── ingestion.py
│   ├── models.py
│   ├── schemas.py
│   └── exceptions.py
scripts/
└── ingest_products_and_docs.py     (local dev CLI script, run manually — no CI/automation per scope)
tests/
├── unit/
│   ├── test_filter_extraction.py
│   └── test_retrieval_service.py
└── integration/
    └── test_rag_end_to_end.py
```

## 6. Files to Create
`embeddings.py`, `filter_extraction.py`, `qdrant_client.py`, `retrieval_service.py`, `ingestion.py`, `models.py`, `schemas.py`, `exceptions.py`, `scripts/ingest_products_and_docs.py`.

## 7. Responsibility of Every File
| File | Responsibility |
|---|---|
| `embeddings.py` | `BgeM3Embedder.embed(texts: list[str]) -> list[list[float]]` wrapping the local BGE-M3 model |
| `filter_extraction.py` | Keyword/lookup-based extraction of structured filters (brand, category, spec values) from the raw query against known SQL vocabulary |
| `qdrant_client.py` | Thin wrapper over the Qdrant Cloud client — collection setup, upsert, filtered search |
| `retrieval_service.py` | `RetrievalService.retrieve_products(query, tenant_id) -> list[ProductResult]`, `.retrieve_docs(query, product_ids, tenant_id) -> list[DocResult]` |
| `ingestion.py` | Batch embed + upsert products/docs into Qdrant, called by the CLI script |
| `models.py` | ORM models for `products`, `product_specs`, `documents` (metadata tables; actual doc/product text embeddings live in Qdrant, not Postgres) |
| `schemas.py` | `ProductResult`, `DocResult`, `ExtractedFilters` |

## 8. Classes
- `BgeM3Embedder` — loads `BAAI/bge-m3` once at startup, `embed(texts) -> list[vector]`.
- `FilterExtractor` — `extract(query: str, tenant_id) -> ExtractedFilters` (brand, category, numeric spec matches like port count).
- `QdrantWrapper` — `search(collection, vector, filter, limit) -> list[ScoredPoint]`, `upsert(collection, points)`.
- `RetrievalService` — the two plan-step entrypoints, composing extraction → SQL narrowing → Qdrant search.
- `IngestionService` — `ingest_products()`, `ingest_documents()`.

## 9. Data Models
`Product` (ORM, table `products`): `id: UUID`, `tenant_id: UUID`, `name`, `brand`, `category`, `description`, `created_at`.
`ProductSpec` (ORM, table `product_specs`): `id: UUID`, `product_id: UUID (fk)`, `tenant_id: UUID`, `spec_key: str` (e.g. `"port_count"`), `spec_value: str`.
`Document` (ORM, table `documents`): `id: UUID`, `tenant_id: UUID`, `product_id: UUID (fk, nullable)`, `title`, `source_path`, `created_at`.

Qdrant collections (not SQL): `products_v1` (payload: `tenant_id, product_id, brand, category`), `documents_v1` (payload: `tenant_id, document_id, product_id`).

## 10. Pydantic Schemas
- `ExtractedFilters { brand: str | None, category: str | None, spec_filters: dict[str, str] }`.
- `ProductResult { product_id: UUID, name: str, brand: str, score: float }`.
- `DocResult { document_id: UUID, title: str, chunk_text: str, score: float }`.

## 11. Repository Layer
- `ProductRepository.find_by_filters(tenant_id, filters: ExtractedFilters) -> list[UUID]` — SQL narrowing step (the "SQL narrows candidate product_id set" layer).
- `DocumentRepository.find_by_product_ids(tenant_id, product_ids) -> list[UUID]`.

## 12. Service Layer
`RetrievalService.retrieve_products(query, tenant_id)`:
1. `filters = FilterExtractor.extract(query, tenant_id)`.
2. `candidate_ids = ProductRepository.find_by_filters(tenant_id, filters)` — if extraction found nothing, `candidate_ids` is `None` (no SQL narrowing, full-tenant Qdrant search as fallback).
3. `vector = BgeM3Embedder.embed([query])[0]`.
4. `results = QdrantWrapper.search("products_v1", vector, filter={"tenant_id": tenant_id, "product_id": {"in": candidate_ids}} if candidate_ids else {"tenant_id": tenant_id}, limit=5)`.
5. Map to `ProductResult` list, return.

`RetrievalService.retrieve_docs(query, product_ids, tenant_id)` — same pattern, scoped Qdrant search restricted to `documents_v1` payloads matching `product_id in product_ids` (from the already-narrowed product set found by `retrieve_products` earlier in the same plan — this is the "layered" part: doc retrieval reuses product retrieval's narrowing rather than re-deriving filters from scratch).

## 13. Internal Interfaces
- Registered as two Tool Executor (Module 10) tools: `retrieve_products`, `retrieve_docs`, each with a Security Policy YAML (`allowed_intents: [sales_inquiry, quote_request]`, no required slots, `audit_log: false` — read-only, non-sensitive).
- `RetrievalService` methods are the only public entrypoints; `FilterExtractor`/`QdrantWrapper`/`BgeM3Embedder` are internal collaborators.

## 14. Database Tables
```sql
CREATE TABLE products (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant_id UUID NOT NULL,
  name TEXT NOT NULL,
  brand TEXT,
  category TEXT,
  description TEXT,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE TABLE product_specs (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  product_id UUID NOT NULL REFERENCES products(id),
  tenant_id UUID NOT NULL,
  spec_key TEXT NOT NULL,
  spec_value TEXT NOT NULL
);
CREATE TABLE documents (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant_id UUID NOT NULL,
  product_id UUID REFERENCES products(id),
  title TEXT NOT NULL,
  source_path TEXT NOT NULL,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX idx_product_specs_lookup ON product_specs (tenant_id, spec_key, spec_value);
```

## 15. Redis Keys
| Key Pattern | TTL | Purpose |
|---|---|---|
| `rag:filters:{tenant_id}:{query_hash}` | 5 min | Optional cache of `ExtractedFilters` for repeated/near-identical queries within a session — listed as an optimization, not required for v4.1 correctness |

## 16. API Endpoints
None public — exposed only as Tool Executor steps. (No `/rag/search` HTTP endpoint in v4.1 scope; the frontend never queries RAG directly, only through `/chat`.)

## 17. Request Models
N/A (internal tool invocation, not HTTP).

## 18. Response Models
`ProductResult`, `DocResult` lists, folded into the LLM's context for the `respond`/`compare` steps and into `ToolExecutionResult.result_summary` for `conversation_turns.tool_calls`.

## 19. Business Logic
- **Filter extraction is keyword/lookup, not an LLM call** — matches known `brand`/`category` values (loaded once from `products` at startup into an in-memory lookup set) and simple numeric-spec regexes (e.g., `r"(\d+)[- ]?port"` for port count) against `product_specs.spec_key = 'port_count'`. This keeps retrieval fast and deterministic — no LLM round-trip needed just to parse "48-port Cisco."
- **SQL narrowing before Qdrant**: if filters extracted zero candidates matching known SQL values (i.e., no brand/spec matched anything), retrieval falls back to unscoped semantic search (same as v3) rather than returning zero results — this is a deliberate fallback, not a bug.
- **Doc retrieval reuses product narrowing**: `retrieve_docs`, when it runs after `retrieve_products` in the same plan, is passed the already-found `product_ids` rather than re-running filter extraction — enforced by the Tool Executor passing prior step results forward as context to later steps in the same plan.

## 20. Validation Rules
- `query` must be non-empty after trimming.
- Qdrant search `limit` capped at a configured max (default 10) regardless of caller input, to bound LLM context size.

## 21. Error Handling
| Error | Handling |
|---|---|
| Qdrant unreachable | Raise `ExternalServiceError`, caught by Tool Executor, recorded as a failed step (`ToolExecutionResult(success=False)`), turn continues degraded (architecture §3: "Qdrant unreachable" — unchanged handling from v3/v4) |
| Embedding model fails to load at startup | Fail fast at app startup (RAG is a core capability when `ENABLE_RAG=true`; if the flag is `false`, embedder is never loaded, saving local memory) |
| Filter extraction finds conflicting values (e.g., two brands mentioned) | Use the first match, log `DEBUG` — this is a heuristic layer, not expected to be perfect; final relevance is still Qdrant's job |

## 22. Logging Strategy
- Log extracted filters and candidate count at `DEBUG` per retrieval call.
- Log Qdrant search latency and result count at `DEBUG`.
- Log Qdrant/embedding failures at `ERROR`.

## 23. Unit Tests
- `test_filter_extraction_finds_brand_and_port_count`
- `test_filter_extraction_returns_empty_when_no_match`
- `test_retrieval_service_falls_back_to_unscoped_search_when_no_filters_match`
- `test_retrieve_docs_reuses_product_ids_from_prior_step`

## 24. Integration Tests
- `test_ingestion_and_retrieval_roundtrip` — ingest a fixture product set, query, assert expected product ranks first.
- `test_layered_retrieval_narrower_than_unscoped` — assert scoped search returns fewer, more relevant results than a deliberately unscoped baseline call.
- `test_rag_end_to_end_via_tool_executor` — full path from plan step to `ProductResult`.

## 25. Configuration
```
rag:
  embedding_model: str = "BAAI/bge-m3"
  qdrant_collection_products: str = "products_v1"
  qdrant_collection_documents: str = "documents_v1"
  search_limit_default: int = 5
  search_limit_max: int = 10
```

## 26. Environment Variables
`QDRANT_URL`, `QDRANT_API_KEY`, `EMBEDDING_MODEL` (already defined in Module 00).

## 27. Sequence Diagram
```
ToolExecutor step: retrieve_products
        │
        ▼
RetrievalService.retrieve_products(query, tenant_id)
        │
   FilterExtractor.extract(query)  →  ExtractedFilters
        │
   ProductRepository.find_by_filters(...)  →  candidate_ids (Postgres)
        │
   BgeM3Embedder.embed([query])  →  vector
        │
   QdrantWrapper.search("products_v1", vector, filter={tenant_id, product_id in candidate_ids}, limit=5)
        │
        ▼
   list[ProductResult]
```

## 28. Request Lifecycle
Invoked once (sometimes twice, for `retrieve_products` then `retrieve_docs`) per turn, as steps within `ToolExecutor.execute_plan` (Module 10).

## 29. Data Flow
`products`/`product_specs`/`documents` (Postgres, source of truth for structured attributes) + Qdrant (`products_v1`/`documents_v1`, vector index, kept in sync via `ingestion.py`) → `RetrievalService` → `ProductResult`/`DocResult` → LLM context (via Prompt Manager's `rag/context_v1.md` template, Module 08) → `respond`/`compare` steps.

## 30. Example Workflow
Matches architecture §2.6 example exactly: query *"48-port Cisco PoE switch"* → `FilterExtractor` finds `brand=Cisco`, `port_count=48` → `ProductRepository.find_by_filters` narrows to matching `product_id`s in Postgres → `QdrantWrapper.search` restricted to that set → ranked, relevant results returned, faster and more precise than v3's unfiltered-then-tagged approach.

## 31. Future Extension Points
- Reranker (`bge-reranker-large`) — explicitly deferred per architecture §2.6 and Build Order closing note ("Reranking ... remain explicitly deferred").
- Percentage-based staged rollout of RAG via Module 09's flag rollout extension.

## 32. Completion Checklist
- [ ] `products`/`product_specs`/`documents` tables created and seedable
- [ ] Qdrant collections created with correct payload schema (`tenant_id` on every point)
- [ ] Filter extraction is deterministic, not an LLM call
- [ ] SQL narrows before Qdrant search; unscoped fallback works when no filters match
- [ ] `retrieve_docs` reuses `retrieve_products`' candidate set within the same plan
- [ ] Tests above pass
