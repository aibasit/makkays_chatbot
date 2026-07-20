"""Unit tests for Module 19 BOMService, ScaleClassifier, and SolutionExplainer."""

from __future__ import annotations

import uuid
from decimal import Decimal
from types import SimpleNamespace
from typing import Any

import pytest

from app.llm.schemas import LLMResponse
from app.quotes.models import ProductPricing
from app.rag.models import Product
from app.rag.schemas import ExtractedFilters
from app.solution_builder.bom_service import BOMService, ScaleClassifier, category_quantities
from app.solution_builder.exceptions import InsufficientProductDataError
from app.solution_builder.schemas import Solution, WizardRequirements
from app.solution_builder.solution_explainer import SolutionExplainer


class FakeProductRepository:
    def __init__(self, products_by_category: dict[str, Product]) -> None:
        self.products_by_category = products_by_category
        self.filters_seen: list[ExtractedFilters] = []

    async def find_by_filters(self, tenant_id: uuid.UUID, filters: ExtractedFilters) -> list[uuid.UUID] | None:
        self.filters_seen.append(filters)
        product = self.products_by_category.get(filters.category or "")
        return [product.id] if product else []

    async def get_by_ids(self, tenant_id: uuid.UUID, product_ids: list[uuid.UUID]) -> dict[uuid.UUID, Product]:
        return {
            product.id: product
            for product in self.products_by_category.values()
            if product.id in product_ids
        }


class FakePricingRepository:
    def __init__(self, prices_by_product: dict[uuid.UUID, Decimal]) -> None:
        self.prices_by_product = prices_by_product

    async def get_prices(self, tenant_id: uuid.UUID, product_ids: list[uuid.UUID]) -> dict[uuid.UUID, ProductPricing]:
        return {
            pid: ProductPricing(product_id=pid, tenant_id=uuid.uuid4(), unit_price=price, currency="USD")
            for pid, price in self.prices_by_product.items()
            if pid in product_ids
        }


def _settings() -> SimpleNamespace:
    return SimpleNamespace(solution_builder=SimpleNamespace(large_device_threshold=500, enterprise_device_threshold=1000))


def test_category_quantities_deterministic_ratios() -> None:
    assert category_quantities(24) == {"switch": 1, "ups": 1}
    assert category_quantities(240) == {"switch": 10, "ups": 1}
    assert category_quantities(0) == {"switch": 1, "ups": 1}


def test_scale_classifier_thresholds() -> None:
    classifier = ScaleClassifier(_settings())  # type: ignore[arg-type]

    assert classifier.classify(50, "school").pricing_mode == "calculated"
    assert classifier.classify(50, "school").size == "small"
    assert classifier.classify(150, "office").size == "medium"
    assert classifier.classify(600, "office").pricing_mode == "call_for_pricing"
    assert classifier.classify(600, "office").size == "large"
    assert classifier.classify(1500, "office").size == "enterprise"
    assert classifier.classify(10, "data_center").pricing_mode == "call_for_pricing"
    assert classifier.classify(10, "data_center").size == "enterprise"


@pytest.mark.asyncio
async def test_bom_builds_deterministic_line_items() -> None:
    switch_id, ups_id = uuid.uuid4(), uuid.uuid4()
    products = {
        "switch": Product(id=switch_id, tenant_id=uuid.uuid4(), name="TL-SG3428", category="switch"),
        "ups": Product(id=ups_id, tenant_id=uuid.uuid4(), name="APC UPS", category="ups"),
    }
    prices = {switch_id: Decimal("120.00"), ups_id: Decimal("300.00")}
    service = BOMService(
        db_session=None,  # type: ignore[arg-type]
        product_repository=FakeProductRepository(products),
        pricing_repository=FakePricingRepository(prices),
    )

    solution = await service.build(WizardRequirements(use_case="school", device_count=200), uuid.uuid4())

    switch_item = next(item for item in solution.line_items if item.category == "switch")
    ups_item = next(item for item in solution.line_items if item.category == "ups")
    assert switch_item.quantity == 9  # ceil(200/24)
    assert switch_item.subtotal == Decimal("1080.00")
    assert ups_item.quantity == 1  # ceil(9/10)
    assert solution.total_estimate == Decimal("1380.00")


