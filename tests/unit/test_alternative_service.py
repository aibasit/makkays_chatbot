"""Unit tests for Module 18 AlternativeService.

Not in Module 18's own folder-structure listing (which only shows 4 unit test
files) even though `test_alternative_finds_same_category_products` is named in
its own unit test list — added as its own file for the same reason earlier
sessions filled similar spec gaps.
"""

from __future__ import annotations

import uuid
from types import SimpleNamespace
from typing import Any

import pytest

from app.product_intelligence.alternative_service import AlternativeService
from app.rag.models import Product


class FakeProductRepository:
    def __init__(self, products: dict[uuid.UUID, Product]) -> None:
        self.products = products

    async def get_by_ids(self, tenant_id: uuid.UUID, product_ids: list[uuid.UUID]) -> dict[uuid.UUID, Product]:
        return {pid: self.products[pid] for pid in product_ids if pid in self.products}


class FakeEmbedder:
    def embed(self, texts: list[str]) -> list[list[float]]:
        return [[0.1, 0.2, 0.3] for _ in texts]


class FakeQdrant:
    def __init__(self, points: list[Any]) -> None:
        self.points = points

    def search(self, collection: str, vector: list[float], payload_filter: dict, limit: int) -> list[Any]:
        return self.points


class FakeDbSession:
    def __init__(self, rows: list[Product]) -> None:
        self.rows = rows

    async def execute(self, *args: Any, **kwargs: Any) -> Any:
        rows = self.rows

        class _Result:
            def scalars(self) -> Any:
                class _Scalars:
                    def all(self_inner) -> list[Product]:
                        return rows

                return _Scalars()

        return _Result()


def _settings() -> SimpleNamespace:
    return SimpleNamespace(
        embedding=SimpleNamespace(model_name="BAAI/bge-m3"),
        rag=SimpleNamespace(qdrant_collection_products="products_v1"),
    )


def _product(product_id: uuid.UUID, name: str, category: str) -> Product:
    return Product(id=product_id, tenant_id=uuid.uuid4(), name=name, brand="Acme", category=category)


@pytest.mark.asyncio
async def test_alternative_finds_same_category_products() -> None:
    primary_id = uuid.uuid4()
    alt_id = uuid.uuid4()
    primary = _product(primary_id, "Switch A", "switch")
    alternative = _product(alt_id, "Switch B", "switch")

    point = SimpleNamespace(payload={"product_id": str(alt_id)}, score=0.8)
    service = AlternativeService(
        db_session=FakeDbSession([alternative]),  # type: ignore[arg-type]
        settings=_settings(),
        product_repository=FakeProductRepository({primary_id: primary, alt_id: alternative}),
        embedder=FakeEmbedder(),
        qdrant=FakeQdrant([point]),
    )

    results = await service.find(primary_id, uuid.uuid4())

    assert len(results) == 1
    assert results[0].product_id == alt_id
    assert results[0].category == "switch"


@pytest.mark.asyncio
async def test_alternative_returns_empty_when_primary_has_no_category() -> None:
    primary_id = uuid.uuid4()
    primary = Product(id=primary_id, tenant_id=uuid.uuid4(), name="Mystery Item", brand=None, category=None)
    service = AlternativeService(
        db_session=FakeDbSession([]),  # type: ignore[arg-type]
        settings=_settings(),
        product_repository=FakeProductRepository({primary_id: primary}),
        embedder=FakeEmbedder(),
        qdrant=FakeQdrant([]),
    )

    results = await service.find(primary_id, uuid.uuid4())

    assert results == []
