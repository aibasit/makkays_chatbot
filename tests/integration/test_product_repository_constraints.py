"""Integration tests for `Constraint`-based product filtering against real Postgres.

Everything here exercises real SQL — `find_by_filters`/`list_products` were
previously only ever validated via fakes (which just echo back a fixed
candidate list, never actually run the generated SQL) or live manual curl
testing. Given how much new operator logic (`eq`/`gte`/`lte`/`between`/`in`/
`not_eq`/`nearest`, plus the categorical EXISTS/NOT EXISTS builder) this
session added, this is the one place a broken WHERE clause would actually be
caught before it reached a live conversation.
"""

from __future__ import annotations

import uuid
from decimal import Decimal

import pytest
from sqlalchemy import text

from app.db.engine import get_db_session, initialize_database
from app.dependencies import get_settings
from app.rag.repository import ProductRepository
from app.rag.retrieval_service import RetrievalService
from app.rag.schemas import Constraint, ExtractedFilters


async def _check_db_available() -> None:
    settings = get_settings()
    initialize_database(settings)
    try:
        async for session in get_db_session():
            await session.execute(text("SELECT 1"))
    except Exception as exc:
        pytest.skip(f"Configured database is not reachable: {exc}")


async def _cleanup(tenant_id: uuid.UUID) -> None:
    async for session in get_db_session():
        await session.execute(text("DELETE FROM product_specs WHERE tenant_id = :t"), {"t": tenant_id})
        await session.execute(text("DELETE FROM products WHERE tenant_id = :t"), {"t": tenant_id})
        await session.commit()


async def _seed_ups(
    repo: ProductRepository,
    tenant_id: uuid.UUID,
    *,
    name: str,
    capacity_kva: Decimal | None = None,
    form_factor_key: str | None = None,
) -> uuid.UUID:
    specs = [{"key": "domain", "value": "i-power"}]
    if form_factor_key:
        specs.append({"key": "form_factor_key", "value": form_factor_key})
    product = await repo.create(
        tenant_id=tenant_id,
        name=name,
        brand="Interconnect Solutions",
        category="UPS Solutions",
        description=None,
        specs=specs,
        capacity_kva=capacity_kva,
    )
    return product.id


@pytest.mark.asyncio
async def test_find_by_filters_capacity_kva_eq() -> None:
    await _check_db_available()
    tenant_id = uuid.uuid4()
    try:
        async for session in get_db_session():
            repository = ProductRepository(session)
            six_kva = await _seed_ups(repository, tenant_id, name="6kVA UPS", capacity_kva=Decimal("6"))
            await _seed_ups(repository, tenant_id, name="10kVA UPS", capacity_kva=Decimal("10"))
            await session.commit()

            filters = ExtractedFilters(
                category="UPS Solutions",
                constraints=[Constraint(field="capacity_kva", operator="eq", value=Decimal("6"))],
            )
            candidate_ids = await repository.find_by_filters(tenant_id, filters)
            assert candidate_ids == [six_kva]
            break
    finally:
        await _cleanup(tenant_id)


@pytest.mark.asyncio
async def test_find_by_filters_capacity_kva_gte_and_lte() -> None:
    await _check_db_available()
    tenant_id = uuid.uuid4()
    try:
        async for session in get_db_session():
            repository = ProductRepository(session)
            low = await _seed_ups(repository, tenant_id, name="1kVA UPS", capacity_kva=Decimal("1"))
            mid = await _seed_ups(repository, tenant_id, name="6kVA UPS", capacity_kva=Decimal("6"))
            high = await _seed_ups(repository, tenant_id, name="10kVA UPS", capacity_kva=Decimal("10"))
            await session.commit()

            gte_filters = ExtractedFilters(
                category="UPS Solutions",
                constraints=[Constraint(field="capacity_kva", operator="gte", value=Decimal("6"))],
            )
            gte_ids = set(await repository.find_by_filters(tenant_id, gte_filters))
            assert gte_ids == {mid, high}

            lte_filters = ExtractedFilters(
                category="UPS Solutions",
                constraints=[Constraint(field="capacity_kva", operator="lte", value=Decimal("6"))],
            )
            lte_ids = set(await repository.find_by_filters(tenant_id, lte_filters))
            assert lte_ids == {low, mid}
            break
    finally:
        await _cleanup(tenant_id)


@pytest.mark.asyncio
async def test_find_by_filters_capacity_kva_between() -> None:
    await _check_db_available()
    tenant_id = uuid.uuid4()
    try:
        async for session in get_db_session():
            repository = ProductRepository(session)
            await _seed_ups(repository, tenant_id, name="1kVA UPS", capacity_kva=Decimal("1"))
            mid = await _seed_ups(repository, tenant_id, name="6kVA UPS", capacity_kva=Decimal("6"))
            await _seed_ups(repository, tenant_id, name="20kVA UPS", capacity_kva=Decimal("20"))
            await session.commit()

            filters = ExtractedFilters(
                category="UPS Solutions",
                constraints=[
                    Constraint(
                        field="capacity_kva", operator="between", value=Decimal("3"), value_max=Decimal("10")
                    )
                ],
            )
            candidate_ids = await repository.find_by_filters(tenant_id, filters)
            assert candidate_ids == [mid]
            break
    finally:
        await _cleanup(tenant_id)