@pytest.mark.asyncio
async def test_bom_finds_ups_products_under_the_real_catalog_category_name() -> None:
    """Regression test for a real bug found live: this tenant's actual catalog
    categorizes UPS products as "UPS Solutions", not the generic "ups" the BOM
    ratio model uses internally — a bare "ups" lookup always found nothing,
    which (combined with no retrieve_products step in the wizard's plan)
    left `respond` with zero real product data and led it to hallucinate
    fictional competitor UPS models instead. The literal "ups" name is tried
    first (kept for backward compatibility with a literally-named catalog,
    e.g. in tests), falling back to "UPS Solutions" when that finds nothing.
    """
    ups_id = uuid.uuid4()
    products = {"UPS Solutions": Product(id=ups_id, tenant_id=uuid.uuid4(), name="T-4003 UPS", category="UPS Solutions")}
    prices = {ups_id: Decimal("2000.00")}
    service = BOMService(
        db_session=None,  # type: ignore[arg-type]
        product_repository=FakeProductRepository(products),
        pricing_repository=FakePricingRepository(prices),
    )

    solution = await service.build(WizardRequirements(use_case="power", device_count=20), uuid.uuid4())

    assert len(solution.line_items) == 1
    assert solution.line_items[0].category == "ups"
    assert solution.line_items[0].product_name == "T-4003 UPS"
    assert solution.total_estimate == Decimal("2000.00")


@pytest.mark.asyncio
async def test_bom_passes_capacity_requirement_through_for_the_ups_category() -> None:
    """Regression test: the wizard never asks for a capacity figure directly,
    but a visitor typically states one in the message that triggered it (e.g.
    "My power requirement is 20KVA"). Without threading it through, the "ups"
    line item could only grab an arbitrary product rather than one sized for
    the visitor's actual load.
    """
    ups_id = uuid.uuid4()
    products = {"UPS Solutions": Product(id=ups_id, tenant_id=uuid.uuid4(), name="T-4003 UPS", category="UPS Solutions")}
    prices = {ups_id: Decimal("300.00")}
    repository = FakeProductRepository(products)
    service = BOMService(
        db_session=None,  # type: ignore[arg-type]
        product_repository=repository,
        pricing_repository=FakePricingRepository(prices),
    )

    await service.build(
        WizardRequirements(
            use_case="power", device_count=20, capacity_requirement=Decimal("20"), capacity_unit="KVA"
        ),
        uuid.uuid4(),
    )

    ups_filters = next(f for f in repository.filters_seen if f.category == "UPS Solutions")
    assert ups_filters.capacity_requirement == Decimal("20")
    assert ups_filters.capacity_unit == "KVA"


@pytest.mark.asyncio
async def test_bom_skips_categories_with_no_products_instead_of_failing() -> None:
    """Regression test for a real bug found live: a power-only catalog (no
    "switch" products at all) made every wizard completion fail with
    InsufficientProductDataError, since `category_quantities` always requires
    both "switch" and "ups". With no retrieval step in the wizard's plan to
    fall back on, `respond` then had zero real product data and hallucinated
    fictional competitor UPS models (Eaton, APC, Vertiv) instead. A category
    with no matches must be skipped, not fail the whole solution, as long as
    at least one other required category has a real match.
    """
    ups_id = uuid.uuid4()
    products = {"UPS Solutions": Product(id=ups_id, tenant_id=uuid.uuid4(), name="T-4003 UPS", category="UPS Solutions")}
    prices = {ups_id: Decimal("2000.00")}
    service = BOMService(
        db_session=None,  # type: ignore[arg-type]
        product_repository=FakeProductRepository(products),
        pricing_repository=FakePricingRepository(prices),
    )

    solution = await service.build(WizardRequirements(use_case="power", device_count=20), uuid.uuid4())

    assert len(solution.line_items) == 1
    assert solution.line_items[0].category == "ups"
    assert solution.total_estimate == Decimal("2000.00")


@pytest.mark.asyncio
async def test_bom_raises_on_empty_catalog() -> None:
    service = BOMService(
        db_session=None,  # type: ignore[arg-type]
        product_repository=FakeProductRepository({}),
        pricing_repository=FakePricingRepository({}),
    )

    with pytest.raises(InsufficientProductDataError):
        await service.build(WizardRequirements(use_case="school", device_count=200), uuid.uuid4())


@pytest.mark.asyncio
async def test_solution_explainer_never_modifies_totals() -> None:
    solution = Solution(
        solution_id=uuid.uuid4(),
        use_case="school",
        line_items=[],
        total_estimate=Decimal("1380.00"),
        currency="USD",
    )
    original_total = solution.total_estimate

    class FakeLLMClient:
        async def chat(self, *args: Any, **kwargs: Any) -> LLMResponse:
            return LLMResponse(content="This solution costs a suspiciously different amount.", tool_calls=[])

    narration = await SolutionExplainer().explain(solution, FakeLLMClient())

    assert solution.total_estimate == original_total
    assert narration == "This solution costs a suspiciously different amount."


@pytest.mark.asyncio
async def test_solution_explainer_falls_back_on_llm_failure() -> None:
    solution = Solution(
        solution_id=uuid.uuid4(),
        use_case="school",
        line_items=[],
        total_estimate=Decimal("1380.00"),
        currency="USD",
    )

    class FailingLLMClient:
        async def chat(self, *args: Any, **kwargs: Any) -> LLMResponse:
            raise RuntimeError("LLM unavailable")

    narration = await SolutionExplainer().explain(solution, FailingLLMClient())

    assert "1380.00" in narration
