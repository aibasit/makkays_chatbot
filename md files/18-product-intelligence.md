# Module 18 — Product Intelligence Service

## 1. Module Name
`product_intelligence` — Comparison, Compatibility, Accessories, Alternatives, NL Search, Spec Explainer.

## 2. Goal
Provide all product-knowledge-intensive capabilities that go beyond simple RAG retrieval: structured comparison, rule-based compatibility lookup, accessory cross-sell, alternative finding, natural-language-to-filter conversion, and terminology explanation. Each capability is a discrete service class with a tool registration in Module 10.

## 3. Purpose
Module 11 owns *retrieval*. Module 18 owns *intelligence* — the layer between raw retrieved product data and actionable answers. No business-intelligence logic leaks into Module 11 (retrieval concerns only) or Module 10 (execution concerns only).

## 4. Dependencies
Module 02 (DB), Module 05 (LLM — `LLMClientProtocol` for AI summary/explanation calls only), Module 09 (`FeatureFlags`), Module 10 (tool registrations), Module 11 (product retrieval, `RetrievalService`, `ProductRepository`, `FilterExtractor`), Module 16 (metrics).

## 5. Folder Structure
```
app/
├── product_intelligence/
│   ├── __init__.py
│   ├── comparison_service.py
│   ├── compatibility_service.py
│   ├── accessory_service.py
│   ├── alternative_service.py
│   ├── specification_service.py
│   ├── nl_search_service.py
│   ├── schemas.py
│   ├── models.py
│   ├── repository.py
│   └── exceptions.py
tests/
├── unit/
│   ├── test_comparison_service.py
│   ├── test_compatibility_service.py
│   ├── test_accessory_service.py
│   └── test_nl_search_service.py
└── integration/
    └── test_product_intelligence_tools.py
```

## 6. Files to Create
`comparison_service.py`, `compatibility_service.py`, `accessory_service.py`, `alternative_service.py`, `specification_service.py`, `nl_search_service.py`, `schemas.py`, `models.py`, `repository.py`, `exceptions.py`.

## 7. Responsibility of Every File
| File | Responsibility |
|---|---|
| `comparison_service.py` | `ComparisonService.compare(product_ids, tenant_id) -> ComparisonResult` |
| `compatibility_service.py` | `CompatibilityService.check(primary_id, secondary_id, type) -> CompatibilityResult` |
| `accessory_service.py` | `AccessoryService.recommend(product_id, tenant_id) -> list[AccessoryResult]` |
| `alternative_service.py` | `AlternativeService.find(product_id, tenant_id) -> list[ProductResult]` |
| `specification_service.py` | `SpecificationService.explain(spec_term, context_text) -> str` |
| `nl_search_service.py` | `NLSearchService.search(query, tenant_id) -> list[ProductResult]` |
| `schemas.py` | All output/input Pydantic schemas for this module |
| `models.py` | `CompatibilityRule`, `AccessoryRelation` ORM models |
| `repository.py` | `CompatibilityRepository`, `AccessoryRepository` database layers |
| `exceptions.py` | `ProductNotFoundError`, `CompatibilityRuleNotFoundError`, `InsufficientProductsForComparisonError` |

## 8. Classes

### `ComparisonService`
`async compare(product_ids: list[UUID], tenant_id: UUID, llm_client: LLMClientProtocol) -> ComparisonResult`:
1. Validate `len(product_ids) >= 2`, else raise `InsufficientProductsForComparisonError`.
2. Load each product's spec rows via `ProductSpecRepository.get_specs_for_products(product_ids, tenant_id)`.
3. Build a structured comparison table: `{spec_key: {product_id: spec_value}}` — keys are the union of all spec keys across products; missing values filled with `None`.
4. Call `LLMClientProtocol.chat([...], tools=[])` with a prompt asking the LLM to write a 2–3 sentence recommendation summary given the comparison table. LLM never modifies the comparison data, only narrates.
5. Return `ComparisonResult(products=..., comparison_table=..., ai_summary=...)`.

