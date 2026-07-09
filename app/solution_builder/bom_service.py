"""Deterministic scale classification and bill-of-materials computation.

`BOMService.build` fetches products/pricing from Postgres, so it is `async` in
this codebase (every DB access here is async) rather than the literal sync
function the spec sketches — but the *computation* itself (category ratios,
quantities, subtotals, total) is pure arithmetic: no LLM call, no randomness,
same inputs always produce the same output.
"""

from __future__ import annotations

import math
from decimal import Decimal
from uuid import UUID, uuid4

from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings
from app.quotes.repository import ProductPricingRepository
from app.rag.repository import ProductRepository
from app.rag.schemas import ExtractedFilters
from app.solution_builder.exceptions import InsufficientProductDataError
from app.solution_builder.schemas import BOMLineItem, ProjectScale, Solution, WizardRequirements

# Category -> devices-per-unit ratio table (business rules, no LLM involvement).
_DEVICES_PER_SWITCH = 24
_SWITCHES_PER_UPS = 10

# Enterprise use cases always trigger call_for_pricing regardless of device count.
_ENTERPRISE_USE_CASES: frozenset[str] = frozenset(
    {"data_center", "enterprise", "isp", "carrier", "government"}
)
_MEDIUM_DEVICE_THRESHOLD = 100


class ScaleClassifier:
    """Determines pricing mode from device_count and use_case. Never shown to the user."""

    def __init__(self, settings: Settings) -> None:
        self.large_threshold = settings.solution_builder.large_device_threshold
        self.enterprise_threshold = settings.solution_builder.enterprise_device_threshold

    def classify(self, device_count: int, use_case: str | None) -> ProjectScale:
        """Return the project scale and pricing mode; first matching rule wins."""
        if use_case and use_case in _ENTERPRISE_USE_CASES:
            return ProjectScale(size="enterprise", pricing_mode="call_for_pricing", reason="enterprise use case")
        if device_count >= self.enterprise_threshold:
            return ProjectScale(
                size="enterprise",
                pricing_mode="call_for_pricing",
                reason=f"device_count >= {self.enterprise_threshold}",
            )
        if device_count >= self.large_threshold:
            return ProjectScale(
                size="large", pricing_mode="call_for_pricing", reason=f"device_count >= {self.large_threshold}"
            )
        if device_count >= _MEDIUM_DEVICE_THRESHOLD:
            return ProjectScale(
                size="medium", pricing_mode="calculated", reason=f"device_count >= {_MEDIUM_DEVICE_THRESHOLD}"
            )
        return ProjectScale(size="small", pricing_mode="calculated", reason=f"device_count < {_MEDIUM_DEVICE_THRESHOLD}")


def category_quantities(device_count: int) -> dict[str, int]:
    """Return category -> quantity for a device count. Pure function, unit-testable alone."""
    switch_qty = max(1, math.ceil(device_count / _DEVICES_PER_SWITCH)) if device_count > 0 else 1
    ups_qty = max(1, math.ceil(switch_qty / _SWITCHES_PER_UPS))
    return {"switch": switch_qty, "ups": ups_qty}


class BOMService:
    """Computes a deterministic BOM. Called only when pricing_mode == 'calculated'."""

    def __init__(
        self,
        db_session: AsyncSession,
        *,
        product_repository: ProductRepository | None = None,
        pricing_repository: ProductPricingRepository | None = None,
    ) -> None:
        self.product_repository = product_repository or ProductRepository(db_session)
        self.pricing_repository = pricing_repository or ProductPricingRepository(db_session)

    async def build(self, requirements: WizardRequirements, tenant_id: UUID) -> Solution:
        """Build line items for each required category, priced from `product_pricing`."""
        quantities = category_quantities(requirements.device_count or 0)
        line_items: list[BOMLineItem] = []
        for category, quantity in quantities.items():
            line_items.append(await self._line_item_for_category(tenant_id, category, quantity))

        total = sum((item.subtotal for item in line_items), start=Decimal("0.00"))
        return Solution(
            solution_id=uuid4(),
            use_case=requirements.use_case,
            line_items=line_items,
            total_estimate=total,
            currency="USD",
        )

    async def _line_item_for_category(self, tenant_id: UUID, category: str, quantity: int) -> BOMLineItem:
        product_ids = await self.product_repository.find_by_filters(
            tenant_id, ExtractedFilters(category=category)
        )
        if not product_ids:
            raise InsufficientProductDataError(f"No products found for category {category!r}")

        product_id = product_ids[0]
        products_by_id = await self.product_repository.get_by_ids(tenant_id, [product_id])
        product = products_by_id.get(product_id)
        prices = await self.pricing_repository.get_prices(tenant_id, [product_id])
        pricing = prices.get(product_id)
        if product is None or pricing is None:
            raise InsufficientProductDataError(f"No priced product found for category {category!r}")

        subtotal = (pricing.unit_price * quantity).quantize(Decimal("0.01"))
        return BOMLineItem(
            category=category,
            product_id=product_id,
            product_name=product.name,
            quantity=quantity,
            unit_price=pricing.unit_price,
            subtotal=subtotal,
        )
