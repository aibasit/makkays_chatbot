"""Unit tests for Module 18 ComparisonService."""

from __future__ import annotations

import uuid
from typing import Any

import pytest

from app.llm.schemas import LLMResponse
from app.product_intelligence.comparison_service import ComparisonService
from app.product_intelligence.exceptions import InsufficientProductsForComparisonError
from app.rag.models import Product, ProductSpec


class FakeProductRepository:
    def __init__(self, products: dict[uuid.UUID, Product]) -> None:
        self.products = products

    async def get_by_ids(self, tenant_id: uuid.UUID, product_ids: list[uuid.UUID]) -> dict[uuid.UUID, Product]:
        return {pid: self.products[pid] for pid in product_ids if pid in self.products}


class FakeSpecRepository:
    def __init__(self, specs_by_product: dict[uuid.UUID, list[ProductSpec]]) -> None:
        self.specs_by_product = specs_by_product

    async def get_specs_for_products(
        self, product_ids: list[uuid.UUID], tenant_id: uuid.UUID
    ) -> dict[uuid.UUID, list[ProductSpec]]:
        return {pid: self.specs_by_product[pid] for pid in product_ids if pid in self.specs_by_product}


class FakeLLMClient:
    def __init__(self, content: str = "Product A has more ports.") -> None:
        self.content = content
        self.calls = 0

    async def chat(self, messages: list[Any], **kwargs: Any) -> LLMResponse:
        self.calls += 1
        return LLMResponse(content=self.content, tool_calls=[])


def _product(product_id: uuid.UUID, name: str) -> Product:
    return Product(id=product_id, tenant_id=uuid.uuid4(), name=name, brand="Acme", category="switch")


def _spec(product_id: uuid.UUID, key: str, value: str) -> ProductSpec:
    return ProductSpec(product_id=product_id, tenant_id=uuid.uuid4(), spec_key=key, spec_value=value)


@pytest.mark.asyncio
async def test_comparison_builds_table_from_specs() -> None:
    product_a, product_b = uuid.uuid4(), uuid.uuid4()
    products = {product_a: _product(product_a, "Switch A"), product_b: _product(product_b, "Switch B")}
    specs = {
        product_a: [_spec(product_a, "ports", "24"), _spec(product_a, "poe", "true")],
        product_b: [_spec(product_b, "ports", "48")],
    }
    service = ComparisonService(
        db_session=None,  # type: ignore[arg-type]
        product_repository=FakeProductRepository(products),
        spec_repository=FakeSpecRepository(specs),
    )

    result = await service.compare([product_a, product_b], uuid.uuid4(), FakeLLMClient())

    assert result.comparison_table["ports"][str(product_a)] == "24"
    assert result.comparison_table["ports"][str(product_b)] == "48"
    assert result.comparison_table["poe"][str(product_b)] is None
    assert len(result.products) == 2


@pytest.mark.asyncio
async def test_comparison_calls_llm_for_summary() -> None:
    product_a, product_b = uuid.uuid4(), uuid.uuid4()
    products = {product_a: _product(product_a, "Switch A"), product_b: _product(product_b, "Switch B")}
    service = ComparisonService(
        db_session=None,  # type: ignore[arg-type]
        product_repository=FakeProductRepository(products),
        spec_repository=FakeSpecRepository({}),
    )
    llm_client = FakeLLMClient("Switch B has more ports and is the better fit.")

    result = await service.compare([product_a, product_b], uuid.uuid4(), llm_client)

    assert llm_client.calls == 1
    assert result.ai_summary == "Switch B has more ports and is the better fit."


@pytest.mark.asyncio
async def test_comparison_raises_when_fewer_than_two_products() -> None:
    service = ComparisonService(
        db_session=None,  # type: ignore[arg-type]
        product_repository=FakeProductRepository({}),
        spec_repository=FakeSpecRepository({}),
    )

    with pytest.raises(InsufficientProductsForComparisonError):
        await service.compare([uuid.uuid4()], uuid.uuid4(), FakeLLMClient())


@pytest.mark.asyncio
async def test_comparison_summary_empty_on_llm_failure() -> None:
    product_a, product_b = uuid.uuid4(), uuid.uuid4()
    products = {product_a: _product(product_a, "Switch A"), product_b: _product(product_b, "Switch B")}
    service = ComparisonService(
        db_session=None,  # type: ignore[arg-type]
        product_repository=FakeProductRepository(products),
        spec_repository=FakeSpecRepository({}),
    )

    class FailingLLMClient:
        async def chat(self, *args: Any, **kwargs: Any) -> LLMResponse:
            raise RuntimeError("LLM unavailable")

    result = await service.compare([product_a, product_b], uuid.uuid4(), FailingLLMClient())

    assert result.ai_summary == ""
    assert len(result.products) == 2