### `CompatibilityService`
`async check(primary_product_id: UUID, secondary_product_id: UUID, compatibility_type: str, tenant_id: UUID, llm_client: LLMClientProtocol) -> CompatibilityResult`:
1. Query `CompatibilityRepository.find(primary_id, secondary_id, compatibility_type, tenant_id)`.
2. If explicit rule found: return `CompatibilityResult(is_compatible=rule.is_compatible, source='rule', notes=rule.notes)`.
3. If no rule: load both products' specs, call LLM to infer compatibility from spec data. Mark `source='llm_inference'`.
4. Log `INFO` with source and result for auditability.

### `AccessoryService`
`async recommend(product_id: UUID, tenant_id: UUID) -> list[AccessoryResult]`:
1. Query `AccessoryRepository.find_accessories(product_id, tenant_id)` — returns explicit `accessory_relations` rows.
2. If fewer than 3 explicit accessories found, supplement with Qdrant vector similarity search scoped to same `category` and `tenant_id`.
3. Return up to 5 results, ranked explicit relations first.

### `AlternativeService`
`async find(product_id: UUID, tenant_id: UUID) -> list[ProductResult]`:
1. Load primary product's `category` and `brand` from `ProductRepository`.
2. SQL query: `products WHERE category = :category AND id != :product_id AND tenant_id = :tenant_id LIMIT 10`.
3. Re-rank by vector similarity (Qdrant search within same category) — top 5 returned.

### `SpecificationService`
`async explain(spec_term: str, context_text: str | None, llm_client: LLMClientProtocol) -> str`:
- Calls `LLMClientProtocol.chat` with a system prompt instructing the LLM to explain the networking/power terminology in plain language. `context_text` (optional doc chunk) is provided for grounding.
- Returns the explanation string only; no structured schema needed.

### `NLSearchService`
`async search(query: str, tenant_id: UUID) -> list[ProductResult]`:
- Delegates `FilterExtractor.extract(query, tenant_id)` (from Module 11) to convert natural language to `ExtractedFilters`.
- Calls `RetrievalService.retrieve_products` with the extracted filters.
- Returns the same `list[ProductResult]` — NL search is a thin orchestration wrapper over M11's layered retrieval.

## 9. Data Models

### `CompatibilityRule` (ORM, table `compatibility_rules`)
```sql
CREATE TABLE compatibility_rules (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant_id UUID NOT NULL,
  primary_product_id UUID NOT NULL REFERENCES products(id),
  secondary_product_id UUID NOT NULL REFERENCES products(id),
  compatibility_type TEXT NOT NULL,
  is_compatible BOOLEAN NOT NULL,
  notes TEXT,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX idx_compat_rules_lookup ON compatibility_rules (tenant_id, primary_product_id, compatibility_type);
```

### `AccessoryRelation` (ORM, table `accessory_relations`)
```sql
CREATE TABLE accessory_relations (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant_id UUID NOT NULL,
  primary_product_id UUID NOT NULL REFERENCES products(id),
  accessory_product_id UUID NOT NULL REFERENCES products(id),
  relation_type TEXT NOT NULL,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX idx_accessory_lookup ON accessory_relations (tenant_id, primary_product_id, relation_type);
```

## 10. Pydantic Schemas
```python
class ComparisonResult(BaseModel):
    products: list[ProductResult]
    comparison_table: dict[str, dict[str, str | None]]  # {spec_key: {product_id_str: value}}
    ai_summary: str

class CompatibilityResult(BaseModel):
    primary_product_id: UUID
    secondary_product_id: UUID
    compatibility_type: str
    is_compatible: bool
    source: Literal['rule', 'llm_inference']
    notes: str | None = None

class AccessoryResult(BaseModel):
    product_id: UUID
    name: str
    relation_type: str
    source: Literal['explicit', 'vector_similarity']
```

## 11. Repository Layer
- `CompatibilityRepository.find(primary_id, secondary_id, compat_type, tenant_id) -> CompatibilityRule | None`
- `CompatibilityRepository.create(tenant_id, data) -> CompatibilityRule`
- `AccessoryRepository.find_accessories(product_id, tenant_id) -> list[AccessoryRelation]`
- `AccessoryRepository.create(tenant_id, data) -> AccessoryRelation`
- `ProductSpecRepository.get_specs_for_products(product_ids, tenant_id) -> dict[UUID, list[ProductSpec]]`

