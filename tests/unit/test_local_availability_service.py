"""Unit tests for Module 22 local availability service."""

from __future__ import annotations

import uuid
from types import SimpleNamespace
from typing import Any

import pytest

from app.availability.dependencies import get_availability_service
from app.availability.erp_client import ERPAvailabilityService
from app.availability.local_service import LocalAvailabilityService


class FakeAvailabilityRepository:
    def __init__(self, rows: dict[uuid.UUID, Any] | None = None) -> None:
        self.rows = rows or {}

    async def get(self, product_id: uuid.UUID, tenant_id: uuid.UUID) -> Any | None:
        return self.rows.get(product_id)

    async def get_batch(self, product_ids: list[uuid.UUID], tenant_id: uuid.UUID) -> list[Any]:
        return [self.rows[product_id] for product_id in product_ids if product_id in self.rows]


@pytest.mark.asyncio
async def test_local_service_returns_from_db_when_found() -> None:
    tenant_id = uuid.uuid4()
    product_id = uuid.uuid4()
    row = SimpleNamespace(
        product_id=product_id,
        quantity=7,
        estimated_delivery_days=3,
    )
    service = LocalAvailabilityService(
        db=None,  # type: ignore[arg-type]
        repository=FakeAvailabilityRepository({product_id: row}),  # type: ignore[arg-type]
    )

    result = await service.check(product_id, tenant_id)

    assert result.product_id == product_id
    assert result.in_stock is True
    assert result.quantity == 7
    assert result.estimated_delivery_days == 3
    assert result.source == "local_db"


@pytest.mark.asyncio
async def test_local_service_returns_mock_when_not_found() -> None:
    service = LocalAvailabilityService(
        db=None,  # type: ignore[arg-type]
        repository=FakeAvailabilityRepository(),  # type: ignore[arg-type]
    )

    result = await service.check(uuid.uuid4(), uuid.uuid4())

    assert result.in_stock is True
    assert result.quantity == 99
    assert result.source == "mock"
    assert result.note is not None


@pytest.mark.asyncio
async def test_batch_check_returns_result_per_product() -> None:
    tenant_id = uuid.uuid4()
    product_a = uuid.uuid4()
    product_b = uuid.uuid4()
    row = SimpleNamespace(product_id=product_a, quantity=0, estimated_delivery_days=10)
    service = LocalAvailabilityService(
        db=None,  # type: ignore[arg-type]
        repository=FakeAvailabilityRepository({product_a: row}),  # type: ignore[arg-type]
    )

    results = await service.check_batch([product_a, product_b], tenant_id)

    assert [result.product_id for result in results] == [product_a, product_b]
    assert results[0].in_stock is False
    assert results[0].source == "local_db"
    assert results[1].source == "mock"


def test_factory_returns_local_service_for_local_provider() -> None:
    settings = SimpleNamespace(availability=SimpleNamespace(provider="local"))

    service = get_availability_service(db=None, settings=settings)  # type: ignore[arg-type]

    assert isinstance(service, LocalAvailabilityService)


def test_factory_returns_erp_stub_for_erp_provider() -> None:
    settings = SimpleNamespace(availability=SimpleNamespace(provider="erp"))

    service = get_availability_service(db=None, settings=settings)  # type: ignore[arg-type]

    assert isinstance(service, ERPAvailabilityService)


def test_factory_raises_on_invalid_provider() -> None:
    settings = SimpleNamespace(availability=SimpleNamespace(provider="bogus"))

    with pytest.raises(ValueError, match="Unknown AVAILABILITY_PROVIDER"):
        get_availability_service(db=None, settings=settings)  # type: ignore[arg-type]
