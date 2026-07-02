# Module 12 — Quote Builder

## 1. Module Name
`quote_builder` — Deterministic SQL-driven quote generation, LLM explains only.

## 2. Goal
Implement the `generate_quote` plan step: SQL → deterministic Quote Builder →
`quotes` table → LLM explains the result in natural language (never computes
pricing itself).

## 3. Purpose
Pricing must be deterministic and auditable — an LLM must never be trusted to
compute a dollar figure. This module keeps that boundary exactly as it was in
v3/v4 (unchanged per architecture §2.9), now triggered as an explicit plan step
gated by the Security Policy like any other tool.

## 4. Dependencies
Module 03 (Facts — quote slots including `quantity`, `company`, `product_interest`, `budget`), Module 05 (LLM — uses `LLMClientProtocol` protocol interface instead of concrete client), Module 08 (Prompt Manager — uses `PromptProvider` protocol interface), Module 09 (`ENABLE_QUOTES` flag), Module 10 (registered tool + policy), Module 11 (product data for pricing lookup — `product_pricing` has FK on `products.id`; **M11 migrations and seed data must be applied before M12's `product_pricing` migration and seed**), Module 16 (Observability & Metrics — quote builder metrics).

## 5. Folder Structure
```
app/
├── quotes/
│   ├── __init__.py
│   ├── models.py
│   ├── schemas.py
│   ├── repository.py
│   ├── builder.py
│   └── exceptions.py
tests/
├── unit/
│   └── test_quote_builder.py
└── integration/
    └── test_quote_generation_end_to_end.py
```

## 6. Files to Create
`models.py`, `schemas.py`, `repository.py`, `builder.py`, `exceptions.py`.

## 7. Responsibility of Every File
| File | Responsibility |
|---|---|
| `models.py` | ORM model for `quotes`, `ProductPricing` |
| `schemas.py` | `QuoteSlots`, `QuoteResult`, `QuoteLineItem` |
| `repository.py` | `QuoteRepository.create(...)`, `get(...)`, `ProductPricingRepository.get_prices(...)` |
| `builder.py` | `QuoteBuilder.build(session, context) -> QuoteResult` — the deterministic pricing calculation; `QuoteExplainer.explain(quote_result, llm_client: LLMClientProtocol, prompt_provider: PromptProvider) -> str` — the LLM narration call |
| `exceptions.py` | `IncompleteQuoteSlotsError`, `PricingDataMissingError` |

## 8. Classes
- `Quote` (ORM).
- `QuoteBuilder` — pure calculation class, no LLM call inside it.
- `QuoteRepository` — persistence.
- `QuoteExplainer` — the (separate, clearly-named) thin wrapper that hands the already-computed `QuoteResult` to the LLM purely to phrase a natural-language summary — never given the ability to alter numbers, only to narrate them.

## 9. Data Models
`Quote` (ORM, table `quotes`): `id: UUID`, `tenant_id: UUID`, `session_id: str`,
`company: str`, `line_items: JSONB` (list of `{product_id, name, unit_price, quantity, subtotal}`),
`total: numeric`, `currency: str = "USD"`, `created_at: timestamptz`.

`product_pricing` (ORM, table, extends Module 11's `products`): `product_id: UUID (fk)`,
`tenant_id: UUID`, `unit_price: numeric`, `currency: str`. *(Kept as a separate table
from `products` rather than a column on it, so pricing can be updated independently
of catalog/spec data without touching RAG ingestion.)*

## 10. Pydantic Schemas
- `QuoteSlots { company: str, product_ids: list[UUID], quantity: int, budget: Decimal }` — the validated, complete version of the four required Facts slots named in architecture §2.4/§2.14.
- `QuoteLineItem { product_id: UUID, name: str, unit_price: Decimal, quantity: int, subtotal: Decimal }`.
- `QuoteResult { quote_id: UUID, company: str, line_items: list[QuoteLineItem], total: Decimal, currency: str }`.

**`quote_slots_complete(facts: FactsSchema) -> bool`** — defined in **`app/quotes/schemas.py`**. This is the **single canonical implementation** owned by the Quote Builder module. Returns `True` if and only if `facts.company is not None and facts.product_interest is not None and facts.quantity is not None and facts.budget is not None`. Imported by:
- Module 07 (`app.quotes.schemas` → `quote_slots_complete`)
- Module 10 `policy.py` predicate registry (`'quote_slots_complete': quote_slots_complete`)
- `builder.py` in this module (defensive re-validation)

No other module may define a `quote_slots_complete` function. The import path is always `from app.quotes.schemas import quote_slots_complete`.

## 11. Repository Layer
`QuoteRepository`:
- `async create(tenant_id, session_id, result: QuoteResult) -> Quote`
- `async get(tenant_id, quote_id) -> Quote | None`

`ProductPricingRepository.get_prices(tenant_id, product_ids) -> dict[UUID, Decimal]`.

## 12. Service Layer
`QuoteBuilder.build(session: SessionContext, context: ExecutionContext) -> QuoteResult`:
1. Read `product_ids = context.get_product_ids()` from `ExecutionContext` (populated by prior `retrieve_products` step in the plan). If `None`, raise `IncompleteQuoteSlotsError('product_ids unavailable in ExecutionContext')`.
2. Validate `quote_slots_complete(session.facts)` — raise `IncompleteQuoteSlotsError` if not (belt-and-suspenders; this should already have been gated by the Security Policy in Module 10).
3. `prices = await ProductPricingRepository.get_prices(session.tenant_id, product_ids)` — returns `dict[UUID, Decimal]`. If any `product_id` has no price row, raise `PricingDataMissingError` with the list of missing IDs.
4. Compute `line_items` deterministically: `subtotal = unit_price * quantity` per product. `quantity` is a single integer from `session.facts.quantity` applied uniformly to all products (v4.1 documented limitation: one aggregate quantity, not per-product quantities).
5. `total = sum(item.subtotal for item in line_items)`.
6. Persist via `QuoteRepository.create(session.tenant_id, session.session_id, result)` — returns `Quote` ORM with a generated `quote_id`.
7. Call `MetricsRegistry.increment_quote_result(success=True)`. On any exception from steps 2–6, call `MetricsRegistry.increment_quote_result(success=False)` in the exception handler before re-raising.
8. Fire-and-forget: `asyncio.create_task(NotificationService.notify_quote_generated(quote_result))` from Module 14 — failure is swallowed and logged at `WARNING`, never re-raised.
9. Return `QuoteResult`.

`QuoteExplainer.explain(quote_result: QuoteResult, llm_client: LLMClientProtocol, prompt_provider: PromptProvider) -> str`:
```python
system_msg = ChatMessage(
    role="system",
    content=prompt_provider.get("quotes", "quote_explanation", "1")
)
user_msg = ChatMessage(
    role="user",
    content=f"Here is the computed quote:\n{quote_result.model_dump_json()}"
)
response = await llm_client.chat(
    messages=[system_msg, user_msg],
    temperature=0.3
)
return response.content
```
The system prompt instructs the LLM to restate the given numbers in natural language, never to recompute them. `response.content` is returned directly as the `result_summary` for the `generate_quote` `ToolExecutionResult`.

**Tool registration** (in `quotes/__init__.py`):
```python
ToolRegistry.register('generate_quote', QuoteBuilder.build)
```

**Interaction with `respond` step**: when `respond` follows `generate_quote` in the plan, the `respond` built-in tool checks `context.results.get('generate_quote')` and returns its `result_summary` directly as the `assistant_message`, without making an additional LLM call.

## 13. Internal Interfaces
- Registered as Tool Executor (Module 10) step `generate_quote`, policy: `allowed_intents: [sales_inquiry, quote_request]`, `required_state: [quote_slots_complete]`, `required_slots: [company, product_interest, quantity, budget]`, `rate_limit: "5/min"`, `audit_log: true`.
- `quote_slots_complete` is the single canonical predicate defined in **`app/quotes/schemas.py`** and imported by Module 07, Module 10, and this module.
- Tool function signature (required by Module 10's `ToolRegistry`): `async def generate_quote_tool(session: SessionContext, context: ExecutionContext) -> ToolExecutionResult` — implemented in `builder.py`, wraps `QuoteBuilder.build` and `QuoteExplainer.explain`, returns `ToolExecutionResult(step='generate_quote', success=True, result_summary=explanation_text, product_ids=None)`.
- **Pricing seed**: run `python scripts/seed_pricing.py --source pricing.json --tenant-id $DEFAULT_TENANT_ID` after M11's ingestion script. Input format: `[{"product_id": "<uuid>", "unit_price": 999.00, "currency": "USD"}]`. Must run after M11 products are ingested so FK constraints are satisfied.

## 14. Database Tables
```sql
CREATE TABLE quotes (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant_id UUID NOT NULL,
  session_id TEXT NOT NULL,
  company TEXT NOT NULL,
  line_items JSONB NOT NULL,
  total NUMERIC NOT NULL,
  currency TEXT NOT NULL DEFAULT 'USD',
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE TABLE product_pricing (
  product_id UUID NOT NULL REFERENCES products(id),
  tenant_id UUID NOT NULL,
  unit_price NUMERIC NOT NULL,
  currency TEXT NOT NULL DEFAULT 'USD',
  PRIMARY KEY (product_id, tenant_id)
);
```

## 15. Redis Keys
`rate_limit:tool:{tenant_id}:{session_id}:generate_quote` — reused from Module 10's generic rate-limit key pattern, backing the `"5/min per session"` policy clause.

## 16. API Endpoints
None public — invoked only via the `generate_quote` plan step inside `/chat` (Module 15). No standalone `/quotes` HTTP endpoint in v4.1 scope (no quote-retrieval UI beyond what's shown in the chat transcript).

## 17. Request Models
N/A (internal tool invocation).

## 18. Response Models
`QuoteResult`, folded into the LLM context for `QuoteExplainer` and into `ToolExecutionResult.result_summary`.

## 19. Business Logic
- **Hard separation of computation and narration**: `QuoteBuilder.build` never calls the LLM; `QuoteExplainer.explain` never touches pricing math — this is the one invariant this module exists to protect, matching architecture §2.9's "unchanged from v3/v4."
- **`generate_quote` plan step** in Module 10's executor calls `QuoteBuilder.build` first, then `QuoteExplainer.explain` on the result, and returns the explanation text as the step's contribution to the eventual `respond` output.

## 20. Validation Rules
- `quantity` must be a positive integer.
- `budget` (from Facts) is informational context passed to `QuoteExplainer` (e.g., "this fits within your stated budget") but never alters `unit_price` or `total` — budget is not a discount input in v4.1 scope.
- Every `product_id` in `product_ids` must have a corresponding `product_pricing` row; missing pricing raises `PricingDataMissingError`, not a silent $0 line item.

## 21. Error Handling
| Error | Handling |
|---|---|
| Quote slots incomplete (defensive re-check fails) | Raise `IncompleteQuoteSlotsError`; Tool Executor records failed step; Orchestrator's `respond`/`request_missing_slots` step (already in the plan per Module 07's rules) explains what's missing via the template library (Module 13) |
| Missing pricing for a product | Raise `PricingDataMissingError`; step fails, logged at `ERROR` (a catalog data gap, worth fixing), quote not generated |
| DB write failure on `QuoteRepository.create` | Raise `ExternalServiceError`; step fails; no partial/inconsistent quote is returned to the user (all-or-nothing) |

## 22. Logging Strategy
- Log every quote build attempt at `INFO`: `tenant_id`, `session_id`, product count, total (total is business data, not a secret — safe to log, unlike raw PII in Facts).
- Log `PricingDataMissingError`/`IncompleteQuoteSlotsError` at `WARNING` (expected, recoverable via clarification) vs DB failures at `ERROR`.

## 23. Unit Tests
- `test_quote_builder_computes_correct_subtotals_and_total`
- `test_quote_builder_raises_on_incomplete_slots`
- `test_quote_builder_raises_on_missing_pricing`
- `test_quote_explainer_never_recomputes_numbers` (assert the prompt template forbids/the explainer doesn't call any pricing function)

## 24. Integration Tests
- `test_generate_quote_step_end_to_end_via_tool_executor`
- `test_generate_quote_denied_when_slots_incomplete_via_security_policy`
- `test_generate_quote_rate_limited_after_five_calls_per_minute`

## 25. Configuration
No new settings — reuses DB/Redis config from Modules 01/02.

## 26. Environment Variables
None new.

## 27. Sequence Diagram
```
ToolExecutor step: generate_quote  (after Security Policy check passes)
        │
        ▼
QuoteBuilder.build(tenant_id, session_id, facts, product_ids)
        │
   ProductPricingRepository.get_prices(...)
        │
   compute line_items, total   (pure arithmetic, no LLM)
        │
   QuoteRepository.create(...)  → Postgres
        │
        ▼
   QuoteResult
        │
        ▼
QuoteExplainer.explain(QuoteResult)   (LLM call, narration only)
        │
        ▼
   explanation str  ──► folded into respond output
```

## 28. Request Lifecycle
Invoked once per turn when `generate_quote` is both in-plan and policy-allowed, as a step inside `ToolExecutor.execute_plan` (Module 10).

## 29. Data Flow
`Facts` (company, budget, product_interest) + `product_ids` (from `retrieve_products`) + `product_pricing` (Postgres) → `QuoteBuilder` → `quotes` table (Postgres) → `QuoteExplainer` (LLM) → user-facing text.

## 30. Example Workflow
1. Facts complete: `company="Acme Corp"`, `budget=50000`, `product_interest` resolved to two `product_id`s, `quantity=10`.
2. Planner includes `generate_quote`; Policy allows it.
3. `QuoteBuilder.build` computes `$450 × 10 = $4,500` per line, total `$9,000`.
4. `QuoteExplainer.explain` produces: "Based on 10 units each of the two switches you're considering, your total comes to $9,000 — well within your $50,000 budget."

## 31. Future Extension Points
- Per-line-item quantities (currently a single aggregate `quantity` slot applies uniformly).
- Discount rules / tiered pricing — explicitly not in v4.1 scope (deterministic flat pricing only).
- PDF quote export.

## 32. Completion Checklist
- [ ] `QuoteBuilder` performs all pricing math with zero LLM involvement
- [ ] `QuoteExplainer` only narrates, never recalculates
- [ ] `quote_slots_complete` predicate shared identically across Planner, Policy, and Builder
- [ ] Rate limit enforced per Security Policy
- [ ] Tests above pass

## 33. Hardening Update: Exception and Context Alignment
The canonical missing-pricing exception is `PricingDataMissingError`. Quote narration uses `quotes/quote_explanation_v1.md` and Module 05 `build_llm_messages(...)`, not ad hoc prompt construction. Quote unavailability follows the user-visible degradation contract in Module 00 §14.
