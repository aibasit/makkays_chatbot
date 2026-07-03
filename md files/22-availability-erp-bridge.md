# Module 22 — Availability & ERP Bridge

## 1. Module Name
`availability` — Product stock/availability checking via a mock-then-real switchable service interface. ERP integration stub.

## 2. Goal
Implement the `check_availability` tool step using a PEP 544 structural protocol interface that allows switching from a local mock implementation to a real ERP HTTP adapter without changing any other module.

## 3. Purpose
The same architecture pattern as the Mock CRM (Module 14): define a `Protocol` interface first, implement a local mock backed by a simple database table, and document exactly where to swap in a real ERP client later. No business logic in any other module should reference the concrete implementation.

## 4. Dependencies
Module 01 (config — `settings.availability`, `AVAILABILITY_PROVIDER`, `ERP_API_BASE_URL`, `ERP_API_KEY`), Module 02 (DB), Module 09 (`FeatureFlags.enable_availability_check`), Module 10 (tool registration), Module 16 (metrics).

## 5. Folder Structure
```
app/
├── availability/
│   ├── __init__.py
│   ├── interfaces.py        # AvailabilityService Protocol
│   ├── local_service.py     # LocalAvailabilityService (mock, DB-backed)
│   ├── erp_client.py        # ERPAvailabilityService stub
│   ├── dependencies.py      # Factory / DI provider
│   ├── schemas.py
│   ├── models.py
│   ├── repository.py
│   └── exceptions.py
tests/
├── unit/
│   └── test_local_availability_service.py
└── integration/
    └── test_check_availability_tool.py
```

## 6. Files to Create
`interfaces.py`, `local_service.py`, `erp_client.py`, `dependencies.py`, `schemas.py`, `models.py`, `repository.py`, `exceptions.py`.

## 7. Responsibility of Every File
| File | Responsibility |
|---|---|
| `interfaces.py` | `AvailabilityService(Protocol)` — structural interface only |
| `local_service.py` | `LocalAvailabilityService` — reads from `product_availability` table |
| `erp_client.py` | `ERPAvailabilityService` — HTTP client stub (raises `NotImplementedError`) |
| `dependencies.py` | `get_availability_service() -> AvailabilityService` — factory based on `AVAILABILITY_PROVIDER` |
| `schemas.py` | `AvailabilityResult`, `AvailabilityBatchResult` |
| `models.py` | `ProductAvailability` ORM model |
| `repository.py` | `AvailabilityRepository` |
| `exceptions.py` | `AvailabilityCheckError`, `ERPConnectionError` |

## 8. Classes

### `AvailabilityService` (Protocol — `interfaces.py`)
```python
from typing import Protocol
from uuid import UUID

class AvailabilityService(Protocol):
    async def check(
        self,
        product_id: UUID,
        tenant_id: UUID,
    ) -> 'AvailabilityResult': ...

    async def check_batch(
        self,
        product_ids: list[UUID],
        tenant_id: UUID,
    ) -> 'list[AvailabilityResult]': ...
```

### `LocalAvailabilityService` (`local_service.py`)
```python
class LocalAvailabilityService:
    def __init__(self, db: AsyncSession):
        self._repo = AvailabilityRepository(db)

    async def check(self, product_id: UUID, tenant_id: UUID) -> AvailabilityResult:
        row = await self._repo.get(product_id, tenant_id)
        if row is None:
            return AvailabilityResult(
                product_id=product_id,
                in_stock=True,
                quantity=99,
                source='mock',
                note='No availability data — using default mock values',
            )
        return AvailabilityResult(
            product_id=row.product_id,
            in_stock=row.quantity > 0,
            quantity=row.quantity,
            estimated_delivery_days=row.estimated_delivery_days,
            source='local_db',
        )

    async def check_batch(
        self,
        product_ids: list[UUID],
        tenant_id: UUID,
    ) -> list[AvailabilityResult]:
        return [await self.check(pid, tenant_id) for pid in product_ids]
```

### `ERPAvailabilityService` (`erp_client.py`)
Stub implementation. Raises `NotImplementedError` with a message pointing to the ERP documentation.
```python
class ERPAvailabilityService:
    """
    Placeholder for real ERP integration.
    To implement: configure ERP_API_BASE_URL and ERP_API_KEY in .env,
    then implement this class to call the ERP's stock/availability endpoint.
    See ERP vendor documentation for exact API contract.
    """
    async def check(self, product_id: UUID, tenant_id: UUID) -> AvailabilityResult:
        raise NotImplementedError(
            'ERPAvailabilityService is not implemented. '
            'Set AVAILABILITY_PROVIDER=local or implement the ERP client.'
        )

    async def check_batch(self, product_ids: list[UUID], tenant_id: UUID) -> list[AvailabilityResult]:
        raise NotImplementedError(...)
```

