# Module 19 — Solution Builder & Recommendation Wizard

## 1. Module Name
`solution_builder` — Multi-turn recommendation wizard, use-case BOM generation, full Bill-of-Materials assembly.

## 2. Goal
Implement three related capabilities: a multi-turn wizard for guided product recommendation, a use-case profiler for deployment-scenario solutions, and a BOM generator that computes deterministic cost estimates. All three share a common `BOMService` computation layer.

## 3. Purpose
Product discovery (Module 11) answers "what product fits this query." Solution building answers "what complete set of products solves this deployment problem." BOM generation keeps all pricing deterministic — LLM never computes quantities or prices, only narrates the pre-computed solution.

## 4. Dependencies
Module 02 (DB), Module 03 (session state — wizard state reading), Module 05 (LLM — narration only via `LLMClientProtocol`), Module 09 (`FeatureFlags`), Module 10 (tool registrations), Module 11 (product retrieval), Module 12 (`product_pricing` table), Module 16 (metrics).

## 5. Folder Structure
```
app/
├── solution_builder/
│   ├── __init__.py
│   ├── wizard_service.py
│   ├── use_case_service.py
│   ├── bom_service.py
│   ├── solution_explainer.py
│   ├── schemas.py
│   ├── models.py
│   ├── repository.py
│   └── exceptions.py
tests/
├── unit/
│   ├── test_wizard_service.py
│   ├── test_use_case_service.py
│   └── test_bom_service.py
└── integration/
    └── test_solution_builder_wizard_multi_turn.py
```

## 6. Files to Create
`wizard_service.py`, `use_case_service.py`, `bom_service.py`, `solution_explainer.py`, `schemas.py`, `models.py`, `repository.py`, `exceptions.py`.

## 7. Responsibility of Every File
| File | Responsibility |
|---|---|
| `wizard_service.py` | `WizardService.advance(session, user_message) -> WizardStep` — multi-turn requirement collection |
| `use_case_service.py` | `UseCaseService.recommend(use_case, tenant_id) -> UseCaseSolution` — maps use-case to BOM |
| `bom_service.py` | `BOMService.build(requirements, tenant_id) -> Solution` — deterministic cost computation |
| `solution_explainer.py` | `SolutionExplainer.explain(solution, llm_client) -> str` — LLM narration only |
| `schemas.py` | `WizardStep`, `WizardRequirements`, `BOMLineItem`, `Solution`, `UseCaseSolution` |
| `models.py` | `WizardSession`, `Solution`, `UseCaseProfile` ORM models |
| `repository.py` | `WizardSessionRepository`, `SolutionRepository`, `UseCaseProfileRepository` |
| `exceptions.py` | `WizardAlreadyCompleteError`, `UseCaseNotFoundError`, `InsufficientProductDataError` |

## 8. Classes

### `WizardService`
Manages a 5-step requirement collection wizard. State is persisted to `wizard_sessions` table so each turn correctly advances to the next unanswered question.

```python
async def advance(session: SessionContext, user_message: str) -> WizardStep:
    """
    Loads current wizard state for (tenant_id, session_id).
    Records user's answer to the current step.
    If all required slots are filled, calls BOMService.build(requirements).
    Returns WizardStep containing: step_number, question_text, is_complete, solution (if complete).
    """
```

Wizard Questions (in order):
1. `use_case` — "What is the primary use case? (networking / power / surveillance / mixed)"
2. `device_count` — "How many devices or users need to be supported?"
3. `budget` — "What is your approximate budget in USD?"
4. `location` — "What is your location or preferred delivery region?"
5. `brand_preference` — "Do you have a preferred brand? (optional — press Enter to skip)"

When all 5 slots are filled: calls `BOMService.build(requirements, tenant_id)` and marks wizard session `completed=True`.

### `UseCaseService`
```python
async def recommend(use_case: str, tenant_id: UUID) -> UseCaseSolution:
    """
    1. Looks up UseCaseProfile for this use_case in use_case_profiles table.
    2. If found: uses the pre-defined requirements profile.
    3. Calls BOMService.build(requirements, tenant_id).
    4. Returns UseCaseSolution { use_case, solution, profile_used }.
    """
```

Default profiles seeded for: `school`, `hospital`, `office`, `data_center`, `cctv`, `enterprise`, `smb`.

### `BOMService`
```python
def build(requirements: WizardRequirements, tenant_id: UUID) -> Solution:
    """
    Pure deterministic function — no LLM, no async.
    1. Maps requirements to product categories via requirement → category mapping.
    2. SQL query: find products per category matching budget constraints.
    3. Join with product_pricing table to get unit prices.
    4. Compute quantities per category from device_count / standard ratios.
    5. Assemble BOMLineItem list with subtotals.
    6. Sum to total_estimate.
    7. Return Solution(line_items, total_estimate, currency='USD').
    """
```

This is a pure synchronous function called with `run_in_executor` if needed.