## 12. Service Layer — Tool Wrappers
Each service is wrapped in a tool function registered in Module 10:

```python
# Registered in app/product_intelligence/__init__.py

async def compare_products_tool(session: SessionContext, context: ExecutionContext) -> ToolExecutionResult:
    product_ids = context.retrieve_products.product_ids or []
    result = await ComparisonService().compare(product_ids, session.tenant_id, llm_client)
    return ToolExecutionResult(step='compare_products', success=True, result_summary=result.model_dump_json())

async def check_compatibility_tool(session: SessionContext, context: ExecutionContext) -> ToolExecutionResult:
    product_ids = context.retrieve_products.product_ids or []
    if len(product_ids) < 2:
        return ToolExecutionResult(step='check_compatibility', success=False, result_summary='Need 2 products to check compatibility')
    compat_type = session.facts.spec_filters.get('compatibility_type', 'general')
    result = await CompatibilityService().check(product_ids[0], product_ids[1], compat_type, session.tenant_id, llm_client)
    return ToolExecutionResult(step='check_compatibility', success=True, result_summary=result.model_dump_json())

async def recommend_accessories_tool(session: SessionContext, context: ExecutionContext) -> ToolExecutionResult:
    product_ids = context.retrieve_products.product_ids or []
    if not product_ids:
        return ToolExecutionResult(step='recommend_accessories', success=False, result_summary='No product identified')
    results = await AccessoryService().recommend(product_ids[0], session.tenant_id)
    return ToolExecutionResult(step='recommend_accessories', success=True, result_summary=json.dumps([r.model_dump() for r in results]))

async def find_alternatives_tool(session: SessionContext, context: ExecutionContext) -> ToolExecutionResult:
    product_ids = context.retrieve_products.product_ids or []
    results = await AlternativeService().find(product_ids[0], session.tenant_id) if product_ids else []
    return ToolExecutionResult(step='find_alternatives', success=True, result_summary=json.dumps([r.model_dump() for r in results]))

async def explain_specification_tool(session: SessionContext, context: ExecutionContext) -> ToolExecutionResult:
    spec_term = session.facts.product_interest or session.conversation_state.last_question or ''
    doc_context = context.retrieve_docs.result_summary if context.retrieve_docs else None
    explanation = await SpecificationService().explain(spec_term, doc_context, llm_client)
    return ToolExecutionResult(step='explain_specification', success=True, result_summary=explanation)
```

**Tool registrations in `app/product_intelligence/__init__.py`:**
```python
ToolRegistry.register('compare_products', compare_products_tool)
ToolRegistry.register('check_compatibility', check_compatibility_tool)
ToolRegistry.register('recommend_accessories', recommend_accessories_tool)
ToolRegistry.register('find_alternatives', find_alternatives_tool)
ToolRegistry.register('explain_specification', explain_specification_tool)
```

## 13. Internal Interfaces
- All tools receive `(session: SessionContext, context: ExecutionContext)` — standard M10 tool signature.
- `NLSearchService.search` is called internally by `retrieve_products_tool` (Module 11) when `intent == 'product_finder_by_problem'`; it is not a separately registered tool step.
- `SpecificationService.explain` is never called with raw user input; it always receives the `spec_term` extracted from `session.facts.product_interest`.

## 14. Database Tables
`compatibility_rules` and `accessory_relations` — see §9 above.

## 15. Redis Keys
None. Results are transient per turn.

## 16. API Endpoints
None directly. All intelligence tools are invoked via `/chat` plan steps (Module 15). Admin seeding of compatibility rules and accessory relations is done via direct DB insert in local dev.

## 17. Request Models
N/A (internal tool calls).

## 18. Response Models
`ComparisonResult`, `CompatibilityResult`, `AccessoryResult` (see §10).

## 19. Business Logic
- **ComparisonService**: AI summary is generated from the structured comparison table, never from raw retrieval text. LLM is constrained to narration only.
- **CompatibilityService**: Explicit rules always take precedence over LLM inference. LLM inference is clearly marked `source='llm_inference'` in the response so the user can be informed this is an estimate.
- **AlternativeService**: Returns alternatives within the same product category only — never recommends products from unrelated categories.
- **NLSearchService**: Purely delegates to M11 retrieval — no business logic of its own.