### `get_availability_service()` (`dependencies.py`)
```python
def get_availability_service(
    db: AsyncSession = Depends(get_db),
) -> AvailabilityService:
    provider = settings.availability.provider  # 'local' | 'erp'
    if provider == 'local':
        return LocalAvailabilityService(db)
    elif provider == 'erp':
        return ERPAvailabilityService()
    else:
        raise ValueError(f'Unknown AVAILABILITY_PROVIDER: {provider}')
```

## 9. Data Models

### `ProductAvailability` (ORM, table `product_availability`)
```sql
CREATE TABLE product_availability (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant_id UUID NOT NULL,
  product_id UUID NOT NULL REFERENCES products(id),
  quantity INTEGER NOT NULL DEFAULT 0,
  in_stock BOOLEAN GENERATED ALWAYS AS (quantity > 0) STORED,
  estimated_delivery_days INTEGER,
  last_updated TIMESTAMPTZ NOT NULL DEFAULT now(),
  source TEXT NOT NULL DEFAULT 'manual',
  UNIQUE (tenant_id, product_id)
);
```

This table is updated manually in local dev (or via ERP sync script in production). No real-time sync in v4.2.

## 10. Pydantic Schemas
```python
class AvailabilityResult(BaseModel):
    product_id: UUID
    in_stock: bool
    quantity: int
    estimated_delivery_days: int | None = None
    source: Literal['local_db', 'mock', 'erp'] = 'local_db'
    note: str | None = None

class AvailabilityBatchResult(BaseModel):
    results: list[AvailabilityResult]
    checked_at: datetime
```

## 11. Repository Layer
```python
class AvailabilityRepository:
    async def get(self, product_id: UUID, tenant_id: UUID) -> ProductAvailability | None
    async def upsert(self, tenant_id: UUID, product_id: UUID, quantity: int, delivery_days: int | None) -> ProductAvailability
    async def get_batch(self, product_ids: list[UUID], tenant_id: UUID) -> list[ProductAvailability]
```

## 12. Service Layer — Tool Wrapper
```python
async def check_availability_tool(
    session: SessionContext,
    context: ExecutionContext,
    availability_service: AvailabilityService = Depends(get_availability_service),
) -> ToolExecutionResult:
    product_ids = context.retrieve_products.product_ids if context.retrieve_products else []
    if not product_ids:
        # Fall back to facts product interest as a product name search
        return ToolExecutionResult(
            step='check_availability',
            success=False,
            result_summary='No product identified to check availability for',
        )
    results = await availability_service.check_batch(product_ids, session.tenant_id)
    batch = AvailabilityBatchResult(results=results, checked_at=datetime.utcnow())
    return ToolExecutionResult(
        step='check_availability',
        success=True,
        result_summary=batch.model_dump_json(),
    )
```

**Tool registration:**
```python
ToolRegistry.register('check_availability', check_availability_tool)
```

## 13. Internal Interfaces
- `AvailabilityService` protocol is satisfied by both `LocalAvailabilityService` and any future `ERPAvailabilityService`.
- The tool executor never imports `LocalAvailabilityService` directly — it receives the resolved `AvailabilityService` through FastAPI's DI system.
- No other module imports from `app.availability` except Module 10 (tool registration).

## 14. Database Tables
`product_availability` — see §9. Seeded manually for local dev.

## 15. Redis Keys
None. Availability data is fetched fresh from DB (or ERP) per turn. For production ERP use, a short TTL Redis cache could be added here as a future extension.

## 16. API Endpoints
`GET /products/{product_id}/availability` (owned by Module 15):
```
GET /products/{product_id}/availability?tenant_id=...
Response: AvailabilityResult
```
This endpoint bypasses the chat pipeline and allows the frontend to check availability outside of a conversation turn.

## 17. Request Models
`AvailabilityCheckRequest { product_id: UUID }` (for direct API use).

## 18. Response Models
`AvailabilityResult`, `AvailabilityBatchResult` (see §10).

## 19. Business Logic
- **Local mock default**: When `AVAILABILITY_PROVIDER=local`, all products not in `product_availability` return `in_stock=True, quantity=99`. This is explicitly a development convenience.
- **ERP swap**: Switching to `AVAILABILITY_PROVIDER=erp` requires only implementing `ERPAvailabilityService` class and setting the env vars. No other code changes needed.
- **Batch check**: All product IDs from `ExecutionContext.retrieve_products` are checked in one batch call to minimize round trips.