### `SolutionExplainer`
```python
async def explain(solution: Solution, llm_client: LLMClientProtocol) -> str:
    """
    Calls LLMClientProtocol.chat with the solution data and a narration prompt.
    LLM describes the solution in natural language — never modifies prices or quantities.
    """
```

## 9. Data Models

### `WizardSession` (ORM, table `wizard_sessions`)
```sql
CREATE TABLE wizard_sessions (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant_id UUID NOT NULL,
  session_id TEXT NOT NULL,
  current_step INTEGER NOT NULL DEFAULT 0,
  collected_requirements JSONB NOT NULL DEFAULT '{}',
  completed BOOLEAN NOT NULL DEFAULT false,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE UNIQUE INDEX idx_wizard_session ON wizard_sessions (tenant_id, session_id) WHERE completed = false;
```

### `UseCaseProfile` (ORM, table `use_case_profiles`)
```sql
CREATE TABLE use_case_profiles (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant_id UUID NOT NULL,
  use_case TEXT NOT NULL,
  requirements JSONB NOT NULL,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE UNIQUE INDEX idx_use_case_profile ON use_case_profiles (tenant_id, use_case);
```

### `Solution` (ORM, table `solutions`)
```sql
CREATE TABLE solutions (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant_id UUID NOT NULL,
  session_id TEXT NOT NULL,
  use_case TEXT,
  requirements JSONB NOT NULL,
  line_items JSONB NOT NULL,
  total_estimate NUMERIC(12,2),
  currency TEXT NOT NULL DEFAULT 'USD',
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
```

## 10. Pydantic Schemas
```python
class WizardRequirements(BaseModel):
    use_case: str | None = None
    device_count: int | None = None
    budget: Decimal | None = None
    location: str | None = None
    brand_preference: str | None = None

class WizardStep(BaseModel):
    step_number: int
    question_text: str | None = None
    is_complete: bool
    solution: 'Solution | None' = None

class BOMLineItem(BaseModel):
    category: str
    product_id: UUID
    product_name: str
    quantity: int
    unit_price: Decimal
    subtotal: Decimal

class Solution(BaseModel):
    solution_id: UUID
    use_case: str | None
    line_items: list[BOMLineItem]
    total_estimate: Decimal
    currency: str = 'USD'
    narration: str = ''

class UseCaseSolution(BaseModel):
    use_case: str
    solution: Solution
    profile_used: bool  # True if a pre-defined profile was matched
```

## 11. Repository Layer
- `WizardSessionRepository.get_active(tenant_id, session_id) -> WizardSession | None`
- `WizardSessionRepository.upsert(tenant_id, session_id, step, requirements, completed) -> WizardSession`
- `UseCaseProfileRepository.get(tenant_id, use_case) -> UseCaseProfile | None`
- `UseCaseProfileRepository.list_all(tenant_id) -> list[UseCaseProfile]`
- `SolutionRepository.create(tenant_id, session_id, solution: Solution) -> Solution`
- `SolutionRepository.get(tenant_id, solution_id) -> Solution | None`

## 12. Service Layer — Tool Wrappers

```python
async def run_wizard_tool(session: SessionContext, context: ExecutionContext) -> ToolExecutionResult:
    user_message = session.conversation_state.last_question or ''
    step = await WizardService().advance(session, user_message)
    return ToolExecutionResult(
        step='run_wizard',
        success=True,
        result_summary=step.model_dump_json(),
        # If wizard complete, embed solution for respond step to use
    )

async def build_use_case_solution_tool(session: SessionContext, context: ExecutionContext) -> ToolExecutionResult:
    use_case = session.facts.use_case or ''
    result = await UseCaseService().recommend(use_case, session.tenant_id)
    return ToolExecutionResult(step='build_use_case_solution', success=True, result_summary=result.model_dump_json())

async def build_solution_tool(session: SessionContext, context: ExecutionContext) -> ToolExecutionResult:
    requirements = WizardRequirements(
        use_case=session.facts.product_interest,
        device_count=session.facts.quantity,
        budget=session.facts.budget,
    )
    solution = BOMService().build(requirements, session.tenant_id)
    narration = await SolutionExplainer().explain(solution, llm_client)
    solution.narration = narration
    saved = await SolutionRepository(db).create(session.tenant_id, session.session_id, solution)
    return ToolExecutionResult(step='build_solution', success=True, result_summary=saved.model_dump_json())
```

**Tool registrations:**
```python
ToolRegistry.register('run_wizard', run_wizard_tool)
ToolRegistry.register('build_use_case_solution', build_use_case_solution_tool)
ToolRegistry.register('build_solution', build_solution_tool)
```

## 13. Internal Interfaces
- `WizardService.advance` always returns a `WizardStep`; callers must check `is_complete` to determine whether the wizard is still running or has produced a `Solution`.
- `BOMService.build` is synchronous (pure function). Called with `run_in_executor` if on the async event loop.
- `SolutionExplainer.explain` only narrates — never modifies `Solution.line_items` or `Solution.total_estimate`.