@pytest.mark.asyncio
async def test_find_by_filters_capacity_kva_in_and_not_eq() -> None:
    await _check_db_available()
    tenant_id = uuid.uuid4()
    try:
        async for session in get_db_session():
            repository = ProductRepository(session)
            five = await _seed_ups(repository, tenant_id, name="5kVA UPS", capacity_kva=Decimal("5"))
            six = await _seed_ups(repository, tenant_id, name="6kVA UPS", capacity_kva=Decimal("6"))
            ten = await _seed_ups(repository, tenant_id, name="10kVA UPS", capacity_kva=Decimal("10"))
            await session.commit()

            in_filters = ExtractedFilters(
                category="UPS Solutions",
                constraints=[
                    Constraint(field="capacity_kva", operator="in", values=[Decimal("5"), Decimal("6")])
                ],
            )
            in_ids = set(await repository.find_by_filters(tenant_id, in_filters))
            assert in_ids == {five, six}

            not_eq_filters = ExtractedFilters(
                category="UPS Solutions",
                constraints=[Constraint(field="capacity_kva", operator="not_eq", value=Decimal("10"))],
            )
            not_eq_ids = set(await repository.find_by_filters(tenant_id, not_eq_filters))
            assert ten not in not_eq_ids
            assert {five, six}.issubset(not_eq_ids)
            break
    finally:
        await _cleanup(tenant_id)


@pytest.mark.asyncio
async def test_find_by_filters_nearest_orders_by_closeness() -> None:
    await _check_db_available()
    tenant_id = uuid.uuid4()
    try:
        async for session in get_db_session():
            repository = ProductRepository(session)
            far = await _seed_ups(repository, tenant_id, name="1kVA UPS", capacity_kva=Decimal("1"))
            near = await _seed_ups(repository, tenant_id, name="6kVA UPS", capacity_kva=Decimal("6"))
            await _seed_ups(repository, tenant_id, name="10kVA UPS", capacity_kva=Decimal("10"))
            await session.commit()

            filters = ExtractedFilters(
                category="UPS Solutions",
                constraints=[Constraint(field="capacity_kva", operator="nearest", value=Decimal("7"))],
            )
            candidate_ids = await repository.find_by_filters(tenant_id, filters)
            assert candidate_ids[0] == near
            assert candidate_ids[-1] == far
            break
    finally:
        await _cleanup(tenant_id)


@pytest.mark.asyncio
async def test_find_by_filters_categorical_eq_and_not_eq() -> None:
    await _check_db_available()
    tenant_id = uuid.uuid4()
    try:
        async for session in get_db_session():
            repository = ProductRepository(session)
            tower = await _seed_ups(repository, tenant_id, name="Tower UPS", form_factor_key="tower")
            rack = await _seed_ups(repository, tenant_id, name="Rack UPS", form_factor_key="rack_mount")
            await session.commit()

            eq_filters = ExtractedFilters(
                category="UPS Solutions",
                constraints=[Constraint(field="form_factor_key", operator="eq", value="tower")],
            )
            eq_ids = await repository.find_by_filters(tenant_id, eq_filters)
            assert eq_ids == [tower]

            not_eq_filters = ExtractedFilters(
                category="UPS Solutions",
                constraints=[Constraint(field="form_factor_key", operator="not_eq", value="tower")],
            )
            not_eq_ids = await repository.find_by_filters(tenant_id, not_eq_filters)
            assert not_eq_ids == [rack]
            break
    finally:
        await _cleanup(tenant_id)


@pytest.mark.asyncio
async def test_list_products_respects_constraints_not_just_category() -> None:
    """Regression test: "list all tower UPS" must list all *tower* UPS, not
    the entire UPS category — `list_products` used to only accept
    category/brand, silently bypassing every other filter."""
    await _check_db_available()
    tenant_id = uuid.uuid4()
    try:
        async for session in get_db_session():
            repository = ProductRepository(session)
            tower = await _seed_ups(repository, tenant_id, name="Tower UPS", form_factor_key="tower")
            await _seed_ups(repository, tenant_id, name="Rack UPS", form_factor_key="rack_mount")
            await session.commit()

            products = await repository.list_products(
                tenant_id,
                category="UPS Solutions",
                constraints=[Constraint(field="form_factor_key", operator="eq", value="tower")],
                limit=50,
            )
            assert [product.id for product in products] == [tower]
            break
    finally:
        await _cleanup(tenant_id)


@pytest.mark.asyncio
async def test_relax_and_retry_drops_lowest_priority_constraint_first() -> None:
    """Regression test for the zero-result relaxation design: a form-factor
    preference should be dropped before capacity, since capacity is the more
    defining requirement — never silently drop to an unscoped search."""
    await _check_db_available()
    tenant_id = uuid.uuid4()
    try:
        async for session in get_db_session():
            repository = ProductRepository(session)
            six_kva_rack = await _seed_ups(
                repository, tenant_id, name="6kVA Rack UPS",
                capacity_kva=Decimal("6"), form_factor_key="rack_mount",
            )
            await session.commit()

            settings = get_settings()
            service = RetrievalService(
                db_session=session,
                settings=settings,
                product_repository=repository,
                embedder=object(),  # never called by _relax_and_retry
                qdrant=object(),  # never called by _relax_and_retry
            )
            # No product is a 6kVA *tower* — the tower preference should be
            # relaxed, not the capacity requirement, leaving the real 6kVA
            # rack-mount product as the fallback result.
            filters = ExtractedFilters(
                category="UPS Solutions",
                constraints=[
                    Constraint(field="capacity_kva", operator="eq", value=Decimal("6")),
                    Constraint(field="form_factor_key", operator="eq", value="tower", source_text="tower"),
                ],
            )
            candidate_ids, dropped = await service._relax_and_retry(tenant_id, filters)  # noqa: SLF001
            assert dropped is not None
            assert dropped.field == "form_factor_key"
            assert candidate_ids == [six_kva_rack]
            break
    finally:
        await _cleanup(tenant_id)