## 20. Validation Rules
- `AVAILABILITY_PROVIDER` must be `'local'` or `'erp'`. Startup validation in Module 01 `AvailabilitySettings`.
- `quantity` in `product_availability` must be `>= 0`. Negative values rejected at upsert.

## 21. Error Handling
| Error | Handling |
|---|---|
| `ERPConnectionError` | `ToolExecutionResult(success=False, result_summary='Availability check temporarily unavailable')` |
| Product not in `product_availability` table | Return mock `AvailabilityResult(in_stock=True, quantity=99, source='mock')` |
| `NotImplementedError` from ERP stub | Log at `ERROR`, return graceful fallback |

## 22. Logging Strategy
- Log each availability check at `DEBUG`: `product_id`, `source`, `in_stock`, `quantity`.
- Log mock fallback at `DEBUG` (not WARNING — expected behavior in local dev).
- Log ERP connection errors at `ERROR`.

## 23. Unit Tests
- `test_local_service_returns_from_db_when_found`
- `test_local_service_returns_mock_when_not_found`
- `test_batch_check_returns_result_per_product`
- `test_factory_returns_local_service_for_local_provider`
- `test_factory_raises_on_invalid_provider`

## 24. Integration Tests
- `test_check_availability_tool_end_to_end`
- `test_availability_api_endpoint_returns_correct_result`

## 25. Configuration
```python
class AvailabilitySettings(BaseModel):
    provider: Literal['local', 'erp'] = 'local'
    erp_api_base_url: str = ''
    erp_api_key: str = ''
```
Added to `Settings` in Module 01.

## 26. Environment Variables
```env
AVAILABILITY_PROVIDER=local
ERP_API_BASE_URL=
ERP_API_KEY=
ENABLE_AVAILABILITY_CHECK=false
```

`ENABLE_AVAILABILITY_CHECK=false` by default. Set to `true` only when ERP is configured or local stock data is seeded.

## 27. Sequence Diagram
```
Orchestrator → ToolExecutor → check_availability_tool(session, context, availability_service)
    │
    ├─ product_ids = context.retrieve_products.product_ids
    │
    ├─ AvailabilityService.check_batch(product_ids, tenant_id)
    │       [LocalAvailabilityService]
    │       ├─ AvailabilityRepository.get_batch(product_ids, tenant_id)
    │       └─ Return AvailabilityResult per product (mock if not found)
    │
    └─ ToolExecutionResult(step='check_availability', result_summary=batch_json)
           │
           ▼
        respond step → "The X200 is in stock (99 units available). Estimated delivery: 3–5 days."
```

## 28. Request Lifecycle
Single tool call per turn. No multi-turn state. Availability data is queried fresh every turn.

## 29. Data Flow
`ExecutionContext.retrieve_products.product_ids` → `AvailabilityService.check_batch` → `product_availability` table (or ERP) → `AvailabilityBatchResult` → `ToolExecutionResult` → `respond` step → user.

## 30. Example Workflow
1. User: "Is the X200 switch in stock?"
2. Intent: `availability_inquiry`.
3. Planner: `['retrieve_products', 'check_availability', 'respond']`.
4. `retrieve_products` → product_id for X200.
5. `check_availability` → `AvailabilityResult(in_stock=True, quantity=15, estimated_delivery_days=3)`.
6. `respond` → "Yes, the X200 is in stock with 15 units available. Estimated delivery: 3 business days."

## 31. Future Extension Points
- Real ERP integration (implement `ERPAvailabilityService`; set `AVAILABILITY_PROVIDER=erp`).
- Redis TTL cache for availability data to reduce ERP API calls.
- Inventory webhook to update `product_availability` table automatically when ERP stock changes.
- Low-stock alert: if `quantity < 5`, surface a "limited stock" warning in the response.

## 32. Completion Checklist
- [ ] `product_availability` table created and seedable
- [ ] `LocalAvailabilityService` satisfies `AvailabilityService` protocol
- [ ] `ERPAvailabilityService` stub raises `NotImplementedError` clearly
- [ ] Factory selects correct implementation based on `AVAILABILITY_PROVIDER`
- [ ] `check_availability` tool registered in `ToolRegistry`
- [ ] `GET /products/{product_id}/availability` endpoint registered in Module 15
- [ ] Tests above pass