## 20. Validation Rules
- `compare_products` requires at least 2 product IDs in `ExecutionContext.retrieve_products`.
- `check_compatibility` requires exactly 2 product IDs and a `compatibility_type` value from the allowed set: `['ups', 'battery', 'controller', 'sfp', 'rack']`.
- `find_alternatives` requires exactly 1 product ID — uses the first product if multiple exist.

## 21. Error Handling
| Error | Handling |
|---|---|
| `InsufficientProductsForComparisonError` | `ToolExecutionResult(success=False, result_summary='Cannot compare: fewer than 2 products found')` |
| LLM failure in `ComparisonService` | AI summary set to empty string; comparison table still returned |
| LLM failure in `CompatibilityService` | Fall back to `CompatibilityResult(is_compatible=None, source='llm_inference', notes='Unable to determine compatibility from available data')` |
| No accessories found | Return empty list; `respond` step generates a helpful "no accessories found" message |

## 22. Logging Strategy
- Log each tool call at `INFO` with `product_ids`, `tenant_id`, result count.
- Log LLM inference use for compatibility at `INFO` with `source='llm_inference'` to enable audit.

## 23. Unit Tests
- `test_comparison_builds_table_from_specs`
- `test_comparison_calls_llm_for_summary`
- `test_compatibility_returns_rule_if_found`
- `test_compatibility_falls_back_to_llm_when_no_rule`
- `test_accessory_supplements_with_vector_when_fewer_than_3_explicit`
- `test_alternative_finds_same_category_products`
- `test_nl_search_delegates_to_retrieval_service`

## 24. Integration Tests
- `test_compare_products_tool_end_to_end_with_orchestrator`
- `test_check_compatibility_tool_end_to_end`

## 25. Configuration
No new settings. Uses `settings.qdrant` (Module 01) for vector search and `settings.ollama` for LLM calls via the protocol interface.

## 26. Environment Variables
None new. Feature flags `ENABLE_PRODUCT_COMPARISON`, `ENABLE_COMPATIBILITY_CHECK`, `ENABLE_ACCESSORY_RECOMMENDATION` (Module 09).

## 27. Sequence Diagram
```
Orchestrator → ToolExecutor.execute_plan(['retrieve_products', 'compare_products', 'respond'])
                    │
                    ├─ retrieve_products → RetrievalService (M11) → product_ids in ExecutionContext
                    │
                    ├─ compare_products → ComparisonService.compare(product_ids, tenant_id)
                    │       ├─ ProductSpecRepository.get_specs_for_products(product_ids)
                    │       ├─ Build comparison table
                    │       └─ LLMClientProtocol.chat([...]) → ai_summary
                    │
                    └─ respond → LLM assembles final message from ComparisonResult
```

## 28. Request Lifecycle
Invoked via Tool Executor (Module 10) as part of a plan; never called directly by any HTTP endpoint.

## 29. Data Flow
`ExecutionContext.retrieve_products.product_ids` → `ComparisonService / CompatibilityService / AccessoryService` → `ToolExecutionResult` → `respond` step → `OrchestratorResult.assistant_message`.

## 30. Example Workflow
1. User: "Compare the Cisco SG350 and the TP-Link TL-SG3428"
2. Tier 1 matches `product_comparison`.
3. Planner: `['retrieve_products', 'compare_products', 'respond']`.
4. `retrieve_products` returns product IDs for both.
5. `compare_products` builds spec table and LLM summary.
6. `respond` presents a formatted comparison table + AI recommendation.

## 31. Future Extension Points
- Admin API endpoints for managing `compatibility_rules` and `accessory_relations` (currently seeded via SQL only).
- Confidence scores on `AccessoryResult` to rank recommendations by purchase correlation data.
- Bundle pricing extension using `QuoteBuilder` integration.

## 32. Completion Checklist
- [ ] `compatibility_rules` and `accessory_relations` tables created and seedable
- [ ] All 5 tool functions registered in `ToolRegistry`
- [ ] `ComparisonService` LLM summary is narration-only (no data modification)
- [ ] `CompatibilityService` explicit rule takes precedence over LLM
- [ ] Tests above pass
