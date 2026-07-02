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
Module 03 (Facts — quote slots), Module 09 (`ENABLE_QUOTES` flag), Module 10 (registered tool + policy), Module 11 (product data for pricing lookup).

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
| `models.py` | ORM model for `quotes` |
| `schemas.py` | `QuoteSlots`, `QuoteResult`, `QuoteLineItem` |
| `repository.py` | `QuoteRepository.create(...)`, `get(...)` |
| `builder.py` | `QuoteBuilder.build(facts, product_ids, tenant_id) -> QuoteResult` — the deterministic pricing calculation |

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
- `QuoteSlots { company: str, product_ids: list[UUID], quantity: int, budget: numeric }` — the validated, complete version of the four required Facts slots named in architecture §2.4/§2.14.
- `QuoteLineItem { product_id: UUID, name: str, unit_price: numeric, quantity: int, subtotal: numeric }`.
- `QuoteResult { quote_id: UUID, company: str, line_items: list[QuoteLineItem], total: numeric, currency: str }`.

## 11. Repository Layer
`QuoteRepository`:
- `async create(tenant_id, session_id, result: QuoteResult) -> Quote`
- `async get(tenant_id, quote_id) -> Quote | None`

`ProductPricingRepository.get_prices(tenant_id, product_ids) -> dict[UUID, Decimal]`.

## 12. Service Layer
`QuoteBuilder.build(tenant_id, session_id, facts: FactsSchema, product_ids: list[UUID]) -> QuoteResult`:
1. Validate `QuoteSlots` completeness (company, product_ids non-empty, quantity, budget) — raise `IncompleteQuoteSlotsError` if not (this should already have been gated by the Security Policy in Module 10, but the builder re-validates defensively rather than trusting the caller blindly).
2. `prices = ProductPricingRepository.get_prices(tenant_id, product_ids)`.
3. Compute `line_items` deterministically: `subtotal = unit_price * quantity` per product (v4.1 scope: quantity applies uniformly if a single aggregate quantity slot is used, per the Facts schema note in Module 07 §19 — a future extension allows per-product quantities).
4. `total = sum(subtotals)`.
5. Persist via `QuoteRepository.create`.
6. Return `QuoteResult`.

`QuoteExplainer.explain(quote_result: QuoteResult) -> str` — single LLM call (via Module 05) using the `tools/quote_explanation_v1.md` prompt (Module 08), given the already-final numbers as context; the prompt explicitly instructs the model to restate the given numbers, not recompute them.

## 13. Internal Interfaces
- Registered as Tool Executor (Module 10) step `generate_quote`, policy per architecture §2.14 example exactly (`allowed_intents: [sales_inquiry, quote_request]`, `required_state: [quote_slots_complete]`, `required_slots: [company, products, quantity, budget]`, `rate_limit: "5/min per session"`, `audit_log: true`).
- `quote_slots_complete` is a named predicate (referenced in the YAML, implemented in Module 10's `policy.py` predicate registry) that calls into this module's `QuoteSlots` validation logic — kept as a shared function so the Planner (Module 07), Policy (Module 10), and Builder (this module) never disagree about what "complete" means.

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
`ratelimit:{tenant_id}:{session_id}:generate_quote` — reused from Module 10's generic rate-limit key pattern, backing the `"5/min per session"` policy clause.

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
- Every `product_id` in `product_ids` must have a corresponding `product_pricing` row; missing pricing raises `MissingPricingError`, not a silent $0 line item.

## 21. Error Handling
| Error | Handling |
|---|---|
| Quote slots incomplete (defensive re-check fails) | Raise `IncompleteQuoteSlotsError`; Tool Executor records failed step; Orchestrator's `respond`/`request_missing_slots` step (already in the plan per Module 07's rules) explains what's missing via the template library (Module 13) |
| Missing pricing for a product | Raise `MissingPricingError`; step fails, logged at `ERROR` (a catalog data gap, worth fixing), quote not generated |
| DB write failure on `QuoteRepository.create` | Raise `ExternalServiceError`; step fails; no partial/inconsistent quote is returned to the user (all-or-nothing) |

## 22. Logging Strategy
- Log every quote build attempt at `INFO`: `tenant_id`, `session_id`, product count, total (total is business data, not a secret — safe to log, unlike raw PII in Facts).
- Log `MissingPricingError`/`IncompleteQuoteSlotsError` at `WARNING` (expected, recoverable via clarification) vs DB failures at `ERROR`.

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