## 14. Database Tables
`wizard_sessions`, `use_case_profiles`, `solutions` — see §9.

## 15. Redis Keys
None. Wizard state is persisted to Postgres (durable across disconnects).

## 16. API Endpoints
None directly. Invoked via Tool Executor (Module 10). Future: `GET /solutions/{solution_id}` and `GET /solutions/{solution_id}/pdf` for saved solution retrieval.

## 17. Request Models
N/A (internal tool calls).

## 18. Response Models
`Solution`, `WizardStep`, `UseCaseSolution` (see §10).

## 19. Business Logic
- **BOM Calculation**: Category→quantity ratio table is seeded from business rules, e.g., `1 switch per 24 devices`, `1 UPS per 10 switches`. No LLM involvement.
- **Use-Case Profiles**: 7 default profiles are seeded by a DB migration seed script. Tenants can add custom profiles via direct DB insert.
- **Wizard Completion**: Wizard steps are always presented in fixed order. If user skips `brand_preference` (sends empty answer), the slot is marked `None` and the wizard advances.

## 20. Validation Rules
- `BOMService.build` raises `InsufficientProductDataError` if the tenant's `products` catalog has no products in a required category.
- `UseCaseService.recommend` raises `UseCaseNotFoundError` if neither a profile nor any product matches the use-case keyword.
- `WizardService.advance` raises `WizardAlreadyCompleteError` if called on a session where `wizard_sessions.completed = True`.

## 21. Error Handling
| Error | Handling |
|---|---|
| `InsufficientProductDataError` | `ToolExecutionResult(success=False, result_summary='Cannot build BOM: no products found for required categories')` |
| `UseCaseNotFoundError` | Fallback to `retrieve_products` with use-case as query string |
| `WizardAlreadyCompleteError` | Return the previously completed solution from DB without re-running |

## 22. Logging Strategy
- Log wizard step advancement at `INFO`: `step_number`, `session_id`, `is_complete`.
- Log BOM computation at `DEBUG`: `requirements`, `line_item_count`, `total_estimate`.
- Log use-case profile hit/miss at `INFO`.

## 23. Unit Tests
- `test_wizard_advances_step_on_each_turn`
- `test_wizard_marks_complete_when_all_slots_filled`
- `test_bom_builds_deterministic_line_items`
- `test_bom_raises_on_empty_catalog`
- `test_use_case_maps_school_to_requirements`
- `test_solution_explainer_never_modifies_totals`

## 24. Integration Tests
- `test_wizard_multi_turn_completes_bom_in_5_turns`
- `test_use_case_recommendation_end_to_end`

## 25. Configuration
No new settings. Uses `settings.ollama` (Module 01) for LLM narration.

## 26. Environment Variables
`ENABLE_SOLUTION_BUILDER`, `ENABLE_WIZARD`, `ENABLE_USE_CASE_RECOMMENDATION` (Module 09 flags).

## 27. Sequence Diagram
```
Turn 1–5 (wizard flow):
Orchestrator → run_wizard_tool
    │
    WizardService.advance(session, user_answer)
    │   ├─ Load WizardSession from DB
    │   ├─ Record answer to current_step
    │   ├─ Advance step counter
    │   └─ If step == 5: BOMService.build() → Solution → SolutionExplainer.explain()
    │
    └─ Return WizardStep(step_number, question or solution)
```

## 28. Request Lifecycle
Multi-turn: each turn calls `run_wizard_tool` once. State persists across turns in `wizard_sessions` table.

## 29. Data Flow
`session.conversation_state.last_question` (user answer) → `WizardService.advance` → `WizardSession` (DB write) → `BOMService.build` (on completion) → `Solution` (DB write) → `SolutionExplainer.explain` → `ToolExecutionResult.result_summary` → `respond` step → user.

## 30. Example Workflow
1. User: "Help me build a solution for my school network"
2. Intent: `product_recommendation_wizard`.
3. Planner: `['run_wizard', 'respond']`.
4. Turn 1: Wizard asks "What is the primary use case?" → User: "networking"
5. Turn 2: "How many devices?" → User: "200 devices"
6. Turn 3: "Budget?" → User: "$15,000"
7. Turn 4: "Location?" → User: "Karachi"
8. Turn 5: "Brand preference?" → User: "TP-Link"
9. BOM computed: 9× TL-SG3428 switches + 1× UPS + cabling → $12,480.
10. Solution narrated in natural language + total presented.

## 31. Future Extension Points
- PDF export of `Solution` (same pattern as Quote PDF in Module 12).
- Configurable BOM ratio tables via admin API.
- Integration with Module 22 Availability to show in-stock status per BOM line item.

## 32. Completion Checklist
- [ ] `wizard_sessions`, `use_case_profiles`, `solutions` tables created and seeded
- [ ] 7 default use-case profiles seeded via migration
- [ ] `BOMService.build` is pure/deterministic with zero LLM
- [ ] Wizard state persists correctly across session turns
- [ ] All 3 tools registered in `ToolRegistry`
- [ ] Tests above pass
