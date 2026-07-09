"""Unit tests for Module 18 AccessoryService."""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from types import SimpleNamespace
from typing import Any

import pytest

from app.product_intelligence.accessory_service import AccessoryService
from app.product_intelligence.models import AccessoryRelation
from app.rag.models import Product


class FakeAccessoryRepository:
    def __init__(self, relations: list[AccessoryRelation]) -> None:
        self.relations = relations

    async def find_accessories(self, product_id: uuid.UUID, tenant_id: uuid.UUID) -> list[AccessoryRelation]:
        return self.relations


class FakeProductRepository:
    def __init__(self, products: dict[uuid.UUID, Product]) -> None:
        self.products = products

    async def get_by_ids(self, tenant_id: uuid.UUID, product_ids: list[uuid.UUID]) -> dict[uuid.UUID, Product]:
        return {pid: self.products[pid] for pid in product_ids if pid in self.products}


class FakeEmbedder:
    def embed(self, texts: list[str]) -> list[list[float]]:
        return [[0.1, 0.2, 0.3] for _ in texts]


@dataclass
class FakeQdrant:
    points: list[Any] = field(default_factory=list)

    def search(self, collection: str, vector: list[float], payload_filter: dict, limit: int) -> list[Any]:
        return self.points


def _settings() -> SimpleNamespace:
    return SimpleNamespace(
        embedding=SimpleNamespace(model_name="BAAI/bge-m3"),
        rag=SimpleNamespace(qdrant_collection_products="products_v1"),
    )


def _product(product_id: uuid.UUID, name: str, category: str = "switch") -> Product:
    return Product(id=product_id, tenant_id=uuid.uuid4(), name=name, brand="Acme", category=category)


@pytest.mark.asyncio
async def test_accessory_returns_explicit_relations_without_supplement_when_enough() -> None:
    primary_id = uuid.uuid4()
    accessory_ids = [uuid.uuid4() for _ in range(3)]
    relations = [
        AccessoryRelation(
            tenant_id=uuid.uuid4(), primary_product_id=primary_id, accessory_product_id=aid, relation_type="cable"
        )
        for aid in accessory_ids
    ]
    products = {aid: _product(aid, f"Accessory {i}") for i, aid in enumerate(accessory_ids)}
    qdrant = FakeQdrant()
    service = AccessoryService(
        db_session=None,  # type: ignore[arg-type]
        settings=_settings(),
        accessory_repository=FakeAccessoryRepository(relations),
        product_repository=FakeProductRepository(products),
        embedder=FakeEmbedder(),
        qdrant=qdrant,
    )

    results = await service.recommend(primary_id, uuid.uuid4())

    assert len(results) == 3
    assert all(item.source == "explicit" for item in results)


@pytest.mark.asyncio
async def test_accessory_supplements_with_vector_when_fewer_than_3_explicit() -> None:
    primary_id = uuid.uuid4()
    accessory_id = uuid.uuid4()
    relations = [
        AccessoryRelation(
            tenant_id=uuid.uuid4(),
            primary_product_id=primary_id,
            accessory_product_id=accessory_id,
            relation_type="cable",
        )
    ]
    vector_id = uuid.uuid4()
    products = {
        primary_id: _product(primary_id, "Primary Switch"),
        accessory_id: _product(accessory_id, "Cable"),
    }
    point = SimpleNamespace(payload={"product_id": str(vector_id), "name": "Similar Switch"}, score=0.9)
    qdrant = FakeQdrant(points=[point])
    service = AccessoryService(
        db_session=None,  # type: ignore[arg-type]
        settings=_settings(),
        accessory_repository=FakeAccessoryRepository(relations),
        product_repository=FakeProductRepository(products),
        embedder=FakeEmbedder(),
        qdrant=qdrant,
    )

    results = await service.recommend(primary_id, uuid.uuid4())

    assert len(results) == 2
    assert results[0].source == "explicit"
    assert results[1].source == "vector_similarity"
    assert results[1].product_id == vector_id


@pytest.mark.asyncio
async def test_accessory_vector_supplement_excludes_already_known_ids() -> None:
    primary_id = uuid.uuid4()
    products = {primary_id: _product(primary_id, "Primary Switch")}
    point = SimpleNamespace(payload={"product_id": str(primary_id), "name": "Primary Switch"}, score=1.0)
    qdrant = FakeQdrant(points=[point])
    service = AccessoryService(
        db_session=None,  # type: ignore[arg-type]
        settings=_settings(),
        accessory_repository=FakeAccessoryRepository([]),
        product_repository=FakeProductRepository(products),
        embedder=FakeEmbedder(),
        qdrant=qdrant,
    )

    results = await service.recommend(primary_id, uuid.uuid4())

    assert results == []
